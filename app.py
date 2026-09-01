import base64
import csv
import io
import json
import os
import re
import secrets
import sqlite3
import threading
import unicodedata
import urllib.error
import urllib.request
import zlib
from datetime import datetime, timezone
from typing import Any

import pdfplumber
from flask import Flask, jsonify, render_template, request, send_file, url_for
from itsdangerous import BadSignature, URLSafeSerializer

try:
    import psycopg
except ImportError:  # pragma: no cover - optional dependency in local dev
    psycopg = None


def load_local_env_file(path: str = ".env") -> None:
    if not os.path.exists(path):
        return

    try:
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                row = line.strip()
                if not row or row.startswith("#") or "=" not in row:
                    continue
                key, value = row.split("=", 1)
                key = key.strip()
                if not key:
                    continue
                # Do not override vars already provided by the runtime (Render, shell, etc.).
                os.environ.setdefault(key, value.strip().strip('"').strip("'"))
    except OSError:
        return


load_local_env_file()

app = Flask(__name__)
app.secret_key = os.environ.get("APP_SECRET_KEY", secrets.token_hex(16))
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024  # 20 MB

SHARE_SERIALIZER = URLSafeSerializer(app.secret_key, salt="ben-share-v1")
TARGET_FIELDS = ["Nom club", "Ligue", "CD"]
TARGET_FIELDS_NORMALIZED = ["nom club", "ligue", "cd"]
MAX_SHARE_RAW_BYTES = 700_000
ALLOWED_FILTER_OPERATORS = {"equals", "contains", "starts_with", "is_empty", "is_not_empty"}
SUPABASE_DB_URL = os.environ.get("SUPABASE_DB_URL", "").strip()
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
HAS_SUPABASE_REST = bool(SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY)
if SUPABASE_DB_URL:
    DB_BACKEND = "postgres"
elif HAS_SUPABASE_REST:
    DB_BACKEND = "supabase_rest"
else:
    DB_BACKEND = "sqlite"
STORAGE_BACKEND_LAST = DB_BACKEND
try:
    SUPABASE_HTTP_TIMEOUT = max(3.0, float(os.environ.get("SUPABASE_HTTP_TIMEOUT", "12")))
except ValueError:
    SUPABASE_HTTP_TIMEOUT = 12.0
DB_PATH = os.environ.get("BEN_DB_PATH", os.path.join(os.path.dirname(__file__), "data", "ben_workspace.db"))
DB_FALLBACK_PATH = os.path.join("/tmp", "ben_workspace.db")
DB_ACTIVE_PATH = DB_PATH
DB_LOCK = threading.Lock()
WORKSPACE_WRITE_LOCK = threading.Lock()
FFR_LINE_PATTERN = re.compile(r"^(?P<ligue>.+?)\s+(?P<cd>\S+)\s+(?P<code>\d{4}[A-Za-z])\s+(?P<club>.+)$")
FFR_IGNORE_PREFIXES = (
    "Liste des clubs inscrits",
    "Semaine Nationale",
    "Code",
    "Ligue CD Nom club",
    "Club",
    "FFR-DS",
)


def set_storage_backend(name: str) -> None:
    global STORAGE_BACKEND_LAST
    STORAGE_BACKEND_LAST = name


def get_storage_backend() -> str:
    return STORAGE_BACKEND_LAST or DB_BACKEND


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).replace("\n", " ").strip().lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = " ".join(text.split())
    return text


def clean_cell(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).replace("\n", " ").split())


def slugify_filename(name: str) -> str:
    base = normalize_text(name)
    base = re.sub(r"[^a-z0-9]+", "-", base).strip("-")
    if not base:
        return "export"
    return base[:80]


def dedupe_headers(headers: list[str]) -> list[str]:
    counts: dict[str, int] = {}
    deduped = []

    for raw in headers:
        header = clean_cell(raw) or "Colonne"
        key = normalize_text(header)
        counts[key] = counts.get(key, 0) + 1

        if counts[key] > 1:
            deduped.append(f"{header} ({counts[key]})")
        else:
            deduped.append(header)

    return deduped


