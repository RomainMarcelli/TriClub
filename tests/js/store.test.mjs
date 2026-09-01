import { test } from "node:test";
import assert from "node:assert/strict";
import { WorkspaceStore } from "../../static/js/store.js";
import {
  DEFAULT_PROSPECTION_COLUMNS,
  ROLE_DEFAULT,
  STATUT_DEFAULT,
} from "../../static/js/schema.js";

function makeStore() {
  return new WorkspaceStore(() => {});
}

test("WorkspaceStore: état initial vide", () => {
  const store = makeStore();
  assert.equal(store.state.columns.length, 0);
  assert.equal(store.state.rows.length, 0);
  assert.equal(store.hasData(), false);
});

test("ensureProspectionSchema crée les 12 colonnes quand vide", () => {
  const store = makeStore();
  store.ensureProspectionSchema();
  assert.equal(store.state.columns.length, 12);
  const ids = store.state.columns.map((c) => c.id);
  assert.deepEqual(ids, DEFAULT_PROSPECTION_COLUMNS.map((c) => c.id));
});

test("ensureProspectionSchema est idempotent", () => {
  const store = makeStore();
  store.ensureProspectionSchema();
  const snapshot = JSON.stringify(store.state.columns);
  store.ensureProspectionSchema();
  store.ensureProspectionSchema();
  assert.equal(JSON.stringify(store.state.columns), snapshot);
});

test("ensureProspectionSchema migre col_ligue → col_region en préservant les valeurs", () => {
  const store = makeStore();
  store.state.columns = [
    { id: "col_nom_club", name: "Nom club", type: "text", width: 200, hidden: false, defaultValue: "", options: [] },
    { id: "col_ligue", name: "Ligue", type: "text", width: 160, hidden: false, defaultValue: "", options: [] },
    { id: "col_cd", name: "CD", type: "text", width: 130, hidden: false, defaultValue: "", options: [] },
  ];
  store.state.rows = [
    { id: "r1", values: { col_nom_club: "Club A", col_ligue: "Auvergne", col_cd: "69" } },
    { id: "r2", values: { col_nom_club: "Club B", col_ligue: "Bretagne", col_cd: "35" } },
  ];

  store.ensureProspectionSchema();

  const region = store.state.columns.find((c) => c.id === "col_region");
  const departement = store.state.columns.find((c) => c.id === "col_departement");
  assert.ok(region, "col_region doit exister après migration");
  assert.ok(departement, "col_departement doit exister après migration");
  assert.equal(store.state.rows[0].values.col_region, "Auvergne");
  assert.equal(store.state.rows[0].values.col_departement, "69");
  assert.equal(store.state.rows[1].values.col_region, "Bretagne");
  // Les anciennes clés n'existent plus.
  assert.equal(store.state.rows[0].values.col_ligue, undefined);
  assert.equal(store.state.rows[0].values.col_cd, undefined);
});

test("ensureProspectionSchema applique les défauts à Rôle et Statut", () => {
  const store = makeStore();
  store.state.columns = [
    { id: "col_nom_club", name: "Nom du club", type: "text", width: 200, hidden: false, defaultValue: "", options: [] },
  ];
  store.state.rows = [
    { id: "r1", values: { col_nom_club: "Club Test" } },
  ];

  store.ensureProspectionSchema();

  assert.equal(store.state.rows[0].values.col_role, ROLE_DEFAULT);
  assert.equal(store.state.rows[0].values.col_statut, STATUT_DEFAULT);
});

test("ensureProspectionSchema préserve les valeurs valides de Rôle/Statut", () => {
  const store = makeStore();
  store.ensureProspectionSchema();
  store.state.rows = [
    { id: "r1", values: { col_role: "coach", col_statut: "signé" } },
  ];
  store.ensureProspectionSchema();
  assert.equal(store.state.rows[0].values.col_role, "coach");
  assert.equal(store.state.rows[0].values.col_statut, "signé");
});

test("ensureProspectionSchema remplace les valeurs invalides par les défauts", () => {
  const store = makeStore();
  store.ensureProspectionSchema();
  store.state.rows = [
    { id: "r1", values: { col_role: "valeur inconnue", col_statut: "n'importe quoi" } },
  ];
  store.ensureProspectionSchema();
  assert.equal(store.state.rows[0].values.col_role, ROLE_DEFAULT);
  assert.equal(store.state.rows[0].values.col_statut, STATUT_DEFAULT);
});

test("addRow crée une ligne en tête avec les défauts", () => {
  const store = makeStore();
  store.ensureProspectionSchema();
  const before = store.state.rows.length;
  const row = store.addRow();
  assert.ok(row);
  assert.equal(store.state.rows.length, before + 1);
  assert.equal(store.state.rows[0].id, row.id);  // en tête
  assert.equal(row.values.col_role, ROLE_DEFAULT);
  assert.equal(row.values.col_statut, STATUT_DEFAULT);
  assert.equal(row.values.col_nom_club, "");
});

test("addRow renvoie null si aucune colonne", () => {
  const store = makeStore();
  assert.equal(store.addRow(), null);
});

test("deleteRow supprime une ligne par id", () => {
  const store = makeStore();
  store.ensureProspectionSchema();
  const row = store.addRow();
  store.deleteRow(row.id);
  assert.equal(store.state.rows.find((r) => r.id === row.id), undefined);
});

test("deleteRow signale explicitement la suppression de la dernière ligne", () => {
  const events = [];
  const store = new WorkspaceStore((event) => events.push(event));
  store.ensureProspectionSchema();
  const row = store.addRow();
  events.length = 0;

  store.deleteRow(row.id);

  assert.equal(events.length, 1);
  assert.equal(events[0].reason, "deleteRow");
  assert.equal(events[0].previousRowCount, 1);
  assert.equal(events[0].rowCount, 0);
});

