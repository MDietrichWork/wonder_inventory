# Wonder DQ console — single image: FastAPI API + the built React console.
# Build context is ./app (so backend/ and frontend-react/ are available).

# --- Stage 1: build the React console (Vite) ---
FROM node:20-slim AS web
WORKDIR /web
COPY frontend-react/package.json frontend-react/package-lock.json ./
RUN npm ci
COPY frontend-react/ ./
RUN npm run build           # -> /web/dist

# --- Stage 2: API image, serving the built console ---
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app/backend

# Install deps first for layer caching.
COPY backend/requirements.txt .
RUN pip install -r requirements.txt

# App code + the React build (main.py serves it from /app/frontend-react/dist).
COPY backend/ /app/backend/
COPY --from=web /web/dist /app/frontend-react/dist

EXPOSE 8000

# Prod/Postgres: apply migrations, then serve. On an already-migrated DB `alembic upgrade
# head` is a no-op. Cloud Run injects $PORT; default 8000 elsewhere.
CMD ["sh", "-c", "alembic upgrade head && uvicorn wonder.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
