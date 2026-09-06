# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# Stage 1 - builder: resolves dependencies into an isolated virtualenv and
# compiles the .proto. Neither pip nor protoc are needed at runtime, so both
# stay behind in this stage.
# ---------------------------------------------------------------------------
FROM python:3.14-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# requirements.txt is copied on its own so this layer is reused on every build
# where only application code changed.
COPY gateway/requirements.txt ./
RUN pip install --no-cache-dir --no-compile -r requirements.txt

# Both images generate their stubs from the same .proto, which is what keeps
# client and server on one contract.
COPY proto/ ./proto/
RUN python -m grpc_tools.protoc -I proto \
        --python_out=. --grpc_python_out=. --pyi_out=. \
        proto/node_registry.proto

# grpc_tools ships a bundled protoc binary and the well-known .proto files:
# ~30 MB that only mattered for the command above. pip and the bytecode caches
# go the same way, before the venv is copied into the runtime stage.
RUN rm -rf /opt/venv/lib/python*/site-packages/grpc_tools \
           /opt/venv/lib/python*/site-packages/grpcio_tools* \
           /opt/venv/lib/python*/site-packages/pip \
           /opt/venv/lib/python*/site-packages/pip-*.dist-info \
           /opt/venv/bin/pip /opt/venv/bin/pip[0-9]* \
 && find /opt/venv -type d -name __pycache__ -prune -exec rm -rf {} +

# ---------------------------------------------------------------------------
# Stage 2 - runtime: the slim base plus the virtualenv, the stubs and the code.
# ---------------------------------------------------------------------------
FROM python:3.14-slim AS runtime

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Unprivileged account: a compromised container gets no root on the host.
RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin appuser

WORKDIR /app

COPY --from=builder --chown=appuser:appuser /opt/venv /opt/venv
COPY --from=builder --chown=appuser:appuser /app/node_registry_pb2.py \
                                            /app/node_registry_pb2_grpc.py ./
COPY --chown=appuser:appuser gateway/ ./gateway/

USER appuser

EXPOSE 8080

# Lets Docker and Compose restart the container when the API stops answering.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=3)" || exit 1

CMD ["uvicorn", "gateway.app:app", "--host", "0.0.0.0", "--port", "8080"]
