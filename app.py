import base64
import csv
import functools
import io
import json
import os
import re
import secrets
import sqlite3
import threading
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import zlib
from datetime import datetime, timezone
from typing import Any

import pdfplumber
from flask import Flask, jsonify, render_template, request, send_file, session, url_for
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
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=bool(os.environ.get("RENDER")),
    SESSION_COOKIE_SAMESITE="Lax",
)


@app.after_request
def add_security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    if request.path == "/" or request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response

SHARE_SERIALIZER = URLSafeSerializer(app.secret_key, salt="ben-share-v1")
TARGET_FIELDS = ["Nom club", "Ligue", "CD"]
TARGET_FIELDS_NORMALIZED = ["nom club", "ligue", "cd"]
MAX_SHARE_RAW_BYTES = 700_000
ALLOWED_FILTER_OPERATORS = {"equals", "contains", "starts_with", "is_empty", "is_not_empty"}
SUPABASE_DB_URL = os.environ.get("SUPABASE_DB_URL", "").strip()
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
SUPABASE_MANAGEMENT_TOKEN = os.environ.get("SUPABASE_MANAGEMENT_TOKEN", "").strip()
SUPABASE_PROJECT_REF = os.environ.get("SUPABASE_PROJECT_REF", "").strip()
KEEPALIVE_TOKEN = os.environ.get("KEEPALIVE_TOKEN", "").strip()
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
WORKSPACE_RECOVERY_LOCK = threading.Lock()
WORKSPACE_RECOVERY_STATE = "idle"
WORKSPACE_READ_EPOCH = secrets.token_urlsafe(24)
SUPABASE_PAUSE_CONFIRMED = False
try:
    WORKSPACE_BACKUP_INTERVAL_SECONDS = max(
        60,
        int(os.environ.get("WORKSPACE_BACKUP_INTERVAL_SECONDS", "900")),
    )
except ValueError:
    WORKSPACE_BACKUP_INTERVAL_SECONDS = 900
try:
    WORKSPACE_BACKUP_RETENTION_COUNT = max(
        5,
        min(200, int(os.environ.get("WORKSPACE_BACKUP_RETENTION_COUNT", "40"))),
    )
except ValueError:
    WORKSPACE_BACKUP_RETENTION_COUNT = 40
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


def set_workspace_recovery_state(value: str) -> None:
    global WORKSPACE_RECOVERY_STATE
    if value not in {"idle", "operation", "awaiting_read"}:
        raise ValueError("Etat de recuperation workspace invalide.")
    with WORKSPACE_RECOVERY_LOCK:
        WORKSPACE_RECOVERY_STATE = value


def begin_workspace_recovery() -> str:
    """Rotate the read epoch only after every in-flight workspace write has completed."""
    global WORKSPACE_READ_EPOCH, WORKSPACE_RECOVERY_STATE
    with WORKSPACE_WRITE_LOCK:
        with WORKSPACE_RECOVERY_LOCK:
            WORKSPACE_READ_EPOCH = secrets.token_urlsafe(24)
            WORKSPACE_RECOVERY_STATE = "operation"
            return WORKSPACE_READ_EPOCH


def begin_supabase_recovery_if_paused() -> str | None:
    """Atomically start a resume only after this process observed a real pause."""
    global WORKSPACE_READ_EPOCH, WORKSPACE_RECOVERY_STATE
    with WORKSPACE_WRITE_LOCK:
        with WORKSPACE_RECOVERY_LOCK:
            if not SUPABASE_PAUSE_CONFIRMED:
                return None
            WORKSPACE_READ_EPOCH = secrets.token_urlsafe(24)
            WORKSPACE_RECOVERY_STATE = "operation"
            return WORKSPACE_READ_EPOCH


def require_fresh_reads_after_paused_storage() -> str:
    """Rotate once when a paused project is observed, then wait for a successful read."""
    global SUPABASE_PAUSE_CONFIRMED, WORKSPACE_READ_EPOCH, WORKSPACE_RECOVERY_STATE
    with WORKSPACE_WRITE_LOCK:
        with WORKSPACE_RECOVERY_LOCK:
            SUPABASE_PAUSE_CONFIRMED = True
            if WORKSPACE_RECOVERY_STATE == "idle":
                WORKSPACE_READ_EPOCH = secrets.token_urlsafe(24)
                WORKSPACE_RECOVERY_STATE = "awaiting_read"
            return WORKSPACE_READ_EPOCH


