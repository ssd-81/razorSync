"""Deterministic customer resolution shared by webhook + worker paths.

The old code used unordered `.first()` as the "no customer_id in payload"
fallback, which returned an arbitrary row (e.g. a synthetic `cust_256_0000`
seed customer). Oldest-first ordering makes the fallback stable and
predictable: it resolves to the earliest-seeded (real, named) customer.
"""
from sqlalchemy.orm import Session
from app.models.customer import CustomerContext


def resolve_fallback_customer(db: Session, merchant_id: str) -> CustomerContext | None:
    """Return the oldest customer for the merchant, or None if empty."""
    return (
        db.query(CustomerContext)
        .filter(CustomerContext.merchant_id == merchant_id)
        .order_by(CustomerContext.created_at.asc(), CustomerContext.id.asc())
        .first()
    )
