# Portable backend image: the FastAPI control plane served by uvicorn against
# Postgres + filesystem storage. (Cloudflare runs the same code as a Python Worker;
# this image is for Docker / k8s / local.)
#
# Build context is the `worker/` directory:
#   docker build -t mikrotik-minder-backend ./worker
FROM python:3.12-slim

WORKDIR /app

# System deps kept minimal; asyncpg ships manylinux wheels so no build toolchain.
COPY requirements-standalone.txt ./
RUN pip install --no-cache-dir -r requirements-standalone.txt

COPY src ./src
COPY migrations ./migrations
COPY docker-entrypoint.sh ./
RUN chmod +x docker-entrypoint.sh && useradd --create-home --uid 10001 app \
    && mkdir -p /var/lib/minder/backups && chown -R app /var/lib/minder
USER app

ENV PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8000 \
    BACKUP_DIR=/var/lib/minder/backups

EXPOSE 8000

# Applies Postgres migrations (idempotent) when DATABASE_URL is set, then serves.
ENTRYPOINT ["./docker-entrypoint.sh"]
