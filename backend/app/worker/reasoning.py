"""Reasoning worker - Option B consumer.

Reads from Redis Stream razor:inbox (or DB fallback) and runs:
Dispatcher (candidates -> LLM propose -> Policy score -> winner) -> Governor -> Audit
"""
import json
import uuid
import logging
import time
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session

from app.config import settings
from app.db.database import SessionLocal
from app.models.customer import CustomerContext
from app.models.action import AgentAction
from app.models.audit import AuditEntry

logger = logging.getLogger(__name__)


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
        fallback = db.query(CustomerContext).filter(CustomerContext.merchant_id == settings.MERCHANT_ID).first()
        if fallback:
            customer_id = fallback.id
        else:
            logger.warning("No customer for event %s", event)
            return None

    # Ensure order stub
    if razorpay_order_id:
        try:
            from app.models.order import Order
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
        except Exception as e:
            logger.warning("Order stub failed: %s", e)

    # Dispatcher -> Governor
    from app.engine.dispatcher import dispatch
    customer = db.query(CustomerContext).filter(CustomerContext.id == customer_id).first()
    if not customer:
        logger.warning("Customer %s not found for event %s", customer_id, event)
        return None

    amount = float(entity.get("amount", 0)) / 100.0 if entity.get("amount") else 0.0
    dispatcher_result = dispatch(event, customer, settings.MERCHANT_ID, amount, db)

    decision_payload = None
    if dispatcher_result.winner:
        try:
            from app.engine.coordinator import CoordinationEngine
            winner = dispatcher_result.winner
            now = datetime.now(timezone.utc)
            action = AgentAction(
                id=f"act_{uuid.uuid4().hex[:12]}",
                agent_id=f"{winner['agent_type']}_webhook_{uuid.uuid4().hex[:6]}",
                agent_type=winner["agent_type"],
                customer_id=customer_id,
                merchant_id=settings.MERCHANT_ID,
                action_type=f"webhook_{event}",
                channel=winner["channel"],
                priority=7,
                message_template=f"{winner.get('reasoning', winner['agent_type'])} for order {razorpay_order_id}",
                discount_offered=winner["discount_offered"],
                amount_involved=amount,
                proposed_at=now,
                proposed_delay_seconds=int(winner.get("delay_h", 0) * 3600),
                confidence=winner["confidence"],
                reasoning=f"Dispatcher winner: {winner['agent_type']} (score={winner['score']:.4f}) — {winner.get('reasoning', '')}",
            )
            db.add(action)
            db.flush()
            engine = CoordinationEngine(db)
            decision = engine.process_action(action)
            # Ensure source is live (process_action commits)
            try:
                decision.source = "live"
                db.add(decision)
                db.commit()
                db.refresh(decision)
            except Exception:
                db.commit()

            # Enrich audit
            audit = db.query(AuditEntry).filter(AuditEntry.decision_id == decision.id).first()
            if audit:
                audit.webhook_event = event
                audit.razorpay_order_id = razorpay_order_id
                db.add(audit)
                db.commit()

            decision_payload = {
                "decision_id": decision.id,
                "verdict": decision.verdict,
                "block_reason": decision.block_reason,
                "reasoning": decision.reasoning,
                "source": getattr(decision, "source", "live"),
            }
            logger.info("Processed %s → winner %s → %s (%s)", event, winner["agent_type"], decision.id, decision.verdict)
        except Exception as e:
            logger.exception("Reasoning failed: %s", e)
            db.rollback()
    elif dispatcher_result and dispatcher_result.candidates:
        # All candidates blocked at policy level (score ≤0). Still create a visible blocked decision
        # so frontend polling (decisions/recent) has something to show instead of infinite "waiting".
        try:
            from app.models.decision import CoordinationDecision
            best = dispatcher_result.candidates[0]  # highest (least negative) score
            now = datetime.now(timezone.utc)
            action = AgentAction(
                id=f"act_{uuid.uuid4().hex[:12]}",
                agent_id=f"{best['agent_type']}_policy_block_{uuid.uuid4().hex[:6]}",
                agent_type=best["agent_type"],
                customer_id=customer_id,
                merchant_id=settings.MERCHANT_ID,
                action_type=f"webhook_{event}",
                channel=best["channel"],
                priority=7,
                message_template=f"Policy blocked: {best['agent_type']} (score={best['score']:.4f}) for order {razorpay_order_id}",
                discount_offered=best["discount_offered"],
                amount_involved=amount,
                proposed_at=now,
                proposed_delay_seconds=int(best.get("delay_h", 0) * 3600),
                confidence=best["confidence"],
                reasoning=f"Policy blocked — {dispatcher_result.block_reason} — best was {best['agent_type']} ({best['score']:.4f})",
            )
            db.add(action)
            db.flush()
            decision = CoordinationDecision(
                id=f"dec_{uuid.uuid4().hex[:12]}",
                action_id=action.id,
                customer_id=customer_id,
                verdict="blocked",
                block_reason=dispatcher_result.block_reason or f"Policy: all candidates scored ≤0 (best {best['agent_type']}={best['score']:.4f})",
                rules_applied="[]",
                reasoning=f"Policy blocked — {dispatcher_result.block_reason}",
                confidence=float(best["confidence"] or 0.5),
                source="live",
            )
            db.add(decision)
            db.flush()
            audit = AuditEntry(
                id=f"aud_{uuid.uuid4().hex[:12]}",
                customer_id=customer_id,
                merchant_id=settings.MERCHANT_ID,
                action_id=action.id,
                decision_id=decision.id,
                customer_snapshot=json.dumps({"id": customer_id, "dispatcher_block": True}),
                active_agent_count=len(dispatcher_result.candidates),
                rules_evaluated=json.dumps([]),
                webhook_event=event,
                razorpay_order_id=razorpay_order_id,
            )
            db.add(audit)
            db.commit()
            decision_payload = {
                "decision_id": decision.id,
                "verdict": "blocked",
                "block_reason": decision.block_reason,
                "reasoning": decision.reasoning,
                "source": "live",
            }
            logger.info("Policy blocked %s → created blocked decision %s for %s: %s", event, decision.id, best["agent_type"], decision.block_reason)
        except Exception as e:
            logger.exception("Policy-blocked handling failed: %s", e)
            db.rollback()

    return {
        "event": event,
        "customer_id": customer_id,
        "order_id": razorpay_order_id,
        "decision": decision_payload,
        "dispatcher": {
            "candidates": [{"agent_type": c["agent_type"], "channel": c["channel"], "score": c["score"]} for c in dispatcher_result.candidates],
            "winner": dispatcher_result.winner["agent_type"] if dispatcher_result.winner else None,
        } if dispatcher_result else None,
    }


