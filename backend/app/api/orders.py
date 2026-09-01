import uuid
import json
import logging
import time
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.schemas import OrderCreateRequest
from app.config import settings
from app.services.razorpay_client import razorpay_client
from app.models.order import Order
from app.models.customer import CustomerContext
from app.models.action import AgentAction
from app.models.decision import CoordinationDecision
from app.engine.coordinator import CoordinationEngine

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/orders", tags=["orders"])


@router.post("")
def create_order(payload: OrderCreateRequest, db: Session = Depends(get_db)):
    """
    Create a test order in Razorpay and record it locally.
    On Razorpay timeout/failure, falls back gracefully with clear status.
    """
    # Validate customer exists
    customer = db.query(CustomerContext).filter(CustomerContext.id == payload.customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail=f"Customer {payload.customer_id} not found")

    start = time.time()
    razorpay_order = None
    fallback = False
    failure_reason = None

    try:
        notes = dict(payload.notes or {})
        notes.setdefault("customer_id", payload.customer_id)
        notes.setdefault("merchant_id", settings.MERCHANT_ID)
        razorpay_order = razorpay_client.create_order(
            amount=payload.amount,
            currency=payload.currency,
            receipt=payload.receipt,
            notes=notes,
        )
        status = razorpay_order.get("status", "created")
        order_id = razorpay_order.get("id", f"order_{uuid.uuid4().hex[:12]}")
        logger.info("Razorpay order %s created in %.2fs", order_id, time.time() - start)
    except TimeoutError as e:
        # Graceful degradation: create local order with fallback status, still return coordination decision
        fallback = True
        failure_reason = str(e)
        order_id = f"order_fallback_{uuid.uuid4().hex[:8]}"
        status = "fallback"
        razorpay_order = {"id": order_id, "status": status, "fallback": True, "error": failure_reason}
        logger.warning("Razorpay unavailable, fallback order %s: %s", order_id, e)
    except Exception as e:
        logger.exception("Razorpay order creation failed: %s", e)
        raise HTTPException(status_code=502, detail=f"Razorpay error: {str(e)}")

    # Persist order locally
    order = Order(
        id=order_id,
        merchant_id=settings.MERCHANT_ID,
        customer_id=payload.customer_id,
        amount=payload.amount,
        currency=payload.currency,
        status=status,
        receipt=payload.receipt,
        razorpay_response=json.dumps(razorpay_order) if razorpay_order else None,
        failure_reason=failure_reason,
    )
    db.add(order)

    # v3: Auto-create AgentAction + run coordination for this order
    # Maps order creation to eligible native agents (autopay_retry for payment failed, etc.)
    try:
        from datetime import datetime, timezone
        from app.simulation.agents import AGENT_DEFS

        now = order.created_at or datetime.now(timezone.utc)
        # For order creation, use autopay_retry as the primary agent (payment link retry)
        agent_type = "autopay_retry"
        ade = AGENT_DEFS.get(agent_type, {})
        primary_channel = ade.get("channels", ["sms"])[0]

        action = AgentAction(
            id=f"act_{uuid.uuid4().hex[:12]}",
            agent_id=f"{agent_type}_order_{uuid.uuid4().hex[:6]}",
            agent_type=agent_type,
            customer_id=payload.customer_id,
            merchant_id=settings.MERCHANT_ID,
            action_type="order_created",
            channel=primary_channel,
            priority=5,
            message_template=f"Order {order_id} created for ₹{payload.amount/100:.2f}",
            discount_offered=0.0,
            amount_involved=payload.amount / 100.0,
            proposed_at=now,
            proposed_delay_seconds=0,
            confidence=0.7,
            reasoning=f"Razorpay order {order_id} — {'fallback' if fallback else 'live'}",
        )
        db.add(action)
        db.flush()

        engine = CoordinationEngine(db)
        decision = engine.process_action(action)
        try:
            decision.source = "fallback" if fallback else "live"
            db.add(decision)
            db.commit()
            db.refresh(decision)
        except Exception as e:
            db.rollback()
            logger.warning("Failed to set source on decision %s: %s", getattr(decision, 'id', '?'), e)
            decision.source = "fallback" if fallback else "live"
        decision_payload = {
            "id": decision.id,
            "verdict": decision.verdict,
            "block_reason": decision.block_reason,
            "reasoning": decision.reasoning,
            "source": decision.source,
        }
    except Exception as e:
        logger.exception("Coordination after order creation failed: %s", e)
        db.rollback()
        decision_payload = None

    latency_ms = int((time.time() - start) * 1000)
    return {
        "order": {
            "id": order.id,
            "status": order.status,
            "amount": order.amount,
            "currency": order.currency,
            "customer_id": order.customer_id,
            "fallback": fallback,
            "failure_reason": failure_reason,
            "razorpay_response": razorpay_order,
        },
        "decision": decision_payload,
        "latency_ms": latency_ms,
        "banner": "⚠️ RazorPay unavailable — using cached coordination decision" if fallback else None,
    }


@router.get("")
def list_orders(customer_id: str = None, db: Session = Depends(get_db)):
    q = db.query(Order)
    if customer_id:
        q = q.filter(Order.customer_id == customer_id)
    orders = q.order_by(Order.created_at.desc()).limit(50).all()
    return [
        {
            "id": o.id,
            "customer_id": o.customer_id,
            "amount": o.amount,
            "currency": o.currency,
            "status": o.status,
            "failure_reason": o.failure_reason,
            "created_at": o.created_at.isoformat() if o.created_at else None,
        }
        for o in orders
    ]