def supabase_pause_is_confirmed() -> bool:
    with WORKSPACE_RECOVERY_LOCK:
        return SUPABASE_PAUSE_CONFIRMED


def is_workspace_recovery_pending() -> bool:
    with WORKSPACE_RECOVERY_LOCK:
        return WORKSPACE_RECOVERY_STATE != "idle"


def complete_workspace_recovery_after_read() -> str | None:
    global SUPABASE_PAUSE_CONFIRMED, WORKSPACE_RECOVERY_STATE
    with WORKSPACE_RECOVERY_LOCK:
        if WORKSPACE_RECOVERY_STATE == "operation":
            return None
        WORKSPACE_RECOVERY_STATE = "idle"
        SUPABASE_PAUSE_CONFIRMED = False
        return WORKSPACE_READ_EPOCH


def invalidate_session_workspace_read() -> None:
    session["workspace_read_verified"] = False
    session.pop("workspace_read_epoch", None)


def mark_session_workspace_read(epoch: str) -> None:
    session["workspace_read_verified"] = True
    session["workspace_read_epoch"] = epoch


def workspace_read_epoch_is_current(read_epoch: Any) -> bool:
    supplied_epoch = clean_cell(read_epoch)
    if not supplied_epoch:
        return False
    with WORKSPACE_RECOVERY_LOCK:
        return bool(
            WORKSPACE_RECOVERY_STATE == "idle"
            and secrets.compare_digest(supplied_epoch, WORKSPACE_READ_EPOCH)
        )


def session_workspace_read_is_current() -> bool:
    return bool(
        session.get("workspace_read_verified") is True
        and workspace_read_epoch_is_current(session.get("workspace_read_epoch"))
    )


def get_csrf_token() -> str:
    token = session.get("csrf_token", "")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def csrf_token_is_valid() -> bool:
    expected = session.get("csrf_token", "")
    supplied = request.headers.get("X-CSRF-Token", "").strip()
    if not supplied and request.is_json:
        payload = request.get_json(silent=True) or {}
        if isinstance(payload, dict):
            supplied = clean_cell(payload.get("csrfToken", ""))
    if not supplied:
        supplied = clean_cell(request.form.get("csrf_token", ""))
    return bool(expected and supplied and secrets.compare_digest(expected, supplied))


