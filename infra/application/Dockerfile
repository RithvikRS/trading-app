FROM ghcr.io/astral-sh/uv:0.13.5@sha256:32a7bb39b496babbd997b0a39a4d66c126bdaf5661b302bf6f06abda8deca6ff AS uv
FROM node:22.23.2-bookworm-slim@sha256:48e4b67d85f87bd551df43704e24d252f56cc5f8e9718841aace50f19948f0f9 AS frontend
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm install --global --ignore-scripts --no-audit --no-fund npm@12.0.2 && npm ci --ignore-scripts --no-audit --no-fund
COPY frontend/workspace.config.ts frontend/workspace-boundary.ts ./
COPY frontend/src/design.css ./src/design.css
COPY frontend/workspace ./workspace
RUN npm run build:workspace

FROM python:3.14.9-slim-bookworm@sha256:945c2676dc2b18e0c1f16879244122c57c0ffede60006bf3df159c507a31bcae AS dependencies
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
ENV UV_PYTHON_DOWNLOADS=never UV_PROJECT_ENVIRONMENT=/opt/venv UV_NO_CACHE=1
RUN uv sync --locked --no-dev --no-install-project --python /usr/local/bin/python

FROM python:3.14.9-slim-bookworm@sha256:945c2676dc2b18e0c1f16879244122c57c0ffede60006bf3df159c507a31bcae AS runtime
ENV PATH=/opt/venv/bin:$PATH PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app/backend
COPY --from=dependencies /opt/venv /opt/venv
COPY backend/trading_api ./trading_api
COPY backend/trading_auth ./trading_auth
COPY backend/trading_db ./trading_db
COPY backend/trading_connectors ./trading_connectors
COPY --from=frontend /build/frontend/workspace/dist /app/frontend/workspace/dist
USER 10001:10001
ENTRYPOINT ["python", "-m", "trading_api.packaged"]
