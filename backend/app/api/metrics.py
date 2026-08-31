from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Optional

from app.db.database import get_db
from app.models.decision import CoordinationDecision
from app.models.audit import AuditEntry
from app.models.action import AgentAction

router = APIRouter(prefix="/api/v1/metrics", tags=["metrics"])


@router.get("")
def get_metrics(
    merchant_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    # Filter in SQL, not python
    q_dec = db.query(CoordinationDecision)
    if merchant_id:
        # join via audit or action to filter merchant? Decisions store customer_id, merchant via audit/action
        # Simpler: filter via AuditEntry merchant_id and join
        q_dec = q_dec.join(AuditEntry, AuditEntry.decision_id == CoordinationDecision.id).filter(AuditEntry.merchant_id == merchant_id)

    total = q_dec.count()
    approved = q_dec.filter(CoordinationDecision.verdict == "approved").count()
    blocked = q_dec.filter(CoordinationDecision.verdict == "blocked").count()
    throttled = q_dec.filter(CoordinationDecision.verdict == "throttled").count()

    # revenue from approved
    revenue = db.query(func.sum(CoordinationDecision.estimated_revenue_impact)).filter(CoordinationDecision.verdict == "approved")
    if merchant_id:
        revenue = revenue.join(AuditEntry, AuditEntry.decision_id == CoordinationDecision.id).filter(AuditEntry.merchant_id == merchant_id)
    total_revenue = revenue.scalar() or 0

    return {
        "total_decisions": total,
        "approved": approved,
        "blocked": blocked,
        "throttled": throttled,
        "approval_rate": round(approved / total, 3) if total else 0,
        "block_rate": round(blocked / total, 3) if total else 0,
        "estimated_revenue_impact": round(float(total_revenue), 2),
    }


@router.get("/summary")
def get_summary(
    merchant_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    # Use proposed_at vs created_at? v0 bug M7 used created_at. We use proposed_at for accuracy.
    # For now return counts by agent_type, channel
    q = db.query(AgentAction)
    if merchant_id:
        q = q.filter(AgentAction.merchant_id == merchant_id)

    # group by agent_type
    from sqlalchemy import func
    agent_counts = db.query(AgentAction.agent_type, func.count()).group_by(AgentAction.agent_type)
    if merchant_id:
        agent_counts = agent_counts.filter(AgentAction.merchant_id == merchant_id)
    agent_counts = {row[0]: row[1] for row in agent_counts.all()}

    channel_counts = db.query(AgentAction.channel, func.count()).group_by(AgentAction.channel)
    if merchant_id:
        channel_counts = channel_counts.filter(AgentAction.merchant_id == merchant_id)
    channel_counts = {row[0]: row[1] for row in channel_counts.all()}

    return {
        "by_agent_type": agent_counts,
        "by_channel": channel_counts,
        "merchant_id": merchant_id,
    }
