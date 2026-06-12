"""FastAPI app: serves the REST API under /api and the console (static) at /."""
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import settings
from .db import init_db
from .api.routes import router

# Production: serve the built React app (app/frontend-react/dist) at / when it exists.
# In dev there is no build — use the Vite dev server on :5173 (it proxies /api here); :8000 is API-only.
FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend-react" / "dist"

app = FastAPI(title="Wonder Inventory Data-Quality Console", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.cors_origins] if settings.cors_origins != "*" else ["*"],
    allow_methods=["*"], allow_headers=["*"],
)


@app.on_event("startup")
def _startup():
    init_db()


app.include_router(router)

# Serve the built React console last so /api/* keeps priority (skipped in dev when no build exists).
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="console")
