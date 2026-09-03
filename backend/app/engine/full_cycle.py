"""v4 Full-cycle helper — one shared path for every live decision.

Event → Dispatcher (all candidates scored) → winning AgentAction
(with rendered message preview) → Coordinator (guardrails/rules) →
Decision with persisted dispatcher trace + Audit.

Used by POST /orders AND the webhook reasoning worker, so both show
the same "coordination decision in action" instead of diverging.
"""
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from sqlalchemy.orm import Session

from app.config import settings
from app.db.database import commit_with_retry
from app.models.action import AgentAction
from app.models.audit import AuditEntry
from app.models.decision import CoordinationDecision

logger = logging.getLogger(__name__)

# Per-agent message preview — what the customer would actually receive.
# Rendered with customer name + amount + order ref so the UI can show
# agents "doing" something real, not just a verdict pill.
MESSAGE_TEMPLATES = {
    "autopay_retry": "Hi {name}, your autopay of ₹{amount:.2f} failed (ref {ref}). Retry securely: {channel} link — no extra charge.",
    "payment_link_recovery": "Hi {name}, your payment link for ₹{amount:.2f} is waiting (ref {ref}). Complete it here via {channel}{discount}.",
    "invoice_dunning": "Hi {name}, invoice {ref} for ₹{amount:.2f} is overdue. Pay now via {channel} to avoid interruption.",
    "x_payout_growth": "Hi {name}, ₹{amount:.2f} received (ref {ref})! Unlock faster payouts with RazorpayX — see {channel}.",
}


def render_message(agent_type: str, name: str, amount: float, ref: str, channel: str, discount: float = 0) -> str:
    tmpl = MESSAGE_TEMPLATES.get(agent_type, "Hi {name}, update on ₹{amount:.2f} (ref {ref}) via {channel}.")
    disc = f" with ₹{discount:.2f} off" if discount else ""
    try:
        return tmpl.format(name=name or "there", amount=float(amount or 0), ref=ref or "n/a", channel=channel, discount=disc)
    except Exception:
        return tmpl


def trace_payload(dispatcher_result) -> Dict[str, Any]:
    """Serialize dispatcher result for persistence + API."""
    cands = []
    for c in (dispatcher_result.candidates if dispatcher_result else []):
        cands.append({
            "agent_type": c.get("agent_type"),
            "channel": c.get("channel"),
            "score": c.get("score"),
            "confidence": c.get("confidence"),
            "discount_offered": c.get("discount_offered", 0),
            "source": c.get("source", "deterministic"),
            "score_breakdown": c.get("score_breakdown", {}),
            # v4.1: agent response payload — what the agent actually proposed
            "reasoning": c.get("reasoning"),
            "delay_h": c.get("delay_h", 0),
            "llm_latency_s": c.get("llm_latency_s"),
        })
    return {
        "candidates": cands,
        "winner": dispatcher_result.winner["agent_type"] if dispatcher_result and dispatcher_result.winner else None,
        "winner_score": dispatcher_result.winner["score"] if dispatcher_result and dispatcher_result.winner else None,
        "all_blocked": bool(dispatcher_result.all_blocked) if dispatcher_result else True,
        "block_reason": dispatcher_result.block_reason if dispatcher_result else None,
    }


def attach_trace(decision: CoordinationDecision, event: str, info: Dict[str, Any], db: Session) -> None:
    try:
        decision.trigger_event = event
        decision.dispatcher_winner = info.get("winner")
        decision.dispatcher_candidates = json.dumps(info.get("candidates", []))
        db.add(decision)
        db.flush()
    except Exception as e:
        logger.warning("Failed to attach dispatch trace to %s: %s", getattr(decision, "id", "?"), e)


