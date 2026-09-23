FROM node:22-bookworm-slim AS frontend-builder

WORKDIR /frontend
COPY frontend/package.json /frontend/package.json
RUN npm install --no-audit --no-fund
COPY frontend /frontend
RUN npm run build


FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DEFAULT_TIMEOUT=60 \
    PIP_RETRIES=10

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        ffmpeg \
        postgresql-client \
        rclone \
        restic \
        tini \
        tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/pyproject.toml /app/pyproject.toml
COPY backend/app /app/app
COPY backend/alembic /app/alembic
COPY backend/alembic.ini /app/alembic.ini
COPY --from=frontend-builder /frontend/dist /app/frontend

RUN python -m pip install --upgrade pip \
    && for attempt in 1 2 3 4; do \
        if python -m pip install .; then \
            break; \
        fi; \
        if [ "$attempt" -eq 4 ]; then \
            exit 1; \
        fi; \
        sleep $((attempt * 5)); \
    done

RUN mkdir -p \
    /var/lib/zero-nvr \
    /var/cache/zero-nvr \
    /recordings \
    /prebuffer \
    /config/deployment

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
