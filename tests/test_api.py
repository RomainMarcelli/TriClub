import io
import json


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
        "workspace": {
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
            "rows": [
                {"id": "r1", "values": {"col_role": "coach"}},
                {"id": "r2", "values": {"col_role": "aucune des catégories"}},
            ],
            "filters": [],
            "searchQuery": "",
            "sort": None,
            "views": [],
            "activeViewId": "",
        }
    }
    response = client.post("/api/workspace", json=payload)
    assert response.status_code == 200, response.get_json()
    assert response.get_json()["status"] == "saved"

    # Le GET suivant doit renvoyer le workspace persisté.
    response = client.get("/api/workspace")
    data = response.get_json()
    assert data["exists"] is True
    assert data["workspace"]["columns"][0]["id"] == "col_role"
    assert data["workspace"]["rows"][0]["values"]["col_role"] == "coach"


def test_workspace_post_rejects_invalid_payload(client):
    response = client.post("/api/workspace", json={"workspace": "not a dict"})
    assert response.status_code == 400


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
