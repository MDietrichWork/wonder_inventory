"""SQLAlchemy engine + session. SQLite locally; set APP_DB_URL to a Postgres URL in prod."""
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings

_connect_args = {"check_same_thread": False} if settings.app_db_url.startswith("sqlite") else {}
engine = create_engine(settings.app_db_url, connect_args=_connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


class Base(DeclarativeBase):
    pass


def init_db():
    from . import models  # noqa: F401  (register mappers)
    # Local SQLite/dev: create tables on startup for zero-friction. Postgres/prod: the schema is
    # owned by Alembic (`alembic upgrade head` runs before the app starts), so don't create_all
    # there or it would drift from the migration history.
    if settings.app_db_url.startswith("sqlite"):
        Base.metadata.create_all(engine)


def reset_db():
    from . import models  # noqa: F401
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
