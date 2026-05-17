import { test } from "node:test";
import assert from "node:assert/strict";
import { buildWorkspaceFromImport } from "../../static/js/pdf.js";
import { ROLE_DEFAULT, STATUT_DEFAULT } from "../../static/js/schema.js";

test("buildWorkspaceFromImport produit les 12 colonnes du schéma", () => {
  const result = buildWorkspaceFromImport({
    rows: [{ "Nom club": "Stade Rennais", Ligue: "Bretagne", CD: "35" }],
    mapping: { "Nom club": "Nom club", Ligue: "Ligue", CD: "CD" },
  });
  assert.equal(result.columns.length, 12);
});

test("buildWorkspaceFromImport mappe les valeurs PDF sur les bonnes colonnes", () => {
  const result = buildWorkspaceFromImport({
    rows: [
      { "Nom club": "OL", Ligue: "Auvergne-Rhône-Alpes", CD: "69" },
      { "Nom club": "PSG", Ligue: "Île-de-France", CD: "75" },
    ],
    mapping: { "Nom club": "Nom club", Ligue: "Ligue", CD: "CD" },
  });
  assert.equal(result.rows.length, 2);
  assert.equal(result.rows[0].values.col_nom_club, "OL");
  assert.equal(result.rows[0].values.col_region, "Auvergne-Rhône-Alpes");
  assert.equal(result.rows[0].values.col_departement, "69");
});

test("buildWorkspaceFromImport applique les défauts Rôle et Statut", () => {
  const result = buildWorkspaceFromImport({
    rows: [{ "Nom club": "Test FC", Ligue: "Test", CD: "00" }],
    mapping: { "Nom club": "Nom club", Ligue: "Ligue", CD: "CD" },
  });
  const row = result.rows[0];
  assert.equal(row.values.col_role, ROLE_DEFAULT);
  assert.equal(row.values.col_statut, STATUT_DEFAULT);
});

test("buildWorkspaceFromImport laisse les colonnes non-mappées vides", () => {
  const result = buildWorkspaceFromImport({
    rows: [{ "Nom club": "Test FC", Ligue: "Test", CD: "00" }],
    mapping: { "Nom club": "Nom club", Ligue: "Ligue", CD: "CD" },
  });
  const row = result.rows[0];
  assert.equal(row.values.col_site, "");
  assert.equal(row.values.col_nom, "");
  assert.equal(row.values.col_telephone, "");
  assert.equal(row.values.col_mail, "");
  assert.equal(row.values.col_commentaires, "");
});

test("buildWorkspaceFromImport ignore les lignes complètement vides", () => {
  const result = buildWorkspaceFromImport({
    rows: [
      { "Nom club": "Real", Ligue: "x", CD: "y" },
      { "Nom club": "", Ligue: "", CD: "" },
    ],
    mapping: { "Nom club": "Nom club", Ligue: "Ligue", CD: "CD" },
  });
  assert.equal(result.rows.length, 1);
});

test("buildWorkspaceFromImport gère un mapping partiel sans crasher", () => {
  const result = buildWorkspaceFromImport({
    rows: [{ "Nom club": "Solo FC" }],
    mapping: { "Nom club": "Nom club", Ligue: "", CD: "" },
  });
  assert.equal(result.rows.length, 1);
  assert.equal(result.rows[0].values.col_nom_club, "Solo FC");
  assert.equal(result.rows[0].values.col_region, "");
  assert.equal(result.rows[0].values.col_departement, "");
});

test("buildWorkspaceFromImport renvoie un tableau de rows vide quand rien à mapper", () => {
  const result = buildWorkspaceFromImport({
    rows: [],
    mapping: { "Nom club": "Nom club", Ligue: "Ligue", CD: "CD" },
  });
  assert.equal(result.rows.length, 0);
  assert.equal(result.columns.length, 12);
});
