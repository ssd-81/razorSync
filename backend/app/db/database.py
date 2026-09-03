import logging
import time
from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from sqlalchemy.exc import OperationalError
from sqlalchemy.pool import NullPool
from app.config import settings

logger = logging.getLogger(__name__)

_IS_SQLITE = "sqlite" in settings.DATABASE_URL

if _IS_SQLITE:
    # NullPool: one physical connection per Session. With SQLite + threads
    # (API threads + background worker thread) a shared QueuePool reuses a
    # single locked connection across threads and amplifies "database is locked".
    engine = create_engine(
        settings.DATABASE_URL,
        connect_args={"check_same_thread": False, "timeout": 30},
        poolclass=NullPool,
        echo=settings.DEBUG,
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_conn, _conn_record):
        # Runs on EVERY new DBAPI connection (pooling makes a one-time
        # PRAGMA insufficient). WAL allows reader/writer concurrency,
        # busy_timeout makes writers wait instead of instantly failing.
        cur = dbapi_conn.cursor()
        try:
            cur.execute("PRAGMA journal_mode=WAL;")
            cur.execute("PRAGMA synchronous=NORMAL;")
            cur.execute("PRAGMA busy_timeout=30000;")
            cur.execute("PRAGMA foreign_keys=ON;")
        finally:
            cur.close()

    logger.info("SQLite engine: NullPool + per-connection WAL/busy_timeout")
else:
    engine = create_engine(settings.DATABASE_URL, echo=settings.DEBUG)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def is_locked_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "database is locked" in msg or "database table is locked" in msg or "database is busy" in msg


def commit_with_retry(db: Session, retries: int = 5, base_sleep: float = 0.05) -> None:
    """Commit with exponential backoff on SQLite lock contention.

    Rolls back on every failure so the Session never stays in a
    PendingRollback state. Raises the last exception if all retries fail.
    """
    last: Exception | None = None
    for attempt in range(retries):
        try:
            db.commit()
            return
        except Exception as e:
            last = e
            try:
                db.rollback()
            except Exception:
                pass
            if is_locked_error(e) and attempt < retries - 1:
                time.sleep(base_sleep * (2**attempt))
                continue
            raise
    if last is not None:
        raise last


def get_db():
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    import app.models.customer  # noqa: F401
    import app.models.action  # noqa: F401
    import app.models.decision  # noqa: F401
    import app.models.rule  # noqa: F401
    import app.models.audit  # noqa: F401
    import app.models.simulation  # noqa: F401
    import app.models.order  # noqa: F401
    import app.models.hitl  # noqa: F401  # v3: HITL suspension tables
    import app.models.inbox  # noqa: F401  # v3: Option B async inbox

    Base.metadata.create_all(bind=engine)
    _migrate_dispatch_columns()
    _heal_customer_names()
    logger.info("Database initialized: %s (echo=%s)", settings.DATABASE_URL, settings.DEBUG)


def _heal_customer_names():
    """Backfill nameless customer rows (stale seeds / pre-name bugs).

    Runs on every boot; no-ops when clean. Keeps the Customers page and Ops
    dropdown from showing blank-name rows again.
    """
    try:
        from sqlalchemy import text
        with engine.connect() as conn:
            r1 = conn.execute(text("UPDATE customer_context SET name = id WHERE name IS NULL OR name = ''"))
            r2 = conn.execute(text("UPDATE customer_context SET archetype = 'new_customer' WHERE archetype IS NULL OR archetype = ''"))
            conn.commit()
            if (r1.rowcount or 0) + (r2.rowcount or 0) > 0:
                logger.info("Healed %s nameless / %s archetype-less customers", r1.rowcount, r2.rowcount)
    except Exception as e:
        logger.warning("Customer name heal skipped: %s", e)


def _migrate_dispatch_columns():
    """Lightweight SQLite/Postgres migration for v4 dispatcher trace columns.

    create_all() never alters existing tables, so ALTER TABLE when missing.
    Safe to run on every boot; no-ops when columns exist.
    """
    try:
        from sqlalchemy import text
        with engine.connect() as conn:
            if _IS_SQLITE:
                existing = {r[1] for r in conn.execute(text("PRAGMA table_info(coordination_decisions)")).fetchall()}
                wanted = {
                    "dispatcher_candidates": "ALTER TABLE coordination_decisions ADD COLUMN dispatcher_candidates TEXT",
                    "dispatcher_winner": "ALTER TABLE coordination_decisions ADD COLUMN dispatcher_winner VARCHAR",
                    "trigger_event": "ALTER TABLE coordination_decisions ADD COLUMN trigger_event VARCHAR",
                }
                for col, ddl in wanted.items():
                    if col not in existing:
                        conn.execute(text(ddl))
                        logger.info("Migrated coordination_decisions: added %s", col)
                conn.commit()
            else:
                for col, typ in [
                    ("dispatcher_candidates", "TEXT"),
                    ("dispatcher_winner", "VARCHAR"),
                    ("trigger_event", "VARCHAR"),
                ]:
                    conn.execute(text(
                        f"ALTER TABLE coordination_decisions ADD COLUMN IF NOT EXISTS {col} {typ}"
                    ))
                conn.commit()
    except Exception as e:
        logger.warning("Dispatcher column migration skipped: %s", e)