def run_full_cycle(
    db: Session,
    event: str,
    customer,
    amount: float,
    source: str = "live",
    order_id: Optional[str] = None,
    action_prefix: str = "webhook",
) -> Dict[str, Any]:
    """Run Event → Dispatcher → Coordinator, persist trace, return API-ready dict."""
    from app.engine.dispatcher import dispatch
    from app.engine.coordinator import CoordinationEngine

    merchant_id = getattr(customer, "merchant_id", None) or settings.MERCHANT_ID
    customer_id = customer.id
    customer_name = getattr(customer, "name", None) or customer_id

    result = dispatch(event, customer, merchant_id, float(amount or 0), db)
    info = trace_payload(result)
    info["event"] = event

    # --- No eligible agents: visible blocked decision so polling never hangs ---
    if not result.candidates:
        now = datetime.now(timezone.utc)
        action = AgentAction(
            id=f"act_{uuid.uuid4().hex[:12]}",
            agent_id=f"no_candidate_{action_prefix}_{uuid.uuid4().hex[:6]}",
            agent_type="none",
            customer_id=customer_id,
            merchant_id=merchant_id,
            action_type=f"{action_prefix}_{event}",
            channel="none",
            priority=1,
            message_template=f"No agent handles event {event} (ref {order_id or 'n/a'}).",
            discount_offered=0.0,
            amount_involved=float(amount or 0),
            proposed_at=now,
            proposed_delay_seconds=0,
            confidence=0.5,
            reasoning=f"No eligible agents for event: {event}",
        )
        db.add(action)
        db.flush()
        decision = CoordinationDecision(
            id=f"dec_{uuid.uuid4().hex[:12]}",
            action_id=action.id,
            customer_id=customer_id,
            verdict="blocked",
            block_reason=result.block_reason or f"No eligible agents for event: {event}",
            rules_applied="[]",
            reasoning=result.block_reason or "No eligible agents",
            confidence=0.5,
            source=source,
        )
        db.add(decision)
        db.flush()
        attach_trace(decision, event, info, db)
        db.add(AuditEntry(
            id=f"aud_{uuid.uuid4().hex[:12]}",
            customer_id=customer_id,
            merchant_id=merchant_id,
            action_id=action.id,
            decision_id=decision.id,
            customer_snapshot=json.dumps({"id": customer_id}),
            active_agent_count=0,
            rules_evaluated=json.dumps([]),
            webhook_event=event,
            razorpay_order_id=order_id,
        ))
        commit_with_retry(db)
        return {"decision": decision, "action": action, "dispatcher": info, "policy_blocked": False}

    # --- Policy blocked (all scores ≤ 0): persisted blocked decision ---
    if not result.winner:
        best = result.candidates[0]
        now = datetime.now(timezone.utc)
        action = AgentAction(
            id=f"act_{uuid.uuid4().hex[:12]}",
            agent_id=f"{best['agent_type']}_policy_block_{uuid.uuid4().hex[:6]}",
            agent_type=best["agent_type"],
            customer_id=customer_id,
            merchant_id=merchant_id,
            action_type=f"{action_prefix}_{event}",
            channel=best["channel"],
            priority=7,
            message_template=render_message(best["agent_type"], customer_name, float(amount or 0), order_id or event, best["channel"], float(best.get("discount_offered") or 0)),
            discount_offered=float(best.get("discount_offered") or 0),
            amount_involved=float(amount or 0),
            proposed_at=now,
            proposed_delay_seconds=int(best.get("delay_h", 0) * 3600),
            confidence=float(best.get("confidence") or 0.5),
            reasoning=f"Policy blocked — {result.block_reason}",
        )
        db.add(action)
        db.flush()
        decision = CoordinationDecision(
            id=f"dec_{uuid.uuid4().hex[:12]}",
            action_id=action.id,
            customer_id=customer_id,
            verdict="blocked",
            block_reason=result.block_reason or "Policy: all candidates scored ≤0",
            rules_applied="[]",
            reasoning=f"Policy blocked — {result.block_reason}",
            confidence=float(best.get("confidence") or 0.5),
            source=source,
        )
        db.add(decision)
        db.flush()
        attach_trace(decision, event, info, db)
        db.add(AuditEntry(
            id=f"aud_{uuid.uuid4().hex[:12]}",
            customer_id=customer_id,
            merchant_id=merchant_id,
            action_id=action.id,
            decision_id=decision.id,
            customer_snapshot=json.dumps({"id": customer_id, "dispatcher_block": True}),
            active_agent_count=len(result.candidates),
            rules_evaluated=json.dumps([]),
            webhook_event=event,
            razorpay_order_id=order_id,
        ))
        commit_with_retry(db)
        logger.info("Policy blocked %s → %s: %s", event, decision.id, decision.block_reason)
        return {"decision": decision, "action": action, "dispatcher": info, "policy_blocked": True}

    # --- Winner path: winning proposal becomes the AgentAction, then governed ---
    winner = result.winner
    now = datetime.now(timezone.utc)
    ref = order_id or event
    message = render_message(winner["agent_type"], customer_name, float(amount or 0), ref, winner["channel"], float(winner.get("discount_offered") or 0))
    action = AgentAction(
        id=f"act_{uuid.uuid4().hex[:12]}",
        agent_id=f"{winner['agent_type']}_{action_prefix}_{uuid.uuid4().hex[:6]}",
        agent_type=winner["agent_type"],
        customer_id=customer_id,
        merchant_id=merchant_id,
        action_type=f"{action_prefix}_{event}",
        channel=winner["channel"],
        priority=7,
        message_template=message,
        discount_offered=float(winner.get("discount_offered") or 0),
        amount_involved=float(amount or 0),
        proposed_at=now,
        proposed_delay_seconds=int(winner.get("delay_h", 0) * 3600),
        confidence=float(winner.get("confidence") or 0.7),
        reasoning=f"Dispatcher winner: {winner['agent_type']} (score={winner['score']:.4f}) — {winner.get('reasoning', '')}",
    )
    db.add(action)
    db.flush()

    engine = CoordinationEngine(db)
    decision = engine.process_action(action)
    try:
        decision.source = source
        db.add(decision)
        db.flush()
        attach_trace(decision, event, info, db)
        commit_with_retry(db)
        db.refresh(decision)
    except Exception:
        commit_with_retry(db)

    try:
        audit = db.query(AuditEntry).filter(AuditEntry.decision_id == decision.id).first()
        if audit:
            audit.webhook_event = event
            audit.razorpay_order_id = order_id
            try:
                snap = json.loads(audit.customer_snapshot or "{}")
            except Exception:
                snap = {}
            snap["dispatcher_winner"] = winner["agent_type"]
            snap["dispatcher_candidates"] = len(info["candidates"])
            audit.customer_snapshot = json.dumps(snap)
            audit.active_agent_count = len(info["candidates"])
            db.add(audit)
            commit_with_retry(db)
    except Exception as e:
        logger.warning("Audit enrichment failed: %s", e)

    logger.info("Full-cycle %s → winner %s → %s (%s)", event, winner["agent_type"], decision.id, decision.verdict)
    return {"decision": decision, "action": action, "dispatcher": info, "policy_blocked": False}
