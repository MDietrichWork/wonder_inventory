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
    # Self-heal the config tables: insert any rules / routing / thresholds defined in code but not yet
    # in the DB (preserves existing Admin edits). Best-effort — never block startup on it.
    try:
        from .db import SessionLocal
        from .seed import sync_catalog
        db = SessionLocal()
        try:
            sync_catalog(db)
        finally:
            db.close()
    except Exception:  # pragma: no cover - never crash startup over a catalog sync
        pass
    # Daily scheduler (localhost stand-in for Cloud Scheduler). No-op unless SCHEDULER_ENABLED=true.
    try:
        from . import scheduler
        scheduler.start()
    except Exception:  # pragma: no cover - never crash startup over the scheduler
        pass


@app.on_event("shutdown")
def _shutdown():
    try:
        from . import scheduler
        scheduler.shutdown()
    except Exception:  # pragma: no cover
        pass


app.include_router(router)

# Serve the built React console last so /api/* keeps priority (skipped in dev when no build exists).
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="console")
