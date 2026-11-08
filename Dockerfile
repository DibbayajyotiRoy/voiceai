# syntax=docker/dockerfile:1
# Demo/API image. Built for linux/arm64 (Fargate Graviton) by deploy/aws/deploy-demo.sh.
ARG PYTHON_IMAGE=python:3.12-slim-bookworm
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.9.30

FROM ${UV_IMAGE} AS uv

FROM ${PYTHON_IMAGE} AS builder
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app
# Dependencies only: the project itself is not installed (hatch build would need
# training/, loadtest/, README, ...). Source is put on PYTHONPATH in the runtime stage.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --extra demo --no-install-project

FROM ${PYTHON_IMAGE} AS runtime
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin app
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY packages ./packages
COPY services ./services
COPY evals/__init__.py evals/metrics.py ./evals/
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONPATH=/app:/app/packages \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).status == 200 else 1)"]
CMD ["uvicorn", "services.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
