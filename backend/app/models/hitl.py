"""v3 HITL models — suspended actions and human-in-the-loop tickets.

DECISION V3-11: Async execution suspension.
DECISION V3-10: Hard vs Soft guardrails — soft=BLOCK (no ticket), hard=SUSPEND (ticket).
"""
from sqlalchemy import Column, String, Float, Integer, Boolean, DateTime, Text
from sqlalchemy.sql import func
from app.db.database import Base


class SuspendedAction(Base):
    """An action that hit a hard guardrail and was suspended for human review."""
    __tablename__ = "suspended_actions"

    id = Column(String, primary_key=True, index=True)
    customer_id = Column(String, nullable=False, index=True)
    merchant_id = Column(String, nullable=False, index=True)

    # The original action payload (JSON) — needed for resume
    action_payload = Column(Text, nullable=False)

    # Which guardrail triggered the suspension
    guardrail_triggered = Column(String, nullable=False)
    guardrail_reason = Column(String, nullable=True)

    # Snapshot of customer state at suspend time
    customer_snapshot = Column(Text, nullable=True)  # JSON

    # Status: pending | approved | rejected | expired
    status = Column(String, default="pending", nullable=False, index=True)

    # When it expires (auto-reject after 24h)
    expires_at = Column(DateTime, nullable=False)

    # Metadata
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class HITLTicket(Base):
    """Human-in-the-loop ticket — linked to a suspended action."""
    __tablename__ = "hitl_tickets"

    id = Column(String, primary_key=True, index=True)
    suspended_action_id = Column(String, nullable=False, index=True)

    # Why it was suspended (summary)
    reason = Column(String, nullable=True)

    # Status: pending | approved | rejected | expired
    status = Column(String, default="pending", nullable=False, index=True)

    # Who picked it up
    assignee = Column(String, nullable=True)

    # Human decision: approve | reject | edit
    decision = Column(String, nullable=True, index=True)

    # If edited, the modified action payload
    edited_payload = Column(Text, nullable=True)

    # Override tracking (maker-checker pattern)
    override = Column(Boolean, default=False)
    override_reason = Column(String, nullable=True)
    original_ceiling = Column(Float, nullable=True)  # what auto-approval limit was
    approved_amount = Column(Float, nullable=True)  # what human approved

    # Timestamps
    created_at = Column(DateTime, server_default=func.now())
    resumed_at = Column(DateTime, nullable=True)
