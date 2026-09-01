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


def make_public_client(app_module):
    public_client = app_module.app.test_client()
    assert public_client.get("/").status_code == 200
    with public_client.session_transaction() as browser_session:
        csrf = browser_session["csrf_token"]

    original_open = public_client.open

    def open_with_csrf(*args, **kwargs):
        method = str(kwargs.get("method", "GET")).upper()
        if method in {"POST", "PUT", "PATCH", "DELETE"}:
            headers = dict(kwargs.get("headers") or {})
            headers.setdefault("X-CSRF-Token", csrf)
            kwargs["headers"] = headers
        return original_open(*args, **kwargs)

    public_client.open = open_with_csrf
    return public_client


def test_application_and_workspace_api_are_public(client):
    app_module = sys.modules["app"]
    anonymous = app_module.app.test_client()

    index = anonymous.get("/")
    assert index.status_code == 200
    assert b"Ben Workspace" in index.data
    assert b"D\xc3\xa9connexion" not in index.data
    assert b'id="btnResumeSupabase"' in index.data
    assert b"btn-resume-supabase hidden" in index.data
    assert anonymous.get("/login").status_code == 404

    loaded = anonymous.get("/api/workspace")
    assert loaded.status_code == 200
    assert loaded.get_json()["exists"] is False
    assert loaded.get_json()["csrf_token"]


def test_public_business_routes_do_not_require_login(client):
    exported = client.post(
        "/api/export",
        json={
            "filename": "public",
            "columns": workspace()["columns"],
            "rows": workspace()["rows"],
        },
    )
    assert exported.status_code == 200

    shared = client.post(
        "/api/share",
        json={"workspace": workspace()},
    )
    assert shared.status_code == 200

    missing_pdf = client.post("/api/extract", data={})
    assert missing_pdf.status_code == 400


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/admin/backups"),
        ("POST", "/api/admin/backups"),
        ("POST", "/api/admin/backups/1/restore"),
        ("POST", "/api/admin/supabase/resume"),
    ],
)
def test_dangerous_admin_routes_are_not_exposed(client, method, path):
    assert client.open(path, method=method, json={}).status_code == 404


def test_anonymous_csrf_protects_writes_and_supports_beacon_json(client):
    app_module = sys.modules["app"]
    raw_client = app_module.app.test_client()
    loaded = raw_client.get("/api/workspace")
    assert loaded.status_code == 200
    csrf_token = loaded.get_json()["csrf_token"]

    payload = {"workspace": workspace(), "persistence": persistence(False)}
    missing = raw_client.post("/api/workspace", json=payload)
    assert missing.status_code == 403

    payload["csrfToken"] = csrf_token
    accepted = raw_client.post("/api/workspace", json=payload)
    assert accepted.status_code == 200
    assert accepted.get_json()["revision"]


def test_wrong_anonymous_csrf_is_rejected(client):
    response = client.post(
        "/api/workspace",
        json={"workspace": workspace(), "persistence": persistence(False)},
        headers={"X-CSRF-Token": "invalid-token"},
    )
    assert response.status_code == 403
    assert response.get_json()["error"] == "csrf_failed"


def test_server_secrets_are_never_rendered_or_returned(client, monkeypatch):
    app_module = sys.modules["app"]
    service_secret = "service-role-key-must-stay-server-side"
    management_secret = "management-token-must-stay-server-side"
    project_ref = "project-ref-must-stay-server-side"
    monkeypatch.setattr(app_module, "SUPABASE_SERVICE_ROLE_KEY", service_secret)
    monkeypatch.setattr(app_module, "SUPABASE_MANAGEMENT_TOKEN", management_secret)
    monkeypatch.setattr(app_module, "SUPABASE_PROJECT_REF", project_ref)

    page = client.get("/").data.decode("utf-8")
    api_body = client.get("/api/workspace").data.decode("utf-8")
    assert service_secret not in page + api_body
    assert management_secret not in page + api_body
    assert project_ref not in page + api_body


def test_public_autosave_keeps_periodic_backups_throttled(client):
    initial = save(client, workspace("A"), False)
    revision_1 = initial.get_json()["revision"]
    updated = save(client, workspace("B"), True, revision_1)
    revision_2 = updated.get_json()["revision"]
    assert save(client, workspace("C"), True, revision_2).status_code == 200

    app_module = sys.modules["app"]
    backups = app_module.list_workspace_backups()
    assert len(backups) == 1
    assert backups[0]["reason"] == "periodic"
    assert "payload" not in backups[0]


