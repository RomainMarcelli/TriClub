#!/usr/bin/env python3
"""
Import du PDF FFR-DS "liste ffr.pdf" dans le workspace Supabase.

A LANCER EN PREMIER, avant l'import du PDF Prospection.

Stratégie : fusion intelligente
- Parse text-based avec la région comme ancre.
- Match des clubs par nom normalisé (sans accents, casse, etc.).
- Club existant : remplit uniquement les cellules vides.
- Club absent : ajoute la ligne avec Région / Département / Code club / Nom du club.
- Ajoute une colonne "Code club" si absente.
- Initialise les 12 colonnes de prospection si le workspace est vide.

Usage
    python scripts/import_ffr_pdf.py "liste ffr.pdf"           # dry-run
    python scripts/import_ffr_pdf.py "liste ffr.pdf" --apply   # écrit en Supabase
"""

from __future__ import annotations

import json
import re
import secrets
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

import pdfplumber  # noqa: E402
from app import (  # noqa: E402
    ensure_database,
    load_workspace_state,
    sanitize_workspace_state,
    save_workspace_state,
)
from import_prospection_pdf import BASE_COLUMNS  # noqa: E402  (réutilise les 12 colonnes)

# === Listes ===

REGIONS = [
    "AUVERGNE-RHÔNE-ALPES",
    "BOURGOGNE-FRANCHE-COMTÉ",
    "BRETAGNE",
    "CENTRE - VAL DE LOIRE",
    "CENTRE-VAL DE LOIRE",
    "CORSE",
    "GRAND EST",
    "GUADELOUPE",
    "GUYANE",
    "HAUTS DE FRANCE",
    "HAUTS-DE-FRANCE",
    "ILE-DE-FRANCE",
    "ÎLE-DE-FRANCE",
    "MARTINIQUE",
    "MAYOTTE",
    "NORMANDIE",
    "NOUVELLE-AQUITAINE",
    "NOUVELLE-CALEDONIE",
    "OCCITANIE",
    "PAYS DE LA LOIRE",
    "POLYNESIE FRANCAISE",
    "PROVENCE-ALPES-CÔTE D'AZUR",
    "REUNION",
    "WALLIS ET FUTUNA",
]
REGIONS_SORTED = sorted(set(REGIONS), key=len, reverse=True)

# Code club FFR : 4 ou 5 chiffres + 1 lettre (ex: 4029E, 6648b, 0001A)
CODE_CLUB_REGEX = re.compile(r"\b(\d{4,5}[A-Za-z])\b")


# === Helpers ===

def normalize(value) -> str:
    if not value:
        return ""
    text = str(value).strip().lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(text.split())


def clean_cell(value) -> str:
    if value is None:
        return ""
    return " ".join(str(value).replace("\n", " ").split())


# === Parsing ===

def parse_line(line: str) -> dict | None:
    line = line.strip()
    if not line:
        return None
    # Lignes de mise en page à ignorer
    if re.match(r"^FFR-DS(\s+\d+)?$", line):
        return None
    if "Liste des clubs inscrits" in line or "Semaine Nationale" in line:
        return None
    if normalize(line).startswith(("ligue cd", "code club", "nom club")):
        return None

    # Trouve une région en préfixe (le plus long d'abord pour éviter les conflits)
    region = None
    for r in REGIONS_SORTED:
        if line.startswith(r):
            region = r
            break
    if not region:
        return None

    rest = line[len(region):].strip()
    if not rest:
        return None

    code_match = CODE_CLUB_REGEX.search(rest)
    if not code_match:
        return None

    dept = rest[: code_match.start()].strip()
    code = code_match.group(1)
    club = rest[code_match.end():].strip()

    if not club:
        return None
    if normalize(club) in ("club", "nom club"):
        return None

    return {
        "Région": region,
        "Département": dept,
        "Code club": code,
        "Nom du club": club,
    }


def parse_pdf(path: str) -> list[dict]:
    records: list[dict] = []
    seen: set[str] = set()
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            for line in text.split("\n"):
                rec = parse_line(line)
                if rec is None:
                    continue
                key = normalize(rec["Nom du club"])
                if key in seen:
                    continue
                seen.add(key)
                records.append(rec)
    return records


# === Merge ===

def ensure_columns(workspace: dict) -> dict[str, str]:
    """Garantit les 12 colonnes de prospection + 'Code club'."""
    existing_by_name = {normalize(c["name"]): c for c in workspace["columns"]}

    for col_def in BASE_COLUMNS:
        key = normalize(col_def["name"])
        if key in existing_by_name:
            continue
        workspace["columns"].append(dict(col_def))
        default_val = col_def.get("defaultValue", "")
        for row in workspace["rows"]:
            row["values"].setdefault(col_def["id"], default_val)

    code_def = {
        "id": "col_code_club",
        "name": "Code club",
        "type": "text",
        "width": 100,
        "hidden": False,
        "defaultValue": "",
        "options": [],
    }
    if normalize(code_def["name"]) not in {normalize(c["name"]) for c in workspace["columns"]}:
        workspace["columns"].append(code_def)
        for row in workspace["rows"]:
            row["values"].setdefault(code_def["id"], "")

    return {normalize(c["name"]): c["id"] for c in workspace["columns"]}


def is_effectively_empty(value: str) -> bool:
    return not value


