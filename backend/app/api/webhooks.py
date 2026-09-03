import json
import uuid
import logging
import time
from datetime import datetime, timezone
from fastapi import APIRouter, Request, HTTPException, Header
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from fastapi import Depends
from starlette.requests import ClientDisconnect
from app.db.database import get_db, commit_with_retry, is_locked_error
from app.utils.time import utc_iso
from app.config import settings
from app.models.order import Order
from app.models.action import AgentAction
from app.models.audit import AuditEntry
from app.services.razorpay_client import razorpay_client

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/webhook", tags=["webhooks"])


def verify_signature(payload: bytes, signature: str) -> bool:
    return razorpay_client.verify_webhook_signature(payload, signature)


def upsert_order_stub(db: Session, razorpay_order_id: str, customer_id: str,
                      entity: dict, event: str, retries: int = 5) -> None:
    """Idempotent order upsert with rollback + retry on SQLite lock contention.

    Safe to call concurrently from the webhook thread and the worker thread
    for the same order id: duplicate PK raises IntegrityError, which we
    treat as 'already exists' and fall through to an update.
    """
    status = "paid" if event in ("payment.captured", "order.paid") else event
    last_exc = None
    for attempt in range(retries):
        try:
            existing = db.query(Order).filter(Order.id == razorpay_order_id).first()
            if existing is None:
                db.add(Order(
                    id=razorpay_order_id,
                    merchant_id=settings.MERCHANT_ID,
                    customer_id=customer_id,
                    amount=int(entity.get("amount", 0) or 0),
                    currency=entity.get("currency", "INR"),
                    status=status,
                    razorpay_response=json.dumps(entity),
                ))
            else:
                existing.status = status
                existing.razorpay_response = json.dumps(entity)
                db.add(existing)
            db.flush()
            return
        except IntegrityError:
            # Lost the insert race with the worker/another delivery for the
            # same order id -> row now exists, update it instead.
            try:
                db.rollback()
            except Exception:
                pass
            try:
                existing = db.query(Order).filter(Order.id == razorpay_order_id).first()
                if existing is not None:
                    existing.status = status
                    existing.razorpay_response = json.dumps(entity)
                    db.add(existing)
                    db.flush()
                return
            except Exception as e2:
                last_exc = e2
                try:
                    db.rollback()
                except Exception:
                    pass
                if is_locked_error(e2) and attempt < retries - 1:
                    time.sleep(0.05 * (2 ** attempt))
                    continue
                raise
        except Exception as e:
            last_exc = e
            try:
                db.rollback()
            except Exception:
                pass
            if is_locked_error(e) and attempt < retries - 1:
                time.sleep(0.05 * (2 ** attempt))
                continue
            raise
    if last_exc is not None:
        raise last_exc


@router.post("/razorpay")
async def handle_razorpay_webhook(
    request: Request,
    x_razorpay_signature: str = Header(None),
    db: Session = Depends(get_db),
):
    try:
        raw = await request.body()
    except ClientDisconnect:
        # Razorpay (or a retry) went away before we could read the body.
        # Ack 200 so it doesn't keep retrying; nothing was lost because we
        # never saw the payload. If it was a real event, Razorpay redelivers.
        logger.warning("Webhook client disconnected before body read - acking to stop retries")
        return {"status": "ok", "note": "client disconnected, acked to stop retries"}
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
            from app.services.customer_resolve import resolve_fallback_customer
            fallback = resolve_fallback_customer(db, settings.MERCHANT_ID)
            if fallback:
                customer_id = fallback.id
                logger.warning("Using fallback customer %s for webhook (no customer_id in payload) — dev only", customer_id)
            else:
                return {"status": "ok", "event": event, "note": "no customer found, ignored"}
    except Exception as e:
        logger.warning("Customer lookup failed: %s", e)
        return {"status": "ok", "event": event, "note": "lookup failed"}

    # Track order stub synchronously (so 200 ack has order linked).
    # Idempotent + rollback-safe: a lock failure here must not poison the
    # session for the inbox write below.
    if razorpay_order_id:
        try:
            upsert_order_stub(db, razorpay_order_id, customer_id, entity, event)
        except Exception as e:
            logger.warning("Order tracking failed after retries: %s", e)
            # Session was rolled back inside upsert_order_stub; safe to continue.

    # v3 Option B: Async ingestion - durable DB inbox commit FIRST, Redis
    # publish SECOND, ack <150ms. DB-first ordering guarantees the worker
    # never dequeues a message whose inbox row isn't committed yet (which
    # was the race causing duplicate order INSERTs + 'database is locked').
    from app.queue.redis_queue import publish_inbox_to_redis
    from app.models.inbox import InboxEntry
    inbox_id = f"inbox_{uuid.uuid4().hex[:12]}"
    try:
        db.add(InboxEntry(
            id=inbox_id,
            event=event,
            customer_id=customer_id,
            order_id=razorpay_order_id,
            merchant_id=settings.MERCHANT_ID,
            payload=json.dumps(payload),
            status="queued",
        ))
        commit_with_retry(db)  # commits order stub + inbox atomically
    except Exception as e:
        logger.warning("Inbox persist failed after retries: %s", e)
        # commit_with_retry already rolled back; return queued=false so the
        # caller knows, but still ack 200 (Razorpay will redeliver).
        return {"status": "ok", "event": event, "queued": False,
                "note": f"persist failed, will redeliver: {e}"}

    publish_inbox_to_redis(inbox_id, event, payload, customer_id, razorpay_order_id)
    logger.info("Persisted webhook %s inbox %s for async reasoning", event, inbox_id)

    # Fallback sync processing for tests / when Redis not configured
    # Ensures test_webhook_valid_and_invalid still gets decision synchronously
    if not settings.redis_enabled:
        try:
            from app.worker.reasoning import process_inbox_item
            result = process_inbox_item(event, payload, db)
            # Mark inbox completed - same session, no extra connection
            try:
                ie = db.query(InboxEntry).filter(InboxEntry.id == inbox_id).first()
                if ie:
                    ie.status = "completed" if result else "failed"
                    ie.processed_at = datetime.now(timezone.utc)
                    db.add(ie)
                commit_with_retry(db)
            except Exception as e:
                logger.warning("Failed to mark inbox %s completed: %s", inbox_id, e)

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
            "created_at": utc_iso(r.created_at),
            "processed_at": utc_iso(r.processed_at),
        }
        for r in rows
    ]
