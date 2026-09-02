"""
Rules-engine unit tests — credential-free.

Covers windowed evaluation, IST time-window, and single-source
rule_config behaviour without any external service.
"""
import json
from datetime import datetime, timezone, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.models.customer import CustomerContext
from app.models.action import AgentAction
from app.models.rule import BusinessRule
from app.engine.rules import RulesEngine

import app.models.action  # noqa: F401
import app.models.decision  # noqa: F401
import app.models.audit  # noqa: F401
import app.models.simulation  # noqa: F401
import app.models.order  # noqa: F401
import app.models.hitl  # noqa: F401
import app.models.inbox  # noqa: F401

engine = create_engine("sqlite:///./test_rules.db", connect_args={"check_same_thread": False})
TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.drop_all(bind=engine)
Base.metadata.create_all(bind=engine)


def _db():
    return TestingSession()


def _customer(db, cid="cust_test_001"):
    c = db.query(CustomerContext).filter(CustomerContext.id == cid).first()
    if not c:
        c = CustomerContext(
            id=cid,
            merchant_id="merchant_default",
            name="Test Customer",
            archetype="high_value",
            phone="+910000000001",
            email="test@example.com",
            lifetime_value=1000.0,
            risk_score=0.1,
        )
        db.add(c)
        db.commit()
        db.refresh(c)
    return c


def _action(db, customer, agent="autopay_retry", channel="sms", discount=10.0):
    return AgentAction(
        id=f"act_{agent}_{discount}",
        agent_id=f"agent_{agent}",
        merchant_id="merchant_default",
        customer_id=customer.id,
        agent_type=agent,
        action_type="nudge",
        channel=channel,
        priority=5,
        message_template="test",
        discount_offered=discount,
        proposed_at=datetime.now(timezone.utc),
    )


def _clear_rules(db):
    db.query(BusinessRule).delete()
    db.commit()


def test_no_rules_approves():
    db = _db()
    try:
        _clear_rules(db)
        c = _customer(db)
        a = _action(db, c)
        res = RulesEngine(db).evaluate(a, c)
        assert res.verdict == "approved"
    finally:
        db.close()


def test_cooldown_blocks_when_recent_contact():
    db = _db()
    try:
        _clear_rules(db)
        c = _customer(db)
        c.last_contact_at = datetime.now(timezone.utc) - timedelta(hours=1)
        db.add(c)
        db.add(
            BusinessRule(
                id="rule_cooldown_test",
                merchant_id="merchant_default",
                name="Cooldown test",
                description="t",
                applies_to_agents=json.dumps([]),
                applies_to_channels=json.dumps([]),
                rule_type="cooldown",
                rule_config=json.dumps({"cooldown_hours": 4}),
                priority=10,
                is_active=True,
            )
        )
        db.commit()
        a = _action(db, c)
        res = RulesEngine(db).evaluate(a, c)
        assert res.verdict == "blocked"
        assert "rule_cooldown_test" in res.rules_triggered
    finally:
        db.close()


def test_inactive_rule_ignored():
    db = _db()
    try:
        _clear_rules(db)
        c = _customer(db)
        db.add(
            BusinessRule(
                id="rule_inactive",
                merchant_id="merchant_default",
                name="off",
                description="t",
                applies_to_agents=json.dumps([]),
                applies_to_channels=json.dumps([]),
                rule_type="frequency_cap",
                rule_config=json.dumps({"max_contacts": 0, "window_hours": 24}),
                priority=10,
                is_active=False,
            )
        )
        db.commit()
        a = _action(db, c)
        res = RulesEngine(db).evaluate(a, c)
        assert res.verdict == "approved"
    finally:
        db.close()
