from datetime import datetime, timedelta, timezone
from typing import Optional
from sqlalchemy.orm import Session
from app.models.action import AgentAction
from app.models.customer import CustomerContext


class CollisionResult:
    def __init__(self, has_duplicates: bool = False, has_conflicts: bool = False, recommended_agent: Optional[str] = None, rules_triggered: Optional[list] = None, reason: str = ""):
        self.has_duplicates = has_duplicates
        self.has_conflicts = has_conflicts
        self.recommended_agent = recommended_agent
        self.rules_triggered = rules_triggered or []
        self.reason = reason


class CollisionDetector:
    def __init__(self, db: Session):
        self.db = db

    def check(self, action: AgentAction, customer: CustomerContext) -> CollisionResult:
        # Duplicate: same agent_type + same action_type + same customer within 1 hour
        now = action.proposed_at or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        window_start = now - timedelta(hours=1)

        recent_dupe = (
            self.db.query(AgentAction)
            .filter(
                AgentAction.customer_id == action.customer_id,
                AgentAction.agent_type == action.agent_type,
                AgentAction.action_type == action.action_type,
                AgentAction.proposed_at >= window_start,
                AgentAction.id != action.id,
            )
            .first()
        )
        if recent_dupe:
            return CollisionResult(has_duplicates=True, reason=f"Duplicate {action.agent_type}/{action.action_type} within 1h")

        # Conflict: if another high-priority action was approved very recently (<30min) for same customer, defer
        # For v1 we keep simple: check if customer cooling_down flag
        if customer.cooling_down and customer.cooldown_until:
            cu = customer.cooldown_until
            if cu.tzinfo is None:
                cu = cu.replace(tzinfo=timezone.utc)
            if now < cu:
                return CollisionResult(has_conflicts=True, recommended_agent=customer.last_contact_agent, reason="Customer in cooldown conflict")

        return CollisionResult()
