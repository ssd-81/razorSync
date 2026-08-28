"""v3 Inbox model - durable audit for async ingestion (Option B).

DECISION V3-01: Split Ingestion vs Reasoning.
Every webhook is durably stored before 200 ack. Redis is hot transport,
DB is cold truth for replay if Redis dies.
"""
from sqlalchemy import Column, String, DateTime, Text, Index
from sqlalchemy.sql import func
from app.db.database import Base


class InboxEntry(Base):
    __tablename__ = "inbox_entries"

    id = Column(String, primary_key=True, index=True)
    event = Column(String, nullable=False, index=True)
    customer_id = Column(String, nullable=True, index=True)
    order_id = Column(String, nullable=True, index=True)
    merchant_id = Column(String, nullable=False, index=True)
    payload = Column(Text, nullable=False)  # raw JSON
    status = Column(String, default="queued", nullable=False, index=True)  # queued | processing | completed | failed
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    processed_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_inbox_status_created", "status", "created_at"),
    )
