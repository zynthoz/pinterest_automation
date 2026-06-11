"""SQLAlchemy database setup for SQLite."""

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings

# SQLite needs special handling for foreign keys
engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},  # needed for SQLite + threads (Celery)
    echo=False,
)


@event.listens_for(engine, "connect")
def _enable_sqlite_fks(dbapi_connection, _connection_record):
    """Enable foreign key enforcement in SQLite (disabled by default)."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")  # better concurrent read/write
    cursor.close()


SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""

    pass


def get_db() -> Session:
    """FastAPI dependency — yields a DB session and closes it after the request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables. Called on app startup."""
    # Import all models so they register with Base.metadata
    import app.models  # noqa: F401

    Base.metadata.create_all(bind=engine)