test("setFilters ne garde que les filtres avec columnId", () => {
  const store = makeStore();
  store.ensureProspectionSchema();
  store.setFilters([
    { id: "f1", columnId: "col_region", operator: "equals", value: "Bretagne" },
    { id: "f2", columnId: "", operator: "equals", value: "x" },
  ]);
  assert.equal(store.state.filters.length, 1);
  assert.equal(store.state.filters[0].columnId, "col_region");
});

test("getProcessedRows filtre selon les critères", () => {
  const store = makeStore();
  store.ensureProspectionSchema();
  store.state.rows = [
    { id: "r1", values: { col_region: "Bretagne", col_role: "coach", col_statut: "signé" } },
    { id: "r2", values: { col_region: "Auvergne", col_role: "président", col_statut: "à contacter" } },
    { id: "r3", values: { col_region: "Bretagne", col_role: "président", col_statut: "en cours" } },
  ];
  store.bumpData("test");

  store.setFilters([
    { id: "f1", columnId: "col_region", operator: "equals", value: "Bretagne" },
  ]);

  const processed = store.getProcessedRows();
  assert.equal(processed.length, 2);
  assert.ok(processed.every((r) => r.values.col_region === "Bretagne"));
});

test("setSort trie correctement asc et desc", () => {
  const store = makeStore();
  store.ensureProspectionSchema();
  store.state.rows = [
    { id: "r1", values: { col_nom_club: "Charlie FC" } },
    { id: "r2", values: { col_nom_club: "Alpha FC" } },
    { id: "r3", values: { col_nom_club: "Bravo FC" } },
  ];
  store.bumpData("test");

  store.setSort("col_nom_club", "asc");
  let processed = store.getProcessedRows();
  assert.deepEqual(processed.map((r) => r.values.col_nom_club), ["Alpha FC", "Bravo FC", "Charlie FC"]);

  store.setSort("col_nom_club", "desc");
  processed = store.getProcessedRows();
  assert.deepEqual(processed.map((r) => r.values.col_nom_club), ["Charlie FC", "Bravo FC", "Alpha FC"]);
});

test("setSearchQuery filtre toutes les colonnes", () => {
  const store = makeStore();
  store.ensureProspectionSchema();
  store.state.rows = [
    { id: "r1", values: { col_nom_club: "Stade Rennais", col_region: "Bretagne" } },
    { id: "r2", values: { col_nom_club: "OL", col_region: "Auvergne" } },
  ];
  store.bumpData("test");

  store.setSearchQuery("bretagne");
  assert.equal(store.getProcessedRows().length, 1);

  store.setSearchQuery("");
  assert.equal(store.getProcessedRows().length, 2);
});

test("addColumn ajoute une colonne et remplit toutes les lignes existantes", () => {
  const store = makeStore();
  store.ensureProspectionSchema();
  store.addRow();
  store.addRow();
  const initialRows = store.state.rows.length;
  store.addColumn({ name: "Note", type: "text", defaultValue: "TODO" });
  const col = store.state.columns.find((c) => c.name === "Note");
  assert.ok(col);
  assert.equal(store.state.rows.length, initialRows);
  for (const row of store.state.rows) {
    assert.equal(row.values[col.id], "TODO");
  }
});

test("updateCell met à jour la valeur d'une cellule", () => {
  const store = makeStore();
  store.ensureProspectionSchema();
  const row = store.addRow();
  store.updateCell(row.id, "col_nom_club", "Stade Rochelais");
  assert.equal(store.state.rows[0].values.col_nom_club, "Stade Rochelais");
});

test("hydrateWorkspace puis ensureProspectionSchema produit un état valide", () => {
  const store = makeStore();
  store.hydrateWorkspace({
    columns: [
      { id: "col_ligue", name: "Ligue", type: "text", width: 160 },
    ],
    rows: [{ id: "r1", values: { col_ligue: "Occitanie" } }],
    filters: [],
    views: [],
  });
  store.ensureProspectionSchema();
  assert.equal(store.state.columns.length, 12);
  const r1 = store.state.rows[0];
  assert.equal(r1.values.col_region, "Occitanie");
});

test("buildExportPayload contient les colonnes et les lignes", () => {
  const store = makeStore();
  store.ensureProspectionSchema();
  store.addRow();
  const payload = store.buildExportPayload({ filename: "test", format: "numbers_csv" });
  assert.equal(payload.filename, "test");
  assert.equal(payload.format, "numbers_csv");
  assert.equal(payload.columns.length, 12);
  assert.equal(payload.rows.length, 1);
});

test("buildSharePayload n'inclut pas les colonnes hidden", () => {
  const store = makeStore();
  store.ensureProspectionSchema();
  store.updateColumn("col_telephone", { hidden: true });
  store.addRow();
  const payload = store.buildSharePayload();
  assert.equal(payload.columns.length, 11);
  assert.ok(!payload.columns.some((c) => c.id === "col_telephone"));
});

test("ensureProspectionSchema ordonne les colonnes du schéma en tête", () => {
  const store = makeStore();
  store.state.columns = [
    { id: "col_perso", name: "Perso", type: "text", width: 100, hidden: false, defaultValue: "", options: [] },
    { id: "col_role", name: "Rôle", type: "text", width: 100, hidden: false, defaultValue: "", options: [] },
  ];
  store.ensureProspectionSchema();
  const ids = store.state.columns.map((c) => c.id);
  // Schéma en tête, col_perso à la fin.
  assert.equal(ids[0], "col_nom_club");
  assert.equal(ids[ids.length - 1], "col_perso");
});
