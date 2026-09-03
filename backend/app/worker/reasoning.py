"""Reasoning worker - Option B consumer.

Reads from Redis Stream razor:inbox (or DB fallback) and runs:
Dispatcher (candidates -> LLM propose -> Policy score -> winner) -> Governor -> Audit
"""
import json
import logging
import time
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.db.database import SessionLocal, commit_with_retry, is_locked_error
from app.models.customer import CustomerContext

logger = logging.getLogger(__name__)


def ensure_order_stub(db: Session, razorpay_order_id: str, customer_id: str,
                      entity: Dict[str, Any], event: str, retries: int = 5) -> None:
    """Idempotent order stub for the worker (mirrors webhooks.upsert_order_stub).

    The webhook thread may have already inserted this order id; a duplicate
    PK insert raises IntegrityError which we absorb via update. Lock
    contention is retried with backoff. Every failure path rolls back so the
    session is never left in PendingRollback state.
    """
    from app.models.order import Order
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
                db.flush()
            return
        except IntegrityError:
            try:
                db.rollback()
            except Exception:
                pass
            return  # row exists now (inserted concurrently) - nothing to do
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


def process_inbox_item(event: str, payload: Dict[str, Any], db: Session) -> Optional[Dict[str, Any]]:
    """Core reasoning logic - called by both Redis worker and DB fallback."""
    # Extract entity same as webhooks.py
    entity = (
        payload.get("payload", {}).get("payment", {}).get("entity")
        or payload.get("payload", {}).get("order", {}).get("entity")
        or {}
    )
    notes = entity.get("notes") or {}
    customer_id = notes.get("customer_id") or entity.get("customer_id") or payload.get("customer_id")
    razorpay_order_id = entity.get("order_id") or entity.get("id") or payload.get("razorpay_order_id")

    if not customer_id:
        try:
            from app.services.customer_resolve import resolve_fallback_customer
            fallback = resolve_fallback_customer(db, settings.MERCHANT_ID)
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass
            fallback = None
        if fallback:
            customer_id = fallback.id
        else:
            logger.warning("No customer for event %s", event)
            return None

    # Ensure order stub (idempotent; never poisons the session on failure)
    if razorpay_order_id:
        try:
            ensure_order_stub(db, razorpay_order_id, customer_id, entity, event)
        except Exception as e:
            logger.warning("Order stub failed after retries: %s", e)

    # v4: single shared full-cycle path (same as POST /orders).
    try:
        customer = db.query(CustomerContext).filter(CustomerContext.id == customer_id).first()
    except Exception as e:
        logger.warning("Customer lookup failed, rolled back: %s", e)
        try:
            db.rollback()
        except Exception:
            pass
        return None
    if not customer:
        logger.warning("Customer %s not found for event %s", customer_id, event)
        return None

    amount = float(entity.get("amount", 0)) / 100.0 if entity.get("amount") else 0.0
    from app.engine.full_cycle import run_full_cycle
    try:
        fc = run_full_cycle(db, event=event, customer=customer, amount=amount, source="live", order_id=razorpay_order_id, action_prefix="webhook")
    except Exception as e:
        logger.exception("Reasoning failed: %s", e)
        try:
            db.rollback()
        except Exception:
            pass
        return None
    decision = fc["decision"]
    dispatcher_info = fc["dispatcher"]
    return {
        "event": event,
        "customer_id": customer_id,
        "order_id": razorpay_order_id,
        "decision": {
            "decision_id": decision.id,
            "verdict": decision.verdict,
            "block_reason": decision.block_reason,
            "reasoning": decision.reasoning,
            "source": getattr(decision, "source", "live"),
            "trigger_event": getattr(decision, "trigger_event", event),
            "dispatcher_winner": getattr(decision, "dispatcher_winner", dispatcher_info.get("winner")),
            "message_preview": fc["action"].message_template,
        },
        "dispatcher": dispatcher_info,
    }


