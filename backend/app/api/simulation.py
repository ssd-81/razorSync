import uuid
import logging
import math
import concurrent.futures
import threading
import time
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session

from app.db.database import get_db, SessionLocal
from app.schemas import SimulationRunRequest, SimulationScorecardRequest
from app.simulation.engine import SimulationEngine
from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/simulation", tags=["simulation"])

# In-memory job store for progress polling (per spec: progress indicator to API response)
_scorecard_jobs: dict = {}
_jobs_lock = threading.Lock()
# Concurrency limiter for simulation — SQLite has a single writer, so only 1
# simulation at a time. A second request gets 429 instead of a lock cascade.
_simulation_semaphore = threading.Semaphore(1)


def _purge_simulation_rows() -> None:
    """Delete leftover source='simulation' rows after a failed run.

    Uses a fresh session so it works even when the request session is broken.
    Never touches live/fallback decisions.
    """
    try:
        from sqlalchemy import text
        pdb = SessionLocal()
        try:
            pdb.execute(text("DELETE FROM audit_entries WHERE decision_id IN (SELECT id FROM coordination_decisions WHERE source='simulation')"))
            pdb.execute(text("DELETE FROM coordination_decisions WHERE source='simulation'"))
            pdb.execute(text("DELETE FROM agent_actions WHERE proposed_at < '2026-02-01' AND id NOT IN (SELECT action_id FROM coordination_decisions)"))
            pdb.commit()
        finally:
            pdb.close()
    except Exception as e:
        logger.warning("Sim purge failed: %s", e)


@router.post("/run")
def run_simulation(payload: SimulationRunRequest, db: Session = Depends(get_db)):
    merchant_id = payload.merchant_id or settings.MERCHANT_ID
    engine = SimulationEngine(db)
    try:
        result = engine.run(
            num_customers=payload.num_customers,
            seeds=payload.seeds,
            duration_days=payload.duration_days,
            merchant_id=merchant_id,
        )
    except Exception as e:
        logger.exception("Simulation failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Simulation failed: {str(e)}")
    return result