def detect_header_row(table: list[list[Any]]) -> int | None:
    best_index = None
    best_score = -1

    for index, row in enumerate(table[:6]):
        if not row:
            continue

        non_empty = sum(1 for cell in row if normalize_text(cell))
        keyword_hits = sum(1 for cell in row if normalize_text(cell) in TARGET_FIELDS_NORMALIZED)
        score = non_empty + (keyword_hits * 3)

        if score > best_score:
            best_score = score
            best_index = index

    return best_index


def extract_candidate_tables(file_storage) -> list[dict[str, Any]]:
    tables_out: list[dict[str, Any]] = []
    file_storage.stream.seek(0)

    with pdfplumber.open(file_storage.stream) as pdf:
        for page_index, page in enumerate(pdf.pages, start=1):
            tables = page.extract_tables() or []
            for table_index, table in enumerate(tables, start=1):
                if not table:
                    continue

                header_row_index = detect_header_row(table)
                if header_row_index is None:
                    continue

                raw_headers = table[header_row_index]
                headers = dedupe_headers([clean_cell(cell) for cell in raw_headers])
                if len(headers) < 2:
                    continue

                rows = []
                for row in table[header_row_index + 1 :]:
                    if not row:
                        continue

                    row_dict = {}
                    has_value = False
                    for col_index, header in enumerate(headers):
                        value = clean_cell(row[col_index] if col_index < len(row) else "")
                        row_dict[header] = value
                        if value:
                            has_value = True

                    if has_value:
                        rows.append(row_dict)

                if not rows:
                    continue

                normalized_headers = [normalize_text(header) for header in headers]
                score = sum(1 for target in TARGET_FIELDS_NORMALIZED if target in normalized_headers)

                tables_out.append(
                    {
                        "page": page_index,
                        "table_index": table_index,
                        "parser": "table",
                        "headers": headers,
                        "rows": rows,
                        "score": score,
                    }
                )

    return tables_out


def extract_candidate_lines(file_storage) -> dict[str, Any] | None:
    file_storage.stream.seek(0)
    parsed_rows: list[dict[str, str]] = []
    first_page: int | None = None

    with pdfplumber.open(file_storage.stream) as pdf:
        for page_index, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            for raw_line in text.splitlines():
                line = clean_cell(raw_line)
                if not line:
                    continue
                if any(line.startswith(prefix) for prefix in FFR_IGNORE_PREFIXES):
                    continue

                match = FFR_LINE_PATTERN.match(line)
                if not match:
                    continue

                if first_page is None:
                    first_page = page_index

                parsed_rows.append(
                    {
                        "Ligue": clean_cell(match.group("ligue")),
                        "CD": clean_cell(match.group("cd")),
                        "Code club": clean_cell(match.group("code")),
                        "Nom club": clean_cell(match.group("club")),
                    }
                )

    if not parsed_rows:
        return None

    unique_rows: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for row in parsed_rows:
        key = (
            row.get("Ligue", ""),
            row.get("CD", ""),
            row.get("Code club", ""),
            row.get("Nom club", ""),
        )
        if key in seen:
            continue
        seen.add(key)
        unique_rows.append(row)

    return {
        "page": first_page or 1,
        "table_index": 0,
        "parser": "text_line",
        "headers": ["Ligue", "CD", "Code club", "Nom club"],
        "rows": unique_rows,
        "score": len(TARGET_FIELDS_NORMALIZED),
    }


def pick_best_table(tables: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not tables:
        return None

    return max(tables, key=lambda t: (t.get("score", 0), len(t.get("rows", []))))


def suggest_mapping(headers: list[str]) -> dict[str, str]:
    normalized_lookup = {normalize_text(header): header for header in headers}
    mapping = {}

    for target, normalized_target in zip(TARGET_FIELDS, TARGET_FIELDS_NORMALIZED):
        mapping[target] = normalized_lookup.get(normalized_target, "")

    return mapping


def build_csv_bytes(
    headers: list[str],
    rows: list[list[str]],
    delimiter: str = ";",
    include_bom: bool = True,
) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output, delimiter=delimiter)
    writer.writerow(headers)
    writer.writerows(rows)
    encoding = "utf-8-sig" if include_bom else "utf-8"
    return output.getvalue().encode(encoding)


