import io
import sqlite3
import sys
import urllib.error

import pytest


def workspace(label="Club", rows=True):
    return {
        "columns": [
            {
                "id": "col_name",
                "name": "Nom",
                "type": "text",
                "width": 180,
                "hidden": False,
                "defaultValue": "",
                "options": [],
            }
        ],
        "rows": [{"id": "r1", "values": {"col_name": label}}] if rows else [],
        "filters": [],
        "searchQuery": "",
        "sort": None,
        "views": [],
        "activeViewId": "",
    }


def persistence(expected_exists, revision=None, empty_intent=None):
    return {
        "initialLoadCompleted": True,
        "expectedExists": expected_exists,
        "baseRevision": revision,
        "emptyRowsIntent": empty_intent,
    }


def save(client, snapshot, expected_exists, revision=None, empty_intent=None):
    return client.post(
        "/api/workspace",
        json={
            "workspace": snapshot,
            "persistence": persistence(expected_exists, revision, empty_intent),
        },
    )


def promote_to_admin(client):
    with client.session_transaction() as auth_session:
        auth_session["role"] = "admin"


def make_authenticated_client(app_module, password="test-user-password"):
    auth_client = app_module.app.test_client()
    auth_client.get("/login")
    with auth_client.session_transaction() as login_session:
        login_csrf = login_session["csrf_token"]
    response = auth_client.post(
        "/login",
        data={"password": password, "csrf_token": login_csrf},
    )
    assert response.status_code == 302

    with auth_client.session_transaction() as auth_session:
        request_csrf = auth_session["csrf_token"]
    original_open = auth_client.open

    def open_with_csrf(*args, **kwargs):
        method = str(kwargs.get("method", "GET")).upper()
        if method in {"POST", "PUT", "PATCH", "DELETE"}:
            headers = dict(kwargs.get("headers") or {})
            headers.setdefault("X-CSRF-Token", request_csrf)
            kwargs["headers"] = headers
        return original_open(*args, **kwargs)

    auth_client.open = open_with_csrf
    return auth_client


def test_pages_and_admin_api_require_the_expected_role(client):
    app_module = sys.modules["app"]
    anonymous = app_module.app.test_client()

    assert anonymous.get("/").status_code == 302
    assert anonymous.get("/api/workspace").status_code == 401
    assert anonymous.get("/api/admin/backups").status_code == 401
    assert client.get("/api/admin/backups").status_code == 403


def test_admin_password_creates_an_admin_session(client):
    app_module = sys.modules["app"]
    login_client = app_module.app.test_client()
    login_client.get("/login")
    with login_client.session_transaction() as login_session:
        csrf = login_session["csrf_token"]
    response = login_client.post(
        "/login",
        data={"password": "test-admin-password", "csrf_token": csrf},
    )
    assert response.status_code == 302
    with login_client.session_transaction() as login_session:
        assert login_session["role"] == "admin"


def test_csrf_is_required_on_authenticated_writes(client):
    response = client.post(
        "/api/workspace",
        json={"workspace": workspace(), "persistence": persistence(False)},
        headers={"X-CSRF-Token": "invalid-token"},
    )
    assert response.status_code == 403
    assert response.get_json()["error"] == "csrf_failed"


def test_missing_csrf_is_rejected_but_beacon_json_token_is_supported(client):
    app_module = sys.modules["app"]
    raw_client = app_module.app.test_client()
    with raw_client.session_transaction() as raw_session:
        raw_session["role"] = "user"
        raw_session["csrf_token"] = "beacon-csrf-token"
        raw_session["workspace_read_verified"] = False
    assert raw_client.get("/api/workspace").status_code == 200

    payload = {"workspace": workspace(), "persistence": persistence(False)}
    missing = raw_client.post("/api/workspace", json=payload)
    assert missing.status_code == 403

    payload["csrfToken"] = "beacon-csrf-token"
    accepted = raw_client.post("/api/workspace", json=payload)
    assert accepted.status_code == 200


def test_secrets_are_never_rendered_or_returned(client, monkeypatch):
    app_module = sys.modules["app"]
    management_secret = "management-token-must-stay-server-side"
    service_secret = "service-role-key-must-stay-server-side"
    monkeypatch.setattr(app_module, "SUPABASE_MANAGEMENT_TOKEN", management_secret)
    monkeypatch.setattr(app_module, "SUPABASE_SERVICE_ROLE_KEY", service_secret)

    page = client.get("/").data.decode("utf-8")
    api_body = client.get("/api/workspace").data.decode("utf-8")
    assert management_secret not in page + api_body
    assert service_secret not in page + api_body


