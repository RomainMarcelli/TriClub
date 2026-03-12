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

## API Endpoints

- `POST /api/extract` - upload PDF and get detected table + preview + mapping hints
- `POST /api/export` - export CSV from workspace payload
- `POST /api/share` - generate signed share link for read-only page
- `GET /shared/<token>` - read-only shared dataset view
- `GET /api/health` - health check
