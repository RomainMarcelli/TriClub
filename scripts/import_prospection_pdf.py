#!/usr/bin/env python3
"""
Import du PDF "Prospection Club exp.pdf" dans le workspace Supabase.

STRATEGIE : FUSION INTELLIGENTE
- Parsing : text-based avec les noms de régions comme ancres
  (le table-detection de pdfplumber est trop fragile sur ce PDF).
- Match des clubs par nom normalisé (sans accents, sans casse, espaces nettoyés).
- Club déjà présent : on ne remplit QUE les cellules vides.
- Club absent : on ajoute la ligne avec Statut inféré.
- "à contacter" et "aucune des catégories" sont considérés "effectivement vides".
- Ajoute 7 colonnes si absentes : Licences, Importance relance,
  RDV Posé, Date RDV, RDV Fait, Date devis, Devis signé.

USAGE
    python scripts/import_prospection_pdf.py "Prospection Club exp.pdf"           # dry-run
    python scripts/import_prospection_pdf.py "Prospection Club exp.pdf" --apply   # écrit en Supabase
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

import pdfplumber  # noqa: E402
from app import (  # noqa: E402
    ensure_database,
    load_workspace_state,
    sanitize_workspace_state,
    save_workspace_state,
)

# === Listes / mappings ===

REGIONS = [
    "AUVERGNE-RHÔNE-ALPES",
    "BOURGOGNE-FRANCHE-COMTÉ",
    "BRETAGNE",
    "CENTRE - VAL DE LOIRE",
    "CENTRE-VAL DE LOIRE",
    "CORSE",
    "GRAND EST",
    "HAUTS-DE-FRANCE",
    "ÎLE-DE-FRANCE",
    "ILE-DE-FRANCE",
    "NORMANDIE",
    "NOUVELLE-AQUITAINE",
    "OCCITANIE",
    "PAYS DE LA LOIRE",
    "PROVENCE-ALPES-CÔTE D'AZUR",
    "PROVENCE-ALPES-COTE D'AZUR",
    "MONACO",
]
# Plus long d'abord pour matcher proprement
REGIONS_SORTED = sorted(set(REGIONS), key=len, reverse=True)
REGION_REGEX = re.compile(
    r"(?<![A-Z])(" + "|".join(re.escape(r) for r in REGIONS_SORTED) + r")(?![A-ZÀ-Ÿ])"
)

ROLES_RAW = [
    "Coach seniors",
    "Directeur Sportif",
    "Directeur sportif",
    "Coordinateur Sportif",
    "Coordinateur sportif",
    "Manager Sportif",
    "Manager sportif",
    "Membre comité",
    "Vice- Président",
    "Vice-président",
    "Vice président",
    "Vice Président",
    "Co-président",
    "Co président",
    "Co Président",
    "Coprésident",
    "Co-Président",
    "Présidente",
    "Président",
    "Trésorière",
    "Trésorier",
    "Tresorier",
    "Secrétaire",
    "Secretaire",
    "Responsable",
    "Respo Sportif",
    "Respo sportif",
    "Respo développement",
    "Respo Développement",
    "Respo edr",
    "Respo EDR",
    "Manager",
    "Coach",
    "EDR",
    "Jeunes",
]
ROLES_SORTED = sorted(set(ROLES_RAW), key=len, reverse=True)
ROLE_REGEX = re.compile(r"\b(" + "|".join(re.escape(r) for r in ROLES_SORTED) + r")\b")

PHONE_REGEX = re.compile(r"0[1-9](?:[ .\-]?\d{2}){4}")
EMAIL_REGEX = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

# Mapping vers les options officielles du dropdown Rôle
ROLE_TO_OPTION = {
    "président": "président",
    "présidente": "président",
    "co président": "co président",
    "co-président": "co président",
    "co-présidente": "co président",
    "coprésident": "co président",
    "co présidente": "co président",
    "vice président": "vice président",
    "vice-président": "vice président",
    "vice- président": "vice président",
    "trésorier": "trésorier",
    "trésorière": "trésorier",
    "tresorier": "trésorier",
    "secrétaire": "secrétaire",
    "secretaire": "secrétaire",
    "coach": "coach",
    "coach seniors": "coach",
    "manager": "manager sportif",
    "manager sportif": "manager sportif",
    "directeur sportif": "manager sportif",
    "respo sportif": "manager sportif",
    "coordinateur sportif": "manager sportif",
    "responsable": "responsable",
    "respo développement": "responsable",
    "respo edr": "responsable",
    "edr": "responsable",
    "membre comité": "responsable",
    "jeunes": "responsable",
}
ROLE_DEFAULT = "aucune des catégories"
STATUT_DEFAULT = "à contacter"

# Schéma de prospection par défaut (12 colonnes de base, identique à static/js/schema.js)
BASE_COLUMNS = [
    {"id": "col_nom_club", "name": "Nom du club", "type": "text", "width": 220,
     "hidden": False, "defaultValue": "", "options": []},
    {"id": "col_region", "name": "Région", "type": "text", "width": 150,
     "hidden": False, "defaultValue": "", "options": []},
    {"id": "col_departement", "name": "Département", "type": "text", "width": 130,
     "hidden": False, "defaultValue": "", "options": []},
    {"id": "col_site", "name": "Site du club", "type": "text", "width": 200,
     "hidden": False, "defaultValue": "", "options": []},
    {"id": "col_nom", "name": "Nom", "type": "text", "width": 150,
     "hidden": False, "defaultValue": "", "options": []},
    {"id": "col_role", "name": "Rôle", "type": "dropdown", "width": 170,
     "hidden": False, "defaultValue": ROLE_DEFAULT,
     "options": ["président", "coach", "trésorier", "secrétaire", "vice président",
                 "co président", "manager sportif", "responsable", "aucune des catégories"]},
    {"id": "col_telephone", "name": "Téléphone", "type": "text", "width": 140,
     "hidden": False, "defaultValue": "", "options": []},
    {"id": "col_mail", "name": "Mail", "type": "text", "width": 220,
     "hidden": False, "defaultValue": "", "options": []},
    {"id": "col_statut", "name": "Statut de la prospection", "type": "dropdown", "width": 190,
     "hidden": False, "defaultValue": STATUT_DEFAULT,
     "options": ["à contacter", "en cours", "rdv fixé", "proposition envoyée",
                 "signé", "pas signé", "à relancer"]},
    {"id": "col_date_premier_contact", "name": "Date premier contact", "type": "date", "width": 150,
     "hidden": False, "defaultValue": "", "options": []},
    {"id": "col_date_derniere_action", "name": "Date dernière action", "type": "date", "width": 150,
     "hidden": False, "defaultValue": "", "options": []},
    {"id": "col_commentaires", "name": "Commentaires", "type": "text", "width": 260,
     "hidden": False, "defaultValue": "", "options": []},
]

# Colonnes supplémentaires à créer si absentes
EXTRA_COLUMNS = [
    {"id": "col_licences", "name": "Licences", "type": "text", "width": 100,
     "hidden": False, "defaultValue": "", "options": []},
    {"id": "col_importance", "name": "Importance relance", "type": "text", "width": 150,
     "hidden": False, "defaultValue": "", "options": []},
    {"id": "col_rdv_pose", "name": "RDV Posé", "type": "checkbox", "width": 110,
     "hidden": False, "defaultValue": "false", "options": []},
    {"id": "col_date_rdv", "name": "Date RDV", "type": "date", "width": 140,
     "hidden": False, "defaultValue": "", "options": []},
    {"id": "col_rdv_fait", "name": "RDV Fait", "type": "checkbox", "width": 110,
     "hidden": False, "defaultValue": "false", "options": []},
    {"id": "col_date_devis", "name": "Date devis", "type": "date", "width": 140,
     "hidden": False, "defaultValue": "", "options": []},
    {"id": "col_devis_signe", "name": "Devis signé", "type": "checkbox", "width": 110,
     "hidden": False, "defaultValue": "false", "options": []},
]


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


def map_role(role_str: str) -> str:
    n = normalize(role_str)
    if not n:
        return ROLE_DEFAULT
    if n in ROLE_TO_OPTION:
        return ROLE_TO_OPTION[n]
    for key, val in ROLE_TO_OPTION.items():
        if key in n:
            return val
    return ROLE_DEFAULT


def infer_statut(record: dict) -> str:
    if record.get("Devis signé"):
        return "signé"
    if record.get("Date devis"):
        return "proposition envoyée"
    if record.get("RDV Fait"):
        return "en cours"
    if record.get("RDV Posé") or record.get("Date"):
        return "rdv fixé"
    return STATUT_DEFAULT


# === Parser text-based ===

def parse_line(line: str) -> dict | None:
    """Parse une ligne de texte du PDF en utilisant la région comme ancre."""
    line = line.strip()
    if not line:
        return None
    # Skip header / footer / page numbers
    if normalize(line).startswith(("club region", "tableau ")):
        return None
    if line.isdigit():
        return None

    # IMPORTANT : un nom de club peut CONTENIR un mot-région
    # ("BAIN DE BRETAGNE RUGBY BRETAGNE 35 ...", "ROUEN NORMANDIE RUGBY NORMANDIE 76 ...").
    # On choisit donc la DERNIERE occurrence de région qui est SUIVIE d'un chiffre
    # (le numéro de département vient juste après la vraie région).
    matches = list(REGION_REGEX.finditer(line))
    if not matches:
        return None

    chosen = None
    for cand in matches:
        after = line[cand.end():].lstrip()
        if after and after[0].isdigit():
            chosen = cand  # on garde la dernière qui qualifie
    if chosen is None:
        chosen = matches[-1]

    region = chosen.group(1)
    club = line[:chosen.start()].strip()
    if not club or normalize(club) == "club":
        return None

    rest = line[chosen.end():].strip()

    # Extrait téléphone et email avant de tokeniser
    phone_m = PHONE_REGEX.search(rest)
    phone = phone_m.group(0).strip() if phone_m else ""

    email_m = EMAIL_REGEX.search(rest)
    email = email_m.group(0).strip() if email_m else ""

    # Retire phone/email pour ne pas perturber la tokenisation
    rest_clean = rest
    if phone:
        rest_clean = rest_clean.replace(phone, " ", 1)
    if email:
        rest_clean = rest_clean.replace(email, " ", 1)
    rest_clean = " ".join(rest_clean.split())

    tokens = rest_clean.split(" ") if rest_clean else []

    # 1er token numérique = département
    dept = ""
    if tokens and re.fullmatch(r"\d{1,3}", tokens[0]):
        dept = tokens.pop(0)

    # 2e token numérique (si présent) = licences
    licences = ""
    if tokens and re.fullmatch(r"\d{1,4}", tokens[0]):
        licences = tokens.pop(0)

    remaining = " ".join(tokens).strip()

    # Recherche d'un rôle dans le reste
    role = ""
    contact = ""
    remarques = ""
    role_m = ROLE_REGEX.search(remaining)
    if role_m:
        role = role_m.group(1)
        contact = remaining[:role_m.start()].strip()
        remarques = remaining[role_m.end():].strip()
    else:
        # Pas de rôle détecté : tout le reste est soit le nom du contact,
        # soit des remarques. Heuristique : si court (≤3 mots), c'est le contact.
        words = remaining.split()
        if len(words) <= 4:
            contact = remaining
        else:
            contact = " ".join(words[:3])
            remarques = " ".join(words[3:])

    return {
        "Club": club,
        "Région": region,
        "Département": dept,
        "Licences": licences,
        "Nom contact": contact,
        "Rôle": role,
        "Téléphone": phone,
        "Mail": email,
        "Remarques": remarques,
        "Importance relance": "",
        "RDV Posé": "",
        "Date": "",
        "RDV Fait": "",
        "Date devis": "",
        "Devis signé": "",
    }


def parse_pdf(path: str) -> list[dict]:
    records: list[dict] = []
    seen_clubs: set[str] = set()
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            for line in text.split("\n"):
                rec = parse_line(line)
                if rec is None:
                    continue
                key = normalize(rec["Club"])
                if key in seen_clubs:
                    continue
                seen_clubs.add(key)
                records.append(rec)
    return records


# === Workspace merge ===

def is_effectively_empty(value: str, col_id: str) -> bool:
    if not value:
        return True
    if col_id == "col_statut" and value == STATUT_DEFAULT:
        return True
    if col_id == "col_role" and value == ROLE_DEFAULT:
        return True
    return False


def ensure_extra_columns(workspace: dict) -> dict[str, str]:
    """Ajoute les colonnes manquantes. Retourne {name: id} pour celles présentes."""
    existing_by_name = {normalize(c["name"]): c for c in workspace["columns"]}
    for col_def in EXTRA_COLUMNS:
        key = normalize(col_def["name"])
        if key in existing_by_name:
            continue
        workspace["columns"].append(dict(col_def))
        default_val = "false" if col_def["type"] == "checkbox" else col_def.get("defaultValue", "")
        for row in workspace["rows"]:
            row["values"].setdefault(col_def["id"], default_val)
    # Rebuild map
    return {normalize(c["name"]): c["id"] for c in workspace["columns"]}


def resolve_ids(workspace: dict) -> dict[str, str]:
    by_name = ensure_extra_columns(workspace)
    return {
        "nom_club": by_name.get("nom du club", "col_nom_club"),
        "region": by_name.get("region", "col_region"),
        "departement": by_name.get("departement", "col_departement"),
        "site": by_name.get("site du club", "col_site"),
        "nom": by_name.get("nom", "col_nom"),
        "role": by_name.get("role", "col_role"),
        "telephone": by_name.get("telephone", "col_telephone"),
        "mail": by_name.get("mail", "col_mail"),
        "statut": by_name.get("statut de la prospection", "col_statut"),
        "date_premier_contact": by_name.get("date premier contact", "col_date_premier_contact"),
        "date_derniere_action": by_name.get("date derniere action", "col_date_derniere_action"),
        "commentaires": by_name.get("commentaires", "col_commentaires"),
        "licences": by_name.get("licences", "col_licences"),
        "importance": by_name.get("importance relance", "col_importance"),
        "rdv_pose": by_name.get("rdv pose", "col_rdv_pose"),
        "date_rdv": by_name.get("date rdv", "col_date_rdv"),
        "rdv_fait": by_name.get("rdv fait", "col_rdv_fait"),
        "date_devis": by_name.get("date devis", "col_date_devis"),
        "devis_signe": by_name.get("devis signe", "col_devis_signe"),
    }


def build_values(record: dict, ids: dict[str, str]) -> dict[str, str]:
    values = {
        ids["nom_club"]: clean_cell(record.get("Club")),
        ids["region"]: clean_cell(record.get("Région")),
        ids["departement"]: clean_cell(record.get("Département")),
        ids["nom"]: clean_cell(record.get("Nom contact")),
        ids["role"]: map_role(record.get("Rôle")),
        ids["telephone"]: clean_cell(record.get("Téléphone")),
        ids["mail"]: clean_cell(record.get("Mail")),
        ids["statut"]: infer_statut(record),
        ids["licences"]: clean_cell(record.get("Licences")),
        ids["importance"]: clean_cell(record.get("Importance relance")),
    }
    parts = []
    if record.get("Remarques"):
        parts.append(clean_cell(record["Remarques"]))
    values[ids["commentaires"]] = " — ".join(parts)
    date_rdv = clean_cell(record.get("Date"))
    values[ids["date_premier_contact"]] = date_rdv
    values[ids["date_derniere_action"]] = date_rdv
    values[ids["date_rdv"]] = date_rdv
    values[ids["date_devis"]] = clean_cell(record.get("Date devis"))
    values[ids["rdv_pose"]] = "true" if record.get("RDV Posé") else ""
    values[ids["rdv_fait"]] = "true" if record.get("RDV Fait") else ""
    values[ids["devis_signe"]] = "true" if record.get("Devis signé") else ""
    return values


def merge(workspace: dict, records: list[dict]) -> tuple[dict, list[str], list[str]]:
    ids = resolve_ids(workspace)
    nom_club_id = ids["nom_club"]

    existing_by_name: dict[str, dict] = {}
    for row in workspace["rows"]:
        name = normalize(row["values"].get(nom_club_id, ""))
        if name and name not in existing_by_name:
            existing_by_name[name] = row

    stats = {"added": 0, "enriched": 0, "unchanged": 0}
    added: list[str] = []
    enriched: list[str] = []

    for record in records:
        club_name = clean_cell(record.get("Club"))
        if not club_name:
            continue
        key = normalize(club_name)
        new_values = build_values(record, ids)

        if key in existing_by_name:
            row = existing_by_name[key]
            filled_any = False
            for col_id, val in new_values.items():
                if not val:
                    continue
                current = row["values"].get(col_id, "")
                if val == current:
                    continue  # déjà identique, ne compte pas comme enrichissement
                if is_effectively_empty(current, col_id):
                    row["values"][col_id] = val
                    filled_any = True
            if filled_any:
                stats["enriched"] += 1
                enriched.append(club_name)
            else:
                stats["unchanged"] += 1
        else:
            new_row = {
                "id": "row_imp_" + secrets.token_urlsafe(6),
                "values": {col["id"]: col.get("defaultValue", "") for col in workspace["columns"]},
            }
            for col_id, val in new_values.items():
                if val:
                    new_row["values"][col_id] = val
            workspace["rows"].append(new_row)
            stats["added"] += 1
            added.append(club_name)

    return stats, added, enriched


# === Entrée principale ===

def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/import_prospection_pdf.py <pdf-path> [--apply]")
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

    if len(records) < 100:
        print("⚠️  Très peu de clubs détectés — vérifie un échantillon ci-dessous :")
        for r in records[:8]:
            print(f"     • {r['Club']:<45} | {r['Région']:<28} | dept={r['Département']:<3} | lic={r['Licences']:<4} | contact={r['Nom contact']!r:<25} | role={r['Rôle']!r}")
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
        print("⚠️  Workspace vide : initialisation du schéma de prospection (12 colonnes de base).")
        workspace["columns"] = [dict(c) for c in BASE_COLUMNS]
        workspace["views"] = [{
            "id": "view_default", "name": "Vue par defaut",
            "filters": [], "sort": None, "hiddenColumnIds": [],
        }]
        workspace["activeViewId"] = "view_default"

    print(f"   → {len(workspace['rows'])} lignes, {len(workspace['columns'])} colonnes\n")

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
        print(f"\n   Exemples d'ajouts   : {sample}{suffix}")
    if enriched:
        sample = ", ".join(enriched[:6])
        suffix = ", ..." if len(enriched) > 6 else ""
        print(f"   Exemples d'enrichis : {sample}{suffix}")

    if not apply_changes:
        print("\n💡 Mode DRY-RUN : rien n'a été sauvegardé.")
        print("   Pour appliquer en Supabase, relance avec --apply :")
        print(f'      python scripts/import_prospection_pdf.py "{pdf_path}" --apply')
        return

    # Backup local AVANT de sauvegarder en Supabase
    backups_dir = ROOT / "backups"
    backups_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = backups_dir / f"workspace_before_import_{timestamp}.json"
    print(f"\n💾 Backup local avant écriture : {backup_file.name}")
    # On sauvegarde l'état AVANT modifications. Mais on a déjà modifié workspace en mémoire,
    # donc on recharge l'original depuis Supabase pour le backup.
    original = load_workspace_state()
    with backup_file.open("w", encoding="utf-8") as f:
        json.dump(original, f, ensure_ascii=False, indent=2)
    print(f"   ✅ Backup écrit ({backup_file.stat().st_size // 1024} Ko)")

    print("\n💾 Sauvegarde dans Supabase...")
    sanitized = sanitize_workspace_state(workspace)
    updated_at = save_workspace_state(sanitized)
    print(f"   ✅ Sauvegardé à {updated_at}")
    print("\n🎉 Import terminé. Recharge l'app pour voir les changements.")
    print(f"\n   Pour annuler cet import : restaure le backup")
    print(f"      python scripts/restore_workspace.py \"{backup_file}\"")


if __name__ == "__main__":
    main()