def test_periodic_backup_is_throttled_and_admin_list_has_no_payload(client):
    initial = save(client, workspace("A"), False)
    revision_1 = initial.get_json()["revision"]
    updated = save(client, workspace("B"), True, revision_1)
    revision_2 = updated.get_json()["revision"]
    assert save(client, workspace("C"), True, revision_2).status_code == 200

    promote_to_admin(client)
    response = client.get("/api/admin/backups")
    assert response.status_code == 200
    backups = response.get_json()["backups"]
    assert len(backups) == 1
    assert backups[0]["reason"] == "periodic"
    assert "payload" not in backups[0]


def test_destructive_empty_save_creates_immediate_backup(client):
    initial = save(client, workspace("A"), False)
    revision = initial.get_json()["revision"]
    emptied = save(client, workspace(rows=False), True, revision, "user_deleted_all_rows")
    assert emptied.status_code == 200

    promote_to_admin(client)
    backups = client.get("/api/admin/backups").get_json()["backups"]
    assert backups[0]["reason"] == "before_empty_transition"
    assert backups[0]["row_count"] == 1


def test_backup_retention_is_bounded(client, monkeypatch):
    app_module = sys.modules["app"]
    monkeypatch.setattr(app_module, "WORKSPACE_BACKUP_RETENTION_COUNT", 5)
    assert save(client, workspace("A"), False).status_code == 200
    promote_to_admin(client)

    for _ in range(7):
        assert client.post("/api/admin/backups", json={}).status_code == 201

    backups = client.get("/api/admin/backups").get_json()["backups"]
    assert len(backups) == 5


def test_admin_restore_backups_current_state_and_invalidates_old_revision(client):
    initial = save(client, workspace("A"), False)
    revision_1 = initial.get_json()["revision"]
    updated = save(client, workspace("B"), True, revision_1)
    revision_2 = updated.get_json()["revision"]

    promote_to_admin(client)
    backup_id = client.get("/api/admin/backups").get_json()["backups"][0]["id"]
    restored = client.post(
        f"/api/admin/backups/{backup_id}/restore",
        json={"confirm": "RESTORE"},
    )
    assert restored.status_code == 200
    assert restored.get_json()["revision"] != revision_2

    blocked_before_get = save(
        client,
        workspace("must-not-write"),
        True,
        restored.get_json()["revision"],
    )
    assert blocked_before_get.status_code == 428
    assert blocked_before_get.get_json()["error"] == "workspace_fresh_read_required"

    assert client.get("/api/workspace").get_json()["workspace"]["rows"][0]["values"]["col_name"] == "A"

    stale = save(client, workspace("stale"), True, revision_2)
    assert stale.status_code == 409
    reasons = [item["reason"] for item in client.get("/api/admin/backups").get_json()["backups"]]
    assert "before_admin_restore" in reasons


def test_restore_requires_a_fresh_get_for_every_session(client):
    app_module = sys.modules["app"]
    initial = save(client, workspace("backup-version"), False)
    revision_1 = initial.get_json()["revision"]
    promote_to_admin(client)
    manual_backup = client.post("/api/admin/backups", json={}).get_json()["backup"]

    updated = save(client, workspace("current-version"), True, revision_1)
    revision_before_restore = updated.get_json()["revision"]
    assert client.get("/api/workspace").status_code == 200

    client_b = make_authenticated_client(app_module)
    loaded_b = client_b.get("/api/workspace")
    assert loaded_b.status_code == 200
    assert loaded_b.get_json()["revision"] == revision_before_restore
    with client_b.session_transaction() as session_b:
        epoch_b_before = session_b["workspace_read_epoch"]
    server_epoch_before = app_module.WORKSPACE_READ_EPOCH

    restored = client.post(
        f"/api/admin/backups/{manual_backup['id']}/restore",
        json={"confirm": "RESTORE"},
    )
    assert restored.status_code == 200
    assert app_module.WORKSPACE_READ_EPOCH != server_epoch_before
    loaded_a = client.get("/api/workspace")
    assert loaded_a.status_code == 200
    restored_revision = loaded_a.get_json()["revision"]

    with client_b.session_transaction() as session_b:
        assert session_b["workspace_read_epoch"] == epoch_b_before
    blocked_b = save(client_b, workspace("stale-client-b"), True, revision_before_restore)
    assert blocked_b.status_code == 428
    assert blocked_b.get_json()["error"] == "workspace_fresh_read_required"

    refreshed_b = client_b.get("/api/workspace")
    assert refreshed_b.status_code == 200
    assert refreshed_b.get_json()["revision"] == restored_revision
    with client_b.session_transaction() as session_b:
        assert session_b["workspace_read_epoch"] == app_module.WORKSPACE_READ_EPOCH
    accepted_b = save(client_b, workspace("fresh-client-b"), True, restored_revision)
    assert accepted_b.status_code == 200


