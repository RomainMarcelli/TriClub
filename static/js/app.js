import { FILTER_OPERATORS, WorkspaceStore } from "./store.js";
import { buildWorkspaceFromImport, uploadPdfWithProgress } from "./pdf.js";
import { VirtualGrid } from "./table.js";
import { ROLE_OPTIONS, STATUT_OPTIONS } from "./schema.js";
import {
  DATABASE_STATES,
  WORKSPACE_LOAD_STATES,
  buildWorkspaceSaveEnvelope,
  evaluateWorkspacePersistence,
  getWorkspaceLoadErrorCode,
  isExplicitLastRowDeletion,
  recoveryActionAfterProbe,
} from "./workspace-persistence.js";

const dom = {
  etatVide: document.getElementById("etatVide"),
  sectionTableau: document.getElementById("sectionTableau"),
  statsTableau: document.getElementById("statsTableau"),
  etiquetteColonne: document.getElementById("etiquetteColonne"),

  tableScroll: document.getElementById("tableScroll"),
  tableHead: document.getElementById("tableHead"),
  tableBody: document.getElementById("tableBody"),

  champRecherche: document.getElementById("champRecherche"),
  panneauFiltres: document.getElementById("panneauFiltres"),
  btnFiltres: document.getElementById("btnFiltres"),
  filtresRapides: document.getElementById("filtresRapides"),
  listeFiltres: document.getElementById("listeFiltres"),
  btnAjouterFiltre: document.getElementById("btnAjouterFiltre"),

  btnImporterHaut: document.getElementById("btnImporterHaut"),
  btnExporterHaut: document.getElementById("btnExporterHaut"),
  btnPartagerHaut: document.getElementById("btnPartagerHaut"),
  btnImporterVide: document.getElementById("btnImporterVide"),
  btnAjouterLigne: document.getElementById("btnAjouterLigne"),
  btnSupprimerLigne: document.getElementById("btnSupprimerLigne"),
  btnAjouterColonne: document.getElementById("btnAjouterColonne"),
  btnGererColonnes: document.getElementById("btnGererColonnes"),

  modalBackdrop: document.getElementById("modalBackdrop"),

  modalImport: document.getElementById("modalImport"),
  fermerImport: document.getElementById("fermerImport"),
  etapeUpload: document.getElementById("etapeUpload"),
  etapePreview: document.getElementById("etapePreview"),
  zoneDepot: document.getElementById("zoneDepot"),
  inputPdf: document.getElementById("inputPdf"),
  barreUpload: document.getElementById("barreUpload"),
  barreExtraction: document.getElementById("barreExtraction"),
  statutImport: document.getElementById("statutImport"),
  apercuLignes: document.getElementById("apercuLignes"),
  apercuMeta: document.getElementById("apercuMeta"),
  mapNomClub: document.getElementById("mapNomClub"),
  mapLigue: document.getElementById("mapLigue"),
  mapCD: document.getElementById("mapCD"),
  tablePreview: document.getElementById("tablePreview"),
  retourUpload: document.getElementById("retourUpload"),
  confirmerImport: document.getElementById("confirmerImport"),

  modalAjoutColonne: document.getElementById("modalAjoutColonne"),
  fermerAjoutColonne: document.getElementById("fermerAjoutColonne"),
  inputNomColonne: document.getElementById("inputNomColonne"),
  inputTypeColonne: document.getElementById("inputTypeColonne"),
  inputValeurParDefaut: document.getElementById("inputValeurParDefaut"),
  inputOptionsColonne: document.getElementById("inputOptionsColonne"),
  creerColonne: document.getElementById("creerColonne"),

  modalEditionColonne: document.getElementById("modalEditionColonne"),
  fermerEditionColonne: document.getElementById("fermerEditionColonne"),
  editSelectColonne: document.getElementById("editSelectColonne"),
  editNomColonne: document.getElementById("editNomColonne"),
  editTypeColonne: document.getElementById("editTypeColonne"),
  editValeurParDefaut: document.getElementById("editValeurParDefaut"),
  editLargeurColonne: document.getElementById("editLargeurColonne"),
  editOptionsColonne: document.getElementById("editOptionsColonne"),
  btnMonterColonne: document.getElementById("btnMonterColonne"),
  btnDescendreColonne: document.getElementById("btnDescendreColonne"),
  infoPositionColonne: document.getElementById("infoPositionColonne"),
  enregistrerColonne: document.getElementById("enregistrerColonne"),
  supprimerColonne: document.getElementById("supprimerColonne"),

  modalExport: document.getElementById("modalExport"),
  fermerExport: document.getElementById("fermerExport"),
  exportScope: document.getElementById("exportScope"),
  exportFormat: document.getElementById("exportFormat"),
  exportRowCount: document.getElementById("exportRowCount"),
  exportRowsInfo: document.getElementById("exportRowsInfo"),
  exportFilename: document.getElementById("exportFilename"),
  exporterMaintenant: document.getElementById("exporterMaintenant"),

  modalPartage: document.getElementById("modalPartage"),
  fermerPartage: document.getElementById("fermerPartage"),
  genererLien: document.getElementById("genererLien"),
  champLienPartage: document.getElementById("champLienPartage"),
  copierLien: document.getElementById("copierLien"),

  modalConfirmSuppression: document.getElementById("modalConfirmSuppression"),
  fermerConfirmSuppression: document.getElementById("fermerConfirmSuppression"),
  annulerSuppression: document.getElementById("annulerSuppression"),
  confirmerSuppression: document.getElementById("confirmerSuppression"),
  apercuLigneSuppression: document.getElementById("apercuLigneSuppression"),

  toast: document.getElementById("toast"),
  databaseStatus: document.getElementById("databaseStatus"),
  databaseStatusLabel: document.getElementById("databaseStatusLabel"),
  supabasePausedPanel: document.getElementById("supabasePausedPanel"),
  supabasePausedMessage: document.getElementById("supabasePausedMessage"),
  btnResumeSupabase: document.getElementById("btnResumeSupabase"),
  btnCreerBackup: document.getElementById("btnCreerBackup"),
  listeBackups: document.getElementById("listeBackups"),
};

const RAISONS_SANS_SAUVEGARDE = new Set(["setSelectedColumn", "setSelectedRow"]);
const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || "";
const utilisateurAdmin = document.body.dataset.isAdmin === "true";

let hydratationEnCours = false;
let timerSauvegarde = null;
let sauvegardeEnCours = false;
let sauvegardeRelance = false;
let alerteSauvegardeActive = false;
let derniereSignatureSauvegardee = "";
let workspaceInitialLoadCompleted = false;
let workspaceStorageAvailable = false;
let workspaceLoadState = WORKSPACE_LOAD_STATES.NOT_STARTED;
let databaseState = DATABASE_STATES.CHECKING;
let workspaceStateSuspect = false;
let workspaceExistsOnServer = false;
let workspaceRevision = null;
let dernierNombreLignesServeur = 0;
let suppressionTotaleLignesConfirmee = false;

const store = new WorkspaceStore((event = {}) => {
  if (isExplicitLastRowDeletion(event, store.state.rows.length)) {
    suppressionTotaleLignesConfirmee = true;
  } else if (store.state.rows.length > 0 || event.reason === "resetWorkspace") {
    suppressionTotaleLignesConfirmee = false;
  }

  renderInterface();

  if (hydratationEnCours) {
    return;
  }
  if (RAISONS_SANS_SAUVEGARDE.has(event.reason)) {
    return;
  }

  planifierSauvegardeWorkspace();
});

