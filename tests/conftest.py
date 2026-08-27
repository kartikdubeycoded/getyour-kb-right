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

from app import last30days_bridge, store


@pytest.fixture(scope="session", autouse=True)
def _schema_is_current():
    """Create/migrate the default database before any test touches it."""
    store.init_db()


@pytest.fixture(autouse=True)
def _no_real_last30days_calls(monkeypatch):
    """fetch_signal shells out to a real subprocess that hits live Reddit/HN/GitHub — ~70s and a
    network dependency. No test should pay that cost or flake on a dead connection; a test that
    wants to exercise real signal should re-patch this explicitly."""
    monkeypatch.setattr(last30days_bridge, "fetch_signal", lambda *a, **k: None)
