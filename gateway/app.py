"""
Exercise 08 - REST gateway.

A thin translation layer: it speaks HTTP/JSON to the outside world and gRPC to
the registry. It holds no business logic and never touches the database -- if
an endpoint here needs to know something, it asks the gRPC server.

The interesting part is the error translation. REST carries failures as status
codes on the response; gRPC carries them as status codes on the call itself,
outside the response message. Every RPC below funnels through _call(), which
turns one into the other.
"""

import os
from contextlib import asynccontextmanager

import grpc
from fastapi import FastAPI, HTTPException, Response, status

import node_registry_pb2 as pb2
import node_registry_pb2_grpc as pb2_grpc

from . import schemas

DEFAULT_TARGET = "grpc_server:50051"
# Ceiling on a single RPC. Without it a hung registry would hang the gateway's
# worker thread indefinitely instead of returning 504.
RPC_TIMEOUT_SECONDS = 5.0
# The health probe gets a tighter budget than a real request: the container
# HEALTHCHECK gives up after 5s, and a probe that outlives its own deadline
# reports nothing at all.
HEALTH_TIMEOUT_SECONDS = 2.0
# How long startup waits for the registry before serving anyway.
STARTUP_TIMEOUT_SECONDS = 30.0

# gRPC status code -> HTTP status code. This table is the whole contract
# between the two protocols; the server picks the left column, clients see the
# right one.
GRPC_TO_HTTP = {
    grpc.StatusCode.NOT_FOUND: 404,
    grpc.StatusCode.ALREADY_EXISTS: 409,
    grpc.StatusCode.INVALID_ARGUMENT: 422,
    grpc.StatusCode.UNAVAILABLE: 503,
    grpc.StatusCode.DEADLINE_EXCEEDED: 504,
}
# Anything the registry did not classify is an upstream failure, not ours.
FALLBACK_HTTP_STATUS = 502
# Shown instead of the raw gRPC text when a timeout is really an outage.
UNAVAILABLE_DETAIL = "Registry unavailable"


def _target() -> str:
    """Address of the gRPC server, from the environment or the compose default."""
    return os.getenv("GRPC_SERVER_ADDRESS", DEFAULT_TARGET)


class _Registry:
    """Holds the gRPC channel, its stub and its last known connectivity state."""

    channel: grpc.Channel | None = None
    stub: pb2_grpc.NodeRegistryStub | None = None
    # The synchronous grpc.Channel cannot be polled for its state, so the value
    # is kept up to date by the subscription opened in lifespan().
    connectivity: grpc.ChannelConnectivity = grpc.ChannelConnectivity.IDLE


registry = _Registry()


