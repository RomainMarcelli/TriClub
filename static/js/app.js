import { FILTER_OPERATORS, WorkspaceStore } from "./store.js";
import { buildWorkspaceFromImport, uploadPdfWithProgress } from "./pdf.js";
import { VirtualGrid } from "./table.js";
import { ROLE_OPTIONS, STATUT_OPTIONS } from "./schema.js";

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
};

const RAISONS_SANS_SAUVEGARDE = new Set(["setSelectedColumn", "setSelectedRow"]);

let hydratationEnCours = false;
let timerSauvegarde = null;
let sauvegardeEnCours = false;
let sauvegardeRelance = false;
let alerteSauvegardeActive = false;
let derniereSignatureSauvegardee = "";

const store = new WorkspaceStore((event = {}) => {
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
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
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
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ workspace: store.buildSharePayload() }),
    });

    const data = await response.json().catch(() => ({}));
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
  return { workspace: store.getPersistencePayload() };
}

function signatureWorkspace(payload) {
  return JSON.stringify(payload);
}

function planifierSauvegardeWorkspace(delay = 800) {
  if (timerSauvegarde) {
    window.clearTimeout(timerSauvegarde);
  }

  timerSauvegarde = window.setTimeout(() => {
    timerSauvegarde = null;
    sauvegarderWorkspace();
  }, delay);
}

async function sauvegarderWorkspace() {
  if (hydratationEnCours) {
    return;
  }

  if (sauvegardeEnCours) {
    sauvegardeRelance = true;
    return;
  }

  const payload = payloadWorkspace();

  // Garde-fou : si on n'a aucune colonne en mémoire, on ne sauvegarde JAMAIS.
  // Un workspace sans colonne ni ligne est presque toujours un état erroné
  // (échec de chargement, race condition, etc.) qui écraserait des données réelles.
  if (!payload.workspace.columns || payload.workspace.columns.length === 0) {
    console.warn("Sauvegarde annulée : workspace sans colonne (état suspect).");
    return;
  }

  const signature = signatureWorkspace(payload);
  if (signature === derniereSignatureSauvegardee) {
    return;
  }

  sauvegardeEnCours = true;
  try {
    const response = await fetch("/api/workspace", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: signature,
    });

    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.error || "Echec de sauvegarde.");
    }

    derniereSignatureSauvegardee = signature;
    alerteSauvegardeActive = false;
  } catch (error) {
    if (!alerteSauvegardeActive) {
      afficherToast("Sauvegarde automatique indisponible.", "warning");
      alerteSauvegardeActive = true;
    }
    console.error(error);
  } finally {
    sauvegardeEnCours = false;

    if (sauvegardeRelance) {
      sauvegardeRelance = false;
      planifierSauvegardeWorkspace(250);
    }
  }
}

async function chargerWorkspacePersistant() {
  let chargementOk = false;
  try {
    const response = await fetch("/api/workspace", { method: "GET", headers: { Accept: "application/json" } });
    if (!response.ok) {
      return;
    }

    const data = await response.json().catch(() => ({}));

    hydratationEnCours = true;
    if (data?.workspace) {
      store.hydrateWorkspace(data.workspace);
    }

    // Migration douce + initialisation : garantit le schéma de prospection cible.
    store.ensureProspectionSchema();

    if (dom.champRecherche) {
      dom.champRecherche.value = store.state.searchQuery || "";
    }

    derniereSignatureSauvegardee = signatureWorkspace(payloadWorkspace());
    chargementOk = true;
  } catch (error) {
    console.error(error);
  } finally {
    hydratationEnCours = false;
  }

  // SECURITE : on ne déclenche JAMAIS d'auto-save tant qu'on n'a pas chargé l'état
  // existant avec succès — sinon une coupure réseau au démarrage écraserait les
  // données par un état vide.
  if (!chargementOk) {
    return;
  }
  // Si la migration a apporté des changements, l'auto-save les persistera après debounce.
  // Mais seulement si on a des données (jamais auto-save un workspace vide).
  if (store.state.columns.length > 0) {
    planifierSauvegardeWorkspace(400);
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
    if (hydratationEnCours) {
      return;
    }
    if (timerSauvegarde) {
      window.clearTimeout(timerSauvegarde);
      timerSauvegarde = null;
    }

    const payload = payloadWorkspace();
    const signature = signatureWorkspace(payload);
    if (signature === derniereSignatureSauvegardee) {
      return;
    }

    if (navigator.sendBeacon) {
      const blob = new Blob([signature], { type: "application/json" });
      navigator.sendBeacon("/api/workspace", blob);
    }
  });
}

async function init() {
  bindEvents();
  await chargerWorkspacePersistant();
  renderInterface();
}

init().catch((error) => {
  console.error(error);
  renderInterface();
});
