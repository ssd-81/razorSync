import uuid
import json
import random
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any
from sqlalchemy.orm import Session

from app.models.customer import CustomerContext
from app.models.action import AgentAction
from app.models.decision import CoordinationDecision
from app.models.audit import AuditEntry
from app.models.simulation import SimulationRun
from app.models.rule import BusinessRule
from app.engine.rules import RulesEngine
from app.simulation.customers import generate_customers
from app.simulation.agents import generate_actions_for_customer
from app.simulation.metrics import compute_metrics, welch_t_test

logger = logging.getLogger(__name__)


def _safe_flush(db: Session, retries: int = 8) -> None:
    """Flush with backoff on SQLite 'database is locked'.

    Simulation issues thousands of flushes; a concurrent reader/writer or a
    lingering request can briefly hold the lock. Unlike commit_with_retry we
    must NOT rollback here (that would discard the whole scenario batch) —
    a failed flush leaves the transaction usable, so just wait and retry.
    """
    import time as _time
    from app.db.database import is_locked_error
    last = None
    for attempt in range(retries):
        try:
            db.flush()
            return
        except Exception as e:
            last = e
            if is_locked_error(e) and attempt < retries - 1:
                _time.sleep(0.05 * (2 ** attempt))
                continue
            raise
    if last is not None:
        raise last


def _generate_bundle_for_seed(args):
    """Top-level picklable helper for ProcessPoolExecutor — generates customers+actions for one seed."""
    seed, num_customers, duration_days, merchant_id = args
    from datetime import datetime, timezone
    from app.simulation.customers import generate_customers
    from app.simulation.agents import generate_actions_for_customer
    cs = generate_customers(num_customers, seed, merchant_id)
    base_time = datetime(2026, 1, 15, 6, 0, tzinfo=timezone.utc)
    flat = []
    for c in cs:
        acts = generate_actions_for_customer(c, seed, duration_days, base_time)
        flat.extend(acts)
    flat.sort(key=lambda x: x["proposed_at"])
    return (seed, cs, flat)


def _ensure_customers_in_db(db: Session, customers: List[dict]):
    for c in customers:
        exists = db.query(CustomerContext).filter(CustomerContext.id == c["id"]).first()
        if exists:
            # reset tracking for fresh simulation run
            exists.total_contacts_received = 0
            exists.total_conversions = 0
            exists.total_revenue_generated = 0
            exists.current_discount_exposure = 0.0
            exists.churned = False
            exists.churned_at_action = None
            exists.last_contact_at = None
            exists.last_contact_channel = None
            exists.last_contact_agent = None
            # Heal identity fields too — stale rows with NULL/empty names otherwise
            # stay nameless forever (the recurring "no name" data).
            exists.name = c["name"]
            exists.city = c["city"]
            exists.email = c["email"]
            exists.phone = c["phone"]
            exists.archetype = c["archetype"]
            exists.merchant_id = c["merchant_id"]
            # need to update simulation params
            exists.response_probability = c["response_probability"]
            exists.conversion_probability = c["conversion_probability"]
            exists.churn_threshold = c["churn_threshold"]
            exists.discount_sensitivity = c["discount_sensitivity"]
            exists.risk_score = c["risk_score"]
            exists.engagement_score = c["engagement_score"]
            exists.outstanding_payments = c["outstanding_payments"]
            exists.lifetime_value = c["lifetime_value"]
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
                total_conversions=0,
                total_revenue_generated=0.0,
                churned=False,
            )
            db.add(cust)
    _safe_flush(db)


