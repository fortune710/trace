FROM ghcr.io/astral-sh/uv:0.11.28@sha256:0f36cb9361a3346885ca3677e3767016687b5a170c1a6b88465ec14aefec90aa AS uv

FROM python:3.12-slim-trixie@sha256:05cda9777409a9c3ffddd94a4c476b79f0769a0b4857f0c7ed9226b6800b0d6f AS base

COPY --from=uv /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_NO_CACHE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:${PATH}"

RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 10001 trace && useradd --uid 10001 --gid trace --create-home trace
RUN mkdir -p /var/lib/trace-audit && chown trace:trace /var/lib/trace-audit

WORKDIR /app

COPY pyproject.toml uv.lock requirements-audit.txt ./
RUN uv sync --locked --no-dev --no-install-project

COPY --chown=trace:trace . ./

FROM base AS test

RUN uv sync --locked --dev
# immudb-py currently declares ecdsa for optional server-signature handling.
# The audit client supplies a cryptography-backed verification compatibility
# module, so install the SDK without its unused transitive dependency.
RUN uv pip install --python /opt/venv/bin/python --requirement requirements-audit.txt
RUN uv pip install --python /opt/venv/bin/python --no-deps immudb-py==1.5.0

USER trace

FROM base AS runtime

RUN uv sync --locked --no-dev
RUN uv pip install --python /opt/venv/bin/python --requirement requirements-audit.txt
RUN uv pip install --python /opt/venv/bin/python --no-deps immudb-py==1.5.0

USER trace

EXPOSE 8000

CMD ["./start.sh"]
