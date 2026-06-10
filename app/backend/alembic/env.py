"""Alembic environment — pulls the DB URL from the app settings (APP_DB_URL) and the schema
from the app's SQLAlchemy models, so `alembic upgrade head` provisions/evolves the prod
(Postgres) schema. Local SQLite/fixtures dev still uses create_all (see wonder.db.init_db)."""
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

from wonder.config import settings
from wonder.db import Base
from wonder import models  # noqa: F401  (register all mappers on Base.metadata)

config = context.config
# Single source of truth for the connection string: the app settings (APP_DB_URL).
config.set_main_option("sqlalchemy.url", settings.app_db_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=settings.app_db_url, target_metadata=target_metadata,
        literal_binds=True, dialect_opts={"paramstyle": "named"}, compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        # batch mode lets SQLite run ALTERs too, so the same migrations work on both backends
        is_sqlite = connection.dialect.name == "sqlite"
        context.configure(connection=connection, target_metadata=target_metadata,
                          compare_type=True, render_as_batch=is_sqlite)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
