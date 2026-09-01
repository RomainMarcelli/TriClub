#!/usr/bin/env python3
"""
Restaure un workspace Supabase depuis un fichier JSON de backup.

Usage:
    python scripts/restore_workspace.py "backups/workspace_before_import_20260519_091833.json"
    python scripts/restore_workspace.py "..." --apply

Sans --apply, c'est un dry-run qui affiche juste un résumé du backup.
"""

from __future__ import annotations

import json
import sys
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
    if len(sys.argv) < 2:
        print("Usage: python scripts/restore_workspace.py <backup.json> [--apply]")
        sys.exit(1)

    backup_path = Path(sys.argv[1])
    apply_changes = "--apply" in sys.argv

    if not backup_path.exists():
        print(f"❌ Backup introuvable : {backup_path}")
        sys.exit(1)

    print(f"📂 Lecture du backup : {backup_path}")
    with backup_path.open("r", encoding="utf-8") as f:
        backup = json.load(f)

    if not isinstance(backup, dict) or "columns" not in backup or "rows" not in backup:
        print("❌ Format de backup invalide (clés 'columns'/'rows' attendues).")
        sys.exit(1)

    print(f"   → {len(backup['rows'])} lignes, {len(backup['columns'])} colonnes\n")

    print("☁️  Chargement du workspace actuel depuis Supabase pour comparaison...")
    try:
        ensure_database()
    except Exception as error:
        print(f"❌ Connexion DB échouée : {error}")
        sys.exit(1)

    current = load_workspace_state()
    if current:
        print(f"   → état actuel : {len(current['rows'])} lignes, {len(current['columns'])} colonnes")
        diff = len(current["rows"]) - len(backup["rows"])
        if diff > 0:
            print(f"   ⚠️  Restaurer va SUPPRIMER {diff} ligne(s) du workspace actuel")
        elif diff < 0:
            print(f"   ⚠️  Restaurer va AJOUTER {-diff} ligne(s) au workspace actuel")
        else:
            print("   ✅ Même nombre de lignes")

    if not apply_changes:
        print("\n💡 Mode DRY-RUN : rien n'a été restauré.")
        print("   Pour appliquer la restauration, relance avec --apply :")
        print(f'      python scripts/restore_workspace.py "{backup_path}" --apply')
        return

    print("\n💾 Restauration en cours...")
    sanitized = sanitize_workspace_state(backup)
    updated_at = save_workspace_state(sanitized)
    print(f"   ✅ Restauré à {updated_at}")
    print("\n🎉 Workspace remis à l'état du backup. Recharge l'app pour voir.")


if __name__ == "__main__":
    main()
