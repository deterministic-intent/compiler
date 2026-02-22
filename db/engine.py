"""Database engine configuration and connection management."""

import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool


def _default_sqlite_url() -> str:
    """
    Default dev DB location (never repo-root dev.db).
    This keeps scraper/dev workflows working without requiring DEV_DB_URL,
    while avoiding dead mutable state in the active repo tree.
    """
    base = Path(__file__).resolve().parents[1]
    p = base / "state" / "dev" / "db" / "dev.db"
    p.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{p}"


# Get database URL from environment; default under state/ (gitignored).
DATABASE_URL = os.getenv("DEV_DB_URL", "").strip() or _default_sqlite_url()

# Create engine
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {},
    poolclass=StaticPool if "sqlite" in DATABASE_URL else None,
)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_engine():
    """Get the database engine."""
    return engine


def get_session() -> Session:
    """Get a database session."""
    return SessionLocal()
