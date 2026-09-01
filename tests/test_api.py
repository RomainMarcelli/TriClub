import io
import json
import sqlite3
import sys


def persistence_metadata(*, expected_exists, base_revision=None, empty_rows_intent=None):
    return {
        "initialLoadCompleted": True,
        "expectedExists": expected_exists,
        "baseRevision": base_revision,
        "emptyRowsIntent": empty_rows_intent,
    }


def basic_workspace(rows=None):
    return {
        "columns": [
            {
                "id": "col_role",
                "name": "Rôle",
                "type": "dropdown",
                "width": 170,
                "hidden": False,
                "defaultValue": "aucune des catégories",
                "options": ["président", "coach", "aucune des catégories"],
            },
        ],
        "rows": rows if rows is not None else [],
        "filters": [],
        "searchQuery": "",
        "sort": None,
        "views": [],
        "activeViewId": "",
    }


def test_index_serves_main_page(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Ben Workspace" in response.data


def test_tutoriel_route_renders(client):
    response = client.get("/tutoriel")
    assert response.status_code == 200
    assert "Tutoriel".encode("utf-8") in response.data


def test_health_endpoint(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_workspace_get_when_empty(client):
    response = client.get("/api/workspace")
    assert response.status_code == 200
    data = response.get_json()
    assert data["exists"] is False
    assert data["workspace"] is None


def test_workspace_post_then_get_roundtrip(client):
    payload = {
        "workspace": basic_workspace(
            [
                {"id": "r1", "values": {"col_role": "coach"}},
                {"id": "r2", "values": {"col_role": "aucune des catégories"}},
            ]
        ),
        "persistence": persistence_metadata(expected_exists=False),
    }
    response = client.post("/api/workspace", json=payload)
    assert response.status_code == 200, response.get_json()
    assert response.get_json()["status"] == "saved"

    # Le GET suivant doit renvoyer le workspace persisté.
    response = client.get("/api/workspace")
    data = response.get_json()
    assert data["exists"] is True
    assert data["revision"]
    assert data["workspace"]["columns"][0]["id"] == "col_role"
    assert data["workspace"]["rows"][0]["values"]["col_role"] == "coach"


def test_workspace_post_rejects_invalid_payload(client):
    response = client.post("/api/workspace", json={"workspace": "not a dict"})
    assert response.status_code == 400


def test_workspace_get_storage_failure_returns_503(client, monkeypatch):
    app_module = sys.modules["app"]

    def fail_load():
        raise RuntimeError("Supabase paused")

    monkeypatch.setattr(app_module, "load_workspace_record", fail_load)
    response = client.get("/api/workspace")

    assert response.status_code == 503
    data = response.get_json()
    assert data["workspace"] is None
    assert data["exists"] is False
    assert data["error"] == "workspace_storage_unavailable"


def test_workspace_get_corrupt_payload_is_not_reported_as_absent(client):
    app_module = sys.modules["app"]
    with sqlite3.connect(app_module.DB_ACTIVE_PATH) as connection:
        connection.execute(
            "INSERT INTO workspace_state (id, payload, updated_at) VALUES (1, ?, ?)",
            ("not-json", "2026-09-01T10:00:00+00:00"),
        )
        connection.commit()

    response = client.get("/api/workspace")
    assert response.status_code == 503
    assert response.get_json()["error"] == "workspace_storage_unavailable"


def test_workspace_storage_recovery_preserves_existing_rows(client, monkeypatch):
    initial = client.post(
        "/api/workspace",
        json={
            "workspace": basic_workspace([{"id": "r1", "values": {"col_role": "coach"}}]),
            "persistence": persistence_metadata(expected_exists=False),
        },
    )
    assert initial.status_code == 200

    app_module = sys.modules["app"]
    real_load = app_module.load_workspace_record

    def fail_load():
        raise RuntimeError("Supabase paused")

    monkeypatch.setattr(app_module, "load_workspace_record", fail_load)
    assert client.get("/api/workspace").status_code == 503

    monkeypatch.setattr(app_module, "load_workspace_record", real_load)
    recovered = client.get("/api/workspace")
    assert recovered.status_code == 200
    assert recovered.get_json()["workspace"]["rows"][0]["id"] == "r1"


def test_workspace_post_requires_valid_initial_load_metadata(client):
    response = client.post("/api/workspace", json={"workspace": basic_workspace()})
    assert response.status_code == 428
    assert response.get_json()["error"] == "workspace_initial_load_required"


def test_workspace_roundtrip_with_1498_rows(client):
    rows = [{"id": f"r{index}", "values": {"col_role": "coach"}} for index in range(1498)]
    response = client.post(
        "/api/workspace",
        json={
            "workspace": basic_workspace(rows),
            "persistence": persistence_metadata(expected_exists=False),
        },
    )
    assert response.status_code == 200

    response = client.get("/api/workspace")
    assert response.status_code == 200
    data = response.get_json()
    assert data["exists"] is True
    assert len(data["workspace"]["rows"]) == 1498
    assert data["revision"]


def test_workspace_post_rejects_stale_revision(client):
    initial = client.post(
        "/api/workspace",
        json={
            "workspace": basic_workspace([{"id": "r1", "values": {"col_role": "coach"}}]),
            "persistence": persistence_metadata(expected_exists=False),
        },
    )
    revision_1 = initial.get_json()["revision"]

    updated = client.post(
        "/api/workspace",
        json={
            "workspace": basic_workspace([{"id": "r1", "values": {"col_role": "président"}}]),
            "persistence": persistence_metadata(expected_exists=True, base_revision=revision_1),
        },
    )
    assert updated.status_code == 200

    stale = client.post(
        "/api/workspace",
        json={
            "workspace": basic_workspace([{"id": "r1", "values": {"col_role": "coach"}}]),
            "persistence": persistence_metadata(expected_exists=True, base_revision=revision_1),
        },
    )
    assert stale.status_code == 409
    assert stale.get_json()["error"] == "workspace_conflict"


def test_workspace_non_empty_row_deletion_is_allowed(client):
    initial = client.post(
        "/api/workspace",
        json={
            "workspace": basic_workspace(
                [
                    {"id": "r1", "values": {"col_role": "coach"}},
                    {"id": "r2", "values": {"col_role": "président"}},
                ]
            ),
            "persistence": persistence_metadata(expected_exists=False),
        },
    )
    revision = initial.get_json()["revision"]

    deleted = client.post(
        "/api/workspace",
        json={
            "workspace": basic_workspace([{"id": "r2", "values": {"col_role": "président"}}]),
            "persistence": persistence_metadata(expected_exists=True, base_revision=revision),
        },
    )
    assert deleted.status_code == 200
    assert [row["id"] for row in client.get("/api/workspace").get_json()["workspace"]["rows"]] == ["r2"]


def test_workspace_empty_transition_requires_explicit_user_intent(client):
    initial = client.post(
        "/api/workspace",
        json={
            "workspace": basic_workspace([{"id": "r1", "values": {"col_role": "coach"}}]),
            "persistence": persistence_metadata(expected_exists=False),
        },
    )
    revision = initial.get_json()["revision"]

    rejected = client.post(
        "/api/workspace",
        json={
            "workspace": basic_workspace([]),
            "persistence": persistence_metadata(expected_exists=True, base_revision=revision),
        },
    )
    assert rejected.status_code == 409
    assert rejected.get_json()["error"] == "workspace_empty_transition_requires_confirmation"
    assert len(client.get("/api/workspace").get_json()["workspace"]["rows"]) == 1

    accepted = client.post(
        "/api/workspace",
        json={
            "workspace": basic_workspace([]),
            "persistence": persistence_metadata(
                expected_exists=True,
                base_revision=revision,
                empty_rows_intent="user_deleted_all_rows",
            ),
        },
    )
    assert accepted.status_code == 200
    assert client.get("/api/workspace").get_json()["workspace"]["rows"] == []


def test_workspace_first_creation_may_be_intentionally_empty(client):
    response = client.post(
        "/api/workspace",
        json={
            "workspace": basic_workspace([]),
            "persistence": persistence_metadata(expected_exists=False),
        },
    )
    assert response.status_code == 200
    assert client.get("/api/workspace").get_json()["workspace"]["rows"] == []


def test_export_csv_returns_expected_columns(client):
    payload = {
        "filename": "export_test",
        "format": "numbers_csv",
        "columns": [
            {"id": "col_a", "name": "Nom du club", "type": "text", "width": 200, "hidden": False, "options": [], "defaultValue": ""},
            {"id": "col_b", "name": "Région", "type": "text", "width": 150, "hidden": False, "options": [], "defaultValue": ""},
        ],
        "rows": [
            {"id": "r1", "values": {"col_a": "RC Lyon", "col_b": "Auvergne-Rhône-Alpes"}},
            {"id": "r2", "values": {"col_a": "Stade Toulousain", "col_b": "Occitanie"}},
        ],
    }
    response = client.post("/api/export", json=payload)
    assert response.status_code == 200
    assert response.headers["Content-Type"].startswith("text/csv")
    body = response.data.decode("utf-8-sig")
    assert "Nom du club;Région" in body
    assert "RC Lyon;Auvergne-Rhône-Alpes" in body


def test_export_csv_standard_uses_comma(client):
    payload = {
        "filename": "export",
        "format": "csv_standard",
        "columns": [
            {"id": "col_a", "name": "A", "type": "text", "width": 100, "hidden": False, "options": [], "defaultValue": ""},
        ],
        "rows": [{"id": "r1", "values": {"col_a": "x"}}],
    }
    response = client.post("/api/export", json=payload)
    assert response.status_code == 200
    body = response.data.decode("utf-8")
    assert "A\r\nx" in body or "A\nx" in body


def test_export_rejects_unsupported_format(client):
    response = client.post(
        "/api/export",
        json={"format": "xlsx", "columns": [{"id": "a", "name": "A"}], "rows": []},
    )
    assert response.status_code == 400


def test_export_rejects_no_columns(client):
    response = client.post(
        "/api/export",
        json={"format": "numbers_csv", "columns": [], "rows": []},
    )
    assert response.status_code == 400


def test_share_link_generation_and_decoding(client):
    payload = {
        "workspace": {
            "name": "Vue Test",
            "columns": [
                {"id": "col_a", "name": "Nom du club", "type": "text", "width": 200, "hidden": False, "options": [], "defaultValue": ""},
            ],
            "rows": [{"id": "r1", "values": {"col_a": "RC Lyon"}}],
        }
    }
    response = client.post("/api/share", json=payload)
    assert response.status_code == 200
    share_url = response.get_json()["share_url"]
    assert "/shared/" in share_url

    token = share_url.rsplit("/", 1)[-1]
    shared_response = client.get(f"/shared/{token}")
    assert shared_response.status_code == 200
    assert b"RC Lyon" in shared_response.data


def test_share_rejects_empty_workspace(client):
    response = client.post("/api/share", json={"workspace": {}})
    assert response.status_code == 400


def test_extract_rejects_non_pdf(client):
    response = client.post(
        "/api/extract",
        data={"pdf_file": (io.BytesIO(b"not a pdf"), "fake.txt")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 400


def test_extract_rejects_missing_file(client):
    response = client.post("/api/extract", data={}, content_type="multipart/form-data")
    assert response.status_code == 400
