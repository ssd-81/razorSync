import time
import logging
from typing import Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.services.razorpay_client import razorpay_client
from app.models.decision import CoordinationDecision
from app.models.audit import AuditEntry
from app.utils.time import utc_iso

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/ops", tags=["ops"])

# In-memory ops state (inspectable, resettable)
_ops_state = {
    "started_at": None,
    "steps": [],
    "last_error": None,
    "failure_simulated": False,
    "replay_count": 0,
}


class FailureToggleRequest(BaseModel):
    enabled: bool


@router.post("/failure-toggle")
def toggle_failure(payload: FailureToggleRequest):
    razorpay_client.set_failure_mode(payload.enabled)
    _ops_state["failure_simulated"] = payload.enabled
    _ops_state["steps"].append(
        {
            "at": time.time(),
            "event": "failure_toggle",
            "enabled": payload.enabled,
            "banner": "⚠️ RazorPay unavailable — using cached coordination decision" if payload.enabled else None,
        }
    )
    return {
        "simulate_razorpay_failure": razorpay_client.failure_mode,
        "banner": "⚠️ RazorPay unavailable — using cached coordination decision" if payload.enabled else None,
        "message": "Failure simulation enabled — Razorpay calls will raise TimeoutError" if payload.enabled else "Failure simulation disabled — live Razorpay",
    }


@router.get("/failure-status")
def failure_status():
    return {
        "simulate_razorpay_failure": razorpay_client.failure_mode,
        "banner": "⚠️ RazorPay unavailable — using cached coordination decision" if razorpay_client.failure_mode else None,
    }


@router.get("/state")
def get_ops_state(db: Session = Depends(get_db)):
    recent_decisions = (
        db.query(CoordinationDecision).filter(CoordinationDecision.source.in_(["live", "fallback"])).order_by(CoordinationDecision.created_at.desc()).limit(10).all()
    )
    recent_audits = db.query(AuditEntry).order_by(AuditEntry.timestamp.desc()).limit(10).all()
    return {
        "ops": _ops_state,
        "failure_mode": razorpay_client.failure_mode,
        "recent_decisions": [
            {
                "id": d.id,
                "verdict": d.verdict,
                "customer_id": d.customer_id,
                "reasoning": d.reasoning,
                "source": getattr(d, "source", "live"),
                "created_at": utc_iso(d.created_at),
            }
            for d in recent_decisions
        ],
        "recent_audits": [
            {
                "id": a.id,
                "customer_id": a.customer_id,
                "webhook_event": a.webhook_event,
                "razorpay_order_id": a.razorpay_order_id,
                "timestamp": utc_iso(a.timestamp),
            }
            for a in recent_audits
        ],
    }


@router.post("/reset")
def reset_ops():
    _ops_state["steps"].clear()
    _ops_state["last_error"] = None
    _ops_state["started_at"] = time.time()
    razorpay_client.set_failure_mode(False)
    _ops_state["failure_simulated"] = False
    return {"status": "reset", "ops": _ops_state}


@router.post("/replay")
def replay_ops(db: Session = Depends(get_db)):
    _ops_state["replay_count"] += 1
    # Return last 5 live decisions as replay payload (exclude simulation)
    decisions = db.query(CoordinationDecision).filter(CoordinationDecision.source.in_(["live", "fallback"])).order_by(CoordinationDecision.created_at.desc()).limit(5).all()
    return {
        "replay_count": _ops_state["replay_count"],
        "decisions": [
            {
                "id": d.id,
                "verdict": d.verdict,
                "customer_id": d.customer_id,
                "reasoning": d.reasoning,
                "source": getattr(d, "source", "live"),
            }
            for d in decisions
        ],
    }
