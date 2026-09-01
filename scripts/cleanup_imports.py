#!/usr/bin/env python3
"""
Supprime les lignes créées par l'import PDF (id qui commence par 'row_imp_').

Usage:
    python scripts/cleanup_imports.py             # dry-run (liste les lignes)
    python scripts/cleanup_imports.py --apply     # supprime + backup

Un backup JSON est créé dans backups/ avant toute suppression.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import (  # noqa: E402
    ensure_database,
    load_workspace_state,
    sanitize_workspace_state,
    save_workspace_state,
)


def main():
    apply_changes = "--apply" in sys.argv

    print("☁️  Chargement du workspace depuis Supabase...")
    try:
        ensure_database()
    except Exception as error:
        print(f"❌ Connexion DB échouée : {error}")
        sys.exit(1)

    workspace = load_workspace_state()
    if not workspace:
        print("❌ Workspace vide ou introuvable.")
        sys.exit(1)

    total_rows = len(workspace["rows"])
    suspect_rows = [r for r in workspace["rows"] if r["id"].startswith("row_imp_")]

    print(f"   → {total_rows} lignes au total")
    print(f"   → {len(suspect_rows)} lignes créées par l'import PDF (id 'row_imp_*')\n")

    if not suspect_rows:
        print("✅ Rien à nettoyer.")
        return

    # Récupère l'id de la colonne 'Nom du club' pour afficher les noms
    nom_club_col = next(
        (c["id"] for c in workspace["columns"] if c.get("name") == "Nom du club"),
        "col_nom_club",
    )

    print("Lignes qui SERONT supprimées :")
    print(f"  {'id':<24} {'Nom du club'}")
    print(f"  {'-' * 24} {'-' * 50}")
    for row in suspect_rows[:40]:
        club_name = row["values"].get(nom_club_col, "(vide)")
        print(f"  {row['id']:<24} {club_name}")
    if len(suspect_rows) > 40:
        print(f"  ... et {len(suspect_rows) - 40} autres")

    if not apply_changes:
        print("\n💡 Mode DRY-RUN : rien n'a été supprimé.")
        print("   Pour réellement supprimer, relance avec --apply :")
        print("      python scripts/cleanup_imports.py --apply")
        return

    # Backup avant suppression
    backups_dir = ROOT / "backups"
    backups_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = backups_dir / f"workspace_before_cleanup_{timestamp}.json"
    print(f"\n💾 Backup local : {backup_file.name}")
    with backup_file.open("w", encoding="utf-8") as f:
        json.dump(workspace, f, ensure_ascii=False, indent=2)
    print(f"   ✅ Backup écrit ({backup_file.stat().st_size // 1024} Ko)")

    # Suppression
    suspect_ids = {r["id"] for r in suspect_rows}
    workspace["rows"] = [r for r in workspace["rows"] if r["id"] not in suspect_ids]

    print("\n💾 Sauvegarde dans Supabase...")
    sanitized = sanitize_workspace_state(workspace)
    updated_at = save_workspace_state(sanitized)
    print(f"   ✅ Sauvegardé à {updated_at}")
    print(f"   → {len(workspace['rows'])} lignes restantes (-{len(suspect_ids)})")
    print("\n🎉 Cleanup terminé.")
    print(f"\n   Pour annuler ce cleanup : restaure le backup")
    print(f"      python scripts/restore_workspace.py \"{backup_file}\"")


if __name__ == "__main__":
    main()
