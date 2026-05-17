import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app as app_module  # noqa: E402


def test_clean_cell_handles_none_and_whitespace():
    assert app_module.clean_cell(None) == ""
    assert app_module.clean_cell("  hello\n world  ") == "hello world"


def test_normalize_text_removes_accents_and_lowercases():
    assert app_module.normalize_text("Région") == "region"
    assert app_module.normalize_text("Département") == "departement"
    assert app_module.normalize_text("  RÔLE  ") == "role"


def test_slugify_filename_strips_special_chars():
    assert app_module.slugify_filename("Export Région 2026 !") == "export-region-2026"
    assert app_module.slugify_filename("") == "export"


def test_dedupe_headers_handles_collisions():
    headers = ["Nom", "Nom", "Région", "nom"]
    deduped = app_module.dedupe_headers(headers)
    # Premier "Nom" garde son nom, les suivants sont suffixés.
    assert deduped[0] == "Nom"
    assert "(2)" in deduped[1]


def test_sanitize_columns_keeps_valid_dropdowns():
    columns = [
        {
            "id": "col_role",
            "name": "Rôle",
            "type": "dropdown",
            "width": 160,
            "hidden": False,
            "defaultValue": "aucune des catégories",
            "options": ["président", "coach", "aucune des catégories"],
        },
    ]
    cleaned = app_module.sanitize_columns(columns)
    assert len(cleaned) == 1
    assert cleaned[0]["type"] == "dropdown"
    assert cleaned[0]["defaultValue"] == "aucune des catégories"
    assert "président" in cleaned[0]["options"]


def test_sanitize_columns_rejects_invalid_entries():
    cleaned = app_module.sanitize_columns([
        {"id": "", "name": "Sans id"},
        {"id": "ok", "name": ""},
        "not a dict",
        {"id": "ok", "name": "OK"},
    ])
    assert len(cleaned) == 1
    assert cleaned[0]["id"] == "ok"


def test_sanitize_columns_clamps_width():
    cleaned = app_module.sanitize_columns([{"id": "a", "name": "A", "width": 9999}])
    assert cleaned[0]["width"] == 180  # invalide → fallback


def test_sanitize_rows_preserves_values_and_assigns_id():
    rows = [
        {"id": "r1", "values": {"col_a": "x", "col_b": "y"}},
        {"values": {"col_a": "z"}},
        "ignored",
    ]
    cleaned = app_module.sanitize_rows(rows)
    assert len(cleaned) == 2
    assert cleaned[0]["id"] == "r1"
    assert cleaned[1]["id"]  # généré


def test_sanitize_filters_drops_unknown_operators():
    filters = [
        {"id": "f1", "columnId": "c1", "operator": "equals", "value": "x"},
        {"id": "f2", "columnId": "c1", "operator": "regex", "value": ".*"},
        {"id": "f3", "columnId": "", "operator": "equals", "value": "x"},
    ]
    cleaned = app_module.sanitize_filters(filters)
    assert len(cleaned) == 2
    # f2 garde son existence mais son opérateur est forcé à "contains".
    operators = {f["id"]: f["operator"] for f in cleaned}
    assert operators["f1"] == "equals"
    assert operators["f2"] == "contains"


def test_sanitize_workspace_state_creates_default_view():
    workspace = app_module.sanitize_workspace_state({"columns": [], "rows": []})
    assert workspace is not None
    assert len(workspace["views"]) == 1
    assert workspace["activeViewId"] == workspace["views"][0]["id"]


def test_suggest_mapping_finds_ffr_columns():
    mapping = app_module.suggest_mapping(["Ligue", "CD", "Code club", "Nom club"])
    assert mapping["Nom club"] == "Nom club"
    assert mapping["Ligue"] == "Ligue"
    assert mapping["CD"] == "CD"