const grille = new VirtualGrid({
  scrollEl: dom.tableScroll,
  headEl: dom.tableHead,
  bodyEl: dom.tableBody,
  callbacks: {
    onCellChange: (rowId, colId, value) => store.updateCell(rowId, colId, value),
    onRowSelect: (rowId) => store.setSelectedRow(rowId),
    onColumnSelect: (colId) => {
      store.setSelectedColumn(colId);
      ouvrirModalEditionColonne();
    },
    onSort: (colId) => store.cycleSort(colId),
    onReorderColumns: (sourceId, targetId) => store.reorderColumns(sourceId, targetId),
    onResizeColumn: (colId, width) => store.updateColumn(colId, { width }),
  },
});

let modalActive = null;
let timerToast = null;
let payloadImport = null;
let ligneEnAttenteSuppression = null;

function texte(value) {
  if (value === null || value === undefined) {
    return "";
  }
  return String(value).trim();
}

function echapperHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function echapperSelecteur(value) {
  if (window.CSS && typeof window.CSS.escape === "function") {
    return window.CSS.escape(String(value));
  }
  return String(value).replace(/[^a-zA-Z0-9_-]/g, "\\$&");
}

function optionsDepuisTexte(input) {
  return texte(input)
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function normaliserCle(value) {
  return texte(value)
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/\s+/g, " ");
}

