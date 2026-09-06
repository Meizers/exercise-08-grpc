"""
Exercise 08 - Node Registry gRPC server.

The registry itself: it owns the database and exposes the five CRUD operations
plus a health probe as remote procedures. It speaks no HTTP at all -- the REST
gateway is its only client, and translates between the two protocols.

Errors do not travel inside the response message. They are raised as gRPC
status codes (ALREADY_EXISTS, NOT_FOUND, INVALID_ARGUMENT), which is the RPC
equivalent of an HTTP status code, and the gateway maps them back.
"""

import os
import signal
from concurrent import futures

import grpc
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

import node_registry_pb2 as pb2
import node_registry_pb2_grpc as pb2_grpc

from . import models
from .database import Base, SessionLocal, engine, wait_for_database

NOT_FOUND_DETAIL = "Node not found"
CONFLICT_DETAIL = "Node already registered"

PORT_MIN = 1
PORT_MAX = 65535

DEFAULT_PORT = 50051
# One thread per in-flight RPC: grpcio's Python server is synchronous, so the
# pool size is the ceiling on concurrent requests.
MAX_WORKERS = 10
# Give in-flight RPCs a moment to finish when the container is asked to stop.
GRACE_SECONDS = 5.0


def _listen_address() -> str:
    """Return the address the server binds to, from GRPC_PORT or the default."""
    port = os.getenv("GRPC_PORT", str(DEFAULT_PORT))
    # "[::]" binds both IPv4 and IPv6, which matters inside Docker networks.
    return f"[::]:{port}"


def _to_response(node: models.Node) -> pb2.NodeResponse:
    """Convert a database row into the wire representation of a node."""
    return pb2.NodeResponse(
        id=node.id,
        name=node.name,
        host=node.host,
        port=node.port,
        status=node.status,
        created_at=node.created_at.isoformat(),
        updated_at=node.updated_at.isoformat(),
    )


def _validate_port(port: int, context: grpc.ServicerContext) -> None:
    """Reject ports outside the TCP range.

    The gateway already rejects them with a 422, but the server does not trust
    its callers: it is reachable by anything on the Docker network.
    """
    if not PORT_MIN <= port <= PORT_MAX:
        context.abort(
            grpc.StatusCode.INVALID_ARGUMENT,
            f"port must be between {PORT_MIN} and {PORT_MAX}",
        )


class NodeRegistryServicer(pb2_grpc.NodeRegistryServicer):
    """Implementation of the NodeRegistry service defined in the .proto."""

    def Register(self, request, context):
        """Register a node. The name is the identity of the discovery protocol."""
        _validate_port(request.port, context)
        with SessionLocal() as db:
            node = models.Node(name=request.name, host=request.host, port=request.port)
            db.add(node)
            try:
                db.commit()
            except IntegrityError:
                # The UNIQUE constraint is the authority, not a prior SELECT:
                # two nodes can register the same name concurrently and only
                # one may win.
                db.rollback()
                context.abort(grpc.StatusCode.ALREADY_EXISTS, CONFLICT_DETAIL)
            db.refresh(node)
            return _to_response(node)

    def List(self, request, context):
        """List every node, active and inactive, oldest first."""
        with SessionLocal() as db:
            nodes = db.scalars(select(models.Node).order_by(models.Node.id)).all()
            return pb2.NodeList(nodes=[_to_response(node) for node in nodes])

    def Get(self, request, context):
        """Look up a single node by name."""
        with SessionLocal() as db:
            return _to_response(self._find(db, request.name, context))

    def Update(self, request, context):
        """Update the endpoint of a node that moved to another host or port.

        HasField is what makes the update partial: an omitted field is left
        untouched instead of being overwritten with proto3's zero value.
        """
        with SessionLocal() as db:
            node = self._find(db, request.name, context)
            if request.HasField("host"):
                node.host = request.host
            if request.HasField("port"):
                _validate_port(request.port, context)
                node.port = request.port
            db.commit()
            db.refresh(node)
            return _to_response(node)

    def Delete(self, request, context):
        """Soft-delete: mark the node inactive and keep the row for auditing."""
        with SessionLocal() as db:
            node = self._find(db, request.name, context)
            node.status = models.INACTIVE
            db.commit()
            return pb2.Empty()

    def Health(self, request, context):
        """Report database reachability and the number of active nodes.

        Never aborts: a degraded answer is more useful to the gateway than an
        error, because it distinguishes "registry down" from "database down".
        """
        try:
            with SessionLocal() as db:
                db.execute(text("SELECT 1"))
                active = db.scalar(
                    select(func.count())
                    .select_from(models.Node)
                    .where(models.Node.status == models.ACTIVE)
                )
            return pb2.HealthResponse(status="ok", db="connected", nodes_count=active or 0)
        except SQLAlchemyError:
            return pb2.HealthResponse(status="degraded", db="disconnected", nodes_count=0)

    @staticmethod
    def _find(db, name: str, context: grpc.ServicerContext) -> models.Node:
        """Return the node called `name` or abort with NOT_FOUND."""
        node = db.scalars(select(models.Node).where(models.Node.name == name)).first()
        if node is None:
            context.abort(grpc.StatusCode.NOT_FOUND, NOT_FOUND_DETAIL)
        return node


def serve() -> None:
    """Create the schema once the database is reachable, then serve forever."""
    wait_for_database()
    Base.metadata.create_all(bind=engine)

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=MAX_WORKERS))
    pb2_grpc.add_NodeRegistryServicer_to_server(NodeRegistryServicer(), server)
    server.add_insecure_port(_listen_address())
    server.start()
    print(f"gRPC server listening on {_listen_address()}", flush=True)

    # Compose sends SIGTERM on `down`/`stop`; without a handler the process is
    # killed after a 10s timeout and in-flight RPCs are cut mid-transaction.
    def _stop(signum, frame):
        server.stop(GRACE_SECONDS)

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    server.wait_for_termination()


if __name__ == "__main__":
    serve()
