"""Simple migration support.

For development, `init-db` (create_all) is sufficient and idempotent. This
module provides an Alembic-ready entrypoint for production schema evolution:

    alembic init infrastructure/alembic        # once, to scaffold
    alembic revision --autogenerate -m "..."   # create migration
    alembic upgrade head                       # apply

env.py should set sqlalchemy.url from NEXUS_DATABASE_URL and import
nexus.db.schema.Base for target_metadata.
"""

from __future__ import annotations

from nexus.db.schema import Base


def run_migrations_online() -> None:
    """Programmatic `alembic upgrade head` equivalent for simple deployments."""
    from alembic import command
    from alembic.config import Config

    from nexus.config import PROJECT_ROOT

    cfg = Config(str(PROJECT_ROOT / "infrastructure" / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", __import__("nexus.config", fromlist=["settings"]).settings.database_url)
    command.upgrade(cfg, "head")
