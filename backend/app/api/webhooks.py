import json
import hmac
import hashlib
import uuid
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Request, HTTPException, Header
from sqlalchemy.orm import Session
from fastapi import Depends
from app.db.database import get_db
from app.config import settings
from app.models.customer import CustomerContext
from app.models.order import Order
from app.models.action import AgentAction
from app.models.audit import AuditEntry
from app.services.razorpay_client import razorpay_client

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/webhook", tags=["webhooks"])


def verify_signature(payload: bytes, signature: str) -> bool:
    return razorpay_client.verify_webhook_signature(payload, signature)


@router.post("/razorpay")
async def handle_razorpay_webhook(
    request: Request,
    x_razorpay_signature: str = Header(None),
    db: Session = Depends(get_db),
):
    raw = await request.body()
    if not verify_signature(raw, x_razorpay_signature or ""):
        logger.warning("Rejected webhook with invalid signature")
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    try:
        payload = json.loads(raw) if raw else {}
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    event = payload.get("event", "unknown")
    logger.info("Received webhook event: %s", event)

    # Resolve customer_id & order_id for enqueue (no hardcoded cust_0000 for prod)
    customer_id = None
    razorpay_order_id = None
    entity = {}
    try:
        entity = (
            payload.get("payload", {}).get("payment", {}).get("entity")
            or payload.get("payload", {}).get("order", {}).get("entity")
            or {}
        )
        notes = entity.get("notes") or {}
        customer_id = notes.get("customer_id") or entity.get("customer_id") or payload.get("customer_id")
        razorpay_order_id = entity.get("order_id") or entity.get("id") or payload.get("razorpay_order_id")
        if not customer_id:
            fallback = db.query(CustomerContext).filter(CustomerContext.merchant_id == settings.MERCHANT_ID).first()
            if fallback:
                customer_id = fallback.id
                logger.warning("Using fallback customer %s for webhook (no customer_id in payload) — dev only", customer_id)
            else:
                return {"status": "ok", "event": event, "note": "no customer found, ignored"}
    except Exception as e:
        logger.warning("Customer lookup failed: %s", e)
        return {"status": "ok", "event": event, "note": "lookup failed"}

    # Track order stub synchronously (so 200 ack has order linked)
    if razorpay_order_id:
        try:
            existing = db.query(Order).filter(Order.id == razorpay_order_id).first()
            if not existing:
                stub = Order(
                    id=razorpay_order_id,
                    merchant_id=settings.MERCHANT_ID,
                    customer_id=customer_id,
                    amount=int(entity.get("amount", 0)),
                    currency=entity.get("currency", "INR"),
                    status="paid" if event in ("payment.captured", "order.paid") else event,
                    razorpay_response=json.dumps(entity),
                )
                db.add(stub)
                db.flush()
            else:
                existing.status = "paid" if event in ("payment.captured", "order.paid") else event
                existing.razorpay_response = json.dumps(entity)
                db.add(existing)
                db.flush()
        except Exception as e:
            logger.warning("Order tracking failed: %s", e)

    # v3 Option B: Async ingestion - enqueue to Redis Stream + DB inbox, ack <150ms (reuse db session to avoid sqlite lock)
    from app.queue.redis_queue import enqueue
    inbox_id = enqueue(event, payload, customer_id, razorpay_order_id, db_session=db)
    # flush inbox insert together with order stub
    try:
        db.flush()
    except Exception:
        pass
    logger.info("Enqueued webhook %s inbox %s for async reasoning", event, inbox_id)

    # Fallback sync processing for tests / when Redis not configured
    # Ensures test_webhook_valid_and_invalid still gets decision synchronously
    if not settings.redis_enabled:
        try:
            from app.worker.reasoning import process_inbox_item
            result = process_inbox_item(event, payload, db)
            # Mark inbox completed - same session, no extra connection
            try:
                from app.models.inbox import InboxEntry
                ie = db.query(InboxEntry).filter(InboxEntry.id == inbox_id).first()
                if ie:
                    ie.status = "completed" if result else "failed"
                    ie.processed_at = datetime.now(timezone.utc)
                    db.add(ie)
                    db.commit()
                else:
                    db.commit()
            except Exception as e:
                logger.warning("Failed to mark inbox %s completed: %s", inbox_id, e)
                try:
                    db.commit()
                except Exception:
                    pass

            dispatcher_info = None
            decision_payload = None
            if result:
                decision_payload = result.get("decision")
                disp = result.get("dispatcher")
                if disp:
                    dispatcher_info = disp
            return {
                "status": "ok",
                "event": event,
                "customer_id": customer_id,
                "order_id": razorpay_order_id,
                "inbox_id": inbox_id,
                "queued": True,
                "decision": decision_payload,
                "dispatcher": dispatcher_info,
            }
        except Exception as e:
            logger.exception("Sync fallback processing failed: %s", e)
            # Still return queued

    # Redis enabled: async - worker will process
    # Return queued response immediately (<150ms)
    return {
        "status": "ok",
        "event": event,
        "customer_id": customer_id,
        "order_id": razorpay_order_id,
        "inbox_id": inbox_id,
        "queued": True,
        "note": "Queued for async reasoning (Option B)",
    }


@router.get("/inbox")
def list_inbox(limit: int = 20, status: str = None, db: Session = Depends(get_db)):
    """Inspect inbox queue (for inspection/debugging)."""
    from app.models.inbox import InboxEntry
    q = db.query(InboxEntry).order_by(InboxEntry.created_at.desc())
    if status:
        q = q.filter(InboxEntry.status == status)
    rows = q.limit(limit).all()
    return [
        {
            "id": r.id,
            "event": r.event,
            "customer_id": r.customer_id,
            "order_id": r.order_id,
            "status": r.status,
            "error": r.error,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "processed_at": r.processed_at.isoformat() if r.processed_at else None,
        }
        for r in rows
    ]