def test_restore_requires_admin_and_explicit_confirmation(client):
    assert save(client, workspace("A"), False).status_code == 200
    assert client.post("/api/admin/backups/1/restore", json={"confirm": "RESTORE"}).status_code == 403
    promote_to_admin(client)
    assert client.post("/api/admin/backups/1/restore", json={}).status_code == 400


def test_keepalive_requires_bearer_and_performs_only_probe(client, monkeypatch):
    app_module = sys.modules["app"]
    calls = []
    monkeypatch.setattr(app_module, "probe_workspace_storage", lambda: calls.append("probe"))
    anonymous = app_module.app.test_client()

    assert anonymous.get("/api/system/keepalive").status_code == 401
    response = anonymous.get(
        "/api/system/keepalive",
        headers={"Authorization": "Bearer test-keepalive-token"},
    )
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok", "database": "available"}
    assert calls == ["probe"]


def test_keepalive_read_does_not_mutate_workspace_or_create_backup(client):
    app_module = sys.modules["app"]
    assert save(client, workspace("unchanged"), False).status_code == 200
    with sqlite3.connect(app_module.DB_ACTIVE_PATH) as connection:
        before_workspace = connection.execute(
            "SELECT payload, updated_at FROM workspace_state WHERE id = 1"
        ).fetchone()
        before_backup_count = connection.execute("SELECT COUNT(*) FROM workspace_backups").fetchone()[0]

    response = app_module.app.test_client().get(
        "/api/system/keepalive",
        headers={"Authorization": "Bearer test-keepalive-token"},
    )
    assert response.status_code == 200

    with sqlite3.connect(app_module.DB_ACTIVE_PATH) as connection:
        after_workspace = connection.execute(
            "SELECT payload, updated_at FROM workspace_state WHERE id = 1"
        ).fetchone()
        after_backup_count = connection.execute("SELECT COUNT(*) FROM workspace_backups").fetchone()[0]
    assert after_workspace == before_workspace
    assert after_backup_count == before_backup_count


def test_keepalive_fails_closed_when_token_is_missing(client, monkeypatch):
    app_module = sys.modules["app"]
    monkeypatch.setattr(app_module, "KEEPALIVE_TOKEN", "")
    response = app_module.app.test_client().get(
        "/api/system/keepalive",
        headers={"Authorization": "Bearer anything"},
    )
    assert response.status_code == 503
    assert response.get_json()["error"] == "keepalive_not_configured"


def test_paused_supabase_has_a_distinct_api_error(client, monkeypatch):
    app_module = sys.modules["app"]
    monkeypatch.setattr(
        app_module,
        "load_workspace_record",
        lambda: (_ for _ in ()).throw(app_module.SupabaseProjectPaused("paused")),
    )
    response = client.get("/api/workspace")
    assert response.status_code == 503
    assert response.get_json()["error"] == "supabase_paused"
    assert app_module.supabase_error_indicates_paused(540, "") is True


def test_supabase_rest_http_540_becomes_paused_signal(client, monkeypatch):
    app_module = sys.modules["app"]
    monkeypatch.setattr(app_module, "HAS_SUPABASE_REST", True)
    monkeypatch.setattr(app_module, "SUPABASE_URL", "https://project.supabase.co")
    monkeypatch.setattr(app_module, "SUPABASE_SERVICE_ROLE_KEY", "server-only-key")

    def paused(*_args, **_kwargs):
        raise urllib.error.HTTPError(
            "https://project.supabase.co/rest/v1/workspace_state",
            540,
            "Project paused",
            {},
            io.BytesIO(b'{"message":"Project paused"}'),
        )

    monkeypatch.setattr(app_module.urllib.request, "urlopen", paused)
    with pytest.raises(app_module.SupabaseProjectPaused):
        app_module.supabase_rest_request("GET", "workspace_state?select=id")


