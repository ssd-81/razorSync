"""v3 Execution Chain API — returns execution timeline data for DAG visualization.

DECISION V3-13: DAG Visualization — vertical timeline per event:
Webhook → Dispatcher (candidates) → Policy winner → Guardrail check → (SUSPENDED → Human) → Executed
"""
import json
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.db.database import get_db
from app.models.decision import CoordinationDecision
from app.models.action import AgentAction
from app.models.audit import AuditEntry
from app.models.hitl import SuspendedAction, HITLTicket
from app.utils.time import utc_iso

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/execution", tags=["execution"])


@router.get("/chain")
def get_execution_chain(
    limit: int = 10,
    since: str = None,
    db: Session = Depends(get_db),
):
    """Get recent execution chains for DAG visualization.

    Each chain represents one webhook event → decision → outcome.
    Returns timeline nodes with reasoning, scores, latency.
    """
    query = (
        db.query(CoordinationDecision)
        .order_by(desc(CoordinationDecision.created_at))
        .limit(limit)
    )
    if since:
        try:
            since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
            query = query.filter(CoordinationDecision.created_at > since_dt)
        except Exception:
            pass

    decisions = query.all()
    chains = []

    for dec in decisions:
        # Load action
        action = db.query(AgentAction).filter(AgentAction.id == dec.action_id).first()

        # Load audit
        audit = db.query(AuditEntry).filter(AuditEntry.decision_id == dec.id).first()

        # Check if suspended
        suspended = None
        ticket = None
        if "SUSPENDED" in (dec.block_reason or ""):
            # Extract ticket ID from block_reason
            import re
            match = re.search(r"ticket (ticket_\w+)", dec.block_reason or "")
            if match:
                ticket_id = match.group(1)
                ticket = db.query(HITLTicket).filter(HITLTicket.id == ticket_id).first()
                if ticket:
                    suspended = db.query(SuspendedAction).filter(
                        SuspendedAction.id == ticket.suspended_action_id
                    ).first()

        # Build timeline nodes
        nodes = []

        # Node 1: Event received
        nodes.append({
            "type": "event",
            "label": "Webhook / Order",
            "status": "completed",
            "detail": f"Event for customer {dec.customer_id}",
            "timestamp": utc_iso(dec.created_at),
        })

        # v4: persisted dispatcher trace — real candidates, not string parsing.
        try:
            candidates = json.loads(getattr(dec, "dispatcher_candidates", None) or "[]")
        except Exception:
            candidates = []
        trigger_event = getattr(dec, "trigger_event", None) or (audit.webhook_event if audit and audit.webhook_event else "order/live")
        winner_type = getattr(dec, "dispatcher_winner", None) or (action.agent_type if action else None)
        # score lookup for winner (persisted breakdown) else parse legacy reasoning
        score = None
        for _c in candidates:
            if _c.get("agent_type") == winner_type:
                score = _c.get("score")
                break
        if score is None and action and action.reasoning and "score=" in action.reasoning:
            import re as _re
            _m = _re.search(r"score=([\d.\-]+)", action.reasoning)
            if _m:
                try:
                    score = float(_m.group(1))
                except Exception:
                    score = None
        nodes.append({
            "type": "dispatcher",
            "label": f"Dispatcher — {trigger_event}",
            "status": "completed",
            "detail": f"{len(candidates)} candidate(s) scored; winner {winner_type}" if candidates else (action.reasoning if action and action.reasoning else f"Agent: {winner_type}"),
            "agent_type": winner_type,
            "channel": action.channel if action else None,
            "candidates": candidates,
            "winner": winner_type,
        })

        # Node 3: Policy score (winner + full candidate list for UI table)
        nodes.append({
            "type": "policy",
            "label": "Policy",
            "status": "completed",
            "detail": f"Winner {winner_type} score: {score:.4f}" if isinstance(score, (int, float)) else f"Winner {winner_type}",
            "score": score,
            "candidates": candidates,
            "winner": winner_type,
        })

        # Node 4: Guardrail check
        guardrail_status = "passed"
        guardrail_detail = "All guardrails passed"
        if dec.verdict == "blocked":
            if "SUSPENDED" in (dec.block_reason or ""):
                guardrail_status = "suspended"
                guardrail_detail = dec.block_reason
            else:
                guardrail_status = "blocked"
                guardrail_detail = dec.block_reason or "Blocked by rule"
        nodes.append({
            "type": "guardrail",
            "label": "Guardrail",
            "status": guardrail_status,
            "detail": guardrail_detail,
        })

        # Node 5: HITL (if suspended)
        if suspended and ticket:
            hitl_status = ticket.status or "pending"
            nodes.append({
                "type": "hitl",
                "label": "Human Review",
                "status": hitl_status,
                "detail": ticket.reason or "Awaiting review",
                "ticket_id": ticket.id,
                "decision": ticket.decision,
                "override": ticket.override,
            })

        # Node 6: Outcome
        nodes.append({
            "type": "outcome",
            "label": "Outcome",
            "status": dec.verdict,
            "detail": f"Verdict: {dec.verdict} — {dec.reasoning or ''}",
            "verdict": dec.verdict,
            "source": dec.source,
        })

        try:
            _cands_out = json.loads(getattr(dec, "dispatcher_candidates", None) or "[]")
        except Exception:
            _cands_out = []
        chains.append({
            "decision_id": dec.id,
            "customer_id": dec.customer_id,
            "agent_type": action.agent_type if action else None,
            "channel": action.channel if action else None,
            "source": dec.source,
            "trigger_event": getattr(dec, "trigger_event", None) or (audit.webhook_event if audit and audit.webhook_event else None),
            "dispatcher_winner": getattr(dec, "dispatcher_winner", None),
            "dispatcher_candidates": _cands_out,
            "message_preview": action.message_template if action else None,
            "verdict": dec.verdict,
            "block_reason": dec.block_reason,
            "created_at": utc_iso(dec.created_at),
            "nodes": nodes,
        })

    return {"chains": chains, "count": len(chains)}


@router.get("/stream")
def get_execution_stream(db: Session = Depends(get_db)):
    """Get latest execution for real-time SSE-like polling (simplified polling view)."""
    latest = (
        db.query(CoordinationDecision)
        .order_by(desc(CoordinationDecision.created_at))
        .first()
    )
    if not latest:
        return {"latest": None}

    action = db.query(AgentAction).filter(AgentAction.id == latest.action_id).first()
    return {
        "latest": {
            "decision_id": latest.id,
            "verdict": latest.verdict,
            "customer_id": latest.customer_id,
            "agent_type": action.agent_type if action else None,
            "channel": action.channel if action else None,
            "reasoning": latest.reasoning,
            "source": latest.source,
            "created_at": utc_iso(latest.created_at),
        }
    }
