# Ben Workspace - PDF to Smart Table

Modern SaaS-style web app to extract structured data from PDF and manage it like an Airtable-style workspace.

## What It Does

- Import a PDF (drag & drop or file picker)
- Detect table headers and preview rows before import
- Confirm mapping for:
  - `Nom club`
  - `Ligue`
  - `CD`
- Import into an interactive smart table
- Edit cells inline
- Add / rename / delete / reorder / resize columns
- Set column types:
  - Text, Number, Tag, Dropdown, Checkbox, Date
- Create stackable filters with operators:
  - equals, contains, starts with, is empty, is not empty
- Global search across all columns
- Save and reuse views (filters + sort + hidden columns)
- Export:
  - full table
  - filtered view
  - choose number of rows to export
  - CSV standard
  - CSV compatible with Apple Numbers
- Share a read-only view via public link

## Tech Stack

- Python + Flask (backend API + SSR entry pages)
- Vanilla JavaScript modules (workspace state, table engine, import workflow)
- Virtualized table rendering for performance

## Run Locally

```bash
cd /home/romain/Data/projetperso/Ben
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open:

```bash
http://127.0.0.1:5000
```

## Deploy on Vercel

This app is already prepared for Vercel serverless deploy.

Files used:

- `vercel.json`
- `api/index.py`

Commands:

```bash
npm i -g vercel
vercel
vercel --prod
```

## Render (Recommended)

Use this start command to avoid worker timeout on long PDF extraction:

```bash
gunicorn app:app --timeout 180 --workers 1 --threads 2
```

Set these environment variables on Render:

- `APP_SECRET_KEY` (long random value; required for stable anonymous CSRF/read-epoch sessions)
- `SUPABASE_DB_URL` (optional if direct Postgres access works)
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `KEEPALIVE_TOKEN` (long random Bearer token, dedicated to the keepalive route)
- `SUPABASE_PROJECT_REF` (project targeted by the paused-project resume button)
- `SUPABASE_MANAGEMENT_TOKEN` (server-only token allowed to restore that project)

Optional backup settings:

- `WORKSPACE_BACKUP_INTERVAL_SECONDS` (default `900`, minimum `60`)
- `WORKSPACE_BACKUP_RETENTION_COUNT` (default `40`, bounded from `5` to `200`)

`SUPABASE_SERVICE_ROLE_KEY` and `SUPABASE_MANAGEMENT_TOKEN` are separate
credentials. Both must stay in Render's server-side environment and must never
be put in HTML, JavaScript, GitHub variables, logs, or browser storage. The
browser only calls a fixed Flask resume endpoint; it never receives either
credential or chooses a project reference.

Storage behavior:

- preferred: direct Postgres (`SUPABASE_DB_URL`)
- automatic fallback: Supabase REST (`SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY`)

Before deploying this version, apply the versioned migration through the
Supabase SQL editor or migration workflow:

```bash
supabase/migrations/20260901_workspace_backups.sql
```

It creates `workspace_backups`, enables RLS, removes access from `anon` and
`authenticated`, and grants the server-side `service_role` only the operations
needed by the application. The application does not modify any pre-existing
backup system or `/backups` directory.

After deployment, check `GET /api/workspace`. Expected when storage is healthy:

- `"exists": true` or `"exists": false` (if no data yet)
- HTTP 200 and no `"error": "workspace_storage_unavailable"`

When storage is unavailable, `GET /api/workspace` returns HTTP 503. Workspace
writes require the revision returned by a successful GET, so a failed read
cannot be converted into a new empty workspace.

## Public Access and CSRF

TriClub is public and has no account, login page, user password, or admin role.
The main page and workspace, extraction, export, and sharing APIs are usable
without authentication.

Every mutating browser route still requires an anonymous-session CSRF token.
The token is rendered on `/` and is also returned by `GET /api/workspace`, so a
direct API client can establish its anonymous session before writing. JSON
requests use `X-CSRF-Token`; the unload beacon sends the same token as the
top-level `csrfToken` field. Sessions use `HttpOnly`, `SameSite=Lax` cookies;
Render production cookies are also `Secure`.

CSRF is a cross-site browser protection, not authorization: because the
application is intentionally public, anyone can deliberately load it and use
its normal workspace features. The fixed Supabase resume endpoint also requires
CSRF and refuses requests unless this server process has first confirmed a real
paused-project response.

## Versioned Workspace Backups

Before an existing workspace is changed, the server creates snapshots:

- periodically, at most once per configured interval;
- immediately before an explicit transition from non-empty to empty;
- immediately before any row deletion;
- immediately before an internal restore operation.

There is no public HTTP route or browser panel for listing, creating, or
restoring backups. Automatic backup creation remains part of the server-side
safe write path. An internal restore first backs up the current workspace,
writes the selected snapshot, and generates a new revision. Any browser still
holding the prior read epoch must reload before it can write again; optimistic
revision locking remains active as a second guard.

Retention is applied after every snapshot. Backup creation is part of the safe
write path: if a required snapshot cannot be created, the workspace mutation is
not performed.

## Supabase Keepalive

`GET /api/system/keepalive` requires:

```text
Authorization: Bearer <KEEPALIVE_TOKEN>
```

The route performs a real lightweight read of `workspace_state`; it does not
write, create an empty workspace, make a backup, or expose database credentials.
It fails closed if the token or Supabase production configuration is missing.

The workflow `.github/workflows/supabase-keepalive.yml` runs daily. Configure:

- GitHub Actions variable `TRICLUB_APP_URL`, for example `https://example.onrender.com`;
- GitHub Actions secret `TRICLUB_KEEPALIVE_TOKEN`, identical to Render's
  `KEEPALIVE_TOKEN`.

