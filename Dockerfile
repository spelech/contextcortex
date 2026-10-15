# Stage 1: Build Frontend
FROM node:22-alpine AS frontend-builder
WORKDIR /app/frontend
RUN apk add --no-cache git
# Optional private CA certificates (certs/*.crt) for npm behind a TLS-inspecting proxy
COPY certs/ /tmp/extra-ca/
COPY frontend/package*.json ./
RUN if ls /tmp/extra-ca/*.crt >/dev/null 2>&1; then \
        cat /tmp/extra-ca/*.crt > /tmp/extra-ca.pem && export NODE_EXTRA_CA_CERTS=/tmp/extra-ca.pem; \
    fi && npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Runtime Environment
FROM python:3.11-slim
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ca-certificates \
    git \
    libpq-dev \
    curl \
    ripgrep \
    && rm -rf /var/lib/apt/lists/*

# Optional private CA certificates (certs/*.crt). Python, pip, and git use the system bundle.
COPY certs/ /usr/local/share/ca-certificates/extra/
RUN update-ca-certificates
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
    PIP_CERT=/etc/ssl/certs/ca-certificates.crt \
    GIT_SSL_CAINFO=/etc/ssl/certs/ca-certificates.crt

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist
COPY --from=frontend-builder /app/frontend/dist ./www

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN sed -i 's/\r$//' /usr/local/bin/docker-entrypoint.sh && chmod +x /usr/local/bin/docker-entrypoint.sh

EXPOSE 3000

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["python", "main.py"]
