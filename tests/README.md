# Tests

## Tests JavaScript (frontend)

Lancent avec le test runner natif de Node.js (aucune dépendance externe).
Pré-requis : **Node.js 18+**.

```powershell
npm test
# ou directement
node --test
```

Couvre notamment :
- `tests/js/schema.test.mjs` — 10 tests sur le schéma cible et la table de migration.
- `tests/js/store.test.mjs` — tests du `WorkspaceStore` (migration douce, addRow, suppressions, filtres, tris, etc.).
- `tests/js/pdf.test.mjs` — 7 tests sur le mapping d'import PDF vers le schéma de prospection.
- `tests/js/workspace-persistence.test.mjs` — garde-fous de chargement, autosave, beacon et suppression de la dernière ligne.

## Tests Python (backend)

Pré-requis :

```powershell
pip install -r requirements-dev.txt
```

Lancer :

```powershell
python -m pytest tests/ -v
```

Couvre :
- `tests/test_sanitization.py` — fonctions de nettoyage (`clean_cell`, `normalize_text`, `sanitize_columns`, `sanitize_rows`, `sanitize_filters`, `sanitize_workspace_state`).
- `tests/test_api.py` — endpoints HTTP, panne de stockage, révisions optimistes et protection contre les écrasements vides.

Les tests Python utilisent une base SQLite isolée par test (via `tmp_path`).