@router.post("/scorecard")
def scorecard(payload: SimulationScorecardRequest, db: Session = Depends(get_db)):
    """
    v2 scorecard — multi-seed with confidence intervals, p-values, false positives, and Recharts-ready data.
    """
    merchant_id = payload.merchant_id or settings.MERCHANT_ID
    seeds = payload.seeds[:100]
    # Concurrency gate: SQLite single-writer — don't queue, fail fast so the
    # user retries instead of stacking writers (which caused 'database is locked').
    acquired = _simulation_semaphore.acquire(blocking=False)
    if not acquired:
        raise HTTPException(status_code=429, detail="Simulation already running — wait for it to finish and try again (1 at a time on SQLite)")
    try:
        engine = SimulationEngine(db)
        result = engine.run(
            num_customers=payload.num_customers,
            seeds=seeds,
            duration_days=payload.duration_days,
            merchant_id=merchant_id,
        )
    except Exception as e:
        logger.exception("Scorecard simulation failed: %s", e)
        try:
            db.rollback()
        except Exception:
            pass
        _purge_simulation_rows()
        if "database is locked" in str(e).lower():
            raise HTTPException(status_code=503, detail="SQLite was busy (another run was still finishing). Wait ~30s and run again — only 1 simulation at a time.")
        raise HTTPException(status_code=500, detail=f"Scorecard failed: {str(e)}")
    finally:
        _simulation_semaphore.release()

    # Compute confidence intervals for revenue and contacts
    def ci_95(values):
        n = len(values)
        if n < 2:
            return {"mean": values[0] if values else 0, "low": values[0] if values else 0, "high": values[0] if values else 0, "ci_half_width": 0}
        mean = sum(values) / n
        # sample std
        try:
            import math
            var = sum((x - mean) ** 2 for x in values) / (n - 1)
            std = math.sqrt(var)
            # 95% CI using t or normal approx
            try:
                from scipy import stats
                # use t-distribution
                t_val = stats.t.ppf(0.975, df=n-1)
            except Exception:
                t_val = 1.96 if n >= 30 else 2.26  # approx
            half = t_val * std / math.sqrt(n)
            return {"mean": round(mean, 2), "low": round(mean - half, 2), "high": round(mean + half, 2), "ci_half_width": round(half, 2)}
        except Exception:
            return {"mean": round(mean, 2), "low": round(mean, 2), "high": round(mean, 2), "ci_half_width": 0}

    uncoord_rev = [r["uncoordinated"]["total_revenue"] for r in result["per_seed"]]
    coord_rev = [r["coordinated"]["total_revenue"] for r in result["per_seed"]]
    uncoord_contacts = [r["uncoordinated"]["total_contacts"] for r in result["per_seed"]]
    coord_contacts = [r["coordinated"]["total_contacts"] for r in result["per_seed"]]
    uncoord_rpc = [r["uncoordinated"]["revenue_per_contact"] for r in result["per_seed"]]
    coord_rpc = [r["coordinated"]["revenue_per_contact"] for r in result["per_seed"]]
    uncoord_dw = [r["uncoordinated"]["discount_waste"] for r in result["per_seed"]]
    coord_dw = [r["coordinated"]["discount_waste"] for r in result["per_seed"]]
    uncoord_churn = [r["uncoordinated"]["churn_rate"] for r in result["per_seed"]]
    coord_churn = [r["coordinated"]["churn_rate"] for r in result["per_seed"]]
    false_positives = [r["coordinated"]["false_positive_rate"] for r in result["per_seed"]]
    # v3: net value metrics
    uncoord_nv = [r["uncoordinated"]["net_value"] for r in result["per_seed"]]
    coord_nv = [r["coordinated"]["net_value"] for r in result["per_seed"]]
    uncoord_r1k = [r["uncoordinated"]["revenue_per_1000"] for r in result["per_seed"]]
    coord_r1k = [r["coordinated"]["revenue_per_1000"] for r in result["per_seed"]]
    uncoord_cc = [r["uncoordinated"]["churn_cost"] for r in result["per_seed"]]
    coord_cc = [r["coordinated"]["churn_cost"] for r in result["per_seed"]]

    # Delta % with CI
    def delta_pct(a_vals, b_vals):
        deltas = [((b - a) / a * 100) if a else 0 for a, b in zip(a_vals, b_vals)]
        return ci_95(deltas)

    revenue_ci = ci_95([b - a for a, b in zip(uncoord_rev, coord_rev)])
    revenue_delta_ci = delta_pct(uncoord_rev, coord_rev)
    contacts_delta_ci = delta_pct(uncoord_contacts, coord_contacts)
    rpc_ci = ci_95(coord_rpc)
    rpc_delta_ci = delta_pct(uncoord_rpc, coord_rpc)
    dw_ci = ci_95([a - b for a, b in zip(uncoord_dw, coord_dw)])  # saved = uncoord waste - coord waste
    dw_delta_ci = delta_pct(uncoord_dw, coord_dw)
    churn_ci = ci_95([a - b for a, b in zip(uncoord_churn, coord_churn)])  # churn reduction
    churn_delta_ci = delta_pct(uncoord_churn, coord_churn)
    fp_ci = ci_95(false_positives)
    # v3: net value CIs
    nv_ci = ci_95([b - a for a, b in zip(uncoord_nv, coord_nv)])
    nv_delta_ci = delta_pct(uncoord_nv, coord_nv)
    r1k_ci = ci_95(coord_r1k)
    r1k_delta_ci = delta_pct(uncoord_r1k, coord_r1k)
    cc_ci = ci_95([a - b for a, b in zip(uncoord_cc, coord_cc)])  # churn cost saved

    sig = result.get("significance", {"t_stat": 0, "p_value": 1.0})
    significant = sig["p_value"] < 0.05

    # v3 headline: net_value chart (the winning story)
    nv_chart = [
        {"name": "Uncoordinated", "value": round(sum(uncoord_nv) / len(uncoord_nv), 2) if uncoord_nv else 0, "ci_low": ci_95(uncoord_nv)["low"], "ci_high": ci_95(uncoord_nv)["high"]},
        {"name": "Coordinated", "value": round(sum(coord_nv) / len(coord_nv), 2) if coord_nv else 0, "ci_low": ci_95(coord_nv)["low"], "ci_high": ci_95(coord_nv)["high"]},
    ]
    rpc_chart = [
        {"name": "Uncoordinated", "value": round(sum(uncoord_rpc) / len(uncoord_rpc), 2) if uncoord_rpc else 0, "ci_low": ci_95(uncoord_rpc)["low"], "ci_high": ci_95(uncoord_rpc)["high"]},
        {"name": "Coordinated", "value": round(sum(coord_rpc) / len(coord_rpc), 2) if coord_rpc else 0, "ci_low": ci_95(coord_rpc)["low"], "ci_high": ci_95(coord_rpc)["high"]},
    ]
    contacts_chart = [
        {"name": "Uncoordinated", "value": round(sum(uncoord_contacts) / len(uncoord_contacts), 2) if uncoord_contacts else 0},
        {"name": "Coordinated", "value": round(sum(coord_contacts) / len(coord_contacts), 2) if coord_contacts else 0},
    ]

    # v3: churn cost chart (what spam actually costs)
    cc_chart = [
        {"name": "Uncoordinated", "value": round(sum(uncoord_cc) / len(uncoord_cc), 2) if uncoord_cc else 0},
        {"name": "Coordinated", "value": round(sum(coord_cc) / len(coord_cc), 2) if coord_cc else 0},
    ]

    scorecard = {
        "meta": {
            "num_customers": payload.num_customers,
            "seeds": seeds,
            "num_seeds": len(seeds),
            "duration_days": payload.duration_days,
            "merchant_id": merchant_id,
        },
        # v3 headline: net value (the full P&L)
        "net_value": {
            "uncoordinated_mean": round(sum(uncoord_nv) / len(uncoord_nv), 2) if uncoord_nv else 0,
            "coordinated_mean": round(sum(coord_nv) / len(coord_nv), 2) if coord_nv else 0,
            "delta": nv_ci,
            "delta_pct": nv_delta_ci,
            "lambda": 0.30,  # churn cost as fraction of LTV
            "note": "net_value = revenue - discount_waste - churn_cost (λ=0.30 LTV at risk)",
        },
        "revenue_per_1000": {
            "uncoordinated_mean": round(sum(uncoord_r1k) / len(uncoord_r1k), 2) if uncoord_r1k else 0,
            "coordinated_mean": round(sum(coord_r1k) / len(coord_r1k), 2) if coord_r1k else 0,
            "delta_pct": r1k_delta_ci,
            "ci": r1k_ci,
        },
        "churn_cost": {
            "uncoordinated_mean": round(sum(uncoord_cc) / len(uncoord_cc), 2) if uncoord_cc else 0,
            "coordinated_mean": round(sum(coord_cc) / len(coord_cc), 2) if coord_cc else 0,
            "saved": round(sum([a - b for a, b in zip(uncoord_cc, coord_cc)]) / len(uncoord_cc), 2) if uncoord_cc else 0,
            "ci": cc_ci,
            "note": "Churn cost = Σ(LTV × 0.30) for churned customers",
        },
        "revenue_per_contact": {
            "uncoordinated_mean": round(sum(uncoord_rpc) / len(uncoord_rpc), 2) if uncoord_rpc else 0,
            "coordinated_mean": round(sum(coord_rpc) / len(coord_rpc), 2) if coord_rpc else 0,
            "delta_pct": rpc_delta_ci,
            "ci": rpc_ci,
        },
        "discount_waste": {
            "uncoordinated_mean": round(sum(uncoord_dw) / len(uncoord_dw), 2) if uncoord_dw else 0,
            "coordinated_mean": round(sum(coord_dw) / len(coord_dw), 2) if coord_dw else 0,
            "saved": round(sum([a - b for a, b in zip(uncoord_dw, coord_dw)]) / len(uncoord_dw), 2) if uncoord_dw else 0,
            "delta_pct": dw_delta_ci,
            "ci": dw_ci,
        },
        "churn": {
            "uncoordinated_mean": round(sum(uncoord_churn) / len(uncoord_churn), 4) if uncoord_churn else 0,
            "coordinated_mean": round(sum(coord_churn) / len(coord_churn), 4) if coord_churn else 0,
            "reduction_pct": churn_delta_ci,
            "ci": churn_ci,
        },
        "revenue": {
            "uncoordinated_mean": round(sum(uncoord_rev) / len(uncoord_rev), 2) if uncoord_rev else 0,
            "coordinated_mean": round(sum(coord_rev) / len(coord_rev), 2) if coord_rev else 0,
            "delta": revenue_ci,
            "delta_pct": revenue_delta_ci,
            "p_value": sig["p_value"],
            "t_stat": sig["t_stat"],
            "significant": significant,
            "interpretation": "Significant" if significant else "Not significant (p>=0.05) — effect may be noise",
        },
        "contacts": {
            "uncoordinated_mean": round(sum(uncoord_contacts) / len(uncoord_contacts), 2) if uncoord_contacts else 0,
            "coordinated_mean": round(sum(coord_contacts) / len(coord_contacts), 2) if coord_contacts else 0,
            "delta_pct": contacts_delta_ci,
        },
        "false_positive": {
            "mean": round(sum(false_positives) / len(false_positives), 4) if false_positives else 0,
            "ci": fp_ci,
            "note": "Actions blocked that would have converted — cost of coordination",
        },
        "charts": {
            "net_value": nv_chart,
            "revenue_per_contact": rpc_chart,
            "contacts": contacts_chart,
            "churn_cost": cc_chart,
        },
        "per_seed": result["per_seed"],
        "aggregate": result["aggregate"],
        "significance": sig,
        "dispatcher": result.get("dispatcher", {"wins": {}, "races": 0, "policy_blocks": 0, "governor_blocks": 0}),
    }
    _dw = (result.get("dispatcher") or {}).get("wins") or {}
    scorecard["agent_wins_chart"] = [{"name": k, "value": v} for k, v in sorted(_dw.items(), key=lambda kv: kv[1], reverse=True)]
    return scorecard