function idRapide(prefix = "id") {
  return `${prefix}_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;
}

function trouverColonneParNoms(candidats) {
  const noms = Array.isArray(candidats) ? candidats.map((value) => normaliserCle(value)) : [];
  const colonnes = store.getColumns({ includeHidden: true });

  for (const colonne of colonnes) {
    const nomColonne = normaliserCle(colonne.name);
    if (!nomColonne) {
      continue;
    }
    if (noms.some((candidat) => nomColonne.includes(candidat))) {
      return colonne.id;
    }
  }

  return null;
}

function creerFiltreRapide(columnId, operator = "is_not_empty", value = "") {
  return {
    id: idRapide("quick"),
    columnId,
    operator,
    value: texte(value),
  };
}

const PICKER_TO_COLUMN = {
  region: "col_region",
  departement: "col_departement",
  role: "col_role",
  statut: "col_statut",
};

const PICKER_LABELS = {
  region: "Filtrer par Région...",
  departement: "Filtrer par Département...",
  role: "Filtrer par Rôle...",
  statut: "Filtrer par Statut...",
};

function appliquerFiltreRapide(code) {
  if (code === "tri_nom_az") {
    store.setSort("col_nom_club", "asc");
    afficherToast("Tri A → Z sur Nom du club.", "success");
    return;
  }
  if (code === "tri_nom_za") {
    store.setSort("col_nom_club", "desc");
    afficherToast("Tri Z → A sur Nom du club.", "success");
    return;
  }
  if (code === "tri_date_asc") {
    store.setSort("col_date_derniere_action", "asc");
    afficherToast("Tri date dernière action croissant.", "success");
    return;
  }
  if (code === "tri_date_desc") {
    store.setSort("col_date_derniere_action", "desc");
    afficherToast("Tri date dernière action décroissant.", "success");
    return;
  }
  if (code === "reset_filtres") {
    store.clearFilters();
    store.clearSort();
    store.setSearchQuery("");
    if (dom.champRecherche) {
      dom.champRecherche.value = "";
    }
    afficherToast("Filtres, tri et recherche réinitialisés.", "info");
  }
}

function appliquerPickerFiltre(pickerKey, value) {
  const columnId = PICKER_TO_COLUMN[pickerKey];
  if (!columnId) {
    return;
  }
  // On retire les anciens filtres "equals" sur cette colonne pour éviter les doublons.
  const autres = store.state.filters.filter(
    (f) => !(f.columnId === columnId && f.operator === "equals"),
  );
  const safeValue = texte(value);
  if (!safeValue) {
    store.setFilters(autres);
    return;
  }
  autres.push({
    id: idRapide("quick"),
    columnId,
    operator: "equals",
    value: safeValue,
  });
  store.setFilters(autres);
  afficherToast(`Filtre appliqué : ${safeValue}.`, "success");
}

function valeursDistinctesPourColonne(columnId) {
  const set = new Set();
  store.state.rows.forEach((row) => {
    const v = texte(row.values?.[columnId] || "");
    if (v) {
      set.add(v);
    }
  });
  return Array.from(set).sort((a, b) => a.localeCompare(b, "fr", { sensitivity: "base" }));
}

function renderPickersFiltres() {
  const root = dom.filtresRapides;
  if (!root) {
    return;
  }
  const selects = root.querySelectorAll("select[data-quick-picker]");
  selects.forEach((select) => {
    const key = select.dataset.quickPicker;
    const columnId = PICKER_TO_COLUMN[key];
    if (!columnId) {
      return;
    }

    let options = [];
    if (key === "role") {
      options = ROLE_OPTIONS.slice();
    } else if (key === "statut") {
      options = STATUT_OPTIONS.slice();
    } else {
      options = valeursDistinctesPourColonne(columnId);
    }

    const activeFilter = store.state.filters.find(
      (f) => f.columnId === columnId && f.operator === "equals",
    );
    const current = activeFilter ? activeFilter.value : "";

    const html = [
      `<option value="">${echapperHtml(PICKER_LABELS[key])}</option>`,
    ]
      .concat(
        options.map(
          (opt) =>
            `<option value="${echapperHtml(opt)}" ${opt === current ? "selected" : ""}>${echapperHtml(opt)}</option>`,
        ),
      )
      .join("");
    select.innerHTML = html;
    select.value = current;
  });
}

function afficherToast(message, tone = "info") {
  if (!dom.toast) {
    return;
  }

  dom.toast.textContent = message;
  dom.toast.className = `toast ${tone}`;

  if (timerToast) {
    window.clearTimeout(timerToast);
  }

  timerToast = window.setTimeout(() => {
    dom.toast.className = "toast hidden";
  }, 2600);
}

function jsonHeaders() {
  return { "Content-Type": "application/json", "X-CSRF-Token": csrfToken };
}

function redirigerSiSessionExpiree(response, data = {}) {
  if (response.status === 401 && data?.error === "authentication_required") {
    window.location.assign("/login");
    return true;
  }
  return false;
}

function afficherStatutBase(label, cssState) {
  if (!dom.databaseStatus || !dom.databaseStatusLabel) {
    return;
  }
  dom.databaseStatusLabel.textContent = label;
  dom.databaseStatus.className = `database-status is-${cssState}`;
}

function definirEtatBase(state, detail = "") {
  databaseState = state;
  const locked = state !== DATABASE_STATES.AVAILABLE;
  document.body.classList.toggle("workspace-locked", locked);
  [document.querySelector(".barre-outils"), dom.etatVide, dom.sectionTableau].forEach((element) => {
    if (element) {
      element.inert = locked;
    }
  });
  [dom.btnImporterHaut, dom.btnExporterHaut, dom.btnPartagerHaut].forEach((button) => {
    if (button) {
      button.disabled = locked;
    }
  });
  if (dom.btnCreerBackup) {
    dom.btnCreerBackup.disabled = locked;
  }
  if (dom.listeBackups) {
    dom.listeBackups.inert = locked;
  }

  const status = {
    [DATABASE_STATES.CHECKING]: ["Vérification de la base…", "checking"],
    [DATABASE_STATES.AVAILABLE]: ["Base connectée", "available"],
    [DATABASE_STATES.UNAVAILABLE]: ["Base indisponible", "unavailable"],
    [DATABASE_STATES.SUPABASE_PAUSED]: ["Supabase en pause", "paused"],
    [DATABASE_STATES.RESTORING]: ["Reprise en cours…", "restoring"],
    [DATABASE_STATES.CONFLICT]: ["Conflit de version", "conflict"],
  }[state] || ["État inconnu", "unavailable"];
  afficherStatutBase(status[0], status[1]);

  if (dom.supabasePausedPanel) {
    dom.supabasePausedPanel.classList.toggle("hidden", state !== DATABASE_STATES.SUPABASE_PAUSED);
  }
  if (dom.supabasePausedMessage && detail) {
    dom.supabasePausedMessage.textContent = detail;
  }
  if (dom.btnResumeSupabase) {
    dom.btnResumeSupabase.disabled = state === DATABASE_STATES.RESTORING;
  }
}

function attendre(delay) {
  return new Promise((resolve) => window.setTimeout(resolve, delay));
}

function ouvrirModal(modal) {
  if (!modal) {
    return;
  }
  fermerModalActive();
  modalActive = modal;
  dom.modalBackdrop.classList.remove("hidden");
  modal.classList.remove("hidden");
}

function fermerModalActive() {
  if (modalActive) {
    modalActive.classList.add("hidden");
    modalActive = null;
  }
  dom.modalBackdrop.classList.add("hidden");
}

function setProgress(bar, percent) {
  if (!bar) {
    return;
  }
  bar.style.width = `${Math.max(0, Math.min(100, percent))}%`;
}

function setEtapeImport(step) {
  const upload = step === "upload";
  dom.etapeUpload.classList.toggle("hidden", !upload);
  dom.etapePreview.classList.toggle("hidden", upload);
}

function resetImport() {
  payloadImport = null;
  setEtapeImport("upload");
  dom.statutImport.textContent = "En attente d'un fichier.";
  setProgress(dom.barreUpload, 0);
  setProgress(dom.barreExtraction, 0);
  dom.inputPdf.value = "";

  [dom.mapNomClub, dom.mapLigue, dom.mapCD].forEach((select) => {
    select.innerHTML = "";
  });

  dom.tablePreview.querySelector("thead").innerHTML = "";
  dom.tablePreview.querySelector("tbody").innerHTML = "";
  dom.apercuLignes.textContent = "0";
  dom.apercuMeta.textContent = "";
}

function ouvrirImport() {
  resetImport();
  ouvrirModal(dom.modalImport);
}

function remplirSelectMapping(selectEl, headers, suggestion) {
  const html = [`<option value="">-- Choisir une colonne --</option>`]
    .concat(headers.map((h) => `<option value="${echapperHtml(h)}">${echapperHtml(h)}</option>`))
    .join("");

  selectEl.innerHTML = html;
  if (suggestion && headers.includes(suggestion)) {
    selectEl.value = suggestion;
  }
}

function renderPreview(headers, rows) {
  const thead = dom.tablePreview.querySelector("thead");
  const tbody = dom.tablePreview.querySelector("tbody");

  thead.innerHTML = `<tr>${headers.map((h) => `<th>${echapperHtml(h)}</th>`).join("")}</tr>`;

  const lignes = rows.slice(0, 10);
  tbody.innerHTML = lignes
    .map((row) => {
      const tds = headers.map((h) => `<td>${echapperHtml(row[h] || "")}</td>`).join("");
      return `<tr>${tds}</tr>`;
    })
    .join("");
}

async function importerPdf(file) {
  if (!file) {
    return;
  }

  dom.statutImport.textContent = "Upload et extraction en cours...";

  try {
    const payload = await uploadPdfWithProgress(file, {
      onUploadProgress: (p) => setProgress(dom.barreUpload, p),
      onExtractionProgress: (p) => setProgress(dom.barreExtraction, p),
      csrfToken,
    });

    payloadImport = payload;
    const headers = Array.isArray(payload.headers) ? payload.headers : [];

    remplirSelectMapping(dom.mapNomClub, headers, payload.suggested_mapping?.["Nom club"]);
    remplirSelectMapping(dom.mapLigue, headers, payload.suggested_mapping?.["Ligue"]);
    remplirSelectMapping(dom.mapCD, headers, payload.suggested_mapping?.["CD"]);

    renderPreview(headers, payload.preview_rows || payload.rows || []);

    dom.apercuLignes.textContent = String(payload.row_count || 0);
    dom.apercuMeta.textContent = `Page ${payload.table_meta?.page || "-"}, analyse ${payload.table_meta?.parser || "-"}`;
    dom.statutImport.textContent = "Apercu pret.";
    setEtapeImport("preview");
  } catch (error) {
    if (error?.status === 401 && error?.code === "authentication_required") {
      window.location.assign("/login");
      return;
    }
    dom.statutImport.textContent = error.message || "Import impossible.";
    afficherToast(error.message || "Import impossible.", "danger");
  }
}

function confirmerImport() {
  if (!payloadImport) {
    afficherToast("Aucun apercu disponible.", "warning");
    return;
  }

  const mapping = {
    "Nom club": dom.mapNomClub.value,
    Ligue: dom.mapLigue.value,
    CD: dom.mapCD.value,
  };

  if (!mapping["Nom club"] || !mapping.Ligue || !mapping.CD) {
    afficherToast("Sélectionne les 3 colonnes : Nom du club, Région, Département.", "warning");
    return;
  }

  const workspace = buildWorkspaceFromImport({
    rows: payloadImport.rows || [],
    mapping,
  });

  if (!workspace.rows.length) {
    afficherToast("Aucune ligne exploitable après mapping.", "warning");
    return;
  }

  if (store.hasData()) {
    const ok = window.confirm(
      "Cela remplacera toutes les données actuelles du tableau. Continuer ?",
    );
    if (!ok) {
      return;
    }
  }

  store.resetWorkspace(workspace.columns, workspace.rows);
  store.ensureProspectionSchema();
  fermerModalActive();
  afficherToast(`${workspace.rows.length} lignes importées.`, "success");
}

function renderFiltres() {
  const { filters } = store.state;
  const columns = store.getColumns();

  if (!filters.length) {
    dom.listeFiltres.innerHTML = '<p class="texte-discret">Aucun filtre pour le moment.</p>';
    return;
  }

  const optionsColonnes = columns
    .map((col) => `<option value="${echapperHtml(col.id)}">${echapperHtml(col.name)}</option>`)
    .join("");

  dom.listeFiltres.innerHTML = filters
    .map((filter) => {
      const optionsOperateurs = FILTER_OPERATORS.map((operator) => {
        const selected = operator.value === filter.operator ? "selected" : "";
        return `<option value="${operator.value}" ${selected}>${operator.label}</option>`;
      }).join("");

      const sansValeur = filter.operator === "is_empty" || filter.operator === "is_not_empty";

      return `
        <div class="ligne-filtre" data-filter-id="${echapperHtml(filter.id)}">
          <select data-filter-field="columnId">${optionsColonnes}</select>
          <select data-filter-field="operator">${optionsOperateurs}</select>
          <input data-filter-field="value" type="text" value="${echapperHtml(filter.value || "")}" ${
            sansValeur ? "disabled" : ""
          } placeholder="Valeur" />
          <button type="button" class="btn-icone" data-action="supprimer-filtre">x</button>
        </div>
      `;
    })
    .join("");

  filters.forEach((filter) => {
    const row = dom.listeFiltres.querySelector(`[data-filter-id="${echapperSelecteur(filter.id)}"]`);
    if (!row) {
      return;
    }
    const columnSelect = row.querySelector('[data-filter-field="columnId"]');
    if (columnSelect) {
      columnSelect.value = filter.columnId;
    }
  });
}

function ouvrirAjoutColonne() {
  dom.inputNomColonne.value = "";
  dom.inputTypeColonne.value = "text";
  dom.inputValeurParDefaut.value = "";
  dom.inputOptionsColonne.value = "";
  ouvrirModal(dom.modalAjoutColonne);
}

function creerColonne() {
  const name = texte(dom.inputNomColonne.value);
  if (!name) {
    afficherToast("Le nom de colonne est obligatoire.", "warning");
    return;
  }

  const colonne = store.addColumn({
    name,
    type: dom.inputTypeColonne.value,
    defaultValue: dom.inputValeurParDefaut.value,
    options: optionsDepuisTexte(dom.inputOptionsColonne.value),
  });

  if (colonne) {
    fermerModalActive();
    afficherToast(`Colonne \"${colonne.name}\" ajoutee.`, "success");
  }
}