def test_destructive_empty_save_creates_immediate_automatic_backup(client):
    initial = save(client, workspace("A"), False)
    revision = initial.get_json()["revision"]
    emptied = save(client, workspace(rows=False), True, revision, "user_deleted_all_rows")
    assert emptied.status_code == 200

    app_module = sys.modules["app"]
    backups = app_module.list_workspace_backups()
    assert backups[0]["reason"] == "before_empty_transition"
    assert backups[0]["row_count"] == 1


def test_automatic_backup_retention_is_bounded_without_public_admin_route(client, monkeypatch):
    app_module = sys.modules["app"]
    monkeypatch.setattr(app_module, "WORKSPACE_BACKUP_RETENTION_COUNT", 5)
    assert save(client, workspace("A"), False).status_code == 200
    record = app_module.load_workspace_record()

    for _ in range(7):
        app_module.create_backup_and_prune(record, "retention_test")

    assert len(app_module.list_workspace_backups()) == 5
    assert client.get("/api/admin/backups").status_code == 404


def test_internal_restore_requires_a_fresh_get_for_every_public_session(client):
    app_module = sys.modules["app"]
    initial = save(client, workspace("backup-version"), False)
    revision_1 = initial.get_json()["revision"]
    backup = app_module.create_backup_and_prune(app_module.load_workspace_record(), "test_restore")

    updated = save(client, workspace("current-version"), True, revision_1)
    revision_before_restore = updated.get_json()["revision"]
    client_a = client
    client_b = make_public_client(app_module)
    assert client_a.get("/api/workspace").status_code == 200
    assert client_b.get("/api/workspace").get_json()["revision"] == revision_before_restore
    with client_b.session_transaction() as session_b:
        epoch_b_before = session_b["workspace_read_epoch"]
    server_epoch_before = app_module.WORKSPACE_READ_EPOCH

    restored = app_module.restore_workspace_backup(backup["id"])
    restored_revision = restored["revision"]
    assert restored_revision != revision_before_restore
    assert app_module.WORKSPACE_READ_EPOCH != server_epoch_before
    loaded_a = client_a.get("/api/workspace")
    assert loaded_a.status_code == 200
    assert loaded_a.get_json()["revision"] == restored_revision

    with client_b.session_transaction() as session_b:
        assert session_b["workspace_read_epoch"] == epoch_b_before
    blocked_b = save(client_b, workspace("stale-client-b"), True, revision_before_restore)
    assert blocked_b.status_code == 428
    assert blocked_b.get_json()["error"] == "workspace_fresh_read_required"

    refreshed_b = client_b.get("/api/workspace")
    assert refreshed_b.status_code == 200
    assert refreshed_b.get_json()["revision"] == restored_revision
    accepted_b = save(client_b, workspace("fresh-client-b"), True, restored_revision)
    assert accepted_b.status_code == 200


def test_resume_route_requires_a_confirmed_supabase_pause(client, monkeypatch):
    app_module = sys.modules["app"]
    calls = []
    monkeypatch.setattr(app_module, "request_supabase_project_restore", lambda: calls.append("resume"))

    response = client.post("/api/system/supabase/resume", json={})

    assert response.status_code == 409
    assert response.get_json()["error"] == "supabase_pause_not_confirmed"
    assert calls == []


def test_resume_route_still_requires_anonymous_csrf(client, monkeypatch):
    app_module = sys.modules["app"]
    app_module.require_fresh_reads_after_paused_storage()
    raw_client = app_module.app.test_client()
    monkeypatch.setattr(app_module, "request_supabase_project_restore", lambda: None)

    response = raw_client.post("/api/system/supabase/resume", json={})

    assert response.status_code == 403
    assert response.get_json()["error"] == "csrf_failed"


