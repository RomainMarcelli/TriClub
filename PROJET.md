# Ben Workspace - Documentation Projet

## 1. Objectif
Application web en francais pour:
- importer un PDF,
- extraire automatiquement les colonnes `Nom club`, `Ligue`, `CD`,
- afficher et modifier les donnees dans un tableau intelligent,
- filtrer/rechercher,
- ajouter des colonnes personnalisees,
- partager une vue en lecture seule,
- exporter en CSV compatible Apple Numbers,
- conserver les donnees et les modifications dans une base de donnees.

## 2. Stack Technique
- Backend: `Python 3` + `Flask`
- Parsing PDF: `pdfplumber`
- Frontend: `HTML + CSS + JavaScript (modules ES)`
- Table performante: rendu virtualise (VirtualGrid)
- Persistance: `PostgreSQL (Supabase)` ou fallback `SQLite`

## 3. Architecture
- `app.py`: API Flask + extraction PDF + export + partage + persistance BDD.
- `api/index.py`: point d'entree pour deploiement Vercel.
- `templates/index.html`: interface principale (FR).
- `templates/shared.html`: page partagee en lecture seule.
- `static/js/store.js`: etat du workspace, filtres, tri, vues, payloads export/partage/persistance.
- `static/js/app.js`: UX, modales, import PDF, interactions table, auto-save/auto-load BDD.
- `static/js/table.js`: tableau editable, tri, resize, drag&drop colonnes.
- `static/js/pdf.js`: upload PDF et creation du workspace initial.
- `static/style.css`: design system et styles UI.

## 4. Fonctionnalites Actuelles
- Import PDF par glisser-deposer ou selection de fichier.
- Detection table + fallback parsing ligne texte pour PDF FFR.
- Ecran d'apercu avant import avec mapping `Nom club`, `Ligue`, `CD`.
- Tableau editable en ligne.
- Edition cellule par cellule avec double-clic (style tableur).
- Ajout / edition / suppression / reorganisation / redimensionnement des colonnes.
- Bouton dedie `Gerer les colonnes` pour renommer/supprimer facilement une colonne.
- Types de colonnes: `text`, `number`, `tag`, `dropdown`, `checkbox`, `date`.
- Filtres avances cumulables (`egal a`, `contient`, `commence par`, `est vide`, `n'est pas vide`).
- Filtres rapides metier:
  - tri alphabetique `Nom club` (A->Z / Z->A),
  - tri `CD` (croissant / decroissant),
  - tri croissant/decroissant sur la colonne selectionnee,
  - vues rapides `clubs`, `regions`, `departements`, `villes` (si colonne Ville),
  - vue `donnees completes`,
  - reinitialisation des filtres/tri/recherche.
- Recherche globale instantanee.
- Partage par lien signe (lecture seule).
- Export CSV (table complete ou vue filtree).
- Sauvegarde automatique en BDD et rechargement automatique au demarrage.

## 5. Base de Donnees
Mode persistance:
- `SUPABASE_DB_URL` defini -> stockage `PostgreSQL` (Supabase)
- sinon -> stockage `SQLite`

SQLite par defaut:
- `data/ben_workspace.db`
- configurable via variable d'environnement `BEN_DB_PATH`.
- fallback automatique sur `/tmp/ben_workspace.db` si le chemin principal est indisponible.

### Schema PostgreSQL (Supabase)
```sql
CREATE TABLE IF NOT EXISTS workspace_state (
  id SMALLINT PRIMARY KEY CHECK (id = 1),
  payload JSONB NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### Schema SQLite (fallback)
```sql
CREATE TABLE IF NOT EXISTS workspace_state (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  payload TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
```

### Donnees stockees
Le champ `payload` contient l'etat complet du workspace:
- colonnes
- lignes
- filtres
- recherche
- tri
- vues
- vue active
- selections courantes

## 6. API Disponible
- `POST /api/extract`: extraction PDF + suggestions de mapping.
- `POST /api/export`: export CSV.
- `POST /api/share`: creation d'un lien partageable.
- `GET /shared/<token>`: consultation partagee (read-only).
- `GET /api/workspace`: charge le dernier workspace sauvegarde.
- `POST /api/workspace`: sauvegarde le workspace en base.
- `GET /api/health`: verification de sante.

## 7. UX/UI
Principes appliques:
- interface simplifiee en francais,
- moins de boutons et de friction,
- actions principales en haut (`Importer`, `Exporter`, `Partager`),
- recherche + filtres + ajout colonne visibles,
- edition colonne via clic sur en-tete,
- etats vides et feedbacks (toast).

## 8. Deploiement et Persistance
- En local/serveur classique: SQLite conserve les donnees si le fichier DB est persistant.
- Sur Vercel: le systeme de fichiers n'est pas garanti persistant. Pour une vraie persistance en production, prevoir une base externe (PostgreSQL/Supabase/Neon) et connecter l'API dessus.

## 9. Journal de Mise a Jour
### 2026-03-12
- Refonte UI/UX complete en francais avec interface simplifiee.
- Correction extraction PDF FFR via parser ligne texte (`1471` lignes detectees sur le fichier de reference).
- Ajout persistance BDD SQLite:
  - sanitization complete du workspace,
  - creation auto de la table `workspace_state`,
  - endpoint `GET /api/workspace`,
  - endpoint `POST /api/workspace`.
- Ajout auto-load au demarrage + auto-save debounce cote frontend.
- Ajout d'une sauvegarde de secours sur fermeture de page (`sendBeacon`).
- Ajout edition cellule par cellule au double-clic dans le tableau.
- Ajout de filtres rapides supplementaires (tri + vues metier clubs/regions/departements/villes).
- Durcissement de `/api/workspace`:
  - fallback automatique SQLite en environnement restreint,
  - gestion d'erreur non bloquante sur lecture workspace,
  - message explicite si la sauvegarde est impossible.
- Migration backend:
  - support natif `SUPABASE_DB_URL` (PostgreSQL) pour `/api/workspace`,
  - creation automatique de la table `workspace_state` sur Supabase,
  - fallback SQLite si `SUPABASE_DB_URL` n'est pas defini.

---

## 10. Regle de Maintenance du Fichier
A chaque evolution du projet, mettre a jour ce fichier:
1. `Fonctionnalites Actuelles` si le comportement change.
2. `Base de Donnees` si schema/stockage evolue.
3. `API Disponible` si endpoint modifie/ajoute/supprime.
4. `Journal de Mise a Jour` avec date + changements.
