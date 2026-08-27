from sqlalchemy import Column, String, Float, Integer, DateTime
from sqlalchemy.sql import func
from app.db.database import Base


class CoordinationDecision(Base):
    __tablename__ = "coordination_decisions"

    id = Column(String, primary_key=True, index=True)
    action_id = Column(String, nullable=False, index=True)
    customer_id = Column(String, nullable=False, index=True)

    verdict = Column(String, nullable=False, index=True)
    approved_channel = Column(String, nullable=True)
    approved_delay_seconds = Column(Integer, nullable=True)
    approved_discount = Column(Float, nullable=True)

    block_reason = Column(String, nullable=True)
    rerouted_to_agent = Column(String, nullable=True)
    deferred_until = Column(DateTime, nullable=True)

    rules_applied = Column(String, nullable=True)  # JSON array
    reasoning = Column(String, nullable=True)

    estimated_revenue_impact = Column(Float, nullable=True)
    confidence = Column(Float, nullable=True)

    # v2: track source (live razorpay vs simulated vs fallback)
    source = Column(String, default="live")

    created_at = Column(DateTime, server_default=func.now())
