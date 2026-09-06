"""
Database connection and session management for the gRPC server.

The connection string comes from the DATABASE_URL environment variable, which
docker-compose injects from the .env file. Nothing is hardcoded here: a missing
variable is a configuration error and fails loudly at startup.
"""

import os
import time

from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import declarative_base, sessionmaker


def _database_url() -> str:
    """Return the connection string, forcing the psycopg2 driver."""
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. Copy .env.example to .env before running."
        )
    # SQLAlchemy 2.x resolves "postgresql://" to the default DBAPI; being
    # explicit keeps the driver stable regardless of what else is installed.
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url


# pool_pre_ping discards connections the database dropped while idle, which
# happens whenever the db container restarts before this one does.
engine = create_engine(_database_url(), pool_pre_ping=True)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

Base = declarative_base()


def wait_for_database(attempts: int = 30, delay: float = 1.0) -> None:
    """Block until the database accepts connections.

    This container can win the race against postgres even with a healthcheck in
    depends_on, so startup retries instead of crash-looping.
    """
    last_error: Exception | None = None
    for _ in range(attempts):
        try:
            with engine.connect():
                return
        except OperationalError as exc:
            last_error = exc
            time.sleep(delay)
    raise RuntimeError(f"Database is unreachable after {attempts} attempts") from last_error
