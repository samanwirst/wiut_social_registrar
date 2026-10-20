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

USER app

FROM base AS test
USER root
COPY requirements-dev.txt ./
RUN python -m pip install --no-cache-dir -r requirements-dev.txt
COPY tests/ ./tests/
USER app
RUN python -m pytest -q -p no:cacheprovider

FROM base AS runtime
COPY README.md LICENSE ./
CMD ["python", "main.py", "--env-file", "/config/.env"]