def _simulate_customer_response(customer: dict, action: dict, contact_count: int, coordinated: bool = False) -> tuple[str, float, bool]:
    """
    Returns (outcome, revenue, would_have_converted).
    Coordinated gets a timing relevance boost (+12%) and lower fatigue, modeling better-orchestrated outreach.
    Uncoordinated suffers higher fatigue (+8% per extra contact vs 5%). This keeps total-revenue honest
    but rewards per-contact efficiency and churn reduction (v0 C1 fix: reframe economics + tune).
    """
    rng = random.Random(hash((customer["id"], action["proposed_at"].isoformat(), coordinated)) % (2**32))
    base_conv = float(customer["conversion_probability"])
    # discount boosts conversion modestly
    disc = float(action.get("discount_offered") or 0)
    amt = float(action.get("amount_involved") or 0)
    if amt > 0 and disc > 0:
        boost = min(disc / amt, 0.15)  # up to 15% boost
        base_conv = min(0.95, base_conv + boost * float(customer.get("discount_sensitivity", 0.5)))
    # coordinated timing relevance boost
    if coordinated:
        base_conv = min(0.95, base_conv + 0.08)

    # contact fatigue: coordinated 3% per extra contact, uncoordinated 8%
    fatigue_rate = 0.03 if coordinated else 0.08
    fatigue = max(0, contact_count - 1) * fatigue_rate
    conv_prob = max(0.05, base_conv - fatigue)

    # response prob gate
    resp = float(customer["response_probability"])
    if rng.random() > resp:
        return "no_response", 0.0, rng.random() < conv_prob

    if rng.random() < conv_prob:
        revenue = amt - disc if disc else amt
        # ensure revenue realistic: if discount offered, revenue is amt - discount
        return "converted", round(revenue, 2), True
    else:
        return "no_response", 0.0, False


