import logging
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models.decision import CoordinationDecision
from app.models.action import AgentAction

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/decisions", tags=["decisions"])


@router.get("/recent")
def recent_decisions(
    since: Optional[str] = Query(None, description="ISO timestamp — only decisions after this"),
    limit: int = Query(20, ge=1, le=100),
    include_simulation: bool = Query(False, description="include simulation decisions (default live/fallback only)"),
    db: Session = Depends(get_db),
):
    q = db.query(CoordinationDecision).order_by(CoordinationDecision.created_at.desc())
    if not include_simulation:
        q = q.filter(CoordinationDecision.source.in_(["live", "fallback"]))
    if since:
        try:
            # parse ISO, handle Z
            ts_str = since.replace("Z", "+00:00") if since.endswith("Z") else since
            ts = datetime.fromisoformat(ts_str)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            # filter by created_at > since
            q = q.filter(CoordinationDecision.created_at > ts)
        except Exception as e:
            logger.warning("Invalid since param %s: %s", since, e)

    decisions = q.limit(limit).all()
    # Join to get action details for chain visualization
    result = []
    for d in decisions:
        # fetch action
        action = db.query(AgentAction).filter(AgentAction.id == d.action_id).first()
        result.append(
            {
                "id": d.id,
                "action_id": d.action_id,
                "customer_id": d.customer_id,
                "verdict": d.verdict,
                "block_reason": d.block_reason,
                "approved_channel": d.approved_channel,
                "reasoning": d.reasoning,
                "rules_applied": d.rules_applied,
                "estimated_revenue_impact": d.estimated_revenue_impact,
                "confidence": d.confidence,
                "source": getattr(d, "source", "live"),
                "created_at": d.created_at.isoformat() if d.created_at else None,
                "action": {
                    "agent_type": action.agent_type if action else None,
                    "channel": action.channel if action else None,
                    "amount_involved": action.amount_involved if action else None,
                    "discount_offered": action.discount_offered if action else None,
                    "proposed_at": action.proposed_at.isoformat() if action and action.proposed_at else None,
                }
                if action
                else None,
            }
        )
    # Return newest-first (desc) — standard REST. Frontend handles chronological append.
    return result
