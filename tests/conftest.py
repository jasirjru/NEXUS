"""Shared test fixtures: hermetic, order-independent database setup.

Tests run against a dedicated SQLite file (never the dev `nexus.db`) and the
per-test `db` fixture rolls back instead of committing, so no test can leave
partial state behind for the next one.
"""

from __future__ import annotations

import os

# Must be set BEFORE nexus.config is imported anywhere in the test process.
os.environ.setdefault("NEXUS_DATABASE_URL", "sqlite:///./nexus.test.db")

import pytest  # noqa: E402

from nexus.db.session import SessionLocal, engine  # noqa: E402
from nexus.db.schema import Base  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    engine.dispose()


@pytest.fixture()
def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.rollback()
        s.close()