def process_pending_db_queue(limit: int = 10):
    """DB fallback poller - processes queued inbox_entries when Redis is not available."""
    db = SessionLocal()
    try:
        from app.models.inbox import InboxEntry
        pending = db.query(InboxEntry).filter(InboxEntry.status == "queued").order_by(InboxEntry.created_at.asc()).limit(limit).all()
        for entry in pending:
            entry.status = "processing"
            db.commit()
            try:
                payload = json.loads(entry.payload)
                result = process_inbox_item(entry.event, payload, db)
                entry.status = "completed"
                entry.processed_at = datetime.now(timezone.utc)
                db.commit()
                logger.info("DB queue processed %s -> %s", entry.id, result)
            except Exception as e:
                logger.exception("DB queue item %s failed: %s", entry.id, e)
                entry.status = "failed"
                entry.error = str(e)
                db.commit()
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
                    # Mark inbox entry completed
                    try:
                        from app.models.inbox import InboxEntry
                        ie = db.query(InboxEntry).filter(InboxEntry.id == inbox_id).first()
                        if ie:
                            ie.status = "completed"
                            ie.processed_at = datetime.now(timezone.utc)
                            db.commit()
                    except Exception:
                        pass
                    ack(msg_id)
                except Exception as e:
                    logger.exception("Worker item %s failed: %s", msg_id, e)
                    try:
                        db.rollback()
                        from app.models.inbox import InboxEntry
                        ie = db.query(InboxEntry).filter(InboxEntry.id == inbox_id).first()
                        if ie:
                            ie.status = "failed"
                            ie.error = str(e)
                            db.commit()
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