def require_csrf(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if not csrf_token_is_valid():
            return jsonify({"error": "csrf_failed"}), 403
        return view(*args, **kwargs)

    return wrapped


app.jinja_env.globals["csrf_token"] = get_csrf_token


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
                    conn.execute(
                        """
                        CREATE TABLE IF NOT EXISTS workspace_backups (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            workspace_id INTEGER NOT NULL,
                            payload TEXT NOT NULL,
                            source_revision TEXT NOT NULL,
                            created_at TEXT NOT NULL,
                            reason TEXT NOT NULL,
                            row_count INTEGER NOT NULL,
                            column_count INTEGER NOT NULL
                        )
                        """
                    )
                    conn.execute(
                        "CREATE INDEX IF NOT EXISTS idx_workspace_backups_created_at "
                        "ON workspace_backups(workspace_id, created_at DESC)"
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
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS workspace_backups (
                        id BIGSERIAL PRIMARY KEY,
                        workspace_id SMALLINT NOT NULL,
                        payload JSONB NOT NULL,
                        source_revision TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        reason TEXT NOT NULL,
                        row_count INTEGER NOT NULL,
                        column_count INTEGER NOT NULL
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_workspace_backups_created_at
                    ON workspace_backups(workspace_id, created_at DESC)
                    """
                )
                cur.execute("ALTER TABLE workspace_backups ENABLE ROW LEVEL SECURITY")
                cur.execute(
                    """
                    DO $$
                    BEGIN
                        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
                            EXECUTE 'REVOKE ALL ON TABLE workspace_backups FROM anon';
                        END IF;
                        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
                            EXECUTE 'REVOKE ALL ON TABLE workspace_backups FROM authenticated';
                        END IF;
                        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
                            EXECUTE 'GRANT SELECT, INSERT, DELETE ON TABLE workspace_backups TO service_role';
                            EXECUTE 'GRANT USAGE, SELECT ON SEQUENCE workspace_backups_id_seq TO service_role';
                        END IF;
                    END
                    $$
                    """
                )


class SupabaseProjectPaused(RuntimeError):
    pass


def supabase_error_indicates_paused(http_status: int, detail: str) -> bool:
    if http_status == 540:
        return True
    try:
        parsed = json.loads(detail)
    except (TypeError, json.JSONDecodeError):
        parsed = {}
    if isinstance(parsed, dict):
        error_code = parsed.get("code") or parsed.get("status")
        if str(error_code) == "540":
            return True
    normalized = normalize_text(detail)
    return "project paused" in normalized or "project is paused" in normalized


def is_supabase_paused_error(error: Exception) -> bool:
    current: BaseException | None = error
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        if isinstance(current, SupabaseProjectPaused):
            return True
        if supabase_error_indicates_paused(0, str(current)):
            return True
        current = current.__cause__ or current.__context__
    return False


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
        if supabase_error_indicates_paused(error.code, detail):
            raise SupabaseProjectPaused("Le projet Supabase est en pause.") from error
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


def workspace_backup_counts(workspace: dict[str, Any]) -> tuple[int, int]:
    return len(workspace.get("rows", [])), len(workspace.get("columns", []))


def create_workspace_backup_sqlite(record: dict[str, Any], reason: str) -> dict[str, Any]:
    ensure_sqlite_database()
    workspace = record["workspace"]
    row_count, column_count = workspace_backup_counts(workspace)
    created_at = datetime.now(timezone.utc).isoformat()
    payload = json.dumps(workspace, ensure_ascii=False, separators=(",", ":"))
    with DB_LOCK:
        with sqlite3.connect(DB_ACTIVE_PATH) as conn:
            cursor = conn.execute(
                """
                INSERT INTO workspace_backups (
                    workspace_id, payload, source_revision, created_at, reason, row_count, column_count
                ) VALUES (1, ?, ?, ?, ?, ?, ?)
                """,
                (payload, record["revision"], created_at, reason, row_count, column_count),
            )
            backup_id = cursor.lastrowid
            conn.commit()
    return {
        "id": backup_id,
        "workspace_id": 1,
        "source_revision": record["revision"],
        "created_at": created_at,
        "reason": reason,
        "row_count": row_count,
        "column_count": column_count,
    }


def create_workspace_backup_postgres(record: dict[str, Any], reason: str) -> dict[str, Any]:
    ensure_postgres_database()
    workspace = record["workspace"]
    row_count, column_count = workspace_backup_counts(workspace)
    payload = json.dumps(workspace, ensure_ascii=False, separators=(",", ":"))
    with DB_LOCK:
        with psycopg.connect(SUPABASE_DB_URL) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO workspace_backups (
                        workspace_id, payload, source_revision, reason, row_count, column_count
                    ) VALUES (1, %s::jsonb, %s, %s, %s, %s)
                    RETURNING id, created_at
                    """,
                    (payload, record["revision"], reason, row_count, column_count),
                )
                row = cur.fetchone()
            conn.commit()
    if not row:
        raise RuntimeError("La creation du backup PostgreSQL n'a retourne aucun identifiant.")
    return {
        "id": row[0],
        "workspace_id": 1,
        "source_revision": record["revision"],
        "created_at": normalize_workspace_revision(row[1]),
        "reason": reason,
        "row_count": row_count,
        "column_count": column_count,
    }


def create_workspace_backup_supabase_rest(record: dict[str, Any], reason: str) -> dict[str, Any]:
    workspace = record["workspace"]
    row_count, column_count = workspace_backup_counts(workspace)
    created_at = datetime.now(timezone.utc).isoformat()
    rows = supabase_rest_request(
        "POST",
        "workspace_backups?select=id,created_at",
        payload=[
            {
                "workspace_id": 1,
                "payload": workspace,
                "source_revision": record["revision"],
                "created_at": created_at,
                "reason": reason,
                "row_count": row_count,
                "column_count": column_count,
            }
        ],
        prefer="return=representation",
    )
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
        raise RuntimeError("La creation du backup Supabase REST n'a retourne aucun identifiant.")
    return {
        "id": rows[0].get("id"),
        "workspace_id": 1,
        "source_revision": record["revision"],
        "created_at": clean_cell(rows[0].get("created_at")) or created_at,
        "reason": reason,
        "row_count": row_count,
        "column_count": column_count,
    }


def create_workspace_backup(record: dict[str, Any], reason: str) -> dict[str, Any]:
    if DB_BACKEND == "postgres":
        try:
            return create_workspace_backup_postgres(record, reason)
        except Exception as error:
            if not HAS_SUPABASE_REST:
                raise
            app.logger.warning("Workspace backup Postgres failed, fallback REST: %s", error)
            return create_workspace_backup_supabase_rest(record, reason)
    if DB_BACKEND == "supabase_rest":
        return create_workspace_backup_supabase_rest(record, reason)
    return create_workspace_backup_sqlite(record, reason)


def list_workspace_backups_sqlite(limit: int) -> list[dict[str, Any]]:
    ensure_sqlite_database()
    with DB_LOCK:
        with sqlite3.connect(DB_ACTIVE_PATH) as conn:
            rows = conn.execute(
                """
                SELECT id, workspace_id, source_revision, created_at, reason, row_count, column_count
                FROM workspace_backups
                WHERE workspace_id = 1
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
    return [
        {
            "id": row[0],
            "workspace_id": row[1],
            "source_revision": row[2],
            "created_at": row[3],
            "reason": row[4],
            "row_count": row[5],
            "column_count": row[6],
        }
        for row in rows
    ]


def list_workspace_backups_postgres(limit: int) -> list[dict[str, Any]]:
    ensure_postgres_database()
    with DB_LOCK:
        with psycopg.connect(SUPABASE_DB_URL) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, workspace_id, source_revision, created_at, reason, row_count, column_count
                    FROM workspace_backups
                    WHERE workspace_id = 1
                    ORDER BY created_at DESC, id DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                rows = cur.fetchall()
    return [
        {
            "id": row[0],
            "workspace_id": row[1],
            "source_revision": row[2],
            "created_at": normalize_workspace_revision(row[3]),
            "reason": row[4],
            "row_count": row[5],
            "column_count": row[6],
        }
        for row in rows
    ]


def list_workspace_backups_supabase_rest(limit: int) -> list[dict[str, Any]]:
    rows = supabase_rest_request(
        "GET",
        "workspace_backups?select=id,workspace_id,source_revision,created_at,reason,row_count,column_count"
        f"&workspace_id=eq.1&order=created_at.desc,id.desc&limit={limit}",
    )
    if rows is None:
        return []
    if not isinstance(rows, list):
        raise RuntimeError("Reponse de listing backups Supabase invalide.")
    return [row for row in rows if isinstance(row, dict)]


def list_workspace_backups(limit: int = 50) -> list[dict[str, Any]]:
    safe_limit = max(1, min(100, int(limit)))
    if DB_BACKEND == "postgres":
        try:
            return list_workspace_backups_postgres(safe_limit)
        except Exception as error:
            if not HAS_SUPABASE_REST:
                raise
            app.logger.warning("Workspace backup list Postgres failed, fallback REST: %s", error)
            return list_workspace_backups_supabase_rest(safe_limit)
    if DB_BACKEND == "supabase_rest":
        return list_workspace_backups_supabase_rest(safe_limit)
    return list_workspace_backups_sqlite(safe_limit)


def load_workspace_backup_sqlite(backup_id: int) -> dict[str, Any] | None:
    ensure_sqlite_database()
    with DB_LOCK:
        with sqlite3.connect(DB_ACTIVE_PATH) as conn:
            row = conn.execute(
                "SELECT payload, source_revision, created_at, reason FROM workspace_backups WHERE id = ? AND workspace_id = 1",
                (backup_id,),
            ).fetchone()
    if not row:
        return None
    return {
        "workspace": build_workspace_record(row[0], row[1])["workspace"],
        "source_revision": row[1],
        "created_at": row[2],
        "reason": row[3],
    }


def load_workspace_backup_postgres(backup_id: int) -> dict[str, Any] | None:
    ensure_postgres_database()
    with DB_LOCK:
        with psycopg.connect(SUPABASE_DB_URL) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT payload, source_revision, created_at, reason FROM workspace_backups WHERE id = %s AND workspace_id = 1",
                    (backup_id,),
                )
                row = cur.fetchone()
    if not row:
        return None
    return {
        "workspace": build_workspace_record(row[0], row[1])["workspace"],
        "source_revision": row[1],
        "created_at": normalize_workspace_revision(row[2]),
        "reason": row[3],
    }


def load_workspace_backup_supabase_rest(backup_id: int) -> dict[str, Any] | None:
    rows = supabase_rest_request(
        "GET",
        "workspace_backups?select=payload,source_revision,created_at,reason"
        f"&id=eq.{backup_id}&workspace_id=eq.1&limit=1",
    )
    if not isinstance(rows, list) or not rows:
        return None
    row = rows[0] if isinstance(rows[0], dict) else {}
    return {
        "workspace": build_workspace_record(row.get("payload"), row.get("source_revision"))["workspace"],
        "source_revision": clean_cell(row.get("source_revision")),
        "created_at": clean_cell(row.get("created_at")),
        "reason": clean_cell(row.get("reason")),
    }


def load_workspace_backup(backup_id: int) -> dict[str, Any] | None:
    if DB_BACKEND == "postgres":
        try:
            return load_workspace_backup_postgres(backup_id)
        except Exception as error:
            if not HAS_SUPABASE_REST:
                raise
            app.logger.warning("Workspace backup load Postgres failed, fallback REST: %s", error)
            return load_workspace_backup_supabase_rest(backup_id)
    if DB_BACKEND == "supabase_rest":
        return load_workspace_backup_supabase_rest(backup_id)
    return load_workspace_backup_sqlite(backup_id)


def prune_workspace_backups_sqlite(keep_count: int) -> None:
    ensure_sqlite_database()
    with DB_LOCK:
        with sqlite3.connect(DB_ACTIVE_PATH) as conn:
            conn.execute(
                """
                DELETE FROM workspace_backups
                WHERE workspace_id = 1 AND id NOT IN (
                    SELECT id FROM workspace_backups
                    WHERE workspace_id = 1
                    ORDER BY created_at DESC, id DESC
                    LIMIT ?
                )
                """,
                (keep_count,),
            )
            conn.commit()


def prune_workspace_backups_postgres(keep_count: int) -> None:
    ensure_postgres_database()
    with DB_LOCK:
        with psycopg.connect(SUPABASE_DB_URL) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM workspace_backups
                    WHERE workspace_id = 1 AND id NOT IN (
                        SELECT id FROM workspace_backups
                        WHERE workspace_id = 1
                        ORDER BY created_at DESC, id DESC
                        LIMIT %s
                    )
                    """,
                    (keep_count,),
                )
            conn.commit()


def prune_workspace_backups_supabase_rest(keep_count: int) -> None:
    previous_batch: tuple[str, ...] = ()
    while True:
        rows = supabase_rest_request(
            "GET",
            "workspace_backups?select=id&workspace_id=eq.1"
            f"&order=created_at.desc,id.desc&offset={keep_count}&limit=200",
        )
        stale_ids = [
            str(row.get("id")) for row in rows or [] if isinstance(row, dict) and row.get("id") is not None
        ]
        if not stale_ids:
            return
        current_batch = tuple(stale_ids)
        if current_batch == previous_batch:
            raise RuntimeError("La retention Supabase n'a pas pu supprimer les anciens backups.")
        previous_batch = current_batch
        supabase_rest_request("DELETE", f"workspace_backups?id=in.({','.join(stale_ids)})")


def prune_workspace_backups(keep_count: int | None = None) -> None:
    if keep_count is None:
        keep_count = WORKSPACE_BACKUP_RETENTION_COUNT
    if DB_BACKEND == "postgres":
        try:
            prune_workspace_backups_postgres(keep_count)
            return
        except Exception as error:
            if not HAS_SUPABASE_REST:
                raise
            app.logger.warning("Workspace backup prune Postgres failed, fallback REST: %s", error)
            prune_workspace_backups_supabase_rest(keep_count)
            return
    if DB_BACKEND == "supabase_rest":
        prune_workspace_backups_supabase_rest(keep_count)
        return
    prune_workspace_backups_sqlite(keep_count)


def parse_utc_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def backup_reason_for_save(current_record: dict[str, Any], workspace: dict[str, Any]) -> str:
    current_rows = len(current_record["workspace"].get("rows", []))
    next_rows = len(workspace.get("rows", []))
    if current_rows > 0 and next_rows == 0:
        return "before_empty_transition"
    if current_rows > next_rows:
        return "before_row_deletion"

    backups = list_workspace_backups(limit=1)
    latest_at = parse_utc_datetime(clean_cell(backups[0].get("created_at"))) if backups else None
    if latest_at is None:
        return "periodic"
    age_seconds = (datetime.now(timezone.utc) - latest_at).total_seconds()
    return "periodic" if age_seconds >= WORKSPACE_BACKUP_INTERVAL_SECONDS else ""


def create_backup_and_prune(record: dict[str, Any], reason: str) -> dict[str, Any]:
    backup = create_workspace_backup(record, reason)
    try:
        prune_workspace_backups()
    except Exception as error:
        app.logger.warning("Workspace backup retention cleanup failed: %s", error)
    return backup


class WorkspaceWriteConflict(RuntimeError):
    pass


class WorkspaceFreshReadRequired(RuntimeError):
    pass


class UnsafeEmptyWorkspaceTransition(RuntimeError):
    pass


def save_workspace_state_conditionally(
    workspace: dict[str, Any],
    *,
    expected_exists: bool,
    base_revision: str,
    empty_rows_intent: str,
    read_epoch: str,
) -> str:
    """Reject stale writes and accidental transitions to an empty workspace."""
    with WORKSPACE_WRITE_LOCK:
        if not workspace_read_epoch_is_current(read_epoch):
            raise WorkspaceFreshReadRequired("Une nouvelle lecture du workspace est requise.")

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

        if current_record and workspace == current_record["workspace"]:
            return current_record["revision"]

        if current_record:
            backup_reason = backup_reason_for_save(current_record, workspace)
            if backup_reason:
                create_backup_and_prune(current_record, backup_reason)

        return save_workspace_state(workspace)


def restore_workspace_backup(backup_id: int) -> dict[str, Any] | None:
    begin_workspace_recovery()
    try:
        with WORKSPACE_WRITE_LOCK:
            backup = load_workspace_backup(backup_id)
            if backup is None:
                return None

            current_record = load_workspace_record()
            if current_record is None:
                raise RuntimeError("Aucun workspace courant a sauvegarder avant restauration.")

            create_backup_and_prune(current_record, "before_restore")
            revision = save_workspace_state(backup["workspace"])
            row_count, column_count = workspace_backup_counts(backup["workspace"])
            return {
                "revision": revision,
                "row_count": row_count,
                "column_count": column_count,
            }
    finally:
        set_workspace_recovery_state("awaiting_read")


def probe_workspace_storage_sqlite() -> None:
    with DB_LOCK:
        with sqlite3.connect(DB_ACTIVE_PATH) as conn:
            conn.execute("SELECT id, updated_at FROM workspace_state WHERE id = 1").fetchone()


def probe_workspace_storage_postgres() -> None:
    with DB_LOCK:
        with psycopg.connect(SUPABASE_DB_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id, updated_at FROM workspace_state WHERE id = 1")
                cur.fetchone()


def probe_workspace_storage_supabase_rest() -> None:
    supabase_rest_request("GET", "workspace_state?select=id,updated_at&id=eq.1&limit=1")


def probe_workspace_storage() -> None:
    if DB_BACKEND == "postgres":
        try:
            probe_workspace_storage_postgres()
            return
        except Exception as error:
            if not HAS_SUPABASE_REST:
                raise
            app.logger.warning("Workspace probe Postgres failed, fallback REST: %s", error)
            probe_workspace_storage_supabase_rest()
            return
    if DB_BACKEND == "supabase_rest":
        probe_workspace_storage_supabase_rest()
        return
    probe_workspace_storage_sqlite()


class SupabaseManagementError(RuntimeError):
    def __init__(self, code: str, message: str, http_status: int = 502):
        super().__init__(message)
        self.code = code
        self.http_status = http_status


def request_supabase_project_restore() -> None:
    """Request restoration of the configured project without exposing credentials."""
    if not SUPABASE_MANAGEMENT_TOKEN or not SUPABASE_PROJECT_REF:
        raise SupabaseManagementError(
            "supabase_management_not_configured",
            "La reprise Supabase n'est pas configuree sur le serveur.",
            503,
        )

    safe_ref = urllib.parse.quote(SUPABASE_PROJECT_REF, safe="")
    management_url = f"https://api.supabase.com/v1/projects/{safe_ref}/restore"
    request_obj = urllib.request.Request(
        url=management_url,
        data=b"{}",
        headers={
            "Authorization": f"Bearer {SUPABASE_MANAGEMENT_TOKEN}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request_obj, timeout=15) as response:
            response.read()
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        normalized = normalize_text(body)
        if error.code in {400, 409} and ("already" in normalized or "active" in normalized):
            raise SupabaseManagementError(
                "supabase_project_already_active",
                "Le projet Supabase semble deja actif.",
                409,
            ) from error
        if error.code in {401, 403}:
            raise SupabaseManagementError(
                "supabase_restore_refused",
                "La Management API Supabase a refuse l'autorisation du serveur.",
                502,
            ) from error
        if error.code == 429:
            raise SupabaseManagementError(
                "supabase_management_rate_limited",
                "La Management API Supabase est temporairement limitee.",
                503,
            ) from error
        raise SupabaseManagementError(
            "supabase_restore_refused",
            f"La Management API Supabase a refuse la reprise (HTTP {error.code}).",
            502,
        ) from error
    except (urllib.error.URLError, TimeoutError) as error:
        raise SupabaseManagementError(
            "supabase_management_unavailable",
            "La Management API Supabase est inaccessible.",
            503,
        ) from error


@app.get("/")
def index():
    return render_template("index.html", csrf_token=get_csrf_token())


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
@require_csrf
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
@require_csrf
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
@require_csrf
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
        invalidate_session_workspace_read()
        app.logger.exception("Workspace load failed: %s", error)
        paused = is_supabase_paused_error(error)
        if paused:
            require_fresh_reads_after_paused_storage()
        error_code = "supabase_paused" if paused else "workspace_storage_unavailable"
        return (
            jsonify(
                {
                    "workspace": None,
                    "exists": False,
                    "error": error_code,
                    "csrf_token": get_csrf_token(),
                    "storage_backend": get_storage_backend(),
                    "preferred_storage_backend": DB_BACKEND,
                    "hint": "Verifie la configuration Supabase et la connectivite serveur.",
                }
            ),
            503,
        )

    read_epoch = complete_workspace_recovery_after_read()
    if read_epoch is None:
        invalidate_session_workspace_read()
        return (
            jsonify(
                {
                    "error": "workspace_recovery_in_progress",
                    "workspace": None,
                    "exists": False,
                    "csrf_token": get_csrf_token(),
                }
            ),
            503,
        )
    mark_session_workspace_read(read_epoch)

    if record is None:
        return jsonify(
            {
                "workspace": None,
                "exists": False,
                "csrf_token": get_csrf_token(),
                "storage_backend": get_storage_backend(),
                "preferred_storage_backend": DB_BACKEND,
            }
        )

    response = {
        "workspace": record["workspace"],
        "exists": True,
        "revision": record["revision"],
        "csrf_token": get_csrf_token(),
        "storage_backend": get_storage_backend(),
        "preferred_storage_backend": DB_BACKEND,
    }
    if get_storage_backend() == "sqlite":
        response["db_path"] = DB_ACTIVE_PATH
    return jsonify(response)


@app.post("/api/workspace")
@require_csrf
def api_workspace_post():
    if is_workspace_recovery_pending() or not session_workspace_read_is_current():
        return (
            jsonify(
                {
                    "error": "workspace_fresh_read_required",
                    "message": "Recharge le workspace distant avant toute sauvegarde.",
                }
            ),
            428,
        )

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
    session_read_epoch = clean_cell(session.get("workspace_read_epoch", ""))

    try:
        updated_at = save_workspace_state_conditionally(
            workspace,
            expected_exists=expected_exists,
            base_revision=base_revision,
            empty_rows_intent=empty_rows_intent,
            read_epoch=session_read_epoch,
        )
    except WorkspaceFreshReadRequired:
        invalidate_session_workspace_read()
        return (
            jsonify(
                {
                    "error": "workspace_fresh_read_required",
                    "message": "Recharge le workspace distant avant toute sauvegarde.",
                }
            ),
            428,
        )
    except WorkspaceWriteConflict as error:
        invalidate_session_workspace_read()
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
        invalidate_session_workspace_read()
        app.logger.exception("Workspace save failed: %s", error)
        paused = is_supabase_paused_error(error)
        if paused:
            require_fresh_reads_after_paused_storage()
        error_code = "supabase_paused" if paused else "workspace_storage_unavailable"
        return (
            jsonify(
                {
                    "error": error_code,
                    "message": "Sauvegarde indisponible (BDD inaccessible). Verifie la config Supabase.",
                    "storage_backend": get_storage_backend(),
                    "preferred_storage_backend": DB_BACKEND,
                }
            ),
            503,
        )

    mark_session_workspace_read(session_read_epoch)
    return jsonify({"status": "saved", "updated_at": updated_at, "revision": updated_at})


@app.get("/api/system/keepalive")
def api_system_keepalive():
    if not KEEPALIVE_TOKEN:
        return jsonify({"error": "keepalive_not_configured"}), 503

    authorization = request.headers.get("Authorization", "")
    scheme, _, supplied_token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not supplied_token or not secrets.compare_digest(supplied_token, KEEPALIVE_TOKEN):
        return jsonify({"error": "keepalive_unauthorized"}), 401

    if DB_BACKEND == "sqlite" and not app.config.get("TESTING"):
        return jsonify({"error": "supabase_not_configured"}), 503

    try:
        probe_workspace_storage()
    except Exception as error:
        app.logger.warning("Keepalive database probe failed: %s", error)
        paused = is_supabase_paused_error(error)
        if paused:
            require_fresh_reads_after_paused_storage()
        error_code = "supabase_paused" if paused else "workspace_storage_unavailable"
        return jsonify({"status": "error", "database": "unavailable", "error": error_code}), 503

    response = jsonify({"status": "ok", "database": "available"})
    response.headers["Cache-Control"] = "no-store"
    return response


@app.post("/api/system/supabase/resume")
@require_csrf
def api_system_supabase_resume():
    if begin_supabase_recovery_if_paused() is None:
        return (
            jsonify(
                {
                    "error": "supabase_pause_not_confirmed",
                    "message": "La reprise est refusee car aucune pause Supabase n'a ete detectee.",
                }
            ),
            409,
        )

    invalidate_session_workspace_read()
    try:
        request_supabase_project_restore()
    except SupabaseManagementError as error:
        set_workspace_recovery_state("awaiting_read")
        if error.code == "supabase_project_already_active":
            return jsonify({"status": "restore_requested", "already_active": True}), 202
        app.logger.warning("Supabase restore request failed: %s", error.code)
        return jsonify({"error": error.code, "message": str(error)}), error.http_status

    set_workspace_recovery_state("awaiting_read")
    app.logger.warning("Supabase restore requested after confirmed paused state")
    return jsonify({"status": "restore_requested"}), 202


@app.get("/api/health")
def api_health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    try:
        ensure_database()
    except Exception as error:
        app.logger.warning("Database initialization warning: %s", error)
    app.run(host="0.0.0.0", port=5000, debug=True)
