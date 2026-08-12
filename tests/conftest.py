"""Shared test setup.

Most tests inject their own in-memory engine, but the route tests drive the app through
`TestClient(app)` declared at module level — which never enters the context manager, so FastAPI's
`lifespan` (and with it `store.init_db`) never runs. Those tests were therefore relying on a
`reels.db` that a previous manual run had already created: they pass on this machine and fail on a
fresh clone, and they break the moment a new column is added.

Running `init_db` once per session fixes both. It is the same call `lifespan` makes on startup, so
it creates any missing tables AND applies the `_ensure_column` migrations — exactly what a real
boot would do before serving the first request.
"""

import pytest

from app import store


@pytest.fixture(scope="session", autouse=True)
def _schema_is_current():
    """Create/migrate the default database before any test touches it."""
    store.init_db()
