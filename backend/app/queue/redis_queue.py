"""Option B queue - Redis Stream with DB fallback.

Hot path: XADD razor:inbox -> XREADGROUP reasoning consumers.
Cold path: DB inbox_entries always written for replay/audit.
If REDIS_URL empty or redis unavailable -> in-memory/DB fallback (tests, dev without docker).

Ordering guarantee: the DB row is committed BEFORE the Redis message is
published, so a worker that dequeues immediately can always find the
matching inbox row and never races an uncommitted webhook transaction.
"""
import json
import uuid
import logging
import time
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from app.config import settings

logger = logging.getLogger(__name__)

_redis_client = None


def get_redis():
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    if not settings.REDIS_URL:
        return None
    try:
        import redis
        _redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True, socket_timeout=2)
        _redis_client.ping()
        logger.info("Redis connected: %s stream=%s", settings.REDIS_URL, settings.REDIS_STREAM)
        # ensure consumer group exists
        try:
            _redis_client.xgroup_create(settings.REDIS_STREAM, settings.REDIS_CONSUMER_GROUP, id="0", mkstream=True)
            logger.info("Created consumer group %s", settings.REDIS_CONSUMER_GROUP)
        except Exception as e:
            if "BUSYGROUP" not in str(e):
                logger.warning("xgroup_create: %s", e)
        return _redis_client
    except Exception as e:
        logger.warning("Redis unavailable (%s) - falling back to DB queue", e)
        return None


def publish_inbox_to_redis(inbox_id: str, event: str, payload: Dict[str, Any],
                           customer_id: Optional[str] = None,
                           order_id: Optional[str] = None) -> bool:
    """Publish an already-committed inbox row to the Redis hot path.

    Never touches the DB. Returns True if published, False if Redis is
    down/absent (DB poller will pick the row up instead).
    """
    r = get_redis()
    if r is None:
        return False
    try:
        r.xadd(settings.REDIS_STREAM, {
            "id": inbox_id,
            "event": event,
            "payload": json.dumps(payload),
            "customer_id": customer_id or "",
            "order_id": order_id or "",
            "merchant_id": settings.MERCHANT_ID,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        logger.info("Published %s to Redis %s", inbox_id, settings.REDIS_STREAM)
        return True
    except Exception as e:
        logger.warning("Redis XADD failed for %s (DB fallback will cover): %s", inbox_id, e)
        return False


def _insert_inbox_row(db_session, inbox_id: str, event: str, payload: Dict[str, Any],
                      customer_id: Optional[str], order_id: Optional[str]) -> None:
    from app.models.inbox import InboxEntry
    ie = InboxEntry(
        id=inbox_id,
        event=event,
        customer_id=customer_id,
        order_id=order_id,
        merchant_id=settings.MERCHANT_ID,
        payload=json.dumps(payload),
        status="queued",
    )
    db_session.add(ie)
    db_session.flush()


def enqueue(event: str, payload: Dict[str, Any], customer_id: Optional[str] = None, order_id: Optional[str] = None, db_session=None) -> str:
    """Durably enqueue: DB commit first, Redis publish second.

    If db_session is passed, the row is flushed into it and the CALLER
    owns the commit (webhook commits order+inbox atomically, then we
    publish to Redis separately). Otherwise we open our own session,
    commit with retry, then publish.
    """
    from app.db.database import SessionLocal, commit_with_retry, is_locked_error

    inbox_id = f"inbox_{uuid.uuid4().hex[:12]}"

    # Caller-owned session (webhook hot path): flush only, no commit here.
    # Caller must commit_with_retry() then call publish_inbox_to_redis().
    if db_session is not None:
        try:
            _insert_inbox_row(db_session, inbox_id, event, payload, customer_id, order_id)
        except Exception as e:
            try:
                db_session.rollback()
            except Exception:
                pass
            logger.warning("DB inbox write (same session) failed, will retry with fresh session: %s", e)
            # Fall through to fresh-session path so the inbox row is not lost.
            # (Caller will see the rollback; it retries its whole unit of work.)
            raise
        return inbox_id

    # Standalone path: own session, commit with retry, then publish.
    for attempt in range(5):
        db = SessionLocal()
        try:
            try:
                _insert_inbox_row(db, inbox_id, event, payload, customer_id, order_id)
            except Exception:
                try:
                    db.rollback()
                except Exception:
                    pass
                raise
            commit_with_retry(db)
            break
        except Exception as e:
            if is_locked_error(e) and attempt < 4:
                time.sleep(0.05 * (2 ** attempt))
                continue
            logger.warning("DB inbox write failed: %s", e)
            break
        finally:
            db.close()

    publish_inbox_to_redis(inbox_id, event, payload, customer_id, order_id)
    return inbox_id


def dequeue_block(timeout_ms: int = 5000) -> Optional[Dict[str, Any]]:
    """Blocking dequeue from Redis (for workers). Returns None if no Redis or timeout."""
    r = get_redis()
    if r is None:
        return None
    try:
        resp = r.xreadgroup(
            settings.REDIS_CONSUMER_GROUP,
            settings.REDIS_CONSUMER_NAME,
            {settings.REDIS_STREAM: ">"},
            count=1,
            block=timeout_ms,
        )
        if not resp:
            return None
        # resp = [(stream, [(id, fields)])]
        stream, entries = resp[0]
        msg_id, fields = entries[0]
        return {"msg_id": msg_id, "fields": fields}
    except Exception as e:
        # A blocking read with no messages inside the window raises a socket
        # timeout. That is the idle steady state, not a failure: stay quiet
        # and let the worker poll again. Only real errors get logged.
        if "timeout" in type(e).__name__.lower() or "timeout" in str(e).lower():
            return None
        logger.warning("XREADGROUP failed: %s", e)
        return None


def ack(msg_id: str):
    r = get_redis()
    if r is None:
        return
    try:
        r.xack(settings.REDIS_STREAM, settings.REDIS_CONSUMER_GROUP, msg_id)
    except Exception as e:
        logger.warning("XACK failed: %s", e)
