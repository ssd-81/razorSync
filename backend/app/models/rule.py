from sqlalchemy import Column, String, Integer, Boolean, DateTime
from sqlalchemy.sql import func
from app.db.database import Base


class BusinessRule(Base):
    __tablename__ = "business_rules"

    id = Column(String, primary_key=True, index=True)
    merchant_id = Column(String, nullable=False, index=True)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)

    applies_to_agents = Column(String, nullable=True)  # JSON array
    applies_to_channels = Column(String, nullable=True)  # JSON array

    rule_type = Column(String, nullable=False, index=True)
    rule_config = Column(String, nullable=False)  # JSON

    priority = Column(Integer, default=5)
    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