def merge(workspace: dict, records: list[dict]):
    by_name = ensure_columns(workspace)
    ids = {
        "nom_club": by_name.get("nom du club", "col_nom_club"),
        "region": by_name.get("region", "col_region"),
        "departement": by_name.get("departement", "col_departement"),
        "code_club": by_name.get("code club", "col_code_club"),
    }

    existing_by_name: dict[str, dict] = {}
    for row in workspace["rows"]:
        name = normalize(row["values"].get(ids["nom_club"], ""))
        if name and name not in existing_by_name:
            existing_by_name[name] = row

    stats = {"added": 0, "enriched": 0, "unchanged": 0}
    added: list[str] = []
    enriched: list[str] = []

    for record in records:
        club_name = clean_cell(record.get("Nom du club"))
        if not club_name:
            continue
        key = normalize(club_name)
        new_values = {
            ids["nom_club"]: club_name,
            ids["region"]: clean_cell(record.get("Région")),
            ids["departement"]: clean_cell(record.get("Département")),
            ids["code_club"]: clean_cell(record.get("Code club")),
        }

        if key in existing_by_name:
            row = existing_by_name[key]
            filled_any = False
            for col_id, val in new_values.items():
                if not val:
                    continue
                current = row["values"].get(col_id, "")
                if val == current:
                    continue
                if is_effectively_empty(current):
                    row["values"][col_id] = val
                    filled_any = True
            if filled_any:
                stats["enriched"] += 1
                enriched.append(club_name)
            else:
                stats["unchanged"] += 1
        else:
            new_row = {
                "id": "row_ffr_" + secrets.token_urlsafe(6),
                "values": {col["id"]: col.get("defaultValue", "") for col in workspace["columns"]},
            }
            for col_id, val in new_values.items():
                if val:
                    new_row["values"][col_id] = val
            workspace["rows"].append(new_row)
            stats["added"] += 1
            added.append(club_name)

    return stats, added, enriched


# === Main ===

def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/import_ffr_pdf.py <pdf-path> [--apply]")
        sys.exit(1)

    pdf_path = sys.argv[1]
    apply_changes = "--apply" in sys.argv

    if not Path(pdf_path).exists():
        print(f"❌ PDF introuvable : {pdf_path}")
        sys.exit(1)

    print(f"📄 Parsing {pdf_path}...")
    records = parse_pdf(pdf_path)
    print(f"   → {len(records)} clubs détectés\n")

    if not records:
        print("❌ Aucun club détecté. Format de PDF inattendu.")
        sys.exit(1)

    print("Échantillon des 5 premiers clubs parsés :")
    for r in records[:5]:
        print(f"     • {r['Nom du club']:<45} | {r['Région']:<28} | dept={r['Département']:<6} | code={r['Code club']}")
    print()

    print("☁️  Chargement du workspace depuis Supabase...")
    try:
        ensure_database()
    except Exception as error:
        print(f"❌ Connexion DB échouée : {error}")
        sys.exit(1)

    workspace = load_workspace_state()
    if not workspace:
        workspace = {
            "columns": [], "rows": [], "filters": [], "searchQuery": "",
            "sort": None, "views": [], "activeViewId": "",
            "selectedColumnId": "", "selectedRowId": "",
        }
    if not workspace.get("columns"):
        print("⚠️  Workspace vide : initialisation du schéma de prospection (12 colonnes + Code club).")
        workspace["views"] = [{
            "id": "view_default", "name": "Vue par defaut",
            "filters": [], "sort": None, "hiddenColumnIds": [],
        }]
        workspace["activeViewId"] = "view_default"

    print(f"   → {len(workspace['rows'])} lignes, {len(workspace['columns'])} colonnes (avant)\n")

    print("🔀 Fusion intelligente en cours...")
    stats, added, enriched = merge(workspace, records)

    print("\n📊 Résultat :")
    print(f"   ➕ {stats['added']:>5}  nouveaux clubs ajoutés")
    print(f"   📝 {stats['enriched']:>5}  clubs existants enrichis")
    print(f"   ⏭️  {stats['unchanged']:>5}  clubs déjà complets (rien changé)")
    print(f"   📐 {len(workspace['columns']):>5}  colonnes au total après import")

    if added:
        sample = ", ".join(added[:6])
        suffix = ", ..." if len(added) > 6 else ""
        print(f"\n   Exemples d'ajouts : {sample}{suffix}")

    if not apply_changes:
        print("\n💡 Mode DRY-RUN : rien n'a été sauvegardé.")
        print("   Pour appliquer en Supabase, relance avec --apply :")
        print(f'      python scripts/import_ffr_pdf.py "{pdf_path}" --apply')
        return

    # Backup
    backups_dir = ROOT / "backups"
    backups_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = backups_dir / f"workspace_before_ffr_import_{timestamp}.json"
    print(f"\n💾 Backup local : {backup_file.name}")
    original = load_workspace_state()
    with backup_file.open("w", encoding="utf-8") as f:
        json.dump(original or {"empty": True}, f, ensure_ascii=False, indent=2)
    print(f"   ✅ Backup écrit ({backup_file.stat().st_size // 1024} Ko)")

    print("\n💾 Sauvegarde dans Supabase...")
    sanitized = sanitize_workspace_state(workspace)
    updated_at = save_workspace_state(sanitized)
    print(f"   ✅ Sauvegardé à {updated_at}")
    print("\n🎉 Import FFR terminé.")
    print("   Étape suivante : enrichir avec le PDF Prospection")
    print('      python scripts/import_prospection_pdf.py "Prospection Club exp.pdf" --apply')


if __name__ == "__main__":
    main()
