"""api.DB_PATH honors the HEALTH_DB override (the post-incident safety valve).

api.DB_PATH defaults to "health.db" but reads HEALTH_DB at import time so a
throwaway/verification backend can point elsewhere and be physically unable to
touch the real medical DB. These reload api under a monkeypatched environment,
then reload it back so the module is restored for the rest of the suite.
"""

from __future__ import annotations

import importlib

import api


def test_default_is_health_db(monkeypatch):
    monkeypatch.delenv("HEALTH_DB", raising=False)
    try:
        importlib.reload(api)
        assert api.DB_PATH == "health.db"
    finally:
        importlib.reload(api)


def test_health_db_env_overrides(monkeypatch):
    monkeypatch.setenv("HEALTH_DB", "/tmp/throwaway-verify.db")
    try:
        importlib.reload(api)
        assert api.DB_PATH == "/tmp/throwaway-verify.db"
    finally:
        monkeypatch.delenv("HEALTH_DB", raising=False)
        importlib.reload(api)
        assert api.DB_PATH == "health.db"
