"""Option B queue - Redis Stream with DB fallback.

Hot path: XADD razor:inbox -> XREADGROUP reasoning consumers.
Cold path: DB inbox_entries always written for replay/audit.
If REDIS_URL empty or redis unavailable -> in-memory/DB fallback (tests, dev without docker).
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


def enqueue(event: str, payload: Dict[str, Any], customer_id: Optional[str] = None, order_id: Optional[str] = None, db_session=None) -> str:
    """Enqueue to Redis Stream (hot) + DB inbox (cold). Returns inbox_id. If db_session passed, reuse it to avoid sqlite lock."""
    inbox_id = f"inbox_{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()
    entry = {
        "id": inbox_id,
        "event": event,
        "payload": json.dumps(payload),
        "customer_id": customer_id or "",
        "order_id": order_id or "",
        "merchant_id": settings.MERCHANT_ID,
        "created_at": now,
    }
    # 1. Hot: Redis XADD (never blocks webhook if down)
    r = get_redis()
    if r is not None:
        try:
            r.xadd(settings.REDIS_STREAM, entry)
            logger.info("Enqueued %s to Redis %s", inbox_id, settings.REDIS_STREAM)
        except Exception as e:
            logger.warning("Redis XADD failed, DB only: %s", e)
    # 2. Cold: DB inbox_entries (always)
    # Reuse passed session to avoid separate connection lock when called inside webhook transaction
    if db_session is not None:
        try:
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
        except Exception as e:
            logger.warning("DB inbox write (same session) failed: %s", e)
        return inbox_id
    for attempt in range(3):
        try:
            from app.db.database import SessionLocal
            from app.models.inbox import InboxEntry
            db = SessionLocal()
            try:
                ie = InboxEntry(
                    id=inbox_id,
                    event=event,
                    customer_id=customer_id,
                    order_id=order_id,
                    merchant_id=settings.MERCHANT_ID,
                    payload=json.dumps(payload),
                    status="queued",
                )
                db.add(ie)
                db.commit()
            finally:
                db.close()
            break
        except Exception as e:
            if "locked" in str(e).lower() and attempt < 2:
                time.sleep(0.15 * (attempt + 1))
                continue
            logger.warning("DB inbox write failed: %s", e)
            break
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