def _remember_connectivity(state: grpc.ChannelConnectivity) -> None:
    """Callback invoked by gRPC on every channel state transition."""
    registry.connectivity = state


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Open one long-lived channel and reuse it for every request.

    A gRPC channel multiplexes concurrent calls over a single HTTP/2 connection,
    so creating one per request would throw away the main advantage of gRPC.
    """
    registry.channel = grpc.insecure_channel(_target())
    registry.stub = pb2_grpc.NodeRegistryStub(registry.channel)
    registry.channel.subscribe(_remember_connectivity, try_to_connect=True)
    try:
        # Connect eagerly so the first real request is not the one that pays
        # for the handshake. Failing here is not fatal: /health must stay
        # answerable so an operator can see *why* the gateway is unhappy.
        grpc.channel_ready_future(registry.channel).result(
            timeout=STARTUP_TIMEOUT_SECONDS
        )
    except grpc.FutureTimeoutError:
        print(f"registry at {_target()} is not reachable yet", flush=True)
    yield
    registry.channel.unsubscribe(_remember_connectivity)
    registry.channel.close()


app = FastAPI(
    title="Node Registry REST Gateway",
    description="REST front-end for the NodeRegistry gRPC service.",
    version="1.0.0",
    lifespan=lifespan,
)


def _status_of(exc: grpc.RpcError) -> grpc.StatusCode:
    """Classify a failed call, correcting a timeout on a dead channel.

    A registry that is simply gone does not refuse connections: its DNS name
    still resolves inside the compose network, so gRPC keeps retrying until the
    deadline and reports DEADLINE_EXCEEDED. That would surface as 504 "upstream
    too slow" when the truth is 503 "upstream is not there", so the channel
    state breaks the tie.
    """
    code = exc.code()
    if (
        code is grpc.StatusCode.DEADLINE_EXCEEDED
        and registry.connectivity is not grpc.ChannelConnectivity.READY
    ):
        return grpc.StatusCode.UNAVAILABLE
    return code


def _call(method_name: str, message):
    """Invoke an RPC and translate a gRPC failure into an HTTP one."""
    rpc = getattr(registry.stub, method_name)
    try:
        return rpc(message, timeout=RPC_TIMEOUT_SECONDS)
    except grpc.RpcError as exc:
        code = _status_of(exc)
        # exc.details() carries the message the server passed to context.abort,
        # so "Node not found" survives the trip unchanged. The exception is a
        # reclassified timeout, whose original text would be misleading.
        detail = UNAVAILABLE_DETAIL if code is not exc.code() else exc.details()
        raise HTTPException(
            status_code=GRPC_TO_HTTP.get(code, FALLBACK_HTTP_STATUS), detail=detail
        ) from exc


def _node_dict(node: pb2.NodeResponse) -> dict:
    """Turn a protobuf node into a plain dict for Pydantic.

    Done field by field on purpose: protobuf's own MessageToDict would rename
    created_at to createdAt and drop fields holding their default value.
    """
    return {
        "id": node.id,
        "name": node.name,
        "host": node.host,
        "port": node.port,
        "status": node.status,
        "created_at": node.created_at,
        "updated_at": node.updated_at,
    }


@app.get("/health", response_model=schemas.HealthResponse)
def health() -> schemas.HealthResponse:
    """Liveness probe covering the whole chain: gateway, registry, database.

    Always answers 200: an orchestrator needs the body to tell a degraded
    service from an unreachable one.
    """
    try:
        response = registry.stub.Health(pb2.Empty(), timeout=HEALTH_TIMEOUT_SECONDS)
    except grpc.RpcError:
        # The registry is down, so the database status is unknown from here.
        return schemas.HealthResponse(status="degraded", db="disconnected", nodes_count=0)
    return schemas.HealthResponse(
        status=response.status, db=response.db, nodes_count=response.nodes_count
    )


@app.post(
    "/api/nodes",
    response_model=schemas.NodeResponse,
    status_code=status.HTTP_201_CREATED,
)
def register_node(payload: schemas.NodeCreate) -> dict:
    """Register a node. Pydantic rejects malformed bodies with 422 before this
    function runs, so the RPC only ever sees well-formed input."""
    node = _call(
        "Register",
        pb2.RegisterRequest(name=payload.name, host=payload.host, port=payload.port),
    )
    return _node_dict(node)


@app.get("/api/nodes", response_model=list[schemas.NodeResponse])
def list_nodes() -> list[dict]:
    """List every node, active and inactive, oldest first."""
    result = _call("List", pb2.Empty())
    return [_node_dict(node) for node in result.nodes]


@app.get("/api/nodes/{name}", response_model=schemas.NodeResponse)
def get_node(name: str) -> dict:
    """Look up a single node by name."""
    return _node_dict(_call("Get", pb2.GetRequest(name=name)))


@app.put("/api/nodes/{name}", response_model=schemas.NodeResponse)
def update_node(name: str, payload: schemas.NodeUpdate) -> dict:
    """Update the endpoint of a node that moved to another host or port.

    Only the fields the client actually sent are copied onto the message, which
    is what makes the update partial on the other side: the server checks
    HasField and leaves the rest alone.
    """
    message = pb2.UpdateRequest(name=name)
    sent = {
        field: value
        for field, value in payload.model_dump(exclude_unset=True).items()
        if value is not None
    }
    if "host" in sent:
        message.host = sent["host"]
    if "port" in sent:
        message.port = sent["port"]
    return _node_dict(_call("Update", message))


@app.delete("/api/nodes/{name}", status_code=status.HTTP_204_NO_CONTENT)
def deregister_node(name: str) -> Response:
    """Soft-delete: the registry marks the node inactive and keeps the row."""
    _call("Delete", pb2.DeleteRequest(name=name))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
