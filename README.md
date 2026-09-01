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

- `APP_SECRET_KEY` (long random value; required for stable and secure sessions)
- `TRICLUB_USER_PASSWORD` (standard user access)
- `TRICLUB_ADMIN_PASSWORD` (admin access; must be different from the user password)
- `SUPABASE_DB_URL` (optional if direct Postgres access works)
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `KEEPALIVE_TOKEN` (long random Bearer token, dedicated to the keepalive route)
- `SUPABASE_PROJECT_REF` (only needed for admin project resume)
- `SUPABASE_MANAGEMENT_TOKEN` (only needed for admin project resume)

Optional backup settings:

- `WORKSPACE_BACKUP_INTERVAL_SECONDS` (default `900`, minimum `60`)
- `WORKSPACE_BACKUP_RETENTION_COUNT` (default `40`, bounded from `5` to `200`)

`SUPABASE_SERVICE_ROLE_KEY` and `SUPABASE_MANAGEMENT_TOKEN` are different
credentials. Both must stay in Render's server-side environment. They must never
be put in HTML, JavaScript, GitHub variables, logs, or browser storage.

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

After deployment, log in and check `GET /api/workspace`. Expected when storage
is healthy:

- `"exists": true` or `"exists": false` (if no data yet)
- HTTP 200 and no `"error": "workspace_storage_unavailable"`

When storage is unavailable, `GET /api/workspace` returns HTTP 503. Workspace
writes require the revision returned by a successful GET, so a failed read
cannot be converted into a new empty workspace.

## Authentication and CSRF

- `/` redirects anonymous visitors to `/login`.
- The standard password can use the workspace APIs.
- The admin password additionally grants backup and Supabase resume APIs.
- Every mutating route requires the session CSRF token, including the unload
  beacon used by workspace autosave.
- Sessions use `HttpOnly`, `SameSite=Lax` cookies; Render production cookies are
  also `Secure`.
- Configuration fails closed when either password is missing or both passwords
  are identical.

## Versioned Workspace Backups

Before an existing workspace is changed, the server creates snapshots:

- periodically, at most once per configured interval;
- immediately before an explicit transition from non-empty to empty;
- immediately before any row deletion;
- immediately before an admin restore;
- manually from the admin panel.

Admin listing returns metadata only, never the stored JSON payload. Restoring a
snapshot first backs up the current workspace, writes the selected snapshot,
and generates a new revision. Any browser still holding the prior revision then
receives HTTP 409 and must reload.

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
the project is paused or restoring, local controls, autosave, scheduled saves,
and `sendBeacon` are blocked.

The admin-only resume button calls the Supabase Management API from Flask with
`POST /v1/projects/{project_ref}/restore`. The management token requires project
write/admin permission. The browser never receives that token. After requesting
resume, the UI polls with `GET /api/workspace`; persistence is re-enabled only
after a successful full GET and hydration. No stale POST is sent first.

## Safe Production Rollout

1. Take/verify an external Supabase backup according to the existing production procedure.
2. Apply `20260901_workspace_backups.sql` and verify the table/index/RLS grants.
3. Add the Render secrets above, using distinct random values.
4. Deploy the application; do not run a standalone restore script.
5. Test standard and admin login, then verify `GET /api/workspace` returns the expected row count and a revision.
6. Create one manual backup in the admin panel and verify metadata listing.
7. Configure the GitHub variable/secret and manually run the keepalive workflow.
8. Test restore/resume only against a non-production project first.

This repository does not automatically alter the production Supabase project,
push Git commits, or invoke a restore during deployment.

## API Endpoints

- `POST /api/extract` - upload PDF and get detected table + preview + mapping hints
- `POST /api/export` - export CSV from workspace payload
- `POST /api/share` - generate signed share link for read-only page
- `GET /api/workspace` - load the workspace and its persistence revision
- `POST /api/workspace` - save with optimistic revision and empty-state safeguards
- `GET /api/admin/backups` - admin-only backup metadata
- `POST /api/admin/backups` - admin-only manual backup
- `POST /api/admin/backups/<id>/restore` - admin-only confirmed restore
- `POST /api/admin/supabase/resume` - admin-only server-side Supabase resume request
- `GET /api/system/keepalive` - dedicated Bearer-protected database read
- `GET /shared/<token>` - read-only shared dataset view
- `GET /api/health` - health check
