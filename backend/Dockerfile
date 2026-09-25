# syntax=docker/dockerfile:1

ARG NODE_BASE_IMAGE=node:22-bookworm-slim
ARG PYTHON_BASE_IMAGE=python:3.12-slim

FROM ${NODE_BASE_IMAGE} AS frontend-builder

ARG NPM_REGISTRY=https://registry.npmjs.org

WORKDIR /frontend
RUN npm config set registry "${NPM_REGISTRY}" \
    && npm config set audit false \
    && npm config set fund false
COPY frontend/package.json /frontend/package.json
RUN --mount=type=cache,target=/root/.npm,sharing=locked \
    npm install --prefer-offline --no-audit --no-fund
COPY frontend /frontend
RUN npm run build


FROM ${PYTHON_BASE_IMAGE}

ARG DEBIAN_MIRROR=http://deb.debian.org/debian
ARG DEBIAN_SECURITY_MIRROR=http://deb.debian.org/debian-security
ARG PYPI_INDEX_URL=https://pypi.org/simple

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DEFAULT_TIMEOUT=60 \
    PIP_RETRIES=10 \
    PIP_INDEX_URL=${PYPI_INDEX_URL}

RUN set -eux; \
    if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
      cp /etc/apt/sources.list.d/debian.sources /tmp/debian.sources.orig; \
      sed -i \
        -e "s|https\?://deb.debian.org/debian-security|${DEBIAN_SECURITY_MIRROR}|g" \
        -e "s|https\?://security.debian.org/debian-security|${DEBIAN_SECURITY_MIRROR}|g" \
        -e "s|https\?://deb.debian.org/debian|${DEBIAN_MIRROR}|g" \
        /etc/apt/sources.list.d/debian.sources; \
    fi; \
    if [ -f /etc/apt/sources.list ]; then \
      cp /etc/apt/sources.list /tmp/sources.list.orig; \
      sed -i \
        -e "s|https\?://deb.debian.org/debian-security|${DEBIAN_SECURITY_MIRROR}|g" \
        -e "s|https\?://security.debian.org/debian-security|${DEBIAN_SECURITY_MIRROR}|g" \
        -e "s|https\?://deb.debian.org/debian|${DEBIAN_MIRROR}|g" \
        /etc/apt/sources.list; \
    fi; \
    if ! apt-get -o Acquire::Retries=3 -o Acquire::http::Pipeline-Depth=0 update; then \
      echo "Preferred Debian mirror unavailable; falling back to official Debian sources" >&2; \
      rm -rf /var/lib/apt/lists/*; \
      if [ -f /tmp/debian.sources.orig ]; then \
        cp /tmp/debian.sources.orig /etc/apt/sources.list.d/debian.sources; \
      fi; \
      if [ -f /tmp/sources.list.orig ]; then \
        cp /tmp/sources.list.orig /etc/apt/sources.list; \
      fi; \
      apt-get -o Acquire::Retries=3 -o Acquire::http::Pipeline-Depth=0 update; \
    fi; \
    DEBIAN_FRONTEND=noninteractive apt-get \
      -o Acquire::Retries=3 \
      -o Acquire::http::Pipeline-Depth=0 \
      install -y --no-install-recommends \
        ca-certificates \
        curl \
        ffmpeg \
        postgresql-client \
        rclone \
        restic \
        tini \
        tzdata; \
    rm -rf /var/lib/apt/lists/* /tmp/debian.sources.orig /tmp/sources.list.orig

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