def process_pending_db_queue(limit: int = 10):
    """DB fallback poller - processes queued inbox_entries when Redis is not available."""
    db = SessionLocal()
    try:
        from app.models.inbox import InboxEntry
        try:
            pending = db.query(InboxEntry).filter(InboxEntry.status == "queued").order_by(InboxEntry.created_at.asc()).limit(limit).all()
        except Exception as e:
            logger.warning("DB queue poll failed: %s", e)
            try:
                db.rollback()
            except Exception:
                pass
            return
        for entry in pending:
            entry_id = entry.id
            try:
                entry.status = "processing"
                commit_with_retry(db)
            except Exception as e:
                logger.warning("DB queue claim %s failed: %s", entry_id, e)
                continue
            try:
                payload = json.loads(entry.payload)
                result = process_inbox_item(entry.event, payload, db)
                # Re-fetch: process_inbox_item may have rolled back, detaching entry
                ie = db.query(InboxEntry).filter(InboxEntry.id == entry_id).first()
                if ie:
                    ie.status = "completed"
                    ie.processed_at = datetime.now(timezone.utc)
                commit_with_retry(db)
                logger.info("DB queue processed %s -> %s", entry_id, result)
            except Exception as e:
                logger.exception("DB queue item %s failed: %s", entry_id, e)
                try:
                    db.rollback()
                except Exception:
                    pass
                try:
                    ie = db.query(InboxEntry).filter(InboxEntry.id == entry_id).first()
                    if ie:
                        ie.status = "failed"
                        ie.error = str(e)[:2000]
                    commit_with_retry(db)
                except Exception:
                    try:
                        db.rollback()
                    except Exception:
                        pass
    finally:
        db.close()


def worker_loop(stop_event=None):
    """Blocking worker loop - XREADGROUP with DB fallback."""
    logger.info("Reasoning worker started (redis_enabled=%s)", settings.redis_enabled)
    while True:
        if stop_event and stop_event.is_set():
            break
        # Prefer Redis
        if settings.redis_enabled:
            from app.queue.redis_queue import dequeue_block, ack
            item = dequeue_block(timeout_ms=5000)
            if item:
                msg_id = item["msg_id"]
                fields = item["fields"]
                event = fields.get("event", "unknown")
                payload_raw = fields.get("payload", "{}")
                inbox_id = fields.get("id", "unknown")
                try:
                    payload = json.loads(payload_raw)
                except Exception:
                    payload = {}
                db = SessionLocal()
                try:
                    result = process_inbox_item(event, payload, db)
                    # Mark inbox entry completed (re-query: reasoning may have
                    # rolled back mid-way, detaching earlier objects)
                    try:
                        from app.models.inbox import InboxEntry
                        ie = db.query(InboxEntry).filter(InboxEntry.id == inbox_id).first()
                        if ie:
                            ie.status = "completed"
                            ie.processed_at = datetime.now(timezone.utc)
                        commit_with_retry(db)
                    except Exception as e:
                        logger.warning("Inbox completion mark failed for %s: %s", inbox_id, e)
                    ack(msg_id)
                except Exception as e:
                    logger.exception("Worker item %s failed: %s", msg_id, e)
                    try:
                        db.rollback()
                    except Exception:
                        pass
                    try:
                        from app.models.inbox import InboxEntry
                        ie = db.query(InboxEntry).filter(InboxEntry.id == inbox_id).first()
                        if ie:
                            ie.status = "failed"
                            ie.error = str(e)[:2000]
                            commit_with_retry(db)
                    except Exception:
                        try:
                            db.rollback()
                        except Exception:
                            pass
                    # Still ack to avoid poison loop (or use XCLAIM for retry)
                    ack(msg_id)
                finally:
                    db.close()
            else:
                # No Redis message, also poll DB fallback for any missed items
                process_pending_db_queue(limit=5)
        else:
            # No Redis - poll DB every 2s
            process_pending_db_queue(limit=5)
            time.sleep(2)
