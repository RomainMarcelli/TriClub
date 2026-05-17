import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """Flask test client backed by an isolated temporary SQLite DB."""
    db_file = tmp_path / "test_workspace.db"
    monkeypatch.setenv("BEN_DB_PATH", str(db_file))
    # On force SQLite local : pas de Postgres / REST dans les tests.
    monkeypatch.setenv("SUPABASE_DB_URL", "")
    monkeypatch.setenv("SUPABASE_URL", "")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "")

    # Re-import propre pour réinitialiser les constantes du module.
    if "app" in sys.modules:
        del sys.modules["app"]
    import app as app_module

    app_module.DB_PATH = str(db_file)
    app_module.DB_ACTIVE_PATH = str(db_file)
    app_module.DB_BACKEND = "sqlite"
    app_module.app.config.update(TESTING=True)
    app_module.ensure_sqlite_database()
    with app_module.app.test_client() as client:
        yield client
