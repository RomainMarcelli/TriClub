# AUDIT — Adaptation du Workspace pour la prospection de clubs

> Document d'audit produit avant toute modification de code.
> Aucune ligne de code n'a été modifiée à ce stade. Objectif : valider la compréhension du projet et le plan d'implémentation avant développement.

---

## 1. Résumé du projet actuel

**Ben Workspace — PDF to Smart Table** est une application web mono-page (Flask + JS vanilla) qui :

1. Reçoit un PDF (typiquement la liste FFR des clubs),
2. Détecte une table (ou parse ligne par ligne avec une regex `Ligue / CD / Code / Nom club`),
3. Propose un mapping vers 3 champs cibles fixes : `Nom club`, `Ligue`, `CD`,
4. Affiche les données dans une **table intelligente** type Airtable (édition inline, tri, filtres, vues, recherche),
5. Permet d'ajouter/supprimer/réordonner des colonnes typées (`text`, `number`, `tag`, `dropdown`, `checkbox`, `date`),
6. Exporte en CSV (format Numbers `;` + BOM ou CSV standard `,`),
7. Génère un lien public read-only (`/shared/<token>`) via `itsdangerous`,
8. Persiste l'état complet du workspace côté serveur (SQLite local ou Postgres/Supabase REST en production).

---

## 2. Architecture détectée

```
TriClub/
├── app.py                    # Backend Flask monolithique (~1000 lignes)
├── api/index.py              # Entry point Vercel (re-exporte `app`)
├── vercel.json               # Config déploiement Vercel
├── requirements.txt
├── data/ben_workspace.db     # Base SQLite locale (mode dev)
├── templates/
│   ├── index.html            # Page principale + tous les modals
│   └── shared.html           # Vue publique read-only
└── static/
    ├── style.css
    └── js/
        ├── app.js            # Orchestration UI + bindings + sauvegarde
        ├── store.js          # `WorkspaceStore` — état + filtres/tri/vues
        ├── table.js          # `VirtualGrid` — rendu virtualisé + édition
        ├── pdf.js            # Upload PDF + `buildWorkspaceFromImport`
        └── shared.js         # Rendu de la vue partagée
```

**Stockage** : trois backends résolus à l'exécution via env vars (`SUPABASE_DB_URL` → Postgres direct, sinon `SUPABASE_URL`+`SUPABASE_SERVICE_ROLE_KEY` → REST, sinon SQLite local + fallback `/tmp` pour Vercel/Render).

**Persistance** : 1 ligne dans `workspace_state(id=1, payload JSONB/TEXT)`. Tout l'état (colonnes + lignes + filtres + vues + sélection) est sauvegardé en un seul blob JSON.

---

## 3. Fichiers importants et leur rôle

| Fichier | Rôle clé pour cette évolution |
|---|---|
| [app.py](app.py) | API REST (`/api/extract`, `/api/export`, `/api/share`, `/api/workspace`), sanitization (sécurité), constantes `TARGET_FIELDS`, regex FFR, backend storage |
| [static/js/store.js](static/js/store.js) | **Cœur de la logique colonnes/lignes/filtres**. `COLUMN_TYPES`, `resetWorkspace`, `addColumn`, `addFilter`, `setSort`, `saveCurrentView`, `hydrateWorkspace` |
| [static/js/pdf.js](static/js/pdf.js) | `buildWorkspaceFromImport` — **définit les 3 colonnes en dur** créées après un import PDF |
| [static/js/app.js](static/js/app.js) | Bindings UI, modals, filtres rapides (codés en dur avec `Nom club`/`Ligue`/`CD`), mapping PDF côté front |
| [static/js/table.js](static/js/table.js) | Rendu de la grille, gestion `dropdown` (input `<select>`), édition inline |
| [templates/index.html](templates/index.html) | Boutons « filtres rapides » (hard-codés), modale d'import avec 3 selects `Nom club / Ligue / CD`, modales d'ajout/édition de colonne |
| [templates/shared.html](templates/shared.html) | Vue publique (read-only) |

---

## 4. Fonctionnement actuel détaillé

### 4.1 Table intelligente (grille)