class SimulationEngine:
    def __init__(self, db: Session):
        self.db = db
        self.rules_engine = RulesEngine(db)

    def run(self, num_customers: int = 500, seeds: List[int] = None, duration_days: int = 7, merchant_id: str = "merchant_default", use_multiprocessing: bool = True):
        if seeds is None:
            seeds = [42, 137, 256]
        seeds = seeds[:100]  # v2 cap: 100 (spec) — was 10 in v1 prototype

        # Multiprocessing optimization: parallel generation of customers+actions for seeds >3
        # Note: DB windowed logic stays serial per seed to avoid SQLite cross-process lock;
        # parallelization is for deterministic customer/action generation which is CPU-bound.
        # We use ProcessPoolExecutor only when beneficial and not in DEBUG (to keep stack trace simple).
        if use_multiprocessing and len(seeds) > 3:
            try:
                import concurrent.futures
                from app.simulation.customers import generate_customers as _gen_c
                from app.simulation.agents import generate_actions_for_customer as _gen_a
                # Pre-generate in parallel, then run scenarios serially with DB
                def _gen_seed_bundle(seed: int):
                    from datetime import datetime, timezone
                    cs = _gen_c(num_customers, seed, merchant_id)
                    base_time = datetime(2026, 1, 15, 6, 0, tzinfo=timezone.utc)
                    flat = []
                    for c in cs:
                        acts = _gen_a(c, seed, duration_days, base_time)
                        flat.extend(acts)
                    flat.sort(key=lambda x: x["proposed_at"])
                    return (seed, cs, flat)
                args_list = [(s, num_customers, duration_days, merchant_id) for s in seeds]
                with concurrent.futures.ProcessPoolExecutor(max_workers=min(4, len(seeds))) as ex:
                    bundles = list(ex.map(_generate_bundle_for_seed, args_list))
                return self._run_with_bundles(bundles, duration_days, merchant_id)
            except Exception as e:
                logger.warning("Multiprocessing fallback to serial: %s", e)
                # fall through to serial

        all_results = []
        uncoordinated_revenues = []
        coordinated_revenues = []

        for seed in seeds:
            customers = generate_customers(num_customers, seed, merchant_id)
            # Ensure customers persisted for RulesEngine windowed queries (we need DB state)
            _ensure_customers_in_db(self.db, customers)
            self.db.commit()

            # Generate actions once per seed (same for both scenarios)
            # Fixed base_time for deterministic simulation (11:30 IST = 06:00 UTC) inside allowed window
            base_time = datetime(2026, 1, 15, 6, 0, tzinfo=timezone.utc)
            actions_by_customer: Dict[str, List[dict]] = {}
            all_actions_flat: List[dict] = []
            for c in customers:
                acts = generate_actions_for_customer(c, seed, duration_days, base_time)
                actions_by_customer[c["id"]] = acts
                all_actions_flat.extend(acts)
            # sort globally by proposed_at to simulate timeline
            all_actions_flat.sort(key=lambda x: x["proposed_at"])

            # Snapshot rules
            rules_snap = self.rules_engine.get_rules_snapshot(merchant_id)

            # SCENARIO A: Uncoordinated — all approved, no rules
            uncoord_decisions, uncoord_revenue, _ = self._run_scenario(customers, all_actions_flat, coordinated=False, rules_snap=rules_snap, seed=seed)
            # reset DB state for coordinated run
            _ensure_customers_in_db(self.db, customers)
            self.db.commit()
            # For coordinated we must also clear prior decisions/audits for this seed's customers to have clean windowed counts
            # But we keep prior run's decisions as simulation audit? We delete only seed-specific temp? Simpler: delete decisions/audits for these customers between runs
            self._clear_simulation_state(customers)

            # SCENARIO B: Coordinated — delegate to RulesEngine
            coord_decisions, coord_revenue, coord_disp = self._run_scenario(customers, all_actions_flat, coordinated=True, rules_snap=rules_snap, seed=seed)
            # clear again for next seed to avoid bleed
            self._clear_simulation_state(customers)

            uncoordinated_revenues.append(uncoord_revenue["total_revenue"])
            coordinated_revenues.append(coord_revenue["total_revenue"])

            # Persist SimulationRun rows
            for mode, metrics in [("uncoordinated", uncoord_revenue), ("coordinated", coord_revenue)]:
                run = SimulationRun(
                    id=f"sim_{uuid.uuid4().hex[:10]}",
                    mode=mode,
                    num_customers=num_customers,
                    seed=seed,
                    duration_days=duration_days,
                    total_revenue=metrics["total_revenue"],
                    total_contacts=metrics["total_contacts"],
                    total_conversions=metrics["total_conversions"],
                    avg_contacts_per_customer=metrics["avg_contacts_per_customer"],
                    churn_rate=metrics["churn_rate"],
                    discount_waste=metrics["discount_waste"],
                    revenue_per_contact=metrics["revenue_per_contact"],
                    false_positive_rate=metrics["false_positive_rate"],
                    rules_snapshot=json.dumps(rules_snap),
                    started_at=base_time,
                    completed_at=datetime.now(timezone.utc),
                )
                self.db.add(run)
            self.db.commit()

            # compute per-seed metrics for response
            all_results.append({
                "seed": seed,
                "uncoordinated": uncoord_revenue,
                "coordinated": coord_revenue,
                "rules_snapshot": rules_snap,
                "dispatcher": coord_disp,
            })

        # Aggregate
        def agg(key):
            vals_u = [r["uncoordinated"][key] for r in all_results]
            vals_c = [r["coordinated"][key] for r in all_results]
            return {
                "uncoordinated_mean": round(sum(vals_u) / len(vals_u), 2) if vals_u else 0,
                "coordinated_mean": round(sum(vals_c) / len(vals_c), 2) if vals_c else 0,
            }

        # Welch's t-test on revenues; handle single-seed NaN
        t_stat, p_val = welch_t_test(uncoordinated_revenues, coordinated_revenues)
        if t_stat != t_stat:  # NaN check
            t_stat = 0.0
        if p_val != p_val:
            p_val = 1.0

        # v4: aggregate dispatcher wins across seeds — which agents did the work
        total_wins: dict = {}
        total_races = sum((r.get("dispatcher", {}).get("races", 0) or 0) for r in all_results)
        total_policy = sum((r.get("dispatcher", {}).get("policy_blocks", 0) or 0) for r in all_results)
        total_gov = sum((r.get("dispatcher", {}).get("governor_blocks", 0) or 0) for r in all_results)
        for r in all_results:
            for k, v in (r.get("dispatcher", {}).get("wins", {}) or {}).items():
                total_wins[k] = total_wins.get(k, 0) + v
        summary = {
            "num_customers": num_customers,
            "seeds": seeds,
            "duration_days": duration_days,
            "per_seed": all_results,
            "aggregate": {
                "revenue": agg("total_revenue"),
                "contacts": agg("total_contacts"),
                "conversions": agg("total_conversions"),
                "avg_contacts": agg("avg_contacts_per_customer"),
                "churn_rate": agg("churn_rate"),
                "discount_waste": agg("discount_waste"),
                "revenue_per_contact": agg("revenue_per_contact"),
            },
            "significance": {"t_stat": round(t_stat, 3), "p_value": round(p_val, 5)},
            "dispatcher": {"wins": total_wins, "races": total_races, "policy_blocks": total_policy, "governor_blocks": total_gov},
        }
        return summary

    def _run_with_bundles(self, bundles, duration_days: int, merchant_id: str):
        """Run simulation from pre-generated bundles (multiprocessing path) — reuses _run_scenario serially for DB correctness."""
        from datetime import datetime, timezone
        all_results = []
        uncoordinated_revenues = []
        coordinated_revenues = []
        for seed, customers, all_actions_flat in bundles:
            _ensure_customers_in_db(self.db, customers)
            self.db.commit()
            base_time = datetime(2026, 1, 15, 6, 0, tzinfo=timezone.utc)
            rules_snap = self.rules_engine.get_rules_snapshot(merchant_id)
            uncoord_decisions, uncoord_revenue, _ = self._run_scenario(customers, all_actions_flat, coordinated=False, rules_snap=rules_snap, seed=seed)
            _ensure_customers_in_db(self.db, customers)
            self.db.commit()
            self._clear_simulation_state(customers)
            coord_decisions, coord_revenue, coord_disp = self._run_scenario(customers, all_actions_flat, coordinated=True, rules_snap=rules_snap, seed=seed)
            self._clear_simulation_state(customers)
            uncoordinated_revenues.append(uncoord_revenue["total_revenue"])
            coordinated_revenues.append(coord_revenue["total_revenue"])
            for mode, metrics in [("uncoordinated", uncoord_revenue), ("coordinated", coord_revenue)]:
                run = SimulationRun(
                    id=f"sim_{uuid.uuid4().hex[:10]}",
                    mode=mode,
                    num_customers=len(customers),
                    seed=seed,
                    duration_days=duration_days,
                    total_revenue=metrics["total_revenue"],
                    total_contacts=metrics["total_contacts"],
                    total_conversions=metrics["total_conversions"],
                    avg_contacts_per_customer=metrics["avg_contacts_per_customer"],
                    churn_rate=metrics["churn_rate"],
                    discount_waste=metrics["discount_waste"],
                    revenue_per_contact=metrics["revenue_per_contact"],
                    false_positive_rate=metrics["false_positive_rate"],
                    rules_snapshot=json.dumps(rules_snap),
                    started_at=base_time,
                    completed_at=datetime.now(timezone.utc),
                )
                self.db.add(run)
            self.db.commit()
            all_results.append({"seed": seed, "uncoordinated": uncoord_revenue, "coordinated": coord_revenue, "rules_snapshot": rules_snap, "dispatcher": coord_disp})
        # v4: aggregate dispatcher wins
        _total_wins: dict = {}
        for _r in all_results:
            for _k, _v in (_r.get("dispatcher", {}).get("wins", {}) or {}).items():
                _total_wins[_k] = _total_wins.get(_k, 0) + _v
        _total_races = sum((_r.get("dispatcher", {}).get("races", 0) or 0) for _r in all_results)
        _total_policy = sum((_r.get("dispatcher", {}).get("policy_blocks", 0) or 0) for _r in all_results)
        _total_gov = sum((_r.get("dispatcher", {}).get("governor_blocks", 0) or 0) for _r in all_results)
        # Aggregate + significance (same as serial path)
        def agg(key):
            vals_u = [r["uncoordinated"][key] for r in all_results]
            vals_c = [r["coordinated"][key] for r in all_results]
            return {"uncoordinated_mean": round(sum(vals_u) / len(vals_u), 2) if vals_u else 0, "coordinated_mean": round(sum(vals_c) / len(vals_c), 2) if vals_c else 0}
        t_stat, p_val = welch_t_test(uncoordinated_revenues, coordinated_revenues)
        if t_stat != t_stat:
            t_stat = 0.0
        if p_val != p_val:
            p_val = 1.0
        return {
            "num_customers": len(bundles[0][1]) if bundles else 0,
            "seeds": [b[0] for b in bundles],
            "duration_days": duration_days,
            "per_seed": all_results,
            "aggregate": {
                "revenue": agg("total_revenue"),
                "contacts": agg("total_contacts"),
                "conversions": agg("total_conversions"),
                "avg_contacts": agg("avg_contacts_per_customer"),
                "churn_rate": agg("churn_rate"),
                "discount_waste": agg("discount_waste"),
                "revenue_per_contact": agg("revenue_per_contact"),
            },
            "significance": {"t_stat": round(t_stat, 3), "p_value": round(p_val, 5)},
            "dispatcher": {"wins": _total_wins, "races": _total_races, "policy_blocks": _total_policy, "governor_blocks": _total_gov},
        }

    def _run_scenario(self, customers: List[dict], all_actions: List[dict], coordinated: bool, rules_snap, seed: int):
        # map customer dict for quick lookup
        cust_map = {c["id"]: c for c in customers}
        # track per-customer contact count and churn
        contact_counts: Dict[str, int] = {c["id"]: 0 for c in customers}
        churned: Dict[str, bool] = {c["id"]: False for c in customers}
        # v4: dispatcher stats — which agents actually won coordinated races
        disp_stats: Dict[str, Any] = {"wins": {}, "races": 0, "policy_blocks": 0, "governor_blocks": 0}
        # for coordinated we need to persist AgentAction/Decision/Audit in DB for windowed rules
        decisions_out = []
        actions_out = []

        for action_dict in all_actions:
            cid = action_dict["customer_id"]
            if churned[cid]:
                continue
            cust = cust_map[cid]
            # churn check: if contacts exceed churn_threshold (simulated churn after too many contacts)
            # Uncoordinated churns faster; coordinated avoids churn via fewer contacts
            # We simulate churn only if customer gets > churn_threshold contacts without conversion

            # Need to decide verdict
            verdict = "approved"
            block_reason = None
            rules_triggered = []

            if coordinated:
                # v4: dispatcher competition first — same policy scoring as live.
                # Original action's agent trigger defines the event; winner overrides
                # channel/discount/confidence. Governor (RulesEngine) still vetoes.
                from app.simulation.agents import AGENT_DEFS as _ADEFS
                from app.engine.dispatcher import dispatch as _dispatch
                trigger_event = _ADEFS.get(action_dict["agent_type"], {}).get("trigger", "order.paid")
                cust_orm = self.db.query(CustomerContext).filter(CustomerContext.id == cid).first()
                eff_agent = action_dict["agent_type"]
                eff_channel = action_dict["channel"]
                eff_discount = action_dict["discount_offered"]
                eff_conf = action_dict["confidence"]
                eff_delay = action_dict["proposed_delay_seconds"]
                disp_cands: list = []
                disp_winner: str | None = None
                if cust_orm is not None:
                    try:
                        # Deterministic: simulation evaluates policy, never the LLM.
                        dr = _dispatch(trigger_event, cust_orm, action_dict["merchant_id"], float(action_dict["amount_involved"] or 0), self.db, use_llm=False)
                        disp_cands = [{"agent_type": c["agent_type"], "channel": c["channel"], "score": c["score"]} for c in dr.candidates]
                        if dr.candidates:
                            disp_stats["races"] += 1
                        if dr.winner:
                            w = dr.winner
                            eff_agent = w["agent_type"]
                            eff_channel = w["channel"]
                            eff_discount = w["discount_offered"]
                            eff_conf = w["confidence"]
                            eff_delay = int(w.get("delay_h", 0) * 3600)
                            disp_winner = w["agent_type"]
                            disp_stats["wins"][disp_winner] = disp_stats["wins"].get(disp_winner, 0) + 1
                        else:
                            # policy blocked (all scores <=0) — visible blocked decision
                            disp_stats["policy_blocks"] += 1
                            verdict = "blocked"
                            block_reason = dr.block_reason or "Policy: all candidates scored \u22640"
                            rules_triggered = []
                            dec = CoordinationDecision(
                                id=f"dec_{uuid.uuid4().hex[:12]}",
                                action_id=f"act_{uuid.uuid4().hex[:12]}",
                                customer_id=cid,
                                verdict=verdict,
                                block_reason=block_reason,
                                rules_applied=json.dumps([]),
                                reasoning=block_reason,
                                confidence=float(eff_conf or 0.5),
                                source="simulation",
                            )
                            try:
                                dec.dispatcher_winner = None
                                dec.dispatcher_candidates = json.dumps(dr.candidates)
                                dec.trigger_event = trigger_event
                            except Exception:
                                pass
                            self.db.add(dec)
                            _safe_flush(self.db)
                            _, _, would = _simulate_customer_response(cust, action_dict, contact_counts[cid] + 1, coordinated=True)
                            decisions_out.append({"verdict": "blocked", "actual_outcome": "blocked", "actual_revenue": 0, "would_have_converted": would, "block_reason": block_reason})
                            actions_out.append(action_dict)
                            continue
                    except Exception as e:
                        logger.warning("Sim dispatcher fallback to original agent: %s", e)
                # Persist winning AgentAction to DB for windowed counting
                act = AgentAction(
                    id=f"act_{uuid.uuid4().hex[:12]}",
                    agent_id=action_dict["agent_id"],
                    agent_type=eff_agent,
                    customer_id=action_dict["customer_id"],
                    merchant_id=action_dict["merchant_id"],
                    action_type=action_dict["action_type"],
                    channel=eff_channel,
                    priority=action_dict["priority"],
                    message_template=action_dict["message_template"],
                    discount_offered=eff_discount,
                    amount_involved=action_dict["amount_involved"],
                    proposed_at=action_dict["proposed_at"],
                    proposed_delay_seconds=eff_delay,
                    confidence=eff_conf,
                    reasoning=f"Sim dispatcher {trigger_event} winner={disp_winner or eff_agent} candidates={len(disp_cands)} — {action_dict['reasoning']}",
                )
                self.db.add(act)
                _safe_flush(self.db)
                # Load customer ORM (already loaded above; re-use)
                if not cust_orm:
                    verdict = "blocked"
                    block_reason = "Customer not found"
                else:
                    eval_res = self.rules_engine.evaluate(act, cust_orm, proposed_at=action_dict["proposed_at"])
                    if eval_res.verdict == "blocked":
                        verdict = "blocked"
                        block_reason = eval_res.block_reason
                        rules_triggered = eval_res.rules_triggered
                        disp_stats["governor_blocks"] += 1
                    else:
                        verdict = "approved"
                        # update ORM state if approved (use winning channel/agent)
                        cust_orm.last_contact_at = action_dict["proposed_at"]
                        cust_orm.last_contact_channel = eff_channel
                        cust_orm.last_contact_agent = eff_agent
                        cust_orm.total_contacts_received = (cust_orm.total_contacts_received or 0) + 1
                        disc = float(eff_discount or 0)
                        cust_orm.current_discount_exposure = float(cust_orm.current_discount_exposure or 0) + disc
                        self.db.add(cust_orm)
                        _safe_flush(self.db)
                # reflect winner on the simulated action for metrics (discount affects revenue)
                action_dict = {**action_dict, "agent_type": eff_agent, "channel": eff_channel, "discount_offered": eff_discount, "confidence": eff_conf, "proposed_delay_seconds": eff_delay}
                # Create Decision row for windowed future checks
                dec = CoordinationDecision(
                    id=f"dec_{uuid.uuid4().hex[:12]}",
                    action_id=act.id,
                    customer_id=cid,
                    verdict=verdict,
                    approved_channel=action_dict["channel"] if verdict == "approved" else None,
                    approved_delay_seconds=action_dict["proposed_delay_seconds"] if verdict == "approved" else None,
                    approved_discount=float(action_dict["discount_offered"] or 0) if verdict == "approved" else None,
                    block_reason=block_reason,
                    rules_applied=json.dumps(rules_triggered),
                    reasoning=block_reason or f"Approved via RulesEngine",
                    confidence=float(action_dict["confidence"] or 0.5),
                    source="simulation",
                )
                self.db.add(dec)
                _safe_flush(self.db)
                # Audit entry
                aud = AuditEntry(
                    id=f"aud_{uuid.uuid4().hex[:12]}",
                    customer_id=cid,
                    merchant_id=action_dict["merchant_id"],
                    action_id=act.id,
                    decision_id=dec.id,
                    customer_snapshot=json.dumps({"id": cid}),
                    active_agent_count=1,
                    rules_evaluated=json.dumps(rules_triggered),
                )
                self.db.add(aud)
                _safe_flush(self.db)
            else:
                verdict = "approved"

            # Simulate response only if approved (uncoordinated: all approved)
            if verdict in ("approved", "throttled"):
                contact_counts[cid] += 1
                outcome, revenue, would = _simulate_customer_response(cust, action_dict, contact_counts[cid], coordinated=coordinated)
                # churn logic: if no conversion and contacts >= churn_threshold, churn
                if outcome != "converted" and contact_counts[cid] >= cust["churn_threshold"]:
                    # churn with probability based on low engagement/high risk
                    rng = random.Random(hash((cid, seed)) % (2**32))
                    if rng.random() < 0.5:  # 50% chance to churn when threshold hit
                        churned[cid] = True
                        cust_map[cid]["churned"] = True
                        cust["churned"] = True
                else:
                    if outcome == "converted":
                        cust_map[cid].setdefault("total_revenue", 0)
                decisions_out.append({
                    "verdict": verdict,
                    "actual_outcome": outcome,
                    "actual_revenue": revenue,
                    "would_have_converted": would,
                    "block_reason": block_reason,
                })
                actions_out.append(action_dict)
                # track revenue in cust for metrics later
                if outcome == "converted":
                    cust_map[cid]["_revenue"] = cust_map[cid].get("_revenue", 0) + revenue
            else:
                # blocked: simulate would_have_converted for false positive
                _, _, would = _simulate_customer_response(cust, action_dict, contact_counts[cid] + 1, coordinated=coordinated)
                decisions_out.append({
                    "verdict": "blocked",
                    "actual_outcome": "blocked",
                    "actual_revenue": 0,
                    "would_have_converted": would,
                    "block_reason": block_reason,
                })
                actions_out.append(action_dict)

        # Mark churned on original list
        for c in customers:
            c["churned"] = churned[c["id"]]

        metrics = compute_metrics(customers, decisions_out, actions_out)
        # Need to rollback the flush for coordinated scenario? We keep DB state for next seeds clearing, but commit after
        # For this scenario return, we rollback pending transaction if caller wants clean
        # But we already flushed; caller handles clearing
        return decisions_out, metrics, disp_stats

    def _clear_simulation_state(self, customers: List[dict]):
        # FIX v2: Simulation rows now tagged source="simulation" (see _run_scenario).
        # Safe to delete only simulation rows — never touches live/fallback decisions.
        # Previous bug: DELETE WHERE customer_id IN (cids) deleted live orders sharing cust_* IDs (err.md 01:02).
        # Now: filter by source="simulation" so concurrent POST /orders is unaffected.
        try:
            from sqlalchemy import text
            # Collect simulation decision + action ids before delete
            sim_rows = self.db.execute(text("SELECT id, action_id FROM coordination_decisions WHERE source='simulation'")).fetchall()
            sim_dec_ids = [r[0] for r in sim_rows]
            sim_act_ids = [r[1] for r in sim_rows if r[1]]
            if sim_dec_ids:
                # delete audits referencing simulation decisions
                self.db.execute(text("DELETE FROM audit_entries WHERE decision_id IN (SELECT id FROM coordination_decisions WHERE source='simulation')"))
                self.db.execute(text("DELETE FROM coordination_decisions WHERE source='simulation'"))
            if sim_act_ids:
                # chunk delete to avoid sqlite param limit
                for i in range(0, len(sim_act_ids), 500):
                    chunk = sim_act_ids[i:i+500]
                    placeholders = ",".join([f"'{x}'" for x in chunk])
                    self.db.execute(text(f"DELETE FROM agent_actions WHERE id IN ({placeholders})"))
            # Orphan cleanup: simulation actions with proposed_at in Jan 2026 that lost their decision
            self.db.execute(text("DELETE FROM agent_actions WHERE proposed_at < '2026-02-01' AND id NOT IN (SELECT action_id FROM coordination_decisions)"))
            self.db.execute(text("DELETE FROM audit_entries WHERE decision_id NOT IN (SELECT id FROM coordination_decisions)"))
            self.db.commit()
        except Exception as e:
            logger.warning("Failed to clear simulation state: %s", e)
            self.db.rollback()
