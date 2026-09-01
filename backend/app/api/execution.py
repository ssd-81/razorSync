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
            "timestamp": dec.created_at.isoformat() if dec.created_at else None,
        })

        # Node 2: Dispatcher candidates (from action reasoning)
        if action and action.reasoning and "Dispatcher" in (action.reasoning or ""):
            nodes.append({
                "type": "dispatcher",
                "label": "Dispatcher",
                "status": "completed",
                "detail": action.reasoning,
                "agent_type": action.agent_type,
                "channel": action.channel,
            })
        else:
            nodes.append({
                "type": "dispatcher",
                "label": "Dispatcher",
                "status": "completed",
                "detail": f"Agent: {action.agent_type if action else 'unknown'}",
                "agent_type": action.agent_type if action else None,
            })

        # Node 3: Policy score
        score = None
        if action and action.reasoning and "score=" in action.reasoning:
            import re
            score_match = re.search(r"score=([\d.]+)", action.reasoning)
            if score_match:
                score = float(score_match.group(1))
        nodes.append({
            "type": "policy",
            "label": "Policy",
            "status": "completed",
            "detail": f"Score: {score:.4f}" if score else "Score: N/A",
            "score": score,
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

        chains.append({
            "decision_id": dec.id,
            "customer_id": dec.customer_id,
            "agent_type": action.agent_type if action else None,
            "channel": action.channel if action else None,
            "source": dec.source,
            "created_at": dec.created_at.isoformat() if dec.created_at else None,
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
            "created_at": latest.created_at.isoformat() if latest.created_at else None,
        }
    }
