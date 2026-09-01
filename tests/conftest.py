import sys
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
    monkeypatch.setenv("SUPABASE_MANAGEMENT_TOKEN", "")
    monkeypatch.setenv("SUPABASE_PROJECT_REF", "")
    monkeypatch.setenv("KEEPALIVE_TOKEN", "test-keepalive-token")
    monkeypatch.setenv("TRICLUB_USER_PASSWORD", "test-user-password")
    monkeypatch.setenv("TRICLUB_ADMIN_PASSWORD", "test-admin-password")
    monkeypatch.setenv("APP_SECRET_KEY", "test-secret-key-not-for-production")

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
        client.get("/login")
        with client.session_transaction() as auth_session:
            login_csrf = auth_session["csrf_token"]
        login_response = client.post(
            "/login",
            data={"password": "test-user-password", "csrf_token": login_csrf},
        )
        assert login_response.status_code == 302

        with client.session_transaction() as auth_session:
            request_csrf = auth_session["csrf_token"]

        original_open = client.open

        def open_with_csrf(*args, **kwargs):
            method = str(kwargs.get("method", "GET")).upper()
            if method in {"POST", "PUT", "PATCH", "DELETE"}:
                headers = dict(kwargs.get("headers") or {})
                headers.setdefault("X-CSRF-Token", request_csrf)
                kwargs["headers"] = headers
            return original_open(*args, **kwargs)

        client.open = open_with_csrf
        initial_read = client.get("/api/workspace")
        assert initial_read.status_code == 200
        yield client
