FROM node:24-alpine AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --ignore-scripts --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt

RUN groupadd --gid 1000 app \
    && useradd --uid 1000 --gid app --create-home app \
    && mkdir /config \
    && chown app:app /config

COPY main.py cli.py config.py ./
COPY app/ ./app/
COPY registrar/ ./registrar/
COPY alembic.ini ./
COPY migrations/ ./migrations/
COPY scripts/transfer_database.py ./scripts/transfer_database.py
COPY --from=frontend /frontend/dist/ ./frontend/dist/

USER app

FROM base AS test
USER root
COPY requirements-dev.txt ./
RUN python -m pip install --no-cache-dir -r requirements-dev.txt
COPY tests/ ./tests/
COPY deploy/ ./deploy/
COPY pyproject.toml ./
USER app
RUN python -m ruff check --no-cache . \
    && python -m ruff format --check --no-cache . \
    && python -m pytest -q -p no:cacheprovider

FROM base AS runtime
COPY README.md LICENSE ./
EXPOSE 8080
CMD ["python", "main.py", "--env-file", "/config/.env"]
