"""v3 HITL API — suspend, resume, override.

DECISION V3-11: Async execution suspension — save state, push to queue, worker exits.
DECISION V3-12: Override with audit — maker-checker pattern, reason required.
"""
import uuid
import json
import logging
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from typing import Optional

from app.db.database import get_db
from app.utils.time import utc_iso
from app.models.hitl import SuspendedAction, HITLTicket
from app.models.decision import CoordinationDecision
from app.models.action import AgentAction
from app.models.customer import CustomerContext
from app.models.audit import AuditEntry
from app.engine.rules import RulesEngine

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/hitl", tags=["hitl"])

# v3: Hard guardrail thresholds — from BusinessRule.rule_config
HARD_GUARDRAILS = {
    "financial_ceiling": {"max_auto_approval": 2000},  # ₹2000 auto, above → SUSPEND
    "state_conflict": {"flags": ["fraud_flag", "dispute_flag"]},  # active flag → SUSPEND
}

SUSPENSION_TTL_HOURS = 24  # auto-reject after 24h


class ResumeRequest(BaseModel):
    decision: str = Field(..., pattern="^(approve|reject|edit)$")
    discount: Optional[float] = Field(None, ge=0)
    reason: Optional[str] = None
    edited_payload: Optional[dict] = None


class TicketResponse(BaseModel):
    id: str
    suspended_action_id: str
    reason: Optional[str]
    status: str
    created_at: Optional[str]
    expires_at: Optional[str]


def check_hard_guardrails(action: AgentAction, customer: CustomerContext, db: Session) -> Optional[dict]:
    """Check if action hits a hard guardrail (SUSPEND) vs soft (BLOCK).
    Returns None if no hard guardrail triggered, or dict with guardrail info.
    """
    amount = float(action.amount_involved or 0)
    discount = float(action.discount_offered or 0)

    # Financial ceiling: amount_involved > max_auto_approval → SUSPEND
    # (amount is the total action value; discount is subset)
    max_auto = HARD_GUARDRAILS["financial_ceiling"]["max_auto_approval"]
    if amount > max_auto:
        return {
            "guardrail": "financial_ceiling",
            "reason": f"Action amount ₹{amount} exceeds auto-approval ceiling ₹{max_auto} — requires human approval",
            "original_ceiling": max_auto,
        }

    # State conflict: fraud/dispute flag active → SUSPEND
    if customer.risk_score and customer.risk_score >= 0.8:
        return {
            "guardrail": "state_conflict",
            "reason": f"High risk score {customer.risk_score} — possible fraud/dispute flag active",
            "original_ceiling": max_auto,
        }

    return None


def suspend_action(action: AgentAction, customer: CustomerContext, guardrail_info: dict, db: Session) -> dict:
    """Save action state and create HITL ticket. Returns ticket info."""
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=SUSPENSION_TTL_HOURS)

    # Snapshot customer state
    customer_snapshot = json.dumps({
        "id": customer.id,
        "risk_score": customer.risk_score,
        "engagement_score": customer.engagement_score,
        "total_contacts_received": customer.total_contacts_received,
        "current_discount_exposure": customer.current_discount_exposure,
        "lifetime_value": customer.lifetime_value,
    })

    # Action payload for resume
    action_payload = json.dumps({
        "agent_id": action.agent_id,
        "agent_type": action.agent_type,
        "customer_id": action.customer_id,
        "merchant_id": action.merchant_id,
        "action_type": action.action_type,
        "channel": action.channel,
        "priority": action.priority,
        "message_template": action.message_template,
        "discount_offered": action.discount_offered,
        "amount_involved": action.amount_involved,
        "proposed_at": utc_iso(action.proposed_at),
        "proposed_delay_seconds": action.proposed_delay_seconds,
        "confidence": action.confidence,
        "reasoning": action.reasoning,
    })

    # Create suspended action
    suspended = SuspendedAction(
        id=f"sus_{uuid.uuid4().hex[:12]}",
        customer_id=action.customer_id,
        merchant_id=action.merchant_id or customer.merchant_id,
        action_payload=action_payload,
        guardrail_triggered=guardrail_info["guardrail"],
        guardrail_reason=guardrail_info["reason"],
        customer_snapshot=customer_snapshot,
        status="pending",
        expires_at=expires_at,
    )
    db.add(suspended)

    # Create HITL ticket
    ticket = HITLTicket(
        id=f"ticket_{uuid.uuid4().hex[:12]}",
        suspended_action_id=suspended.id,
        reason=guardrail_info["reason"],
        status="pending",
    )
    db.add(ticket)
    db.flush()

    logger.info("SUSPENDED action %s for customer %s — guardrail: %s, ticket: %s",
                action.id, action.customer_id, guardrail_info["guardrail"], ticket.id)

    return {
        "suspended_action_id": suspended.id,
        "ticket_id": ticket.id,
        "guardrail": guardrail_info["guardrail"],
        "reason": guardrail_info["reason"],
        "expires_at": utc_iso(expires_at),
    }