def test_supabase_resume_requires_a_fresh_get_for_every_public_session(client, monkeypatch):
    app_module = sys.modules["app"]
    initial = save(client, workspace("before-pause"), False)
    revision = initial.get_json()["revision"]
    client_a = client
    client_b = make_public_client(app_module)
    assert client_a.get("/api/workspace").status_code == 200
    assert client_b.get("/api/workspace").get_json()["revision"] == revision
    with client_b.session_transaction() as session_b:
        epoch_b_before = session_b["workspace_read_epoch"]
    server_epoch_before = app_module.WORKSPACE_READ_EPOCH

    real_load = app_module.load_workspace_record

    def paused_load():
        raise app_module.SupabaseProjectPaused("Project paused")

    monkeypatch.setattr(app_module, "load_workspace_record", paused_load)
    paused = client_a.get("/api/workspace")
    assert paused.status_code == 503
    assert paused.get_json()["error"] == "supabase_paused"
    assert app_module.WORKSPACE_READ_EPOCH != server_epoch_before
    assert app_module.supabase_pause_is_confirmed() is True

    monkeypatch.setattr(app_module, "load_workspace_record", real_load)
    calls = []
    monkeypatch.setattr(app_module, "request_supabase_project_restore", lambda: calls.append("resume"))
    resumed = client_a.post("/api/system/supabase/resume", json={})
    assert resumed.status_code == 202
    assert resumed.get_json()["status"] == "restore_requested"
    assert calls == ["resume"]

    loaded_a = client_a.get("/api/workspace")
    assert loaded_a.status_code == 200
    assert loaded_a.get_json()["revision"] == revision
    assert app_module.supabase_pause_is_confirmed() is False

    with client_b.session_transaction() as session_b:
        assert session_b["workspace_read_epoch"] == epoch_b_before
    blocked_b = save(client_b, workspace("stale-after-pause"), True, revision)
    assert blocked_b.status_code == 428
    assert blocked_b.get_json()["error"] == "workspace_fresh_read_required"

    refreshed_b = client_b.get("/api/workspace")
    assert refreshed_b.status_code == 200
    assert refreshed_b.get_json()["revision"] == revision
    accepted_b = save(client_b, workspace("fresh-after-pause"), True, revision)
    assert accepted_b.status_code == 200


def test_failed_supabase_resume_keeps_workspace_writes_blocked(client, monkeypatch):
    app_module = sys.modules["app"]
    assert save(client, workspace("before-failure"), False).status_code == 200

    real_load = app_module.load_workspace_record
    monkeypatch.setattr(
        app_module,
        "load_workspace_record",
        lambda: (_ for _ in ()).throw(app_module.SupabaseProjectPaused("Project paused")),
    )
    assert client.get("/api/workspace").status_code == 503
    monkeypatch.setattr(app_module, "load_workspace_record", real_load)

    def fail_resume():
        raise app_module.SupabaseManagementError(
            "supabase_management_unavailable",
            "Management API indisponible.",
            503,
        )

    monkeypatch.setattr(app_module, "request_supabase_project_restore", fail_resume)
    failed = client.post("/api/system/supabase/resume", json={})
    assert failed.status_code == 503
    assert failed.get_json()["error"] == "supabase_management_unavailable"

    blocked = save(client, workspace("must-not-write"), True, real_load()["revision"])
    assert blocked.status_code == 428
    assert blocked.get_json()["error"] == "workspace_fresh_read_required"


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


def test_keepalive_pause_detection_rotates_the_public_read_epoch(client, monkeypatch):
    app_module = sys.modules["app"]
    initial_epoch = app_module.WORKSPACE_READ_EPOCH

    def paused_probe():
        raise app_module.SupabaseProjectPaused("Project paused")

    monkeypatch.setattr(app_module, "probe_workspace_storage", paused_probe)
    response = app_module.app.test_client().get(
        "/api/system/keepalive",
        headers={"Authorization": "Bearer test-keepalive-token"},
    )

    assert response.status_code == 503
    assert response.get_json()["error"] == "supabase_paused"
    assert app_module.WORKSPACE_READ_EPOCH != initial_epoch


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


def test_management_restore_calls_fixed_endpoint_with_server_token(client, monkeypatch):
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


def test_management_restore_maps_permission_failure_without_leaking_body(client, monkeypatch):
    app_module = sys.modules["app"]
    monkeypatch.setattr(app_module, "SUPABASE_PROJECT_REF", "project-ref")
    monkeypatch.setattr(app_module, "SUPABASE_MANAGEMENT_TOKEN", "server-only-token")

    def forbidden(*_args, **_kwargs):
        raise urllib.error.HTTPError(
            "https://api.supabase.com/v1/projects/project-ref/restore",
            403,
            "Forbidden",
            {},
            io.BytesIO(b'{"message":"sensitive provider detail"}'),
        )

    monkeypatch.setattr(app_module.urllib.request, "urlopen", forbidden)
    with pytest.raises(app_module.SupabaseManagementError) as captured:
        app_module.request_supabase_project_restore()

    assert captured.value.code == "supabase_restore_refused"
    assert "sensitive provider detail" not in str(captured.value)
