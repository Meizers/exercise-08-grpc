.PHONY: proto up down logs test clean

# Regenerate the gRPC stubs from the contract. Run this after editing the
# .proto; the Docker images run the same command at build time.
proto:
	python -m grpc_tools.protoc -I proto --python_out=. --grpc_python_out=. --pyi_out=. proto/node_registry.proto

up:
	docker compose up --build -d

down:
	docker compose down -v

logs:
	docker compose logs -f

test:
	pytest tests/ -v

clean:
	rm -f node_registry_pb2.py node_registry_pb2_grpc.py node_registry_pb2.pyi
