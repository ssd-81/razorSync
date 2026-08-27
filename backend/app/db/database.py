import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from app.config import settings

logger = logging.getLogger(__name__)

engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 30} if "sqlite" in settings.DATABASE_URL else {},
    echo=settings.DEBUG,
)
# Enable WAL mode for better concurrent write handling (fixes "database is locked" under stress)
if "sqlite" in settings.DATABASE_URL:
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql("PRAGMA journal_mode=WAL;")
            conn.exec_driver_sql("PRAGMA synchronous=NORMAL;")
            conn.exec_driver_sql("PRAGMA busy_timeout=30000;")
            conn.commit()
        logger.info("SQLite WAL mode enabled")
    except Exception as e:
        logger.warning("Failed to set WAL mode: %s", e)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


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
    logger.info("Database initialized: %s (echo=%s)", settings.DATABASE_URL, settings.DEBUG)
