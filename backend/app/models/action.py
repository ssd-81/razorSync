from sqlalchemy import Column, String, Float, Integer, DateTime
from sqlalchemy.sql import func
from app.db.database import Base


class AgentAction(Base):
    __tablename__ = "agent_actions"

    id = Column(String, primary_key=True, index=True)
    agent_id = Column(String, nullable=False)
    agent_type = Column(String, nullable=False, index=True)
    customer_id = Column(String, nullable=False, index=True)
    merchant_id = Column(String, nullable=False, index=True)

    action_type = Column(String, nullable=False)
    channel = Column(String, nullable=False)
    priority = Column(Integer, nullable=False)

    message_template = Column(String, nullable=True)
    discount_offered = Column(Float, default=0.0)
    amount_involved = Column(Float, default=0.0)

    proposed_at = Column(DateTime, nullable=False, index=True)
    proposed_delay_seconds = Column(Integer, default=0)

    confidence = Column(Float, default=0.5)
    reasoning = Column(String, nullable=True)

    created_at = Column(DateTime, server_default=func.now())