- Rendu virtualisé dans [static/js/table.js](static/js/table.js) (`VirtualGrid`).
- Cellules en lecture seule par défaut, double-clic → édition.
- Types supportés et rendus distinctement : `text`, `number`, `date`, `checkbox`, `tag`, `dropdown` (cf. [static/js/table.js:149-185](static/js/table.js#L149-L185)).
- Drag & drop des colonnes, redimensionnement, tri par clic sur l'en-tête (cycle asc/desc/none).

### 4.2 Colonnes et types

- **Liste des types autorisés** : [static/js/store.js:1](static/js/store.js#L1)
  ```js
  const COLUMN_TYPES = ["text", "number", "tag", "dropdown", "checkbox", "date"];
  ```
- **Création** via `store.addColumn({name, type, defaultValue, options})` ([static/js/store.js:326-352](static/js/store.js#L326-L352)).
  - Lors de l'ajout, chaque ligne reçoit `column.defaultValue` (ou `"false"` pour les checkbox).
- **Modèle de colonne** : `{ id, name, type, width, hidden, defaultValue, options[] }`.
- **Modale d'édition** : `editOptionsColonne` activé uniquement si `type === "dropdown"` ([static/js/app.js:1134-1136](static/js/app.js#L1134-L1136)).
- **Création initiale des colonnes** (après import) en dur dans [static/js/pdf.js:78-82](static/js/pdf.js#L78-L82) :
  ```js
  const columns = [
    { id: "col_nom_club", name: "Nom club", ... },
    { id: "col_ligue",    name: "Ligue",    ... },
    { id: "col_cd",       name: "CD",       ... },
  ];
  ```

### 4.3 Dropdowns et valeurs par défaut

- Le rendu d'un `<select>` se fait dans [static/js/table.js:157-169](static/js/table.js#L157-L169) ; il préfixe systématiquement une option vide.
- La valeur par défaut est appliquée **uniquement** :
  - au moment où une nouvelle colonne est créée (toutes les lignes existantes héritent de `defaultValue`),
  - **pas** au moment où une nouvelle ligne est ajoutée à une colonne existante (à vérifier ci-dessous : actuellement il n'y a même pas de fonction `addRow` côté store).
- ⚠️ **Constat important** : il n'existe actuellement **aucune fonction `addRow` / bouton « Ajouter une ligne »**. L'application est conçue pour peupler le tableau via l'import PDF puis éditer. Cette fonctionnalité est à créer (le brief la demande).

### 4.4 Filtres

- **Filtres applicables** : opérateurs `equals`, `contains`, `starts_with`, `is_empty`, `is_not_empty` ([static/js/store.js:2](static/js/store.js#L2) et [app.py:57](app.py#L57)).
- **Filtres rapides** (boutons hard-codés) : [templates/index.html:41-52](templates/index.html#L41-L52) (`tri_nom_az`, `tri_cd_asc`, `filtre_clubs`, `filtre_regions`, etc.).
- **Logique de résolution** des colonnes ciblées par les filtres rapides via `trouverColonneParNoms` ([static/js/app.js:174-189](static/js/app.js#L174-L189)) — recherche **par nom normalisé** (insensible à la casse, sans accents). C'est important : si on garde ces noms cohérents avec les nouveaux libellés (« Région », « Département »…), les filtres rapides existants continuent à fonctionner avec des ajustements mineurs.
- **Tri** : un seul tri actif (`state.sort = { columnId, direction }`), avec comparateurs typés (number, date, sinon `localeCompare` français) — [static/js/store.js:35-69](static/js/store.js#L35-L69).
- **Recherche globale** : `state.searchQuery`, match sur toutes les colonnes ([static/js/store.js:530-535](static/js/store.js#L530-L535)).

### 4.5 Vues sauvegardées

- Présent et fonctionnel : `state.views`, `saveCurrentView`, `applyView` ([static/js/store.js:457-493](static/js/store.js#L457-L493)).
- Stocke `filters`, `sort`, `hiddenColumnIds`.
- ⚠️ **Mais aucune UI** dans `index.html` ne permet actuellement à l'utilisateur de **créer/sélectionner** une vue (la logique store existe, l'IHM non). Le brief demande de « conserver les vues sauvegardées si elles existent actuellement » → elles existent **en backend/store** mais pas en UI. À clarifier.

### 4.6 Import PDF

- Endpoint backend : `POST /api/extract` ([app.py:813-859](app.py#L813-L859)).
  - Deux parsers : table (pdfplumber) et regex ligne FFR (`FFR_LINE_PATTERN`).
  - Renvoie `headers`, `rows`, `suggested_mapping` basé sur `TARGET_FIELDS = ["Nom club", "Ligue", "CD"]` ([app.py:54](app.py#L54)).
- Côté front : `uploadPdfWithProgress` puis modale de mapping (3 selects), puis `buildWorkspaceFromImport` qui **crée 3 colonnes en dur** et appelle `store.resetWorkspace(...)` ([static/js/app.js:472-502](static/js/app.js#L472-L502)).
- ⚠️ `resetWorkspace` **écrase** complètement les colonnes existantes — important pour la stratégie de mapping.

### 4.7 Export CSV

- `POST /api/export` ([app.py:862-898](app.py#L862-L898)).
- Reçoit `columns + rows`, sérialise dans l'ordre des colonnes, `;`+BOM ou `,` selon format.
- Indépendant de la sémantique des colonnes → **insensible à l'évolution demandée**.

### 4.8 Stockage workspace

- `GET/POST /api/workspace` ([app.py:938-1003](app.py#L938-L1003)).
- Sanitization stricte côté serveur (`sanitize_workspace_state` → `sanitize_columns`, `sanitize_rows`, `sanitize_filters`, `sanitize_views`).
- Auto-save côté front : `planifierSauvegardeWorkspace` debouncé 800 ms + `sendBeacon` à la fermeture.
- Toute donnée non listée dans `sanitize_columns` est **filtrée silencieusement** (ex : un futur champ `kind: "prospection"` au niveau colonne serait perdu).

### 4.9 Partage public

- `POST /api/share` → payload zlib+base64, signé `itsdangerous` ([app.py:901-935](app.py#L901-L935)).
- Limite : 700 ko bruts avant compression.
- Vue rendue par `templates/shared.html` + `static/js/shared.js`.

---

## 5. Analyse de l'évolution demandée

### 5.1 Mapping des colonnes cibles

| # | Colonne demandée | Type      | Default              | Options                                                                                                  |
|---|------------------|-----------|----------------------|----------------------------------------------------------------------------------------------------------|
| 1 | Nom du club      | text      | —                    | —                                                                                                        |
| 2 | Région           | text      | —                    | —                                                                                                        |
| 3 | Département      | text      | —                    | —                                                                                                        |
| 4 | Site du club     | text      | —                    | — (idéalement type `url`, mais pas dans `COLUMN_TYPES` — on reste en `text`)                              |
| 5 | Nom              | text      | —                    | —                                                                                                        |
| 6 | Rôle             | dropdown  | `aucune des catégories` | président, coach, trésorier, secrétaire, vice président, co président, manager sportif, responsable, aucune des catégories |
| 7 | Téléphone        | text      | —                    | —                                                                                                        |
| 8 | Mail             | text      | —                    | —                                                                                                        |
| 9 | Statut de la prospection | dropdown | `à contacter`   | à contacter, en cours, rdv fixé, proposition envoyée, signé, pas signé, à relancer                       |
| 10 | Date premier contact   | date  | —                    | —                                                                                                        |
| 11 | Date dernière action   | date  | —                    | —                                                                                                        |
| 12 | Commentaires           | text  | —                    | —                                                                                                        |

### 5.2 Filtres / tris attendus

| Demande            | Mécanique cible                                                                 |
|--------------------|----------------------------------------------------------------------------------|
| Ordre alphabétique | `store.setSort(colNomClub, "asc"\|"desc")`                                       |
| Région             | filtre `equals` + filtre rapide « Par régions »                                  |
| Département        | filtre `equals` + filtre rapide « Par départements »                             |
| Rôle               | filtre `equals` (dropdown values)                                                |
| Statut prospection | filtre `equals` (dropdown values)                                                |
| Date dernière action | `store.setSort(colDateDerniereAction, "asc"\|"desc")`                          |

→ Les opérateurs `equals` et `contains` existent déjà ; **aucune extension du moteur de filtre n'est nécessaire**. Ce qui change, ce sont :
- les **noms de colonnes** cherchés par `trouverColonneParNoms` (passer de `"nom club"/"ligue"/"cd"` à `"nom du club"/"région"/"département"/"rôle"/"statut"/"date dernière action"`),
- les **boutons** de l'IHM filtres rapides ([templates/index.html:41-52](templates/index.html#L41-L52)).

### 5.3 Initialisation des colonnes au lancement du workspace

Deux scénarios possibles (à arbitrer avec l'utilisateur — cf. §10) :

- **A. Auto-init à la première ouverture** : si `GET /api/workspace` renvoie `exists:false`, on crée côté front un workspace par défaut avec ces 12 colonnes et 0 ligne, puis on sauvegarde. Avantage : zéro friction.
- **B. Init seulement après import PDF** : on conserve l'écran « état vide → importer un PDF », mais `buildWorkspaceFromImport` crée désormais les 12 colonnes (et mappe le PDF FFR dans `Nom du club`, `Région`, `Département`). Plus cohérent avec le flow actuel.

Recommandation : **B + bouton « Démarrer sans PDF »** sur l'état vide, qui appelle un nouveau `store.initProspectionWorkspace()`. Le PDF reste optionnel mais ne casse rien.

### 5.4 Mapping PDF

Le mapping PDF actuel (`Nom club / Ligue / CD`) est aligné avec les nouveaux libellés :
- `Nom club` → `Nom du club`
- `Ligue` → `Région`
- `CD` → `Département`

→ Le formulaire de mapping de l'import PDF doit afficher 3 cibles : **Nom du club / Région / Département**. Les autres 9 colonnes sont créées vides avec leur valeur par défaut.

---

## 6. Plan d'implémentation proposé (étape par étape)

> **Aucune modification tant que cet audit n'est pas validé.**

### Étape 1 — Schéma de colonnes par défaut (source de vérité unique)

- Créer un module `static/js/schema.js` exportant `DEFAULT_PROSPECTION_COLUMNS` (ordre, id stable, type, defaultValue, options).
- Stable IDs proposés : `col_nom_club`, `col_region`, `col_departement`, `col_site`, `col_nom`, `col_role`, `col_telephone`, `col_mail`, `col_statut`, `col_date_premier_contact`, `col_date_derniere_action`, `col_commentaires`.

### Étape 2 — Refonte de `buildWorkspaceFromImport`

- [static/js/pdf.js](static/js/pdf.js) : importer `DEFAULT_PROSPECTION_COLUMNS`, créer **les 12 colonnes**, mapper les valeurs PDF sur `col_nom_club / col_region / col_departement`, laisser les autres vides (ou à `defaultValue` pour les dropdowns).
- Garantir : `col_role` = `"aucune des catégories"`, `col_statut` = `"à contacter"` pour chaque ligne importée.

### Étape 3 — Initialisation sans PDF (option recommandée)

- Ajouter `store.initProspectionWorkspace()` dans [static/js/store.js](static/js/store.js) qui crée les 12 colonnes + 0 ligne.
- Ajouter un bouton « Démarrer sans PDF » dans `#etatVide` ([templates/index.html:63-67](templates/index.html#L63-L67)).
- Au démarrage : si `GET /api/workspace` renvoie `exists:false` et l'utilisateur clique le bouton → init.

### Étape 4 — Ajout de lignes

- Ajouter `store.addRow()` dans [static/js/store.js](static/js/store.js) :
  - Crée un row avec `values[col.id] = col.defaultValue` pour chaque colonne (ou `"false"` pour checkbox, `""` pour types neutres).
  - **C'est ici** que les defaults `aucune des catégories` et `à contacter` doivent être appliqués automatiquement.
- Ajouter un bouton « + Ajouter une ligne » dans la barre d'outils ou en bas du tableau.

### Étape 5 — Mise à jour des filtres rapides

- [templates/index.html:38-54](templates/index.html#L38-L54) : remplacer les boutons par :
  - `Trier A → Z` / `Z → A` (sur Nom du club)
  - `Trier par date dernière action`
  - `Filtrer par région` / `par département` / `par rôle` / `par statut`
  - `Réinitialiser`
- [static/js/app.js](static/js/app.js) `appliquerFiltreRapide` : adapter `trouverColonneParNoms` pour pointer vers les nouveaux noms ("nom du club", "région", "département", "rôle", "statut", "date dernière action").
- Pour les filtres par dropdown (`région`, `département`, `rôle`, `statut`) : générer dynamiquement un menu listant les valeurs distinctes (région/département) ou les options (rôle/statut) afin d'appliquer un filtre `equals`.

### Étape 6 — Mapping PDF UI

- [templates/index.html:119-132](templates/index.html#L119-L132) : renommer les 3 labels en `Nom du club / Région / Département`. IDs JS conservés (`mapNomClub`, `mapLigue` → `mapRegion`, `mapCD` → `mapDepartement` pour clarté).
- [static/js/app.js:42-44 + 478-485](static/js/app.js#L478-L485) : ajuster les clés du mapping.
- Backend : adapter `TARGET_FIELDS` ([app.py:54](app.py#L54)) en `["Nom du club", "Région", "Département"]` **et** la regex FFR (mêmes données mais clés renommées dans la sortie) — ou laisser le backend inchangé et faire la traduction côté front. **Plus sûr : traduction côté front uniquement**, le backend continue à publier `Nom club/Ligue/CD` et le front consomme ces clés.

### Étape 7 — UI Vues sauvegardées (optionnel, à confirmer)

Si l'utilisateur veut effectivement exposer les vues sauvegardées (le store les gère déjà), ajouter un sélecteur dans la barre d'outils + un bouton « Enregistrer la vue actuelle ». Sinon → ne rien faire (la logique reste latente, sans régression).

### Étape 8 — Tests manuels (cf. checklist §11)

---

## 7. Fichiers à modifier (récapitulatif)

| Fichier | Nature de la modification |
|---|---|
| [static/js/schema.js](static/js/schema.js) | **Création** — constantes de schéma |
| [static/js/store.js](static/js/store.js) | Ajout `addRow()`, `initProspectionWorkspace()` |
| [static/js/pdf.js](static/js/pdf.js) | Refonte `buildWorkspaceFromImport` (12 colonnes au lieu de 3) |
| [static/js/app.js](static/js/app.js) | Filtres rapides, bouton « Ajouter une ligne », bouton « Démarrer sans PDF », mapping import |
| [templates/index.html](templates/index.html) | Boutons filtres rapides, libellés mapping, bouton « + ligne », bouton « Démarrer sans PDF » |
| [app.py](app.py) | **À discuter** : pas obligatoire. Si on veut renommer `TARGET_FIELDS` côté backend pour cohérence, c'est un changement isolé. Sanitization déjà OK pour les 12 colonnes (tout passe par `sanitize_columns`). |

> Aucun changement de **schéma DB** : le payload `workspace_state.payload` est déjà JSONB/TEXT libre. Aucune migration Postgres/Supabase à faire.

---

## 8. Données / structures à ajouter

```js
// static/js/schema.js (proposition)
export const ROLE_OPTIONS = [
  "président", "coach", "trésorier", "secrétaire",
  "vice président", "co président", "manager sportif",
  "responsable", "aucune des catégories",
];
export const ROLE_DEFAULT = "aucune des catégories";

export const STATUT_OPTIONS = [
  "à contacter", "en cours", "rdv fixé", "proposition envoyée",
  "signé", "pas signé", "à relancer",
];
export const STATUT_DEFAULT = "à contacter";

export const DEFAULT_PROSPECTION_COLUMNS = [
  { id: "col_nom_club",             name: "Nom du club",     type: "text",     width: 200, defaultValue: "", options: [] },
  { id: "col_region",               name: "Région",          type: "text",     width: 160, defaultValue: "", options: [] },
  { id: "col_departement",          name: "Département",     type: "text",     width: 140, defaultValue: "", options: [] },
  { id: "col_site",                 name: "Site du club",    type: "text",     width: 220, defaultValue: "", options: [] },
  { id: "col_nom",                  name: "Nom",             type: "text",     width: 160, defaultValue: "", options: [] },
  { id: "col_role",                 name: "Rôle",            type: "dropdown", width: 160, defaultValue: ROLE_DEFAULT,   options: ROLE_OPTIONS },
  { id: "col_telephone",            name: "Téléphone",       type: "text",     width: 140, defaultValue: "", options: [] },
  { id: "col_mail",                 name: "Mail",            type: "text",     width: 200, defaultValue: "", options: [] },
  { id: "col_statut",               name: "Statut de la prospection", type: "dropdown", width: 180, defaultValue: STATUT_DEFAULT, options: STATUT_OPTIONS },
  { id: "col_date_premier_contact", name: "Date premier contact", type: "date", width: 150, defaultValue: "", options: [] },
  { id: "col_date_derniere_action", name: "Date dernière action", type: "date", width: 150, defaultValue: "", options: [] },
  { id: "col_commentaires",         name: "Commentaires",    type: "text",     width: 280, defaultValue: "", options: [] },
];
```

---

## 9. Risques techniques

| Risque | Impact | Mitigation |
|---|---|---|
| **Régression import PDF** : modifier `buildWorkspaceFromImport` casse l'extraction FFR | Haut | Test manuel avec le PDF FFR-DS de référence. Conserver les clés `Nom club / Ligue / CD` côté backend pour ne pas toucher au parser regex. |
| **Caractères accentués dans les noms de colonnes** (Région, Département, Rôle) | Moyen | Tous les chemins critiques utilisent déjà `normalize_text` (NFKD + suppression diacritiques). `dedupe_headers` et la sanitization côté serveur les acceptent. À vérifier : le matching de `trouverColonneParNoms` (`normaliserCle` fait la même chose côté JS — OK). |
| **Workspaces existants** déjà persistés avec les anciennes colonnes (`col_nom_club / col_ligue / col_cd`) | Moyen | À l'hydratation, ces workspaces ne sont **pas** automatiquement migrés. Décision à prendre : (a) écraser ? (b) laisser tel quel ? (c) bouton « Réinitialiser avec le schéma prospection » ? — recommandé (c). |
| **Filtres rapides existants** (`tri_nom_az`, `filtre_clubs`, etc.) | Faible | Ils cherchent les colonnes par nom — l'évolution change ces noms → les anciens boutons cesseront de matcher. Comme on remplace les boutons, OK. |
| **Vues sauvegardées** persistées avec d'anciens `columnId` | Faible | Les `columnId` resteront stables si on garde `col_nom_club` etc. Les références aux anciens IDs `col_ligue` / `col_cd` deviendront `col_region` / `col_departement` → les vues stockées avec ces IDs deviendraient inopérantes. Mitigation : transformation au chargement (rename id `col_ligue→col_region`, `col_cd→col_departement`). |
| **Export CSV** | Faible | Insensible aux noms/types : sérialise dans l'ordre des colonnes. OK. |
| **Partage public** | Faible/Moyen | Limite 700 ko : 12 colonnes au lieu de 3 → 4× plus de cellules par ligne. À considérer pour de gros datasets (>5000 lignes). Le message d'erreur existant est suffisant. |
| **Compatibilité Vercel/Render** | Faible | Aucun changement backend critique. La sanitization gère déjà tous les types/options. Stockage JSON inchangé. |
| **Type `dropdown` vs `tag`** | Faible | Le rendu `<select>` ([static/js/table.js:157](static/js/table.js#L157)) inclut une option vide en tête, ce qui permet à l'utilisateur d'« effacer » la valeur. Si on veut **forcer** la valeur par défaut (jamais vide), il faut supprimer cette option vide pour les colonnes `role` et `statut`. À arbitrer. |

---

## 10. Questions / points à valider avant développement

1. **Initialisation** : workspace auto-créé au premier démarrage (option A) ou bouton « Démarrer sans PDF » (option B, recommandée) ?
2. **Migration des workspaces existants** : que faire des données déjà persistées avec l'ancien schéma `Nom club / Ligue / CD` ? Migration automatique (rename d'IDs `col_ligue → col_region`, `col_cd → col_departement`) ou bouton manuel de remise à zéro ?
3. **Option vide dans les dropdowns** : laisse-t-on l'utilisateur effacer la valeur d'un dropdown (option `""` en tête du `<select>`) ou bien la valeur par défaut est-elle obligatoire (toujours une des options) ?
4. **Vues sauvegardées en UI** : on expose enfin l'UI (créer/sélectionner vue) ou on laisse latent ?
5. **« Site du club »** : type `text` (statu quo, suffisant) ou ajouter un type `url` à `COLUMN_TYPES` (gros chantier, non recommandé) ?
6. **Filtres « par région/département/rôle/statut »** : on les rend interactifs (menu déroulant pour choisir la valeur) ou simples raccourcis vers un tri ?
7. **Ordre des actions du brief** : « ajouter une ligne » n'existe **pas** aujourd'hui. Confirmation que c'est bien à créer (et pas une référence à un comportement supposé existant) ?
8. **PDF** : on conserve la possibilité d'importer un PDF FFR (et il alimente `Nom du club / Région / Département`), ou on supprime entièrement l'import ?

---

## 11. Checklist de validation après développement

### Schéma
- [ ] À l'ouverture d'un workspace neuf, les 12 colonnes apparaissent dans l'ordre exact du brief.
- [ ] La colonne « Rôle » a bien 9 options ; valeur par défaut = `aucune des catégories`.
- [ ] La colonne « Statut de la prospection » a bien 7 options ; valeur par défaut = `à contacter`.
- [ ] Les colonnes `Date premier contact` et `Date dernière action` affichent un picker date.

### Lignes
- [ ] Bouton « Ajouter une ligne » fonctionnel ; nouvelle ligne créée avec `Rôle=aucune des catégories` et `Statut=à contacter`.
- [ ] Édition inline (double-clic) fonctionne sur `text`, `date`, `dropdown`.
- [ ] Auto-save Supabase/SQLite OK après ajout, édition, suppression.

### Colonnes
- [ ] Ajout d'une colonne personnalisée toujours possible.
- [ ] Suppression / réorganisation / redimensionnement OK.

### Filtres et tris
- [ ] Tri alphabétique sur `Nom du club` (A→Z et Z→A).
- [ ] Tri sur `Date dernière action`.
- [ ] Filtre par `Région`, `Département`, `Rôle`, `Statut` (au moins via opérateur `equals`).
- [ ] Recherche globale fonctionne sur toutes les colonnes (y compris les nouvelles).

### Import PDF
- [ ] Import d'un PDF FFR existant : les données tombent dans `Nom du club / Région / Département`.
- [ ] Les 9 autres colonnes sont créées vides (sauf `Rôle` et `Statut` qui prennent leur défaut).
- [ ] Aucune régression sur la détection table / regex FFR.

### Export CSV
- [ ] Export Numbers (`;` + BOM) : ouvre correctement dans Numbers/Excel avec les 12 colonnes.
- [ ] Export CSV standard (`,`) : OK.
- [ ] Les caractères accentués (Région, Département, Rôle…) ressortent bien encodés.

### Partage public
- [ ] Génération de lien OK avec les 12 colonnes.
- [ ] La page `/shared/<token>` affiche les valeurs de dropdown lisiblement.

### Stockage / persistance
- [ ] `GET /api/workspace` : renvoie les 12 colonnes après sauvegarde.
- [ ] Aucune `warning: workspace_storage_unavailable` en local SQLite ni en Supabase.
- [ ] Reload de page : l'état est restauré tel quel.

### Déploiement
- [ ] Build/déploiement Vercel : OK (fonction Python, pas de migration DB).
- [ ] Déploiement Render : OK.

---

> Fin de l'audit. **Aucune modification de code n'a été effectuée.** Merci de valider (ou demander des ajustements) avant que je passe à l'implémentation.
