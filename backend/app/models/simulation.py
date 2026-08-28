from sqlalchemy import Column, String, Float, Integer, DateTime
from sqlalchemy.sql import func
from app.db.database import Base


class SimulationRun(Base):
    __tablename__ = "simulation_runs"

    id = Column(String, primary_key=True, index=True)
    mode = Column(String, nullable=False)

    num_customers = Column(Integer, nullable=False)
    seed = Column(Integer, nullable=False)
    duration_days = Column(Integer, default=7)

    total_revenue = Column(Float, nullable=True)
    total_contacts = Column(Integer, nullable=True)
    total_conversions = Column(Integer, nullable=True)
    avg_contacts_per_customer = Column(Float, nullable=True)
    churn_rate = Column(Float, nullable=True)
    discount_waste = Column(Float, nullable=True)
    revenue_per_contact = Column(Float, nullable=True)
    false_positive_rate = Column(Float, nullable=True)

    rules_snapshot = Column(String, nullable=True)  # JSON
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
