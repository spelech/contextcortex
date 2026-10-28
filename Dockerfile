# syntax=docker/dockerfile:1
ARG FRONTEND_IMAGE=node:22-alpine
ARG PYTHON_IMAGE=python:3.11-slim

# Stage 1: Build Frontend
FROM ${FRONTEND_IMAGE} AS frontend-builder
WORKDIR /app/frontend
COPY certs/ /usr/local/share/ca-certificates/extra/
# Bootstrap trust before apk, then use the system bundle for npm and Git dependencies.
RUN set -eu; \
    cp /etc/ssl/cert.pem /tmp/bootstrap-ca.pem; \
    for cert in /usr/local/share/ca-certificates/extra/*.crt; do \
        [ -f "$cert" ] || continue; \
        cat "$cert" >> /tmp/bootstrap-ca.pem; printf '\n' >> /tmp/bootstrap-ca.pem; \
    done; \
    SSL_CERT_FILE=/tmp/bootstrap-ca.pem apk add --no-cache ca-certificates git; \
    update-ca-certificates; \
    rm /tmp/bootstrap-ca.pem
ENV NODE_EXTRA_CA_CERTS=/etc/ssl/certs/ca-certificates.crt \
    GIT_SSL_CAINFO=/etc/ssl/certs/ca-certificates.crt
COPY frontend/package*.json ./
COPY frontend/packages* ./packages/
RUN --mount=type=secret,id=npmrc,target=/root/.npmrc npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Runtime Environment
FROM ${PYTHON_IMAGE}
WORKDIR /app

COPY certs/ /usr/local/share/ca-certificates/extra/
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
    PIP_CERT=/etc/ssl/certs/ca-certificates.crt \
    GIT_SSL_CAINFO=/etc/ssl/certs/ca-certificates.crt
RUN set -eu; \
    mkdir -p "$(dirname "$SSL_CERT_FILE")"; \
    for cert in /usr/local/share/ca-certificates/extra/*.crt; do \
        [ -f "$cert" ] || continue; \
        cat "$cert" >> "$SSL_CERT_FILE"; printf '\n' >> "$SSL_CERT_FILE"; \
    done; \
    apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ca-certificates \
    git \
    libpq-dev \
    curl \
    ripgrep \
    && rm -rf /var/lib/apt/lists/* \
    && update-ca-certificates

COPY requirements.txt .
RUN --mount=type=secret,id=pip_config,target=/etc/pip.conf \
    --mount=type=secret,id=python_constraints,target=/run/secrets/python-constraints.txt \
    if [ -f /run/secrets/python-constraints.txt ]; then \
        PIP_CONSTRAINT=/run/secrets/python-constraints.txt pip install --no-cache-dir -r requirements.txt; \
    else \
        pip install --no-cache-dir -r requirements.txt; \
    fi

COPY . .
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist
COPY --from=frontend-builder /app/frontend/dist ./www

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN sed -i 's/\r$//' /usr/local/bin/docker-entrypoint.sh && chmod +x /usr/local/bin/docker-entrypoint.sh

EXPOSE 3000

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["python", "main.py"]
