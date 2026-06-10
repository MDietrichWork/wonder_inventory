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
    Base.metadata.create_all(engine)


def reset_db():
    from . import models  # noqa: F401
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
