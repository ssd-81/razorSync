import uuid
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.schemas import ActionProposeRequest
from app.models.action import AgentAction
from app.models.customer import CustomerContext
from app.engine.coordinator import CoordinationEngine

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/actions", tags=["actions"])


@router.post("/propose")
def propose_action(payload: ActionProposeRequest, db: Session = Depends(get_db)):
    # ensure customer exists
    customer = db.query(CustomerContext).filter(CustomerContext.id == payload.customer_id).first()
    if not customer:
        logger.warning(" propose for unknown customer %s", payload.customer_id)
        raise HTTPException(status_code=404, detail="Customer not found")

    proposed_at = payload.proposed_at or datetime.now(timezone.utc)
    if proposed_at.tzinfo is None:
        proposed_at = proposed_at.replace(tzinfo=timezone.utc)

    action = AgentAction(
        id=f"act_{uuid.uuid4().hex[:12]}",
        agent_id=payload.agent_id,
        agent_type=payload.agent_type,
        customer_id=payload.customer_id,
        merchant_id=payload.merchant_id or customer.merchant_id,
        action_type=payload.action_type,
        channel=payload.channel,
        priority=payload.priority,
        message_template=payload.message_template,
        discount_offered=payload.discount_offered,
        amount_involved=payload.amount_involved,
        proposed_at=proposed_at,
        proposed_delay_seconds=payload.proposed_delay_seconds,
        confidence=payload.confidence,
        reasoning=payload.reasoning,
    )
    db.add(action)
    db.flush()

    engine = CoordinationEngine(db)
    decision = engine.process_action(action)

    return {
        "action_id": action.id,
        "decision_id": decision.id,
        "verdict": decision.verdict,
        "block_reason": decision.block_reason,
        "approved_channel": decision.approved_channel,
        "reasoning": decision.reasoning,
        "estimated_revenue_impact": decision.estimated_revenue_impact,
    }


@router.get("/{action_id}")
def get_action(action_id: str, db: Session = Depends(get_db)):
    action = db.query(AgentAction).filter(AgentAction.id == action_id).first()
    if not action:
        raise HTTPException(status_code=404, detail="Action not found")
    # get decision
    from app.models.decision import CoordinationDecision
    decision = db.query(CoordinationDecision).filter(CoordinationDecision.action_id == action_id).first()
    return {
        "action": {
            "id": action.id,
            "agent_type": action.agent_type,
            "customer_id": action.customer_id,
            "channel": action.channel,
            "priority": action.priority,
            "amount_involved": action.amount_involved,
            "discount_offered": action.discount_offered,
            "proposed_at": action.proposed_at,
            "confidence": action.confidence,
        },
        "decision": {
            "id": decision.id if decision else None,
            "verdict": decision.verdict if decision else None,
            "block_reason": decision.block_reason if decision else None,
            "reasoning": decision.reasoning if decision else None,
        } if decision else None,
    }
