from sqlalchemy import Column, String, Float, Integer, DateTime
from sqlalchemy.sql import func
from app.db.database import Base


class Order(Base):
    __tablename__ = "orders"

    id = Column(String, primary_key=True, index=True)  # Razorpay order_id
    merchant_id = Column(String, nullable=False, index=True)
    customer_id = Column(String, nullable=False, index=True)
    amount = Column(Integer, nullable=False)  # in paise
    currency = Column(String, default="INR")
    status = Column(String, nullable=False, index=True)  # created, paid, failed
    receipt = Column(String, nullable=True)
    razorpay_response = Column(String, nullable=True)  # JSON
    failure_reason = Column(String, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
