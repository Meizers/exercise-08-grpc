# Exercise 08 — gRPC Service Communication

> **Distributed Systems & Parallel Programming — UNLu 2026**
>
> This exercise is part of the continuous assessment for the course. Throughout the semester you will solve hands-on exercises that are graded automatically. Each exercise builds on the previous one and reinforces concepts you will need for the major assignments: REST APIs, Docker, Compose, Kubernetes, messaging, etc.
>
> The goal is not just to "pass the tests" but to understand what you are building. Tests validate the output — comprehension is on you.

## Course topics covered

| Unit | Topic | How it applies here |
|------|-------|-------------------|
| **U1.8 Remote Procedure Call (RPC)** | gRPC, Protocol Buffers | Implement gRPC server + REST gateway. Compare with pure REST. |

---

## Automated grading

Every time you push to your fork, we will run hidden tests. Within 10 minutes you will receive a ✅/❌ comment on your latest commit.

You have a maximum of **5 submissions**.

**Deadline: July 15, 2026 at 23:59 UTC-3** (3 late days allowed with penalty)

---

## Context

Implement gRPC server + REST gateway. Compare with pure REST.

## How to submit

1. **Fork** this repo
2. Implement the solution
3. Push to your fork — grading is automatic

---

# Solution

## What this is

The node registry of exercise 01, split into two services. A REST client cannot
tell the difference: same paths, same status codes, same JSON. What changed is
what happens behind the gateway — the registry is now reached through a remote
procedure call instead of a local function call.

```
                    ┌──────────────────────── compose network ────────────────────────┐
                    │                                                                  │
  HTTP/JSON         │  ┌───────────────┐   gRPC / HTTP-2    ┌──────────────┐          │
  ─────────────────────▶    gateway    ├───────────────────▶│ grpc_server  ├──────────┼──▶ ┌────┐
  :8080             │  │   FastAPI     │  Protobuf, :50051  │  registry    │  psycopg2│    │ db │
                    │  │               │◀───────────────────┤  + SQLAlchemy│◀─────────┼────│ 17 │
                    │  └───────────────┘                    └──────────────┘          │    └────┘
                    │   published :8080                      no published port         │  no published port
                    └──────────────────────────────────────────────────────────────────┘
```

Only the gateway is reachable from the host. The registry and the database live
inside the network, addressed by their compose service names through Docker's
internal DNS.

## The contract

`proto/node_registry.proto` is the single source of truth. Both images run
`grpc_tools.protoc` against it at build time, so client and server stubs can
never drift from each other or from the file in the repo.

| RPC | REST endpoint | Notes |
|---|---|---|
| `Register(RegisterRequest) → NodeResponse` | `POST /api/nodes` | 201, or 409 on duplicate name |
| `List(Empty) → NodeList` | `GET /api/nodes` | every node, active and inactive |
| `Get(GetRequest) → NodeResponse` | `GET /api/nodes/{name}` | 404 if unknown |
| `Update(UpdateRequest) → NodeResponse` | `PUT /api/nodes/{name}` | partial update |
| `Delete(DeleteRequest) → Empty` | `DELETE /api/nodes/{name}` | soft delete, 204 |
| `Health(Empty) → HealthResponse` | `GET /health` | reports the whole chain |

## Errors: two protocols, two vocabularies

REST puts failures in the status line of the response. gRPC puts them on the
call itself, outside the response message: the server calls `context.abort`
with a status code and the client raises `RpcError`. The gateway owns the
translation, in `GRPC_TO_HTTP`:

| gRPC status | HTTP | Raised when |
|---|---|---|
| `ALREADY_EXISTS` | 409 | the UNIQUE constraint on `name` rejects an insert |
| `NOT_FOUND` | 404 | no row for that name |
| `INVALID_ARGUMENT` | 422 | port outside 1–65535 (server-side backstop) |
| `UNAVAILABLE` | 503 | the registry is not reachable |
| `DEADLINE_EXCEEDED` | 504 | the registry answered too slowly |
| anything else | 502 | unclassified upstream failure |

`exc.details()` carries the server's message across, so `404` still returns
exactly `{"detail": "Node not found"}`.

One subtlety: a stopped container does not refuse connections — its name still
resolves on the compose network — so gRPC retries until the deadline and reports
`DEADLINE_EXCEEDED`, which would surface as a misleading 504. The gateway
subscribes to channel connectivity and, if the channel is not `READY` when a
deadline expires, reports 503 instead. "Not there" and "too slow" are different
failures and deserve different codes.

