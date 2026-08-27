from sqlalchemy import Column, String, Float, Integer, Boolean, DateTime
from sqlalchemy.sql import func
from app.db.database import Base


class CustomerContext(Base):
    __tablename__ = "customer_context"

    id = Column(String, primary_key=True, index=True)
    merchant_id = Column(String, nullable=False, index=True)
    name = Column(String, nullable=False)
    city = Column(String, nullable=True)
    email = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    archetype = Column(String, nullable=False)

    last_contact_at = Column(DateTime, nullable=True)
    last_contact_channel = Column(String, nullable=True)
    last_contact_agent = Column(String, nullable=True)
    last_action_result = Column(String, nullable=True)

    outstanding_payments = Column(Float, default=0.0)
    lifetime_value = Column(Float, default=0.0)
    current_discount_exposure = Column(Float, default=0.0)

    risk_score = Column(Float, default=0.5)
    engagement_score = Column(Float, default=0.5)
    last_purchase_at = Column(DateTime, nullable=True)
    cart_abandonment_count = Column(Integer, default=0)
    failed_payment_count = Column(Integer, default=0)
    dispute_count = Column(Integer, default=0)

    cooling_down = Column(Boolean, default=False)
    cooldown_until = Column(DateTime, nullable=True)
    priority_tier = Column(String, default="medium")

    response_probability = Column(Float, nullable=True)
    conversion_probability = Column(Float, nullable=True)
    churn_threshold = Column(Integer, nullable=True)
    discount_sensitivity = Column(Float, nullable=True)

    total_contacts_received = Column(Integer, default=0)
    total_conversions = Column(Integer, default=0)
    total_revenue_generated = Column(Float, default=0.0)
    churned = Column(Boolean, default=False)
    churned_at_action = Column(Integer, nullable=True)

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