function remplirSelectColonnesEdition(columnId = "") {
  const columns = store.getColumns({ includeHidden: true });
  const safeColumns = Array.isArray(columns) ? columns : [];

  if (!safeColumns.length) {
    dom.editSelectColonne.innerHTML = '<option value="">Aucune colonne</option>';
    dom.editSelectColonne.value = "";
    dom.editSelectColonne.disabled = true;
    return null;
  }

  const html = safeColumns
    .map((col) => `<option value="${echapperHtml(col.id)}">${echapperHtml(col.name)}</option>`)
    .join("");

  dom.editSelectColonne.innerHTML = html;
  dom.editSelectColonne.disabled = false;

  const cible = columnId && safeColumns.some((col) => col.id === columnId) ? columnId : safeColumns[0].id;
  dom.editSelectColonne.value = cible;
  return cible;
}

function remplirFormulaireEditionColonne(colonne) {
  const hasColumn = Boolean(colonne);
  dom.editNomColonne.disabled = !hasColumn;
  dom.editTypeColonne.disabled = !hasColumn;
  dom.editValeurParDefaut.disabled = !hasColumn;
  dom.editLargeurColonne.disabled = !hasColumn;
  dom.btnMonterColonne.disabled = !hasColumn;
  dom.btnDescendreColonne.disabled = !hasColumn;
  dom.enregistrerColonne.disabled = !hasColumn;
  dom.supprimerColonne.disabled = !hasColumn;

  if (!hasColumn) {
    dom.editNomColonne.value = "";
    dom.editTypeColonne.value = "text";
    dom.editValeurParDefaut.value = "";
    dom.editLargeurColonne.value = "180";
    dom.editOptionsColonne.value = "";
    dom.editOptionsColonne.disabled = true;
    if (dom.infoPositionColonne) {
      dom.infoPositionColonne.textContent = "";
    }
    return;
  }

  dom.editNomColonne.value = colonne.name;
  dom.editTypeColonne.value = colonne.type;
  dom.editValeurParDefaut.value = colonne.defaultValue || "";
  dom.editLargeurColonne.value = String(colonne.width || 180);
  dom.editOptionsColonne.value = (colonne.options || []).join(", ");
  dom.editOptionsColonne.disabled = colonne.type !== "dropdown";

  const columns = store.getColumns({ includeHidden: true });
  const index = columns.findIndex((item) => item.id === colonne.id);
  const total = columns.length;
  const isFirst = index <= 0;
  const isLast = index < 0 || index >= total - 1;
  dom.btnMonterColonne.disabled = isFirst;
  dom.btnDescendreColonne.disabled = isLast;
  if (dom.infoPositionColonne) {
    dom.infoPositionColonne.textContent = index >= 0 ? `Position: ${index + 1} / ${total}` : "";
  }
}

function deplacerColonneSelectionnee(step) {
  const col = store.getSelectedColumn();
  if (!col) {
    return;
  }

  const columns = store.getColumns({ includeHidden: true });
  const index = columns.findIndex((item) => item.id === col.id);
  if (index < 0) {
    return;
  }

  const targetIndex = index + step;
  if (targetIndex < 0 || targetIndex >= columns.length) {
    return;
  }

  const target = columns[targetIndex];
  if (!target) {
    return;
  }

  store.reorderColumns(col.id, target.id);
  const selectedId = col.id;
  remplirSelectColonnesEdition(selectedId);
  store.setSelectedColumn(selectedId);
  remplirFormulaireEditionColonne(store.getSelectedColumn());
}

function ouvrirModalEditionColonne(columnId = "") {
  const selectedId = columnId || store.getSelectedColumn()?.id || "";
  const idCible = remplirSelectColonnesEdition(selectedId);
  if (!idCible) {
    afficherToast("Aucune colonne a gerer.", "warning");
    return;
  }

  store.setSelectedColumn(idCible);
  remplirFormulaireEditionColonne(store.getSelectedColumn());
  ouvrirModal(dom.modalEditionColonne);
}

function enregistrerEditionColonne() {
  const col = store.getSelectedColumn();
  if (!col) {
    return;
  }

  store.updateColumn(col.id, {
    name: dom.editNomColonne.value,
    type: dom.editTypeColonne.value,
    defaultValue: dom.editValeurParDefaut.value,
    width: Number(dom.editLargeurColonne.value || 180),
    options: optionsDepuisTexte(dom.editOptionsColonne.value),
  });

  if (dom.editSelectColonne) {
    remplirSelectColonnesEdition(col.id);
  }

  fermerModalActive();
  afficherToast("Colonne mise a jour.", "success");
}

function supprimerColonneSelectionnee() {
  const col = store.getSelectedColumn();
  if (!col) {
    return;
  }

  const ok = window.confirm(`Supprimer la colonne \"${col.name}\" ?`);
  if (!ok) {
    return;
  }

  store.deleteColumn(col.id);

  if (dom.editSelectColonne) {
    const nextId = remplirSelectColonnesEdition(store.getSelectedColumn()?.id || "");
    if (nextId) {
      store.setSelectedColumn(nextId);
      remplirFormulaireEditionColonne(store.getSelectedColumn());
    }
  }

  fermerModalActive();
  afficherToast("Colonne supprimee.", "success");
}

function parseFilename(contentDisposition, fallback) {
  if (!contentDisposition) {
    return fallback;
  }

  const utf8Match = /filename\*=UTF-8''([^;]+)/i.exec(contentDisposition);
  if (utf8Match) {
    return decodeURIComponent(utf8Match[1]);
  }

  const simpleMatch = /filename="?([^";]+)"?/i.exec(contentDisposition);
  if (simpleMatch) {
    return simpleMatch[1];
  }

  return fallback;
}

function telechargerBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function getExportScope() {
  return dom.exportScope?.value === "filtered" ? "filtered" : "all";
}

function getRowsDisponiblesPourExport(scope = "all") {
  return scope === "filtered" ? store.getProcessedRows().length : store.state.rows.length;
}

function actualiserInfosExport() {
  const scope = getExportScope();
  const disponibles = getRowsDisponiblesPourExport(scope);

  if (dom.exportRowsInfo) {
    dom.exportRowsInfo.textContent = `Lignes disponibles: ${disponibles}`;
  }

  const rawLimit = Number(dom.exportRowCount?.value || "");
  if (!Number.isFinite(rawLimit) || rawLimit <= 0) {
    return;
  }

  const limit = Math.floor(rawLimit);
  if (limit > disponibles && dom.exportRowCount) {
    dom.exportRowCount.value = disponibles > 0 ? String(disponibles) : "";
  }
}

async function exporterDepuisModal() {
  if (!store.hasData()) {
    afficherToast("Aucune donnee a exporter.", "warning");
    return;
  }

  const scope = getExportScope();
  const format = texte(dom.exportFormat?.value || "numbers_csv") || "numbers_csv";
  const disponibles = getRowsDisponiblesPourExport(scope);

  if (disponibles <= 0) {
    afficherToast("Aucune ligne disponible pour cet export.", "warning");
    return;
  }

  let rowLimit = null;
  if (dom.exportRowCount) {
    const parsed = Number(dom.exportRowCount.value || "");
    if (Number.isFinite(parsed) && parsed > 0) {
      rowLimit = Math.min(Math.floor(parsed), disponibles);
    }
  }

  const nomParDefaut = scope === "filtered" ? "export_vue_filtree" : "export_table_complete";
  const filename = texte(dom.exportFilename?.value || "") || nomParDefaut;

  const payload = store.buildExportPayload({
    filteredOnly: scope === "filtered",
    includeHidden: scope !== "filtered",
    rowLimit,
    filename,
    format,
  });

  try {
    const response = await fetch("/api/export", {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      if (redirigerSiSessionExpiree(response, err)) {
        return;
      }
      throw new Error(err.error || "Echec export.");
    }

    const blob = await response.blob();
    const filename = parseFilename(response.headers.get("Content-Disposition"), `${payload.filename}.csv`);
    telechargerBlob(blob, filename);
    fermerModalActive();
    const labelFormat = format === "numbers_csv" ? "Numbers" : "CSV";
    afficherToast(`Export ${labelFormat} termine.`, "success");
  } catch (error) {
    afficherToast(error.message || "Echec export.", "danger");
  }
}

function ouvrirExport() {
  if (!store.hasData()) {
    afficherToast("Aucune donnee a exporter.", "warning");
    return;
  }

  if (dom.exportScope) {
    dom.exportScope.value = "all";
  }
  if (dom.exportFormat) {
    dom.exportFormat.value = "numbers_csv";
  }
  if (dom.exportRowCount) {
    dom.exportRowCount.value = "";
  }
  if (dom.exportFilename) {
    dom.exportFilename.value = "export_tableau";
  }
  actualiserInfosExport();
  ouvrirModal(dom.modalExport);
}

function ouvrirConfirmSuppression() {
  const rowId = store.state.selectedRowId;
  if (!rowId) {
    afficherToast("Aucune ligne sélectionnée.", "warning");
    return;
  }
  const row = store.state.rows.find((r) => r.id === rowId);
  if (!row) {
    return;
  }
  ligneEnAttenteSuppression = rowId;

  // Aperçu : nom du club + région si dispo
  const nomClub = texte(row.values?.col_nom_club || "");
  const region = texte(row.values?.col_region || "");
  let apercu = "";
  if (nomClub) {
    apercu = nomClub;
    if (region) {
      apercu += ` — ${region}`;
    }
  }
  if (dom.apercuLigneSuppression) {
    dom.apercuLigneSuppression.textContent = apercu;
  }

  ouvrirModal(dom.modalConfirmSuppression);
}

function ouvrirPartage() {
  if (!store.hasData()) {
    afficherToast("Importe un PDF avant de partager.", "warning");
    return;
  }
  dom.champLienPartage.value = "";
  ouvrirModal(dom.modalPartage);
}

async function genererLienPartage() {
  try {
    const response = await fetch("/api/share", {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify({ workspace: store.buildSharePayload() }),
    });

    const data = await response.json().catch(() => ({}));
    if (redirigerSiSessionExpiree(response, data)) {
      return;
    }
    if (!response.ok) {
      throw new Error(data.error || "Impossible de generer le lien.");
    }

    dom.champLienPartage.value = data.share_url || "";
    afficherToast("Lien de partage genere.", "success");
  } catch (error) {
    afficherToast(error.message || "Partage impossible.", "danger");
  }
}

async function copierLienPartage() {
  const value = dom.champLienPartage.value;
  if (!value) {
    return;
  }

  try {
    await navigator.clipboard.writeText(value);
    afficherToast("Lien copie.", "success");
  } catch (error) {
    afficherToast("Copie automatique impossible.", "warning");
  }
}

function payloadWorkspace() {
  return buildWorkspaceSaveEnvelope(store.getPersistencePayload(), {
    initialLoadCompleted: workspaceInitialLoadCompleted,
    serverWorkspaceExists: workspaceExistsOnServer,
    baseRevision: workspaceRevision,
    emptyRowsExplicitlyAuthorized: suppressionTotaleLignesConfirmee,
    csrfToken,
  });
}

function signatureWorkspace(payload) {
  return JSON.stringify(payload?.workspace || payload);
}

function peutSauvegarderWorkspace({ mode = "autosave", payload = null, journaliser = true } = {}) {
  const snapshot = payload || payloadWorkspace();
  const decision = evaluateWorkspacePersistence({
    workspace: snapshot.workspace,
    initialLoadCompleted: workspaceInitialLoadCompleted,
    storageAvailable: workspaceStorageAvailable,
    databaseState,
    hydrationInProgress: hydratationEnCours,
    workspaceStateSuspect,
    saveInProgress: mode !== "schedule" && sauvegardeEnCours,
    serverWorkspaceExists: workspaceExistsOnServer,
    lastServerRowCount: dernierNombreLignesServeur,
    emptyRowsExplicitlyAuthorized: suppressionTotaleLignesConfirmee,
  });

  if (!decision.allowed && journaliser) {
    console.warn(`Sauvegarde workspace annulée (${decision.reason}).`);
  }
  return decision;
}

function annulerSauvegardesPlanifiees() {
  if (timerSauvegarde) {
    window.clearTimeout(timerSauvegarde);
    timerSauvegarde = null;
  }
  sauvegardeRelance = false;
}

function bloquerPersistanceWorkspace(
  state = WORKSPACE_LOAD_STATES.STORAGE_UNAVAILABLE,
  nextDatabaseState = DATABASE_STATES.UNAVAILABLE,
) {
  workspaceStorageAvailable = false;
  workspaceStateSuspect = true;
  workspaceLoadState = state;
  annulerSauvegardesPlanifiees();
  definirEtatBase(nextDatabaseState);
}

function planifierSauvegardeWorkspace(delay = 800) {
  const decision = peutSauvegarderWorkspace({ mode: "schedule", journaliser: false });
  if (!decision.allowed) {
    return;
  }

  if (timerSauvegarde) {
    window.clearTimeout(timerSauvegarde);
  }

  timerSauvegarde = window.setTimeout(() => {
    timerSauvegarde = null;
    sauvegarderWorkspace();
  }, delay);
}

async function sauvegarderWorkspace() {
  const payload = payloadWorkspace();
  const decision = peutSauvegarderWorkspace({ mode: "autosave", payload });
  if (!decision.allowed) {
    if (decision.reason === "save_in_progress") {
      sauvegardeRelance = true;
    }
    return;
  }

  const signature = signatureWorkspace(payload);
  if (signature === derniereSignatureSauvegardee) {
    return;
  }

  sauvegardeEnCours = true;
  afficherStatutBase("Sauvegarde…", "saving");
  let sauvegardeReussie = false;
  try {
    const response = await fetch("/api/workspace", {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify(payload),
    });
    const data = await response.json().catch(() => ({}));
    if (redirigerSiSessionExpiree(response, data)) {
      return;
    }

    if (!response.ok || data?.error) {
      const error = new Error(data.message || data.error || "Echec de sauvegarde.");
      error.code = data.error || "workspace_save_failed";
      error.status = response.status;
      throw error;
    }
    if (!data.revision) {
      throw new Error("La sauvegarde n'a pas renvoyé de révision exploitable.");
    }

    workspaceRevision = data.revision;
    workspaceExistsOnServer = true;
    dernierNombreLignesServeur = payload.workspace.rows.length;
    suppressionTotaleLignesConfirmee = false;
    derniereSignatureSauvegardee = signature;
    alerteSauvegardeActive = false;
    sauvegardeReussie = true;
    afficherStatutBase("Sauvegardé", "saved");
  } catch (error) {
    const conflict = error?.status === 409 || error?.code === "workspace_conflict";
    const paused = error?.code === "supabase_paused";
    bloquerPersistanceWorkspace(
      conflict ? WORKSPACE_LOAD_STATES.CONFLICT : WORKSPACE_LOAD_STATES.STORAGE_UNAVAILABLE,
      conflict
        ? DATABASE_STATES.CONFLICT
        : paused
          ? DATABASE_STATES.SUPABASE_PAUSED
          : DATABASE_STATES.UNAVAILABLE,
    );
    if (!alerteSauvegardeActive) {
      afficherToast(
        conflict
          ? "Le workspace a changé ailleurs. Recharge la page avant de continuer."
          : paused
            ? "Le projet Supabase est en pause. Aucune écriture ne sera envoyée."
          : "Sauvegarde automatique indisponible. Recharge la page plus tard.",
        "warning",
      );
      alerteSauvegardeActive = true;
    }
    console.error("Echec de sauvegarde du workspace :", error);
  } finally {
    sauvegardeEnCours = false;

    if (sauvegardeReussie && sauvegardeRelance) {
      sauvegardeRelance = false;
      planifierSauvegardeWorkspace(250);
    }
  }
}

async function chargerWorkspacePersistant({ silencieux = false, recoveryInProgress = false } = {}) {
  annulerSauvegardesPlanifiees();
  workspaceLoadState = WORKSPACE_LOAD_STATES.LOADING;
  workspaceInitialLoadCompleted = false;
  workspaceStorageAvailable = false;
  workspaceStateSuspect = false;
  definirEtatBase(DATABASE_STATES.CHECKING);

  let schemaModifie = false;
  let signatureServeur = "";
  try {
    const response = await fetch("/api/workspace", { method: "GET", headers: { Accept: "application/json" } });
    const data = await response.json().catch(() => ({}));
    if (redirigerSiSessionExpiree(response, data)) {
      return false;
    }

    const loadErrorCode = getWorkspaceLoadErrorCode(response.ok, data);
    if (loadErrorCode) {
      const error = new Error(data.message || loadErrorCode || "Chargement du workspace impossible.");
      error.code = loadErrorCode;
      error.status = response.status;
      throw error;
    }
    if (typeof data.exists !== "boolean") {
      throw new Error("Réponse de chargement ambiguë : le champ exists est absent.");
    }
    if (data.exists && (!data.workspace || typeof data.workspace !== "object" || !data.revision)) {
      throw new Error("Réponse de chargement invalide : workspace ou révision absent.");
    }
    if (!data.exists && data.workspace !== null) {
      throw new Error("Réponse de chargement incohérente pour un workspace inexistant.");
    }

    hydratationEnCours = true;
    if (data.exists) {
      signatureServeur = signatureWorkspace({ workspace: data.workspace });
      store.hydrateWorkspace(data.workspace);
    } else {
      store.hydrateWorkspace({
        columns: [],
        rows: [],
        filters: [],
        searchQuery: "",
        sort: null,
        views: [],
        activeViewId: "",
      });
    }

    // Cette initialisation n'est autorisée qu'après une lecture distante validée.
    schemaModifie = store.ensureProspectionSchema();

    if (dom.champRecherche) {
      dom.champRecherche.value = store.state.searchQuery || "";
    }

    workspaceInitialLoadCompleted = true;
    workspaceStorageAvailable = true;
    workspaceStateSuspect = false;
    workspaceExistsOnServer = data.exists;
    workspaceRevision = data.exists ? data.revision : null;
    dernierNombreLignesServeur = data.exists && Array.isArray(data.workspace.rows) ? data.workspace.rows.length : 0;
    suppressionTotaleLignesConfirmee = false;
    workspaceLoadState = data.exists
      ? WORKSPACE_LOAD_STATES.LOADED_EXISTING
      : WORKSPACE_LOAD_STATES.LOADED_ABSENT;
    definirEtatBase(DATABASE_STATES.AVAILABLE);

    const signatureCourante = signatureWorkspace(payloadWorkspace());
    derniereSignatureSauvegardee = data.exists && schemaModifie ? signatureServeur : signatureCourante;
  } catch (error) {
    const paused = error?.code === "supabase_paused";
    bloquerPersistanceWorkspace(
      WORKSPACE_LOAD_STATES.STORAGE_UNAVAILABLE,
      recoveryInProgress
        ? DATABASE_STATES.RESTORING
        : paused
          ? DATABASE_STATES.SUPABASE_PAUSED
          : DATABASE_STATES.UNAVAILABLE,
    );
    console.error("Chargement du workspace distant impossible :", error);
    if (!silencieux) {
      afficherToast(
        paused
          ? "Le projet Supabase est en pause. Aucune sauvegarde ne sera envoyée."
          : "Base temporairement indisponible : aucune sauvegarde ne sera envoyée. Recharge la page plus tard.",
        "warning",
      );
    }
    return false;
  } finally {
    hydratationEnCours = false;
  }

  if (workspaceExistsOnServer && schemaModifie) {
    planifierSauvegardeWorkspace(400);
  }
  return true;
}

function afficherBackups(backups) {
  if (!dom.listeBackups) {
    return;
  }
  if (!Array.isArray(backups) || backups.length === 0) {
    dom.listeBackups.innerHTML = '<p class="texte-discret">Aucun backup disponible.</p>';
    return;
  }
  dom.listeBackups.innerHTML = backups
    .map((backup) => {
      const date = new Date(backup.created_at);
      const dateLabel = Number.isNaN(date.getTime()) ? texte(backup.created_at) : date.toLocaleString("fr-FR");
      return `
        <div class="backup-row">
          <div class="backup-meta">
            <strong>#${Number(backup.id)} · ${echapperHtml(backup.reason || "backup")}</strong>
            <span class="texte-discret">${echapperHtml(dateLabel)} · ${Number(backup.row_count) || 0} lignes</span>
          </div>
          <button class="btn-secondaire petit" type="button" data-restore-backup="${Number(backup.id)}">Restaurer</button>
        </div>`;
    })
    .join("");
}

async function chargerBackups() {
  if (!utilisateurAdmin || !dom.listeBackups) {
    return;
  }
  try {
    const response = await fetch("/api/admin/backups", { headers: { Accept: "application/json" } });
    const data = await response.json().catch(() => ({}));
    if (redirigerSiSessionExpiree(response, data)) {
      return;
    }
    if (!response.ok) {
      throw new Error(data.error || "Liste des backups indisponible.");
    }
    afficherBackups(data.backups);
  } catch (error) {
    dom.listeBackups.innerHTML = `<p class="texte-discret">${echapperHtml(error.message)}</p>`;
  }
}

async function creerBackupManuel() {
  if (databaseState !== DATABASE_STATES.AVAILABLE) {
    afficherToast("La base doit être connectée pour créer un backup.", "warning");
    return;
  }
  dom.btnCreerBackup.disabled = true;
  try {
    const response = await fetch("/api/admin/backups", {
      method: "POST",
      headers: jsonHeaders(),
      body: "{}",
    });
    const data = await response.json().catch(() => ({}));
    if (redirigerSiSessionExpiree(response, data)) {
      return;
    }
    if (!response.ok) {
      throw new Error(data.error || "Création du backup impossible.");
    }
    afficherToast("Backup créé.", "success");
    await chargerBackups();
  } catch (error) {
    afficherToast(error.message || "Création du backup impossible.", "danger");
  } finally {
    dom.btnCreerBackup.disabled = databaseState !== DATABASE_STATES.AVAILABLE;
  }
}

async function restaurerBackup(backupId) {
  if (!window.confirm(`Restaurer le backup #${backupId} ? Le workspace actuel sera d'abord sauvegardé.`)) {
    return;
  }

  bloquerPersistanceWorkspace(WORKSPACE_LOAD_STATES.LOADING, DATABASE_STATES.RESTORING);
  workspaceInitialLoadCompleted = false;
  try {
    const response = await fetch(`/api/admin/backups/${backupId}/restore`, {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify({ confirm: "RESTORE" }),
    });
    const data = await response.json().catch(() => ({}));
    if (redirigerSiSessionExpiree(response, data)) {
      return;
    }
    if (!response.ok) {
      throw new Error(data.error || "Restauration impossible.");
    }

    const reloaded = await chargerWorkspacePersistant({ silencieux: true, recoveryInProgress: true });
    if (!reloaded) {
      throw new Error("Backup restauré, mais le workspace n'a pas pu être rechargé.");
    }
    afficherToast("Backup restauré et workspace rechargé.", "success");
    await chargerBackups();
  } catch (error) {
    bloquerPersistanceWorkspace(WORKSPACE_LOAD_STATES.STORAGE_UNAVAILABLE, DATABASE_STATES.UNAVAILABLE);
    afficherToast(error.message || "Restauration impossible.", "danger");
  }
}

async function attendreRepriseSupabase() {
  for (let attempt = 0; attempt < 30; attempt += 1) {
    await attendre(attempt === 0 ? 2500 : 5000);
    const action = recoveryActionAfterProbe(DATABASE_STATES.RESTORING, true);
    if (action.action !== "reload_workspace") {
      continue;
    }
    const loaded = await chargerWorkspacePersistant({ silencieux: true, recoveryInProgress: true });
    if (loaded) {
      afficherToast("Supabase est de nouveau disponible. Workspace rechargé.", "success");
      await chargerBackups();
      return true;
    }
    definirEtatBase(DATABASE_STATES.RESTORING);
  }
  bloquerPersistanceWorkspace(WORKSPACE_LOAD_STATES.STORAGE_UNAVAILABLE, DATABASE_STATES.UNAVAILABLE);
  afficherToast("La reprise prend plus de temps que prévu. Réessaie plus tard.", "warning");
  return false;
}

async function reprendreSupabase() {
  if (!window.confirm("Demander la reprise du projet Supabase ? Les écritures resteront bloquées jusqu'au rechargement.")) {
    return;
  }
  bloquerPersistanceWorkspace(WORKSPACE_LOAD_STATES.LOADING, DATABASE_STATES.RESTORING);
  workspaceInitialLoadCompleted = false;
  try {
    const response = await fetch("/api/admin/supabase/resume", {
      method: "POST",
      headers: jsonHeaders(),
      body: "{}",
    });
    const data = await response.json().catch(() => ({}));
    if (redirigerSiSessionExpiree(response, data)) {
      return;
    }
    if (!response.ok && data.error !== "supabase_project_already_active") {
      throw new Error(data.message || data.error || "La reprise Supabase a échoué.");
    }
    await attendreRepriseSupabase();
  } catch (error) {
    bloquerPersistanceWorkspace(WORKSPACE_LOAD_STATES.STORAGE_UNAVAILABLE, DATABASE_STATES.SUPABASE_PAUSED);
    afficherToast(error.message || "La reprise Supabase a échoué.", "danger");
  }
}

function renderInterface() {
  const hasData = store.hasData();

  dom.etatVide.classList.toggle("hidden", hasData);
  dom.sectionTableau.classList.toggle("hidden", !hasData);

  renderFiltres();
  renderPickersFiltres();

  if (!hasData) {
    dom.statsTableau.textContent = "0 ligne";
    dom.etiquetteColonne.textContent = "Double-clique une cellule pour l'editer";
    grille.setData({ columns: [], rows: [], sort: null, selectedRowId: null, selectedColumnId: null });
    return;
  }

  const rows = store.getProcessedRows();
  const total = store.state.rows.length;
  const columns = store.getColumns({ includeHidden: false });
  const selected = store.getSelectedColumn();

  dom.statsTableau.textContent = `${rows.length} ligne(s) affichee(s) / ${total} total`;
  dom.etiquetteColonne.textContent = selected
    ? `Colonne selectionnee: ${selected.name} | Double-clique une cellule pour modifier`
    : "Double-clique une cellule pour modifier";

  if (dom.btnSupprimerLigne) {
    dom.btnSupprimerLigne.disabled = !store.state.selectedRowId;
  }

  grille.setData({
    columns,
    rows,
    sort: store.state.sort,
    selectedRowId: store.state.selectedRowId,
    selectedColumnId: store.state.selectedColumnId,
  });
}

function bindEvents() {
  dom.btnResumeSupabase?.addEventListener("click", reprendreSupabase);
  dom.btnCreerBackup?.addEventListener("click", creerBackupManuel);
  dom.listeBackups?.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-restore-backup]");
    const backupId = Number(button?.dataset.restoreBackup);
    if (Number.isInteger(backupId) && backupId > 0) {
      restaurerBackup(backupId);
    }
  });

  [dom.btnImporterHaut, dom.btnImporterVide].forEach((btn) => {
    btn?.addEventListener("click", ouvrirImport);
  });

  dom.btnExporterHaut?.addEventListener("click", ouvrirExport);
  dom.btnPartagerHaut?.addEventListener("click", ouvrirPartage);
  dom.btnAjouterLigne?.addEventListener("click", () => {
    const row = store.addRow();
    if (!row) {
      afficherToast("Aucune colonne disponible.", "warning");
      return;
    }
    afficherToast("Nouvelle ligne ajoutée.", "success");
    // Scroll en haut pour voir la nouvelle ligne (placée en tête).
    if (dom.tableScroll) {
      dom.tableScroll.scrollTop = 0;
    }
  });
  dom.btnSupprimerLigne?.addEventListener("click", ouvrirConfirmSuppression);
  dom.fermerConfirmSuppression?.addEventListener("click", fermerModalActive);
  dom.annulerSuppression?.addEventListener("click", fermerModalActive);
  dom.confirmerSuppression?.addEventListener("click", () => {
    const rowId = ligneEnAttenteSuppression;
    ligneEnAttenteSuppression = null;
    fermerModalActive();
    if (!rowId) {
      return;
    }
    store.deleteRow(rowId);
    afficherToast("Ligne supprimée.", "success");
  });

  dom.btnAjouterColonne?.addEventListener("click", ouvrirAjoutColonne);
  dom.btnGererColonnes?.addEventListener("click", () => ouvrirModalEditionColonne());

  dom.btnFiltres?.addEventListener("click", () => {
    dom.panneauFiltres.classList.toggle("hidden");
  });

  dom.btnAjouterFiltre?.addEventListener("click", () => store.addFilter());
  dom.filtresRapides?.addEventListener("click", (event) => {
    const bouton = event.target.closest("button[data-quick-filter]");
    if (!bouton) {
      return;
    }
    appliquerFiltreRapide(bouton.dataset.quickFilter);
  });

  dom.filtresRapides?.addEventListener("change", (event) => {
    const picker = event.target.closest("select[data-quick-picker]");
    if (!picker) {
      return;
    }
    appliquerPickerFiltre(picker.dataset.quickPicker, picker.value);
  });

  dom.champRecherche?.addEventListener("input", (event) => {
    store.setSearchQuery(event.target.value);
  });

  dom.listeFiltres?.addEventListener("change", (event) => {
    const row = event.target.closest("[data-filter-id]");
    if (!row) {
      return;
    }

    const filterId = row.dataset.filterId;
    const field = event.target.dataset.filterField;
    if (!filterId || !field) {
      return;
    }

    store.updateFilter(filterId, { [field]: event.target.value });
  });

  dom.listeFiltres?.addEventListener("click", (event) => {
    const remove = event.target.closest('[data-action="supprimer-filtre"]');
    if (!remove) {
      return;
    }

    const row = event.target.closest("[data-filter-id]");
    if (!row) {
      return;
    }

    store.removeFilter(row.dataset.filterId);
  });

  dom.modalBackdrop?.addEventListener("click", fermerModalActive);

  dom.fermerImport?.addEventListener("click", fermerModalActive);
  dom.fermerAjoutColonne?.addEventListener("click", fermerModalActive);
  dom.fermerEditionColonne?.addEventListener("click", fermerModalActive);
  dom.fermerExport?.addEventListener("click", fermerModalActive);
  dom.fermerPartage?.addEventListener("click", fermerModalActive);

  dom.retourUpload?.addEventListener("click", () => setEtapeImport("upload"));
  dom.confirmerImport?.addEventListener("click", confirmerImport);

  dom.zoneDepot?.addEventListener("click", () => dom.inputPdf.click());
  dom.inputPdf?.addEventListener("change", (event) => {
    importerPdf(event.target.files?.[0]);
  });

  ["dragenter", "dragover"].forEach((eventName) => {
    dom.zoneDepot?.addEventListener(eventName, (event) => {
      event.preventDefault();
      dom.zoneDepot.classList.add("is-dragover");
    });
  });

  ["dragleave", "drop"].forEach((eventName) => {
    dom.zoneDepot?.addEventListener(eventName, (event) => {
      event.preventDefault();
      dom.zoneDepot.classList.remove("is-dragover");
    });
  });

  dom.zoneDepot?.addEventListener("drop", (event) => {
    const file = event.dataTransfer?.files?.[0];
    if (file) {
      importerPdf(file);
    }
  });

  dom.creerColonne?.addEventListener("click", creerColonne);

  dom.editTypeColonne?.addEventListener("change", (event) => {
    dom.editOptionsColonne.disabled = event.target.value !== "dropdown";
  });

  dom.editSelectColonne?.addEventListener("change", (event) => {
    const columnId = texte(event.target.value);
    if (!columnId) {
      remplirFormulaireEditionColonne(null);
      return;
    }

    store.setSelectedColumn(columnId);
    remplirFormulaireEditionColonne(store.getSelectedColumn());
  });

  dom.enregistrerColonne?.addEventListener("click", enregistrerEditionColonne);
  dom.supprimerColonne?.addEventListener("click", supprimerColonneSelectionnee);
  dom.btnMonterColonne?.addEventListener("click", () => deplacerColonneSelectionnee(-1));
  dom.btnDescendreColonne?.addEventListener("click", () => deplacerColonneSelectionnee(1));

  dom.exportScope?.addEventListener("change", actualiserInfosExport);
  dom.exportRowCount?.addEventListener("input", actualiserInfosExport);
  dom.exporterMaintenant?.addEventListener("click", exporterDepuisModal);

  dom.genererLien?.addEventListener("click", genererLienPartage);
  dom.copierLien?.addEventListener("click", copierLienPartage);

  // Désélectionner la ligne courante lorsque l'utilisateur clique en dehors du tableau.
  document.addEventListener("click", (event) => {
    if (!store.state.selectedRowId) {
      return;
    }
    // Tout clic à l'intérieur de la carte du tableau garde la sélection
    // (lignes, en-têtes, bouton "Supprimer la ligne", stats).
    if (event.target.closest(".section-tableau")) {
      return;
    }
    // Tout clic à l'intérieur d'une modal ne désélectionne pas
    // (on garde la sélection pendant la confirmation de suppression).
    if (event.target.closest(".modal")) {
      return;
    }
    store.setSelectedRow(null);
  });

  // La touche Échap désélectionne (sauf pendant l'édition d'une cellule, gérée par la grille).
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    if (modalActive) return;
    if (event.defaultPrevented) return;
    if (!store.state.selectedRowId) return;
    store.setSelectedRow(null);
  });

  window.addEventListener("beforeunload", () => {
    const payload = payloadWorkspace();
    const decision = peutSauvegarderWorkspace({ mode: "beacon", payload, journaliser: false });
    if (!decision.allowed) {
      return;
    }

    const signature = signatureWorkspace(payload);
    if (signature === derniereSignatureSauvegardee) {
      return;
    }

    annulerSauvegardesPlanifiees();
    if (navigator.sendBeacon) {
      const blob = new Blob([JSON.stringify(payload)], { type: "application/json" });
      const queued = navigator.sendBeacon("/api/workspace", blob);
      if (!queued) {
        console.warn("Le beacon de sauvegarde du workspace n'a pas pu être mis en file.");
      }
    }
  });
}

async function init() {
  renderInterface();
  await chargerWorkspacePersistant();
  bindEvents();
  if (utilisateurAdmin) {
    await chargerBackups();
  }
  renderInterface();
}

init().catch((error) => {
  console.error(error);
  renderInterface();
});
