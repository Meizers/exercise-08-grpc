"""
Pydantic schemas for the REST surface.

These are the gateway's own contract with HTTP clients, deliberately kept apart
from the protobuf messages: Pydantic is what produces the 422 responses on bad
input, before a single byte reaches the gRPC server.
"""

from datetime import datetime

from pydantic import BaseModel, Field

PORT_MIN = 1
PORT_MAX = 65535


class NodeCreate(BaseModel):
    """Body of POST /api/nodes. Every field is mandatory."""

    name: str = Field(..., min_length=1, description="Unique node identifier")
    host: str = Field(..., min_length=1, description="IP address or hostname")
    port: int = Field(..., ge=PORT_MIN, le=PORT_MAX, description="TCP port")


class NodeUpdate(BaseModel):
    """Body of PUT /api/nodes/{name}. Partial update: both fields optional."""

    host: str | None = Field(None, min_length=1)
    port: int | None = Field(None, ge=PORT_MIN, le=PORT_MAX)


class NodeResponse(BaseModel):
    """Representation returned by every endpoint that serves a node.

    Timestamps arrive from gRPC as ISO-8601 strings; declaring them as datetime
    lets Pydantic parse and re-serialize them, so the JSON is identical to what
    a direct database-backed REST API would emit.
    """

    id: int
    name: str
    host: str
    port: int
    status: str
    created_at: datetime
    updated_at: datetime


class HealthResponse(BaseModel):
    """Body of GET /health."""

    status: str
    db: str
    nodes_count: int
