from sqlalchemy.orm import Session
from app.models.customer import CustomerContext
from app.models.action import AgentAction
from app.models.decision import CoordinationDecision
from datetime import datetime, timezone
import json

class ContextManager:
    def __init__(self, db: Session):
        self.db = db

    def load(self, customer_id: str) -> CustomerContext | None:
        return self.db.query(CustomerContext).filter(CustomerContext.id == customer_id).first()

    def update_after_decision(self, customer: CustomerContext, action: AgentAction, decision: CoordinationDecision):
        """Update customer state after approved/throttled decision. Cumulative budget + contacts."""
        if decision.verdict in ("approved", "throttled"):
            customer.last_contact_at = action.proposed_at or datetime.now(timezone.utc)
            customer.last_contact_channel = decision.approved_channel or action.channel
            customer.last_contact_agent = action.agent_type
            customer.total_contacts_received = (customer.total_contacts_received or 0) + 1
            # cumulative discount exposure
            disc = float(decision.approved_discount or action.discount_offered or 0)
            customer.current_discount_exposure = float(customer.current_discount_exposure or 0) + disc
            # cooling
            # cooldown handling is via rules, but we set flag for collision detector
            self.db.add(customer)
            self.db.flush()
