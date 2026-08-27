from sqlalchemy import Column, String, Float, Integer, DateTime, Boolean
from sqlalchemy.sql import func
from app.db.database import Base


class AuditEntry(Base):
    __tablename__ = "audit_entries"

    id = Column(String, primary_key=True, index=True)
    timestamp = Column(DateTime, server_default=func.now(), index=True)
    customer_id = Column(String, nullable=False, index=True)
    merchant_id = Column(String, nullable=False, index=True)

    action_id = Column(String, nullable=False, index=True)
    decision_id = Column(String, nullable=False, index=True)

    customer_snapshot = Column(String, nullable=True)  # JSON
    active_agent_count = Column(Integer, nullable=True)
    rules_evaluated = Column(String, nullable=True)  # JSON

    actual_outcome = Column(String, nullable=True)
    actual_revenue = Column(Float, nullable=True)
    feedback_loop = Column(Boolean, nullable=True)

    # v2: external call audit
    webhook_event = Column(String, nullable=True)
    razorpay_order_id = Column(String, nullable=True)
