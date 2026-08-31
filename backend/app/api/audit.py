import json
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.db.database import get_db
from app.models.audit import AuditEntry
from app.models.decision import CoordinationDecision
from app.models.action import AgentAction

router = APIRouter(prefix="/api/v1/audit", tags=["audit"])


@router.get("")
def get_audit(
    merchant_id: Optional[str] = Query(None),
    customer_id: Optional[str] = Query(None),
    verdict: Optional[str] = Query(None),
    agent_type: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    # Build filtered query in SQL (fix H4: total counted before filtering was bug)
    # We join AuditEntry -> CoordinationDecision -> AgentAction for filtering by verdict/agent_type

    base_q = db.query(AuditEntry)

    # Need joins for verdict/agent_type filters
    if verdict or agent_type:
        base_q = base_q.join(CoordinationDecision, AuditEntry.decision_id == CoordinationDecision.id)
    if agent_type:
        base_q = base_q.join(AgentAction, AuditEntry.action_id == AgentAction.id)

    filters = []
    if merchant_id:
        filters.append(AuditEntry.merchant_id == merchant_id)
    if customer_id:
        filters.append(AuditEntry.customer_id == customer_id)
    if verdict:
        filters.append(CoordinationDecision.verdict == verdict)
    if agent_type:
        filters.append(AgentAction.agent_type == agent_type)

    if filters:
        base_q = base_q.filter(and_(*filters))

    total = base_q.count()

    rows = base_q.order_by(AuditEntry.timestamp.desc()).offset(offset).limit(limit).all()

    # To include decision data, fetch decisions map
    entries = []
    for a in rows:
        dec = db.query(CoordinationDecision).filter(CoordinationDecision.id == a.decision_id).first()
        act = db.query(AgentAction).filter(AgentAction.id == a.action_id).first()
        entries.append({
            "id": a.id,
            "timestamp": a.timestamp,
            "customer_id": a.customer_id,
            "merchant_id": a.merchant_id,
            "action_id": a.action_id,
            "decision_id": a.decision_id,
            "verdict": dec.verdict if dec else None,
            "decision": dec.verdict if dec else None,  # alias for frontend (allow/block/modify)
            "block_reason": dec.block_reason if dec else None,
            "reasoning": dec.reasoning if dec else None,
            "approved_channel": dec.approved_channel if dec else None,
            "agent_type": act.agent_type if act else None,
            "action_type": act.agent_type if act else None,  # alias
            "channel": act.channel if act else None,
            "amount_involved": act.amount_involved if act else None,
            "discount_offered": act.discount_offered if act else None,
            "customer_snapshot": json.loads(a.customer_snapshot) if a.customer_snapshot else None,
            "rules_evaluated": json.loads(a.rules_evaluated) if a.rules_evaluated else [],
            "rules_applied": json.loads(a.rules_evaluated) if a.rules_evaluated else [],  # alias
            "actual_outcome": a.actual_outcome,
            "actual_revenue": a.actual_revenue,
            "webhook_event": a.webhook_event,
            "razorpay_order_id": a.razorpay_order_id,
            "event_type": a.webhook_event,
            "latency_ms": None,
        })

    return {"total": total, "limit": limit, "offset": offset, "entries": entries}
