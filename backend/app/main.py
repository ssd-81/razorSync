import logging
import threading
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db.database import init_db
from app.api.actions import router as actions_router
from app.api.customers import router as customers_router
from app.api.rules import router as rules_router
from app.api.audit import router as audit_router
from app.api.simulation import router as simulation_router
from app.api.webhooks import router as webhooks_router
from app.api.metrics import router as metrics_router
from app.api.orders import router as orders_router
from app.api.ops import router as ops_router
from app.api.decisions import router as decisions_router
from app.api.checkout import router as checkout_router
from app.api.hitl import router as hitl_router
from app.api.execution import router as execution_router
from app.api.agents_config import router as agents_config_router

logger = logging.getLogger(__name__)

_worker_thread = None
_stop_event = threading.Event()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    from app.db.database import SessionLocal
    from app.models.rule import BusinessRule
    import json

    db = SessionLocal()
    try:
        existing = db.query(BusinessRule).filter(BusinessRule.merchant_id == settings.MERCHANT_ID).count()
        if existing == 0:
            defaults = [
                {
                    "id": "rule_freq_default",
                    "name": "Frequency Cap — 2 contacts / 24h",
                    "description": "Max 2 contacts per customer in 24h window",
                    "rule_type": "frequency_cap",
                    "rule_config": {"max_contacts": 2, "window_hours": 24},
                    "priority": 10,
                },
                {
                    "id": "rule_cooldown_default",
                    "name": "Cooldown — 4h between contacts",
                    "description": "Minimum 4h gap between contacts",
                    "rule_type": "cooldown",
                    "rule_config": {"cooldown_hours": 4},
                    "priority": 9,
                },
                {
                    "id": "rule_time_window_default",
                    "name": "Time Window — 09:00-21:00 IST",
                    "description": "Only contact 09:00-21:00 IST",
                    "rule_type": "time_window",
                    "rule_config": {"start_hour": 9, "end_hour": 21},
                    "priority": 8,
                },
                {
                    "id": "rule_budget_default",
                    "name": "Budget Limit — ₹200 discount cap",
                    "description": "Cumulative discount exposure per customer",
                    "rule_type": "budget_limit",
                    "rule_config": {"max_discount": 200},
                    "priority": 7,
                },
                {
                    "id": "rule_escalation_default",
                    "name": "Escalation Ceiling — 3 per 7 days",
                    "description": "Max 3 escalations in 7 days",
                    "rule_type": "escalation_ceiling",
                    "rule_config": {"max_escalations": 3, "window_hours": 168},
                    "priority": 6,
                },
            ]
            for r in defaults:
                br = BusinessRule(
                    id=r["id"],
                    merchant_id=settings.MERCHANT_ID,
                    name=r["name"],
                    description=r["description"],
                    applies_to_agents=json.dumps([]),
                    applies_to_channels=json.dumps([]),
                    rule_type=r["rule_type"],
                    rule_config=json.dumps(r["rule_config"]),
                    priority=r["priority"],
                    is_active=True,
                )
                db.add(br)
            db.commit()
            logger.info("Seeded %d default rules", len(defaults))
    except Exception as e:
        logger.warning("Failed to seed default rules: %s", e)
        db.rollback()
    finally:
        db.close()

    # Option B: Start reasoning worker thread if Redis configured
    global _worker_thread
    if settings.redis_enabled:
        try:
            from app.worker.reasoning import worker_loop
            _stop_event.clear()
            _worker_thread = threading.Thread(target=worker_loop, args=(_stop_event,), daemon=True)
            _worker_thread.start()
            logger.info("Reasoning worker started (Redis %s)", settings.REDIS_URL)
        except Exception as e:
            logger.warning("Failed to start worker: %s", e)
    else:
        logger.info("REASONING worker not started - REDIS_URL empty (DB fallback, tests use sync path)")

    yield
    _stop_event.set()
    logger.info("Shutting down RazorSync v2")


app = FastAPI(title=settings.APP_NAME, version=settings.APP_VERSION, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(actions_router)
app.include_router(customers_router)
app.include_router(rules_router)
app.include_router(audit_router)
app.include_router(simulation_router)
app.include_router(webhooks_router)
app.include_router(metrics_router)
app.include_router(orders_router)
app.include_router(ops_router)
app.include_router(decisions_router)
app.include_router(checkout_router)
app.include_router(hitl_router)
app.include_router(execution_router)
app.include_router(agents_config_router)


@app.get("/")
def root():
    return {"service": settings.APP_NAME, "version": settings.APP_VERSION, "status": "ok"}


@app.get("/health")
def health():
    return {"status": "ok", "merchant_id": settings.MERCHANT_ID, "debug": settings.DEBUG}