def compress_payload(payload: dict[str, Any]) -> str:
    raw_json = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(raw_json) > MAX_SHARE_RAW_BYTES:
        raise ValueError("Payload too large")

    compressed = zlib.compress(raw_json, level=9)
    return base64.urlsafe_b64encode(compressed).decode("ascii")


def decompress_payload(encoded_payload: str) -> dict[str, Any]:
    compressed = base64.urlsafe_b64decode(encoded_payload.encode("ascii"))
    raw_json = zlib.decompress(compressed)
    return json.loads(raw_json.decode("utf-8"))


def sanitize_columns(columns: Any) -> list[dict[str, Any]]:
    if not isinstance(columns, list):
        return []

    out = []
    for col in columns:
        if not isinstance(col, dict):
            continue

        col_id = clean_cell(col.get("id", ""))
        name = clean_cell(col.get("name", ""))
        col_type = clean_cell(col.get("type", "text")) or "text"
        width = col.get("width", 180)
        hidden = bool(col.get("hidden", False))
        default_value = clean_cell(col.get("defaultValue", ""))
        options = col.get("options", [])

        if not col_id or not name:
            continue

        if not isinstance(options, list):
            options = []

        safe_options = [clean_cell(opt) for opt in options if clean_cell(opt)]
        safe_width = width if isinstance(width, int) and 100 <= width <= 600 else 180

        out.append(
            {
                "id": col_id,
                "name": name,
                "type": col_type,
                "width": safe_width,
                "hidden": hidden,
                "defaultValue": default_value,
                "options": safe_options,
            }
        )

    return out


def sanitize_rows(rows: Any) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []

    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue

        row_id = clean_cell(row.get("id", "")) or secrets.token_urlsafe(8)
        values = row.get("values", {})

        if not isinstance(values, dict):
            values = {}

        safe_values = {clean_cell(k): clean_cell(v) for k, v in values.items() if clean_cell(k)}
        out.append({"id": row_id, "values": safe_values})

    return out


def sanitize_filters(filters: Any) -> list[dict[str, str]]:
    if not isinstance(filters, list):
        return []

    out = []
    for item in filters:
        if not isinstance(item, dict):
            continue

        filter_id = clean_cell(item.get("id", "")) or secrets.token_urlsafe(8)
        column_id = clean_cell(item.get("columnId", ""))
        operator = clean_cell(item.get("operator", "contains"))
        value = clean_cell(item.get("value", ""))

        if not column_id:
            continue
        if operator not in ALLOWED_FILTER_OPERATORS:
            operator = "contains"

        out.append(
            {
                "id": filter_id,
                "columnId": column_id,
                "operator": operator,
                "value": value,
            }
        )

    return out


def sanitize_sort(sort: dict[str, Any] | None) -> dict[str, str] | None:
    if not isinstance(sort, dict):
        return None

    column_id = clean_cell(sort.get("columnId", ""))
    direction = clean_cell(sort.get("direction", "asc")).lower()
    if not column_id:
        return None
    if direction not in {"asc", "desc"}:
        direction = "asc"

    return {"columnId": column_id, "direction": direction}


def sanitize_views(views: Any) -> list[dict[str, Any]]:
    if not isinstance(views, list):
        return []

    out = []
    for index, item in enumerate(views):
        if not isinstance(item, dict):
            continue

        view_id = clean_cell(item.get("id", "")) or f"view_{index + 1}"
        name = clean_cell(item.get("name", "")) or f"Vue {index + 1}"
        filters = sanitize_filters(item.get("filters", []))
        sort = sanitize_sort(item.get("sort"))
        hidden_column_ids = item.get("hiddenColumnIds", [])
        if not isinstance(hidden_column_ids, list):
            hidden_column_ids = []

        out.append(
            {
                "id": view_id,
                "name": name,
                "filters": filters,
                "sort": sort,
                "hiddenColumnIds": [clean_cell(value) for value in hidden_column_ids if clean_cell(value)],
            }
        )

    return out


