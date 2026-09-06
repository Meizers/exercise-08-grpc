"""
Container healthcheck for the gRPC server.

Docker's HEALTHCHECK runs a command inside the container, and this service has
no HTTP endpoint to curl. So the probe is a gRPC client of one call: if the
Health RPC answers at all, the server is alive.

A degraded database is deliberately *not* a failure here, matching the gateway:
killing the container would not bring postgres back, and the reported status is
more useful to an operator than a restart loop.
"""

import os
import sys

import grpc

import node_registry_pb2 as pb2
import node_registry_pb2_grpc as pb2_grpc

TIMEOUT_SECONDS = 3.0


def main() -> int:
    target = f"127.0.0.1:{os.getenv('GRPC_PORT', '50051')}"
    try:
        with grpc.insecure_channel(target) as channel:
            stub = pb2_grpc.NodeRegistryStub(channel)
            stub.Health(pb2.Empty(), timeout=TIMEOUT_SECONDS)
    except grpc.RpcError:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
