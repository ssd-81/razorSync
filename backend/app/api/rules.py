import uuid
import json
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.schemas import RuleCreateRequest, RuleUpdateRequest
from app.models.rule import BusinessRule
from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/rules", tags=["rules"])


@router.get("")
def list_rules(merchant_id: str = None, db: Session = Depends(get_db)):
    merchant_id = merchant_id or settings.MERCHANT_ID
    rules = db.query(BusinessRule).filter(BusinessRule.merchant_id == merchant_id).order_by(BusinessRule.priority.desc()).all()
    return {
        "rules": [
            {
                "id": r.id,
                "merchant_id": r.merchant_id,
                "name": r.name,
                "description": r.description,
                "applies_to_agents": json.loads(r.applies_to_agents) if r.applies_to_agents else [],
                "applies_to_channels": json.loads(r.applies_to_channels) if r.applies_to_channels else [],
                "rule_type": r.rule_type,
                "rule_config": json.loads(r.rule_config) if isinstance(r.rule_config, str) else r.rule_config,
                "priority": r.priority,
                "is_active": r.is_active,
                "created_at": r.created_at,
            }
            for r in rules
        ]
    }


@router.post("")
def create_rule(payload: RuleCreateRequest, db: Session = Depends(get_db)):
    merchant_id = payload.merchant_id or settings.MERCHANT_ID
    rule = BusinessRule(
        id=f"rule_{uuid.uuid4().hex[:8]}",
        merchant_id=merchant_id,
        name=payload.name,
        description=payload.description,
        applies_to_agents=json.dumps(payload.applies_to_agents) if payload.applies_to_agents else json.dumps([]),
        applies_to_channels=json.dumps(payload.applies_to_channels) if payload.applies_to_channels else json.dumps([]),
        rule_type=payload.rule_type,
        rule_config=json.dumps(payload.rule_config),
        priority=payload.priority,
        is_active=payload.is_active,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    logger.info("Created rule %s type %s", rule.id, rule.rule_type)

    return {
        "id": rule.id,
        "merchant_id": rule.merchant_id,
        "name": rule.name,
        "rule_type": rule.rule_type,
        "rule_config": payload.rule_config,
        "priority": rule.priority,
        "is_active": rule.is_active,
    }


@router.put("/{rule_id}")
def update_rule(rule_id: str, payload: RuleUpdateRequest, db: Session = Depends(get_db)):
    rule = db.query(BusinessRule).filter(BusinessRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    if payload.name is not None:
        rule.name = payload.name
    if payload.description is not None:
        rule.description = payload.description
    if payload.applies_to_agents is not None:
        rule.applies_to_agents = json.dumps(payload.applies_to_agents)
    if payload.applies_to_channels is not None:
        rule.applies_to_channels = json.dumps(payload.applies_to_channels)
    if payload.rule_config is not None:
        # validate if rule_type-specific?
        rule.rule_config = json.dumps(payload.rule_config)
    if payload.priority is not None:
        rule.priority = payload.priority
    if payload.is_active is not None:
        rule.is_active = payload.is_active
    db.commit()
    db.refresh(rule)
    logger.info("Updated rule %s is_active=%s", rule.id, rule.is_active)
    return {
        "id": rule.id,
        "name": rule.name,
        "rule_type": rule.rule_type,
        "rule_config": json.loads(rule.rule_config) if isinstance(rule.rule_config, str) else rule.rule_config,
        "priority": rule.priority,
        "is_active": rule.is_active,
    }


@router.delete("/{rule_id}")
def delete_rule(rule_id: str, db: Session = Depends(get_db)):
    rule = db.query(BusinessRule).filter(BusinessRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    db.delete(rule)
    db.commit()
    return {"status": "deleted", "id": rule_id}


@router.patch("/{rule_id}/toggle")
def toggle_rule(rule_id: str, db: Session = Depends(get_db)):
    rule = db.query(BusinessRule).filter(BusinessRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    rule.is_active = not rule.is_active
    db.commit()
    db.refresh(rule)
    logger.info("Toggled rule %s to %s", rule.id, rule.is_active)
    return {"id": rule.id, "is_active": rule.is_active}