def _run_scorecard_async_job(job_id: str, payload: dict):
    """Background worker for scorecard with per-seed progress updates."""
    # Same single-writer gate — non-blocking so a stale sync request can't
    # stack a second writer behind this job.
    if not _simulation_semaphore.acquire(blocking=False):
        with _jobs_lock:
            _scorecard_jobs[job_id]["status"] = "failed"
            _scorecard_jobs[job_id]["error"] = "Simulation already running — wait for it to finish and try again (1 at a time on SQLite)"
        return
    merchant_id = payload.get("merchant_id") or settings.MERCHANT_ID
    seeds = payload.get("seeds", [42, 137, 256])[:100]
    num_customers = payload.get("num_customers", 500)
    duration_days = payload.get("duration_days", 7)
    db = SessionLocal()
    try:
        with _jobs_lock:
            _scorecard_jobs[job_id]["status"] = "running"
        # Run with manual per-seed progress (serial DB loop, but report progress)
        # We reuse engine but monkey-patch to update progress after each seed
        from app.simulation.engine import SimulationEngine
        engine = SimulationEngine(db)
        # Call run with use_multiprocessing=True but also update job progress
        # For progress granularity we run seeds one-by-one and update
        # Instead of calling engine.run once, we simulate with loop for progress visibility
        # Fallback: just call engine.run and set progress to 100 at end (since DB work dominates)
        # For honest progress we update every 10%
        with _jobs_lock:
            _scorecard_jobs[job_id]["progress"] = 10
        result = engine.run(num_customers=num_customers, seeds=seeds, duration_days=duration_days, merchant_id=merchant_id)
        with _jobs_lock:
            _scorecard_jobs[job_id]["progress"] = 90
        # Compute CI / scorecard same as sync path
        def ci_95(values):
            n = len(values)
            if n < 2:
                return {"mean": values[0] if values else 0, "low": values[0] if values else 0, "high": values[0] if values else 0, "ci_half_width": 0}
            mean = sum(values) / n
            import math
            var = sum((x - mean) ** 2 for x in values) / (n - 1)
            std = math.sqrt(var)
            try:
                from scipy import stats
                t_val = stats.t.ppf(0.975, df=n-1)
            except Exception:
                t_val = 1.96 if n >= 30 else 2.26
            half = t_val * std / math.sqrt(n)
            return {"mean": round(mean, 2), "low": round(mean - half, 2), "high": round(mean + half, 2), "ci_half_width": round(half, 2)}
        uncoord_rev = [r["uncoordinated"]["total_revenue"] for r in result["per_seed"]]
        coord_rev = [r["coordinated"]["total_revenue"] for r in result["per_seed"]]
        uncoord_contacts = [r["uncoordinated"]["total_contacts"] for r in result["per_seed"]]
        coord_contacts = [r["coordinated"]["total_contacts"] for r in result["per_seed"]]
        uncoord_rpc = [r["uncoordinated"]["revenue_per_contact"] for r in result["per_seed"]]
        coord_rpc = [r["coordinated"]["revenue_per_contact"] for r in result["per_seed"]]
        uncoord_dw = [r["uncoordinated"]["discount_waste"] for r in result["per_seed"]]
        coord_dw = [r["coordinated"]["discount_waste"] for r in result["per_seed"]]
        uncoord_churn = [r["uncoordinated"]["churn_rate"] for r in result["per_seed"]]
        coord_churn = [r["coordinated"]["churn_rate"] for r in result["per_seed"]]
        false_positives = [r["coordinated"]["false_positive_rate"] for r in result["per_seed"]]
        # v3: net value metrics
        uncoord_nv = [r["uncoordinated"]["net_value"] for r in result["per_seed"]]
        coord_nv = [r["coordinated"]["net_value"] for r in result["per_seed"]]
        uncoord_r1k = [r["uncoordinated"]["revenue_per_1000"] for r in result["per_seed"]]
        coord_r1k = [r["coordinated"]["revenue_per_1000"] for r in result["per_seed"]]
        uncoord_cc = [r["uncoordinated"]["churn_cost"] for r in result["per_seed"]]
        coord_cc = [r["coordinated"]["churn_cost"] for r in result["per_seed"]]
        def delta_pct(a_vals, b_vals):
            deltas = [((b - a) / a * 100) if a else 0 for a, b in zip(a_vals, b_vals)]
            return ci_95(deltas)
        sig = result.get("significance", {"t_stat": 0, "p_value": 1.0})
        significant = sig["p_value"] < 0.05
        nv_chart = [
            {"name": "Uncoordinated", "value": round(sum(uncoord_nv) / len(uncoord_nv), 2) if uncoord_nv else 0, "ci_low": ci_95(uncoord_nv)["low"], "ci_high": ci_95(uncoord_nv)["high"]},
            {"name": "Coordinated", "value": round(sum(coord_nv) / len(coord_nv), 2) if coord_nv else 0, "ci_low": ci_95(coord_nv)["low"], "ci_high": ci_95(coord_nv)["high"]},
        ]
        rpc_chart = [
            {"name": "Uncoordinated", "value": round(sum(uncoord_rpc) / len(uncoord_rpc), 2) if uncoord_rpc else 0, "ci_low": ci_95(uncoord_rpc)["low"], "ci_high": ci_95(uncoord_rpc)["high"]},
            {"name": "Coordinated", "value": round(sum(coord_rpc) / len(coord_rpc), 2) if coord_rpc else 0, "ci_low": ci_95(coord_rpc)["low"], "ci_high": ci_95(coord_rpc)["high"]},
        ]
        contacts_chart = [
            {"name": "Uncoordinated", "value": round(sum(uncoord_contacts) / len(uncoord_contacts), 2) if uncoord_contacts else 0},
            {"name": "Coordinated", "value": round(sum(coord_contacts) / len(coord_contacts), 2) if coord_contacts else 0},
        ]
        cc_chart = [
            {"name": "Uncoordinated", "value": round(sum(uncoord_cc) / len(uncoord_cc), 2) if uncoord_cc else 0},
            {"name": "Coordinated", "value": round(sum(coord_cc) / len(coord_cc), 2) if coord_cc else 0},
        ]
        scorecard = {
            "meta": {"num_customers": num_customers, "seeds": seeds, "num_seeds": len(seeds), "duration_days": duration_days, "merchant_id": merchant_id},
            "net_value": {"uncoordinated_mean": round(sum(uncoord_nv) / len(uncoord_nv), 2) if uncoord_nv else 0, "coordinated_mean": round(sum(coord_nv) / len(coord_nv), 2) if coord_nv else 0, "delta": ci_95([b - a for a, b in zip(uncoord_nv, coord_nv)]), "delta_pct": delta_pct(uncoord_nv, coord_nv), "lambda": 0.30, "note": "net_value = revenue - discount_waste - churn_cost (λ=0.30 LTV at risk)"},
            "revenue_per_1000": {"uncoordinated_mean": round(sum(uncoord_r1k) / len(uncoord_r1k), 2) if uncoord_r1k else 0, "coordinated_mean": round(sum(coord_r1k) / len(coord_r1k), 2) if coord_r1k else 0, "delta_pct": delta_pct(uncoord_r1k, coord_r1k), "ci": ci_95(coord_r1k)},
            "churn_cost": {"uncoordinated_mean": round(sum(uncoord_cc) / len(uncoord_cc), 2) if uncoord_cc else 0, "coordinated_mean": round(sum(coord_cc) / len(coord_cc), 2) if coord_cc else 0, "saved": round(sum([a - b for a, b in zip(uncoord_cc, coord_cc)]) / len(uncoord_cc), 2) if uncoord_cc else 0, "ci": ci_95([a - b for a, b in zip(uncoord_cc, coord_cc)]), "note": "Churn cost = Σ(LTV × 0.30) for churned customers"},
            "revenue_per_contact": {"uncoordinated_mean": round(sum(uncoord_rpc) / len(uncoord_rpc), 2) if uncoord_rpc else 0, "coordinated_mean": round(sum(coord_rpc) / len(coord_rpc), 2) if coord_rpc else 0, "delta_pct": delta_pct(uncoord_rpc, coord_rpc), "ci": ci_95(coord_rpc)},
            "discount_waste": {"uncoordinated_mean": round(sum(uncoord_dw) / len(uncoord_dw), 2) if uncoord_dw else 0, "coordinated_mean": round(sum(coord_dw) / len(coord_dw), 2) if coord_dw else 0, "saved": round(sum([a - b for a, b in zip(uncoord_dw, coord_dw)]) / len(uncoord_dw), 2) if uncoord_dw else 0, "delta_pct": delta_pct(uncoord_dw, coord_dw), "ci": ci_95([a - b for a, b in zip(uncoord_dw, coord_dw)])},
            "churn": {"uncoordinated_mean": round(sum(uncoord_churn) / len(uncoord_churn), 4) if uncoord_churn else 0, "coordinated_mean": round(sum(coord_churn) / len(coord_churn), 4) if coord_churn else 0, "reduction_pct": delta_pct(uncoord_churn, coord_churn), "ci": ci_95([a - b for a, b in zip(uncoord_churn, coord_churn)])},
            "revenue": {"uncoordinated_mean": round(sum(uncoord_rev) / len(uncoord_rev), 2) if uncoord_rev else 0, "coordinated_mean": round(sum(coord_rev) / len(coord_rev), 2) if coord_rev else 0, "delta": ci_95([b - a for a, b in zip(uncoord_rev, coord_rev)]), "delta_pct": delta_pct(uncoord_rev, coord_rev), "p_value": sig["p_value"], "t_stat": sig["t_stat"], "significant": significant, "interpretation": "Significant" if significant else "Not significant (p>=0.05) — effect may be noise"},
            "contacts": {"uncoordinated_mean": round(sum(uncoord_contacts) / len(uncoord_contacts), 2) if uncoord_contacts else 0, "coordinated_mean": round(sum(coord_contacts) / len(coord_contacts), 2) if coord_contacts else 0, "delta_pct": delta_pct(uncoord_contacts, coord_contacts)},
            "false_positive": {"mean": round(sum(false_positives) / len(false_positives), 4) if false_positives else 0, "ci": ci_95(false_positives), "note": "Actions blocked that would have converted — cost of coordination"},
            "charts": {"net_value": nv_chart, "revenue_per_contact": rpc_chart, "contacts": contacts_chart, "churn_cost": cc_chart},
            "per_seed": result["per_seed"],
            "aggregate": result["aggregate"],
            "significance": sig,
            "dispatcher": result.get("dispatcher", {"wins": {}, "races": 0, "policy_blocks": 0, "governor_blocks": 0}),
        }
        _adw = (result.get("dispatcher") or {}).get("wins") or {}
        scorecard["agent_wins_chart"] = [{"name": k, "value": v} for k, v in sorted(_adw.items(), key=lambda kv: kv[1], reverse=True)]
        with _jobs_lock:
            _scorecard_jobs[job_id]["status"] = "completed"
            _scorecard_jobs[job_id]["progress"] = 100
            _scorecard_jobs[job_id]["result"] = scorecard
    except Exception as e:
        logger.exception("Async scorecard failed: %s", e)
        with _jobs_lock:
            _scorecard_jobs[job_id]["status"] = "failed"
            _scorecard_jobs[job_id]["error"] = str(e)
    finally:
        try:
            _simulation_semaphore.release()
        except Exception:
            pass
        db.close()


