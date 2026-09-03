import json
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models.customer import CustomerContext
from app.models.audit import AuditEntry
from app.utils.time import utc_iso

router = APIRouter(prefix="/api/v1/customers", tags=["customers"])


@router.get("")
def list_customers(
    merchant_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    archetype: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    q = db.query(CustomerContext)
    if merchant_id:
        q = q.filter(CustomerContext.merchant_id == merchant_id)
    if archetype:
        q = q.filter(CustomerContext.archetype == archetype)
    total = q.count()
    rows = q.order_by(CustomerContext.created_at.desc(), CustomerContext.id.asc()).offset(offset).limit(limit).all()
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "customers": [
            {
                "id": c.id,
                "name": c.name,
                "city": c.city,
                "archetype": c.archetype,
                "risk_score": c.risk_score,
                "engagement_score": c.engagement_score,
                "lifetime_value": c.lifetime_value,
                "total_contacts_received": c.total_contacts_received,
                "current_discount_exposure": c.current_discount_exposure,
                "churned": c.churned,
                "last_contact_at": utc_iso(c.last_contact_at),
            }
            for c in rows
        ],
    }


@router.get("/{customer_id}/context")
def get_customer_context(customer_id: str, db: Session = Depends(get_db)):
    c = db.query(CustomerContext).filter(CustomerContext.id == customer_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Customer not found")
    # recent audit entries for timeline
    audits = db.query(AuditEntry).filter(AuditEntry.customer_id == customer_id).order_by(AuditEntry.timestamp.desc()).limit(20).all()
    return {
        "customer": {
            "id": c.id,
            "merchant_id": c.merchant_id,
            "name": c.name,
            "city": c.city,
            "email": c.email,
            "phone": c.phone,
            "archetype": c.archetype,
            "risk_score": c.risk_score,
            "engagement_score": c.engagement_score,
            "lifetime_value": c.lifetime_value,
            "outstanding_payments": c.outstanding_payments,
            "current_discount_exposure": c.current_discount_exposure,
            "total_contacts_received": c.total_contacts_received,
            "total_conversions": c.total_conversions,
            "churned": c.churned,
            "last_contact_at": utc_iso(c.last_contact_at),
            "last_contact_channel": c.last_contact_channel,
            "last_contact_agent": c.last_contact_agent,
            "response_probability": c.response_probability,
            "conversion_probability": c.conversion_probability,
            "churn_threshold": c.churn_threshold,
        },
        "recent_audits": [
            {
                "id": a.id,
                "timestamp": utc_iso(a.timestamp),
                "action_id": a.action_id,
                "decision_id": a.decision_id,
                "rules_evaluated": json.loads(a.rules_evaluated) if a.rules_evaluated else [],
            }
            for a in audits
        ],
    }