@router.get("/pending")
def list_pending_tickets(db: Session = Depends(get_db)):
    """List all pending HITL tickets."""
    tickets = (
        db.query(HITLTicket)
        .filter(HITLTicket.status == "pending")
        .order_by(HITLTicket.created_at.desc())
        .all()
    )
    result = []
    for t in tickets:
        suspended = db.query(SuspendedAction).filter(SuspendedAction.id == t.suspended_action_id).first()
        result.append({
            "ticket_id": t.id,
            "suspended_action_id": t.suspended_action_id,
            "reason": t.reason,
            "guardrail": suspended.guardrail_triggered if suspended else None,
            "customer_id": suspended.customer_id if suspended else None,
            "created_at": utc_iso(t.created_at),
            "expires_at": utc_iso(suspended.expires_at) if suspended else None,
            "action_payload": json.loads(suspended.action_payload) if suspended else None,
        })
    return {"tickets": result, "count": len(result)}


@router.get("/{ticket_id}")
def get_ticket(ticket_id: str, db: Session = Depends(get_db)):
    """Get a specific HITL ticket with full context."""
    ticket = db.query(HITLTicket).filter(HITLTicket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    suspended = db.query(SuspendedAction).filter(SuspendedAction.id == ticket.suspended_action_id).first()
    return {
        "ticket": {
            "id": ticket.id,
            "suspended_action_id": ticket.suspended_action_id,
            "reason": ticket.reason,
            "status": ticket.status,
            "decision": ticket.decision,
            "override": ticket.override,
            "override_reason": ticket.override_reason,
            "created_at": utc_iso(ticket.created_at),
            "resumed_at": utc_iso(ticket.resumed_at),
        },
        "suspended_action": {
            "id": suspended.id if suspended else None,
            "customer_id": suspended.customer_id if suspended else None,
            "guardrail": suspended.guardrail_triggered if suspended else None,
            "guardrail_reason": suspended.guardrail_reason if suspended else None,
            "action_payload": json.loads(suspended.action_payload) if suspended else None,
            "customer_snapshot": json.loads(suspended.customer_snapshot) if suspended else None,
            "expires_at": utc_iso(suspended.expires_at) if suspended else None,
            "status": suspended.status if suspended else None,
        } if suspended else None,
    }


@router.post("/{ticket_id}/resume")
def resume_ticket(ticket_id: str, payload: ResumeRequest, db: Session = Depends(get_db)):
    """Resume a suspended action — approve, reject, or edit+approve.

    DECISION V3-12: Override requires reason. Re-validates Memory (stale approve risk).
    """
    ticket = db.query(HITLTicket).filter(HITLTicket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if ticket.status != "pending":
        raise HTTPException(status_code=400, detail=f"Ticket already {ticket.status}")

    suspended = db.query(SuspendedAction).filter(SuspendedAction.id == ticket.suspended_action_id).first()
    if not suspended:
        raise HTTPException(status_code=404, detail="Suspended action not found")

    # Check expiry — handle naive datetime from SQLite
    now_utc = datetime.now(timezone.utc)
    expires = suspended.expires_at
    if expires:
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires < now_utc:
            suspended.status = "expired"
            ticket.status = "expired"
            db.commit()
            raise HTTPException(status_code=400, detail="Ticket expired — auto-rejected after 24h")

    now = datetime.now(timezone.utc)
    action_payload = json.loads(suspended.action_payload)

    if payload.decision == "reject":
        # Simply reject — no execution
        ticket.decision = "reject"
        ticket.status = "rejected"
        ticket.resumed_at = now
        suspended.status = "rejected"

        # Audit the rejection
        _audit_hitl(ticket, suspended, "rejected", payload.reason, db)
        db.commit()

        return {"status": "rejected", "ticket_id": ticket_id}

    elif payload.decision in ("approve", "edit"):
        # Determine final payload (edited or original)
        final_payload = payload.edited_payload if payload.decision == "edit" and payload.edited_payload else action_payload
        discount = payload.discount if payload.discount is not None else final_payload.get("discount_offered", 0)

        # RE-VALIDATE: Check if guardrail still applies (stale approve risk)
        customer = db.query(CustomerContext).filter(CustomerContext.id == suspended.customer_id).first()
        if customer:
            # Re-check state conflict (fraud flag may have arrived while suspended)
            if customer.risk_score and customer.risk_score >= 0.8:
                # Fraud flag still active — block even after human approval
                ticket.decision = "blocked_revalidate"
                ticket.status = "rejected"
                ticket.resumed_at = now
                suspended.status = "rejected"
                _audit_hitl(ticket, suspended, "blocked_revalidate",
                           "Re-validation failed: fraud flag still active", db)
                db.commit()
                return {"status": "blocked_revalidate",
                        "reason": "Fraud flag still active — re-validation failed"}

        # Override tracking (maker-checker)
        is_override = discount > HARD_GUARDRAILS["financial_ceiling"]["max_auto_approval"]
        if is_override and not payload.reason:
            raise HTTPException(status_code=400, detail="Override requires reason (maker-checker)")

        # Execute: create the action + run coordination
        from app.engine.coordinator import CoordinationEngine

        action = AgentAction(
            id=f"act_{uuid.uuid4().hex[:12]}",
            agent_id=action_payload.get("agent_id", "hitl_resume"),
            agent_type=action_payload.get("agent_type", "autopay_retry"),
            customer_id=suspended.customer_id,
            merchant_id=suspended.merchant_id,
            action_type=action_payload.get("action_type", "hitl_approved"),
            channel=action_payload.get("channel", "whatsapp"),
            priority=action_payload.get("priority", 5),
            message_template=action_payload.get("message_template"),
            discount_offered=discount,
            amount_involved=action_payload.get("amount_involved", 0),
            proposed_at=now,
            proposed_delay_seconds=action_payload.get("proposed_delay_seconds", 0),
            confidence=action_payload.get("confidence", 0.7),
            reasoning=f"HITL {payload.decision}: {payload.reason or 'approved'}",
        )
        db.add(action)
        db.flush()

        engine = CoordinationEngine(db)
        decision = engine.process_action(action)
        decision.source = "hitl"
        db.commit()

        # Update ticket
        ticket.decision = payload.decision
        ticket.status = "approved"
        ticket.resumed_at = now
        ticket.override = is_override
        ticket.override_reason = payload.reason if is_override else None
        ticket.original_ceiling = HARD_GUARDRAILS["financial_ceiling"]["max_auto_approval"]
        ticket.approved_amount = discount
        if payload.decision == "edit":
            ticket.edited_payload = json.dumps(payload.edited_payload)

        suspended.status = "approved"
        db.commit()

        # Audit
        _audit_hitl(ticket, suspended, payload.decision, payload.reason, db)
        db.commit()

        return {
            "status": "approved",
            "ticket_id": ticket_id,
            "decision_id": decision.id,
            "verdict": decision.verdict,
            "override": is_override,
        }


@router.post("/check-expired")
def check_expired(db: Session = Depends(get_db)):
    """Auto-reject expired tickets (called periodically or on-demand)."""
    now = datetime.now(timezone.utc)
    expired = (
        db.query(SuspendedAction)
        .filter(SuspendedAction.status == "pending", SuspendedAction.expires_at < now)
        .all()
    )
    count = 0
    for sus in expired:
        sus.status = "expired"
        ticket = db.query(HITLTicket).filter(
            HITLTicket.suspended_action_id == sus.id,
            HITLTicket.status == "pending",
        ).first()
        if ticket:
            ticket.status = "expired"
            ticket.decision = "auto_reject"
            ticket.resumed_at = now
            _audit_hitl(ticket, sus, "expired", "Auto-rejected after 24h", db)
        count += 1
    db.commit()
    return {"expired": count}


def _audit_hitl(ticket: HITLTicket, suspended: SuspendedAction, decision_type: str, reason: str, db: Session):
    """Create audit entry for HITL decisions."""
    try:
        entry = AuditEntry(
            id=f"aud_{uuid.uuid4().hex[:12]}",
            customer_id=suspended.customer_id,
            merchant_id=suspended.merchant_id,
            action_id=f"hitl_{ticket.id}",
            decision_id=f"hitl_{ticket.id}",
            customer_snapshot=suspended.customer_snapshot,
            active_agent_count=0,
            rules_evaluated=json.dumps([suspended.guardrail_triggered]),
            actual_outcome=decision_type,
            webhook_event=f"hitl_{decision_type}",
        )
        db.add(entry)
        db.flush()
    except Exception as e:
        logger.warning("Failed to create HITL audit entry: %s", e)
