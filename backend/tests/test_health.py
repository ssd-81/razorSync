"""
Health + contract tests — credential-free.

Runs fully offline with an isolated SQLite DB. No Razorpay keys,
no webhook secret, no Redis, no LLM key required.
"""
import os

os.environ.setdefault("RAZORPAY_WEBHOOK_SECRET", "")
os.environ.setdefault("REDIS_URL", "")
os.environ.setdefault("LLM_ENDPOINT", "")

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.db.database import Base, get_db

TEST_DB_URL = "sqlite:///./test_health.db"
test_engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


def override_get_db():
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)

import app.models.customer  # noqa: F401
import app.models.action  # noqa: F401
import app.models.decision  # noqa: F401
import app.models.rule  # noqa: F401
import app.models.audit  # noqa: F401
import app.models.simulation  # noqa: F401
import app.models.order  # noqa: F401
import app.models.hitl  # noqa: F401
import app.models.inbox  # noqa: F401

Base.metadata.drop_all(bind=test_engine)
Base.metadata.create_all(bind=test_engine)


def test_root_ok():
    r = client.get("/")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "service" in body


def test_health_ok():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_openapi_lists_versioned_routes():
    r = client.get("/openapi.json")
    assert r.status_code == 200
    paths = r.json()["paths"]
    assert any(p.startswith("/api/v1/rules") for p in paths)
    assert any(p.startswith("/api/v1/customers") for p in paths)
    assert any(p.startswith("/api/v1/decisions") for p in paths)
    assert any(p.startswith("/api/v1/simulation") for p in paths)


def test_rules_list_empty_ok():
    r = client.get("/api/v1/rules")
    assert r.status_code == 200


def test_customers_list_ok():
    r = client.get("/api/v1/customers?limit=5")
    assert r.status_code == 200


def test_decisions_recent_ok():
    r = client.get("/api/v1/decisions/recent?limit=5")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_ops_state_ok():
    r = client.get("/api/v1/ops/state")
    assert r.status_code == 200
    assert "failure_mode" in r.json()


def test_invalid_rule_rejected():
    # Validation layer: bad rule_type must be 400/422, not 500.
    r = client.post("/api/v1/rules", json={"name": "x", "rule_type": "not_a_rule"})
    assert r.status_code in (400, 422)