def sanitize_workspace_state(workspace: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(workspace, dict):
        return None

    columns = sanitize_columns(workspace.get("columns", []))
    rows = sanitize_rows(workspace.get("rows", []))
    filters = sanitize_filters(workspace.get("filters", []))
    search_query = clean_cell(workspace.get("searchQuery", ""))
    sort = sanitize_sort(workspace.get("sort"))
    views = sanitize_views(workspace.get("views", []))

    if not views:
        views = [
            {
                "id": "view_default",
                "name": "Vue par defaut",
                "filters": [],
                "sort": None,
                "hiddenColumnIds": [],
            }
        ]

    active_view_id = clean_cell(workspace.get("activeViewId", ""))
    if not any(view["id"] == active_view_id for view in views):
        active_view_id = views[0]["id"]

    selected_column_id = clean_cell(workspace.get("selectedColumnId", ""))
    if selected_column_id and not any(col["id"] == selected_column_id for col in columns):
        selected_column_id = ""

    selected_row_id = clean_cell(workspace.get("selectedRowId", ""))
    if selected_row_id and not any(row["id"] == selected_row_id for row in rows):
        selected_row_id = ""

    return {
        "columns": columns,
        "rows": rows,
        "filters": filters,
        "searchQuery": search_query,
        "sort": sort,
        "views": views,
        "activeViewId": active_view_id,
        "selectedColumnId": selected_column_id,
        "selectedRowId": selected_row_id,
    }


def ensure_sqlite_database() -> None:
    global DB_ACTIVE_PATH
    errors: list[str] = []

    with DB_LOCK:
        candidates = []
        for path in (DB_ACTIVE_PATH, DB_PATH, DB_FALLBACK_PATH):
            if path and path not in candidates:
                candidates.append(path)

        for candidate in candidates:
            try:
                db_dir = os.path.dirname(candidate)
                if db_dir:
                    os.makedirs(db_dir, exist_ok=True)

                with sqlite3.connect(candidate) as conn:
                    conn.execute(
                        """
                        CREATE TABLE IF NOT EXISTS workspace_state (
                            id INTEGER PRIMARY KEY CHECK (id = 1),
                            payload TEXT NOT NULL,
                            updated_at TEXT NOT NULL
                        )
                        """
                    )
                    conn.commit()

                DB_ACTIVE_PATH = candidate
                return
            except (OSError, sqlite3.Error) as error:
                errors.append(f"{candidate}: {error}")

    raise RuntimeError(f"Impossible d'initialiser la base SQLite. Details: {' | '.join(errors)}")


def ensure_postgres_database() -> None:
    if psycopg is None:
        raise RuntimeError("Le package 'psycopg' est requis pour utiliser SUPABASE_DB_URL.")
    if not SUPABASE_DB_URL:
        raise RuntimeError("SUPABASE_DB_URL est vide.")

    with DB_LOCK:
        with psycopg.connect(SUPABASE_DB_URL, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS workspace_state (
                        id SMALLINT PRIMARY KEY CHECK (id = 1),
                        payload JSONB NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )


def supabase_rest_request(
    method: str,
    path_with_query: str,
    payload: Any | None = None,
    prefer: str | None = None,
) -> Any:
    if not HAS_SUPABASE_REST:
        raise RuntimeError("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY manquants pour le mode REST.")

    url = f"{SUPABASE_URL}/rest/v1/{path_with_query.lstrip('/')}"
    headers = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Accept": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer

    body = None
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request_obj = urllib.request.Request(url=url, data=body, headers=headers, method=method.upper())
    try:
        with urllib.request.urlopen(request_obj, timeout=SUPABASE_HTTP_TIMEOUT) as response:
            raw = response.read().decode("utf-8", errors="replace").strip()
    except urllib.error.HTTPError as error:
        error_body = error.read().decode("utf-8", errors="replace")
        detail = clean_cell(error_body) or clean_cell(error.reason)
        raise RuntimeError(f"Supabase REST HTTP {error.code}: {detail[:260]}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"Supabase REST inaccessible: {clean_cell(error.reason or error)}") from error

    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def ensure_supabase_rest_database() -> None:
    supabase_rest_request("GET", "workspace_state?select=id&limit=1")


def ensure_database() -> None:
    if DB_BACKEND == "postgres":
        try:
            ensure_postgres_database()
            set_storage_backend("postgres")
            return
        except Exception as error:
            if not HAS_SUPABASE_REST:
                raise
            app.logger.warning("Postgres direct inaccessible, fallback Supabase REST: %s", error)
            ensure_supabase_rest_database()
            set_storage_backend("supabase_rest")
            return
    if DB_BACKEND == "supabase_rest":
        ensure_supabase_rest_database()
        set_storage_backend("supabase_rest")
        return
    ensure_sqlite_database()
    set_storage_backend("sqlite")


def decode_workspace_payload(raw_payload: Any) -> dict[str, Any] | None:
    if isinstance(raw_payload, dict):
        return raw_payload

    if isinstance(raw_payload, (bytes, bytearray, memoryview)):
        try:
            raw_payload = bytes(raw_payload).decode("utf-8")
        except Exception:
            return None

    if isinstance(raw_payload, str):
        try:
            parsed = json.loads(raw_payload)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None

    return None


def normalize_workspace_revision(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return clean_cell(value)


def build_workspace_record(raw_payload: Any, raw_revision: Any) -> dict[str, Any]:
    data = decode_workspace_payload(raw_payload)
    if data is None:
        raise RuntimeError("Le workspace stocke contient un payload JSON invalide.")

    workspace = sanitize_workspace_state(data)
    if workspace is None:
        raise RuntimeError("Le workspace stocke ne peut pas etre nettoye.")

    revision = normalize_workspace_revision(raw_revision)
    if not revision:
        raise RuntimeError("Le workspace stocke ne contient pas de revision.")

    return {"workspace": workspace, "revision": revision}


def load_workspace_record_sqlite() -> dict[str, Any] | None:
    ensure_sqlite_database()
    set_storage_backend("sqlite")
    with DB_LOCK:
        with sqlite3.connect(DB_ACTIVE_PATH) as conn:
            row = conn.execute("SELECT payload, updated_at FROM workspace_state WHERE id = 1").fetchone()

    if not row:
        return None

    return build_workspace_record(row[0], row[1])


def load_workspace_record_postgres() -> dict[str, Any] | None:
    ensure_postgres_database()
    set_storage_backend("postgres")
    with DB_LOCK:
        with psycopg.connect(SUPABASE_DB_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT payload, updated_at FROM workspace_state WHERE id = 1")
                row = cur.fetchone()

    if not row:
        return None

    return build_workspace_record(row[0], row[1])


def load_workspace_record_supabase_rest() -> dict[str, Any] | None:
    ensure_supabase_rest_database()
    set_storage_backend("supabase_rest")
    rows = supabase_rest_request("GET", "workspace_state?select=payload,updated_at&id=eq.1&limit=1")
    if not isinstance(rows, list) or not rows:
        return None

    first = rows[0] if isinstance(rows[0], dict) else {}
    return build_workspace_record(first.get("payload"), first.get("updated_at"))


def load_workspace_record() -> dict[str, Any] | None:
    if DB_BACKEND == "postgres":
        try:
            return load_workspace_record_postgres()
        except Exception as error:
            if not HAS_SUPABASE_REST:
                raise
            app.logger.warning("Workspace load Postgres failed, fallback REST: %s", error)
            return load_workspace_record_supabase_rest()
    if DB_BACKEND == "supabase_rest":
        return load_workspace_record_supabase_rest()
    return load_workspace_record_sqlite()


def load_workspace_state_sqlite() -> dict[str, Any] | None:
    record = load_workspace_record_sqlite()
    return record["workspace"] if record else None


def load_workspace_state_postgres() -> dict[str, Any] | None:
    record = load_workspace_record_postgres()
    return record["workspace"] if record else None


def load_workspace_state_supabase_rest() -> dict[str, Any] | None:
    record = load_workspace_record_supabase_rest()
    return record["workspace"] if record else None


def load_workspace_state() -> dict[str, Any] | None:
    record = load_workspace_record()
    return record["workspace"] if record else None


def save_workspace_state_sqlite(workspace: dict[str, Any]) -> str:
    ensure_sqlite_database()
    set_storage_backend("sqlite")
    payload = json.dumps(workspace, ensure_ascii=False, separators=(",", ":"))
    updated_at = datetime.now(timezone.utc).isoformat()

    with DB_LOCK:
        with sqlite3.connect(DB_ACTIVE_PATH) as conn:
            conn.execute(
                """
                INSERT INTO workspace_state (id, payload, updated_at)
                VALUES (1, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    payload = excluded.payload,
                    updated_at = excluded.updated_at
                """,
                (payload, updated_at),
            )
            conn.commit()

    return updated_at


def save_workspace_state_postgres(workspace: dict[str, Any]) -> str:
    ensure_postgres_database()
    set_storage_backend("postgres")
    payload = json.dumps(workspace, ensure_ascii=False, separators=(",", ":"))

    with DB_LOCK:
        with psycopg.connect(SUPABASE_DB_URL) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO workspace_state (id, payload, updated_at)
                    VALUES (1, %s::jsonb, NOW())
                    ON CONFLICT (id) DO UPDATE SET
                        payload = EXCLUDED.payload,
                        updated_at = NOW()
                    RETURNING updated_at
                    """,
                    (payload,),
                )
                row = cur.fetchone()
            conn.commit()

    if not row or not row[0]:
        return datetime.now(timezone.utc).isoformat()

    if isinstance(row[0], datetime):
        return row[0].isoformat()

    return clean_cell(row[0])


def save_workspace_state_supabase_rest(workspace: dict[str, Any]) -> str:
    ensure_supabase_rest_database()
    set_storage_backend("supabase_rest")
    updated_at = datetime.now(timezone.utc).isoformat()
    payload = [{"id": 1, "payload": workspace, "updated_at": updated_at}]

    rows = supabase_rest_request(
        "POST",
        "workspace_state?on_conflict=id&select=updated_at",
        payload=payload,
        prefer="resolution=merge-duplicates,return=representation",
    )

    if isinstance(rows, list) and rows and isinstance(rows[0], dict):
        raw_updated_at = rows[0].get("updated_at")
        if raw_updated_at:
            return clean_cell(raw_updated_at)
    return updated_at


def save_workspace_state(workspace: dict[str, Any]) -> str:
    if DB_BACKEND == "postgres":
        try:
            return save_workspace_state_postgres(workspace)
        except Exception as error:
            if not HAS_SUPABASE_REST:
                raise
            app.logger.warning("Workspace save Postgres failed, fallback REST: %s", error)
            return save_workspace_state_supabase_rest(workspace)
    if DB_BACKEND == "supabase_rest":
        return save_workspace_state_supabase_rest(workspace)
    return save_workspace_state_sqlite(workspace)


class WorkspaceWriteConflict(RuntimeError):
    pass


class UnsafeEmptyWorkspaceTransition(RuntimeError):
    pass


def save_workspace_state_conditionally(
    workspace: dict[str, Any],
    *,
    expected_exists: bool,
    base_revision: str,
    empty_rows_intent: str,
) -> str:
    """Reject stale writes and accidental transitions to an empty workspace."""
    with WORKSPACE_WRITE_LOCK:
        current_record = load_workspace_record()
        current_exists = current_record is not None

        if current_exists != expected_exists:
            raise WorkspaceWriteConflict("L'existence du workspace distant a change.")

        if current_record:
            current_revision = current_record["revision"]
            if not base_revision or base_revision != current_revision:
                raise WorkspaceWriteConflict("La revision du workspace distant a change.")
        elif base_revision:
            raise WorkspaceWriteConflict("Une revision a ete fournie pour un workspace inexistant.")

        current_row_count = len(current_record["workspace"].get("rows", [])) if current_record else 0
        next_row_count = len(workspace.get("rows", []))
        if current_row_count > 0 and next_row_count == 0 and empty_rows_intent != "user_deleted_all_rows":
            raise UnsafeEmptyWorkspaceTransition(
                "Le passage d'un workspace non vide a zero ligne exige une suppression utilisateur explicite."
            )

        return save_workspace_state(workspace)


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/tutoriel")
def tutoriel_view():
    return render_template("tutoriel.html")


@app.get("/shared/<token>")
def shared_view(token: str):
    try:
        encoded_payload = SHARE_SERIALIZER.loads(token)
        workspace = decompress_payload(encoded_payload)
    except (BadSignature, ValueError, OSError, json.JSONDecodeError):
        return render_template("shared.html", workspace_json=json.dumps({"error": "invalid"}))

    return render_template("shared.html", workspace_json=json.dumps(workspace, ensure_ascii=False))


@app.post("/api/extract")
def api_extract():
    pdf_file = request.files.get("pdf_file")

    if not pdf_file or not pdf_file.filename:
        return jsonify({"error": "Selectionne un fichier PDF."}), 400

    if not pdf_file.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Le fichier doit etre au format PDF."}), 400

    try:
        # Fast path for large federation-style PDFs:
        # text-line parsing is usually much faster than full table extraction.
        line_candidate = extract_candidate_lines(pdf_file)
        if line_candidate and len(line_candidate.get("rows", [])) >= 20:
            tables = [line_candidate]
            best_table = line_candidate
        else:
            tables = extract_candidate_tables(pdf_file)
            if line_candidate:
                tables.append(line_candidate)
            best_table = pick_best_table(tables)
    except Exception:
        return jsonify({"error": "Impossible de lire ce PDF."}), 400

    if not best_table:
        return jsonify({"error": "Aucune table exploitable n'a ete detectee dans ce PDF."}), 404

    headers = best_table["headers"]
    rows = best_table["rows"]

    return jsonify(
        {
            "headers": headers,
            "rows": rows,
            "row_count": len(rows),
            "preview_rows": rows[:12],
            "suggested_mapping": suggest_mapping(headers),
            "required_fields": TARGET_FIELDS,
            "table_meta": {
                "page": best_table.get("page"),
                "table_index": best_table.get("table_index"),
                "parser": best_table.get("parser", "table"),
                "detected_tables": len(tables),
            },
        }
    )


@app.post("/api/export")
def api_export():
    data = request.get_json(silent=True) or {}

    columns = sanitize_columns(data.get("columns", []))
    rows = sanitize_rows(data.get("rows", []))
    filename = clean_cell(data.get("filename", "export_numbers"))
    export_format = clean_cell(data.get("format", "numbers_csv")).lower()

    if export_format in {"numbers", "numbers_csv"}:
        export_format = "numbers_csv"
    elif export_format in {"csv", "csv_standard", "standard_csv"}:
        export_format = "csv_standard"
    else:
        return jsonify({"error": "Format d'export non supporte."}), 400

    if not columns:
        return jsonify({"error": "Aucune colonne a exporter."}), 400

    headers = [col["name"] for col in columns]
    csv_rows = []

    for row in rows:
        values = row.get("values", {})
        csv_rows.append([clean_cell(values.get(col["id"], "")) for col in columns])

    delimiter = ";" if export_format == "numbers_csv" else ","
    include_bom = export_format == "numbers_csv"
    csv_bytes = build_csv_bytes(headers, csv_rows, delimiter=delimiter, include_bom=include_bom)
    safe_filename = f"{slugify_filename(filename)}.csv"

    return send_file(
        io.BytesIO(csv_bytes),
        mimetype="text/csv",
        as_attachment=True,
        download_name=safe_filename,
    )


@app.post("/api/share")
def api_share():
    data = request.get_json(silent=True) or {}

    workspace = data.get("workspace", {})
    if not isinstance(workspace, dict):
        return jsonify({"error": "Payload de partage invalide."}), 400

    workspace_name = clean_cell(workspace.get("name", "Vue partagee"))
    columns = sanitize_columns(workspace.get("columns", []))
    rows = sanitize_rows(workspace.get("rows", []))

    if not columns:
        return jsonify({"error": "Impossible de partager une vue vide."}), 400

    payload = {
        "name": workspace_name,
        "columns": columns,
        "rows": rows,
        "generatedAt": clean_cell(workspace.get("generatedAt", "")),
    }

    try:
        encoded_payload = compress_payload(payload)
    except ValueError:
        return jsonify(
            {
                "error": "Cette vue est trop volumineuse pour un lien partageable."
                " Exporte en CSV ou reduis la vue (filtres)."
            }
        ), 413

    token = SHARE_SERIALIZER.dumps(encoded_payload)
    share_url = url_for("shared_view", token=token, _external=True)
    return jsonify({"share_url": share_url})


@app.get("/api/workspace")
def api_workspace_get():
    try:
        record = load_workspace_record()
    except Exception as error:
        app.logger.exception("Workspace load failed: %s", error)
        return (
            jsonify(
                {
                    "workspace": None,
                    "exists": False,
                    "error": "workspace_storage_unavailable",
                    "storage_backend": get_storage_backend(),
                    "preferred_storage_backend": DB_BACKEND,
                    "hint": "Verifie SUPABASE_DB_URL ou SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY et la connectivite.",
                    "detail": clean_cell(str(error))[:260],
                }
            ),
            503,
        )

    if record is None:
        return jsonify(
            {
                "workspace": None,
                "exists": False,
                "storage_backend": get_storage_backend(),
                "preferred_storage_backend": DB_BACKEND,
            }
        )

    response = {
        "workspace": record["workspace"],
        "exists": True,
        "revision": record["revision"],
        "storage_backend": get_storage_backend(),
        "preferred_storage_backend": DB_BACKEND,
    }
    if get_storage_backend() == "sqlite":
        response["db_path"] = DB_ACTIVE_PATH
    return jsonify(response)


@app.post("/api/workspace")
def api_workspace_post():
    data = request.get_json(silent=True) or {}
    workspace = sanitize_workspace_state(data.get("workspace"))
    if workspace is None:
        return jsonify({"error": "Payload workspace invalide."}), 400

    if not workspace.get("columns"):
        return jsonify({"error": "workspace_without_columns", "message": "Un workspace sans colonne est refuse."}), 400

    persistence = data.get("persistence")
    if not isinstance(persistence, dict) or persistence.get("initialLoadCompleted") is not True:
        return (
            jsonify(
                {
                    "error": "workspace_initial_load_required",
                    "message": "Charge le workspace distant avant toute sauvegarde.",
                }
            ),
            428,
        )

    expected_exists = persistence.get("expectedExists")
    if not isinstance(expected_exists, bool):
        return jsonify({"error": "workspace_persistence_metadata_invalid"}), 400

    base_revision = clean_cell(persistence.get("baseRevision", ""))
    empty_rows_intent = clean_cell(persistence.get("emptyRowsIntent", ""))

    try:
        updated_at = save_workspace_state_conditionally(
            workspace,
            expected_exists=expected_exists,
            base_revision=base_revision,
            empty_rows_intent=empty_rows_intent,
        )
    except WorkspaceWriteConflict as error:
        app.logger.warning("Workspace save conflict: %s", error)
        return (
            jsonify(
                {
                    "error": "workspace_conflict",
                    "message": "Le workspace distant a change. Recharge la page avant de sauvegarder.",
                }
            ),
            409,
        )
    except UnsafeEmptyWorkspaceTransition as error:
        app.logger.warning("Unsafe empty workspace save rejected: %s", error)
        return (
            jsonify(
                {
                    "error": "workspace_empty_transition_requires_confirmation",
                    "message": str(error),
                }
            ),
            409,
        )
    except Exception as error:
        app.logger.exception("Workspace save failed: %s", error)
        return (
            jsonify(
                {
                    "error": "workspace_storage_unavailable",
                    "message": "Sauvegarde indisponible (BDD inaccessible). Verifie la config Supabase.",
                    "detail": clean_cell(str(error))[:260],
                    "storage_backend": get_storage_backend(),
                    "preferred_storage_backend": DB_BACKEND,
                }
            ),
            503,
        )

    return jsonify({"status": "saved", "updated_at": updated_at, "revision": updated_at})


@app.get("/api/health")
def api_health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    try:
        ensure_database()
    except Exception as error:
        app.logger.warning("Database initialization warning: %s", error)
    app.run(host="0.0.0.0", port=5000, debug=True)
