# Wonder DQ console — single image: FastAPI API + the static console.
# Build context is ./app (so both backend/ and frontend/ are available).
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app/backend

# Install deps first for layer caching.
COPY backend/requirements.txt .
RUN pip install -r requirements.txt

# App code: keep the on-disk layout main.py expects (frontend at ../../frontend).
COPY backend/ /app/backend/
COPY frontend/ /app/frontend/

EXPOSE 8000

# Prod/Postgres: apply migrations, then serve. On an already-migrated DB `alembic upgrade
# head` is a no-op. Cloud Run injects $PORT; default 8000 elsewhere.
CMD ["sh", "-c", "alembic upgrade head && uvicorn wonder.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