## Design decisions

**Validation lives in the gateway, and again in the server.** Pydantic rejects a
malformed body with 422 before a byte reaches gRPC, which keeps FastAPI's
standard error shape. The server re-validates the port range anyway: it is
reachable by anything on the Docker network, so it does not trust its callers.

**`optional` on `UpdateRequest`.** proto3 scalars have no field presence: an
omitted `host` arrives as `""` and an omitted `port` as `0`, indistinguishable
from values sent on purpose. A `PUT` carrying only `port` would blank the host.
`optional` restores presence, and the server checks `HasField`. It is the same
problem Pydantic solves with `exclude_unset=True`, on the other side of the wire.

**Timestamps as ISO-8601 strings, not `google.protobuf.Timestamp`.** The gateway
serves them as JSON, so a string crosses the wire unmodified. `Timestamp` would
be the stricter choice for a polyglot system; here it would only add a
conversion at each end.

**One long-lived channel, opened at startup.** A gRPC channel multiplexes
concurrent calls over a single HTTP/2 connection. Building one per request would
pay a TCP and HTTP/2 handshake every time and discard the main advantage of the
protocol.

**The gateway gets no database credentials.** It has `GRPC_SERVER_ADDRESS` and
nothing else — no `env_file` in compose. It never opens a database connection,
so holding the password would be surface area with no purpose.

**The registry publishes no port.** Like the database, it is reachable only from
inside the compose network. The gateway is the only entrypoint.

**Health probe over gRPC.** The registry speaks no HTTP, so its Docker
`HEALTHCHECK` cannot be a curl. `grpc_server/healthcheck.py` is a one-call gRPC
client instead. A degraded database is deliberately not a failure: restarting
the container would not bring postgres back.

**Generated stubs are committed.** `node_registry_pb2*.py` are in the repo so it
can be inspected and tested without running `protoc` first, while the images
still regenerate them from the `.proto` at build time.

## gRPC vs pure REST, measured

Taken on this stack, from a container on the same compose network so both paths
start from the same place (300 calls after 30 warm-up calls):

**Message size**

| Message | Protobuf | JSON | Saved |
|---|---|---|---|
| node response (7 fields) | 98 B | 167 B | 41% |
| register request (3 fields) | 23 B | 49 B | 53% |

Protobuf never puts field *names* on the wire — `"created_at"` costs 12 bytes in
JSON and one byte of field tag in Protobuf — and it writes integers in binary
instead of as decimal text. The saving grows with the number of fields and
shrinks when payloads are dominated by long string values.

**Latency of `Get`**

| Path | mean | p50 | p95 |
|---|---|---|---|
| gRPC, direct to the registry | 0.84 ms | 0.83 ms | 0.97 ms |
| REST → gateway → gRPC | 2.04 ms | 1.94 ms | 2.57 ms |

The 1.2 ms difference is the cost of the extra hop: HTTP/1.1 parsing, Pydantic
validation and JSON serialisation in the gateway, plus a second network trip. It
is the price of keeping a REST interface for clients that cannot speak gRPC —
which is exactly what a gateway is for.

**Development experience.** The `.proto` is a real contract: rename a field and
nothing breaks, change its number and every old client breaks — silently, which
is why numbers are never reused. Compared with REST, the cost is a code
generation step in the build and the loss of `curl` as a debugging tool; the
gain is that client and server cannot disagree about the shape of a message.

## Running it

```bash
cp .env.example .env
docker compose up --build -d

curl localhost:8080/health
curl -X POST localhost:8080/api/nodes \
     -H 'Content-Type: application/json' \
     -d '{"name":"worker-1","host":"10.0.0.5","port":9001}'
curl localhost:8080/api/nodes

docker compose down -v
```

Regenerating the stubs after editing the contract (needs `grpcio-tools`):

```bash
make proto
```

## Layout

```
proto/node_registry.proto      the contract
node_registry_pb2*.py          generated stubs (committed, rebuilt in each image)
grpc_server/
  server.py                    the six RPCs, and the only code that sees the database
  models.py  database.py       SQLAlchemy model, engine and startup retry
  healthcheck.py               gRPC client used by Docker HEALTHCHECK
gateway/
  app.py                       REST endpoints and the gRPC error translation
  schemas.py                   Pydantic request/response models (source of the 422s)
docker-compose.yml             db + grpc_server + gateway
```