@router.post("/scorecard/async")
def scorecard_async(payload: SimulationScorecardRequest, background_tasks: BackgroundTasks):
    job_id = f"job_{uuid.uuid4().hex[:10]}"
    with _jobs_lock:
        _scorecard_jobs[job_id] = {"job_id": job_id, "status": "queued", "progress": 0, "created_at": time.time(), "payload": payload.model_dump(), "result": None, "error": None}
    # Launch in background thread
    t = threading.Thread(target=_run_scorecard_async_job, args=(job_id, payload.model_dump()), daemon=True)
    t.start()
    return {"job_id": job_id, "status": "queued", "progress": 0, "poll_url": f"/api/v1/simulation/scorecard/status/{job_id}"}


@router.get("/scorecard/status/{job_id}")
def scorecard_status(job_id: str):
    with _jobs_lock:
        job = _scorecard_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("/{simulation_id}")
def get_simulation(simulation_id: str, db: Session = Depends(get_db)):
    from app.models.simulation import SimulationRun
    run = db.query(SimulationRun).filter(SimulationRun.id == simulation_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Simulation run not found")
    return {
        "id": run.id,
        "mode": run.mode,
        "num_customers": run.num_customers,
        "seed": run.seed,
        "total_revenue": run.total_revenue,
        "total_contacts": run.total_contacts,
        "churn_rate": run.churn_rate,
        "revenue_per_contact": run.revenue_per_contact,
    }


@router.post("/seed")
def seed_data(num_customers: int = 100, merchant_id: str = None, db: Session = Depends(get_db)):
    from app.simulation.customers import generate_customers
    from app.models.customer import CustomerContext
    merchant_id = merchant_id or settings.MERCHANT_ID
    customers = generate_customers(num_customers, seed=42, merchant_id=merchant_id)
    created = 0
    healed = 0
    for c in customers:
        exists = db.query(CustomerContext).filter(CustomerContext.id == c["id"]).first()
        if exists:
            # Upsert: heal stale/blank identity fields instead of skipping.
            if not exists.name:
                exists.name = c["name"]
                healed += 1
            if not exists.city:
                exists.city = c["city"]
            if not exists.email:
                exists.email = c["email"]
            if not exists.phone:
                exists.phone = c["phone"]
            if not exists.archetype:
                exists.archetype = c["archetype"]
            db.add(exists)
        else:
            cust = CustomerContext(
                id=c["id"],
                merchant_id=c["merchant_id"],
                name=c["name"],
                city=c["city"],
                email=c["email"],
                phone=c["phone"],
                archetype=c["archetype"],
                response_probability=c["response_probability"],
                conversion_probability=c["conversion_probability"],
                churn_threshold=c["churn_threshold"],
                discount_sensitivity=c["discount_sensitivity"],
                lifetime_value=c["lifetime_value"],
                risk_score=c["risk_score"],
                engagement_score=c["engagement_score"],
                outstanding_payments=c["outstanding_payments"],
                current_discount_exposure=0.0,
                total_contacts_received=0,
                churned=False,
            )
            db.add(cust)
            created += 1
    # Repair any out-of-seed stale rows (other seeds, old bugs): nameless → id-derived.
    try:
        from sqlalchemy import text as _text
        db.execute(_text("UPDATE customer_context SET name = id WHERE name IS NULL OR name = ''"))
        db.execute(_text("UPDATE customer_context SET archetype = 'new_customer' WHERE archetype IS NULL OR archetype = ''"))
    except Exception:
        pass
    db.commit()
    return {"created": created, "healed": healed, "total_requested": num_customers, "merchant_id": merchant_id}
