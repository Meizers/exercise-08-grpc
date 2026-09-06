"""SQLAlchemy model for the nodes table."""

from sqlalchemy import Column, DateTime, Integer, String
from sqlalchemy.sql import func

from .database import Base

ACTIVE = "active"
INACTIVE = "inactive"


class Node(Base):
    """A node registered in the registry.

    Nodes are never physically removed: Delete flips `status` to "inactive" so
    the registry keeps a history of every peer that ever joined.
    """

    __tablename__ = "nodes"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False, index=True)
    host = Column(String, nullable=False)
    port = Column(Integer, nullable=False)
    status = Column(String, nullable=False, default=ACTIVE, server_default=ACTIVE)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