def test_admin_resume_route_uses_server_side_management_call(client, monkeypatch):
    app_module = sys.modules["app"]
    calls = []
    monkeypatch.setattr(app_module, "request_supabase_project_restore", lambda: calls.append("restore"))
    assert client.post("/api/admin/supabase/resume", json={}).status_code == 403

    promote_to_admin(client)
    response = client.post("/api/admin/supabase/resume", json={})
    assert response.status_code == 200
    assert calls == ["restore"]


def test_resume_requires_a_fresh_get_for_every_session(client, monkeypatch):
    app_module = sys.modules["app"]
    initial = save(client, workspace("before-resume"), False)
    revision = initial.get_json()["revision"]
    assert client.get("/api/workspace").status_code == 200

    client_b = make_authenticated_client(app_module)
    loaded_b = client_b.get("/api/workspace")
    assert loaded_b.status_code == 200
    assert loaded_b.get_json()["revision"] == revision
    with client_b.session_transaction() as session_b:
        epoch_b_before = session_b["workspace_read_epoch"]
    server_epoch_before = app_module.WORKSPACE_READ_EPOCH

    promote_to_admin(client)
    monkeypatch.setattr(app_module, "request_supabase_project_restore", lambda: None)
    resumed = client.post("/api/admin/supabase/resume", json={})
    assert resumed.status_code == 200
    assert app_module.WORKSPACE_READ_EPOCH != server_epoch_before
    assert client.get("/api/workspace").status_code == 200

    with client_b.session_transaction() as session_b:
        assert session_b["workspace_read_epoch"] == epoch_b_before
    blocked_b = save(client_b, workspace("stale-after-resume"), True, revision)
    assert blocked_b.status_code == 428
    assert blocked_b.get_json()["error"] == "workspace_fresh_read_required"

    refreshed_b = client_b.get("/api/workspace")
    assert refreshed_b.status_code == 200
    assert refreshed_b.get_json()["revision"] == revision
    with client_b.session_transaction() as session_b:
        assert session_b["workspace_read_epoch"] == app_module.WORKSPACE_READ_EPOCH
    accepted_b = save(client_b, workspace("fresh-after-resume"), True, revision)
    assert accepted_b.status_code == 200


def test_management_restore_calls_official_endpoint_without_returning_token(client, monkeypatch):
    app_module = sys.modules["app"]
    monkeypatch.setattr(app_module, "SUPABASE_PROJECT_REF", "project-ref")
    monkeypatch.setattr(app_module, "SUPABASE_MANAGEMENT_TOKEN", "server-only-token")
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b"{}"

    def fake_urlopen(request_obj, timeout):
        captured["url"] = request_obj.full_url
        captured["authorization"] = request_obj.headers["Authorization"]
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(app_module.urllib.request, "urlopen", fake_urlopen)
    app_module.request_supabase_project_restore()
    assert captured["url"] == "https://api.supabase.com/v1/projects/project-ref/restore"
    assert captured["authorization"] == "Bearer server-only-token"
    assert captured["timeout"] == 15


def test_management_restore_maps_permission_failure(client, monkeypatch):
    app_module = sys.modules["app"]
    monkeypatch.setattr(app_module, "SUPABASE_PROJECT_REF", "project-ref")
    monkeypatch.setattr(app_module, "SUPABASE_MANAGEMENT_TOKEN", "server-only-token")

    def forbidden(*_args, **_kwargs):
        raise urllib.error.HTTPError(
            "https://api.supabase.com/v1/projects/project-ref/restore",
            403,
            "Forbidden",
            {},
            io.BytesIO(b'{"message":"forbidden"}'),
        )

    monkeypatch.setattr(app_module.urllib.request, "urlopen", forbidden)
    with pytest.raises(app_module.SupabaseManagementError) as captured:
        app_module.request_supabase_project_restore()
    assert captured.value.code == "supabase_restore_refused"