Do not put a Supabase key in GitHub for this workflow. Run `workflow_dispatch`
once after configuration and verify a successful response.

## Paused Supabase Recovery

Storage errors and a paused Supabase project have distinct API/UI states. While
the project is paused, local controls, autosave, scheduled saves, and
`sendBeacon` are blocked. Only after the backend identifies a real paused state,
the header displays **Réactiver Supabase**. The button calls the fixed
server-side resume route; the Management API token stays on the server.

During resume, the button is disabled with a spinner and all workspace writes
remain blocked. The browser periodically retries `GET /api/workspace`. A
successful full GET hydrates the remote data and records the current read epoch
before autosave is re-enabled and the button is hidden. A failed or timed-out
resume leaves persistence blocked and makes the button available for retry.

When a paused project is detected, and whenever an internal restore starts, the
server rotates an in-memory workspace read epoch. Every anonymous browser
session must then perform its own successful `GET /api/workspace` before it may
write again. The first successful GET never reauthorizes other sessions. This
is safe with the current Render command using one Gunicorn worker. If the
application later uses multiple workers or instances, move the recovery state
and read epoch to shared storage (for example PostgreSQL) before scaling out.

## Safe Production Rollout

1. Take/verify an external Supabase backup according to the existing production procedure.
2. Apply `20260901_workspace_backups.sql` and verify the table/index/RLS grants.
3. Add the Render secrets above, including the server-only Management API credentials.
4. Deploy the application; do not run a standalone restore script.
5. Verify that `/` is public and `GET /api/workspace` returns the expected row count and a revision.
6. Verify automatic backup creation through the normal server-side validation procedure.
7. Configure the GitHub variable/secret and manually run the keepalive workflow.
8. Test internal restore and the resume button only against a non-production project first.

This repository does not automatically alter the production Supabase project,
push Git commits, or invoke a restore during deployment.

## API Endpoints

- `POST /api/extract` - upload PDF and get detected table + preview + mapping hints
- `POST /api/export` - export CSV from workspace payload
- `POST /api/share` - generate signed share link for read-only page
- `GET /api/workspace` - load the workspace and its persistence revision
- `POST /api/workspace` - save with optimistic revision and empty-state safeguards
- `GET /api/system/keepalive` - dedicated Bearer-protected database read
- `POST /api/system/supabase/resume` - CSRF-protected fixed-project resume, enabled only after confirmed pause
- `GET /shared/<token>` - read-only shared dataset view
- `GET /api/health` - health check
