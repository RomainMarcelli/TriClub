import { test } from "node:test";
import assert from "node:assert/strict";
import {
  DEFAULT_PROSPECTION_COLUMNS,
  LEGACY_COLUMN_MAP,
  ROLE_DEFAULT,
  ROLE_OPTIONS,
  STATUT_DEFAULT,
  STATUT_OPTIONS,
  normalizeColumnKey,
} from "../../static/js/schema.js";

test("schema: 12 colonnes dans l'ordre attendu", () => {
  assert.equal(DEFAULT_PROSPECTION_COLUMNS.length, 12);
  const ids = DEFAULT_PROSPECTION_COLUMNS.map((c) => c.id);
  assert.deepEqual(ids, [
    "col_nom_club",
    "col_region",
    "col_departement",
    "col_site",
    "col_nom",
    "col_role",
    "col_telephone",
    "col_mail",
    "col_statut",
    "col_date_premier_contact",
    "col_date_derniere_action",
    "col_commentaires",
  ]);
});

test("schema: Rôle a 9 options et 'aucune des catégories' comme défaut", () => {
  assert.equal(ROLE_OPTIONS.length, 9);
  assert.equal(ROLE_DEFAULT, "aucune des catégories");
  assert.ok(ROLE_OPTIONS.includes("président"));
  assert.ok(ROLE_OPTIONS.includes("coach"));
  assert.ok(ROLE_OPTIONS.includes(ROLE_DEFAULT));
});

test("schema: Statut a 7 options et 'à contacter' comme défaut", () => {
  assert.equal(STATUT_OPTIONS.length, 7);
  assert.equal(STATUT_DEFAULT, "à contacter");
  assert.ok(STATUT_OPTIONS.includes("signé"));
  assert.ok(STATUT_OPTIONS.includes("à relancer"));
  assert.ok(STATUT_OPTIONS.includes(STATUT_DEFAULT));
});

test("schema: la colonne Rôle est un dropdown avec le bon défaut", () => {
  const role = DEFAULT_PROSPECTION_COLUMNS.find((c) => c.id === "col_role");
  assert.equal(role.type, "dropdown");
  assert.equal(role.defaultValue, ROLE_DEFAULT);
  assert.deepEqual(role.options, ROLE_OPTIONS);
});

test("schema: la colonne Statut est un dropdown avec le bon défaut", () => {
  const statut = DEFAULT_PROSPECTION_COLUMNS.find((c) => c.id === "col_statut");
  assert.equal(statut.type, "dropdown");
  assert.equal(statut.defaultValue, STATUT_DEFAULT);
});

test("schema: les colonnes de date ont le type 'date'", () => {
  const premier = DEFAULT_PROSPECTION_COLUMNS.find((c) => c.id === "col_date_premier_contact");
  const derniere = DEFAULT_PROSPECTION_COLUMNS.find((c) => c.id === "col_date_derniere_action");
  assert.equal(premier.type, "date");
  assert.equal(derniere.type, "date");
});

test("LEGACY_COLUMN_MAP: les anciens IDs sont mappés vers les nouveaux", () => {
  assert.equal(LEGACY_COLUMN_MAP.ids.col_ligue, "col_region");
  assert.equal(LEGACY_COLUMN_MAP.ids.col_cd, "col_departement");
});

test("LEGACY_COLUMN_MAP: les anciens noms FFR sont reconnus", () => {
  assert.equal(LEGACY_COLUMN_MAP.names["nom club"], "col_nom_club");
  assert.equal(LEGACY_COLUMN_MAP.names["ligue"], "col_region");
  assert.equal(LEGACY_COLUMN_MAP.names["cd"], "col_departement");
});

test("normalizeColumnKey gère les valeurs nulles et trim", () => {
  assert.equal(normalizeColumnKey(null), "");
  assert.equal(normalizeColumnKey(undefined), "");
  assert.equal(normalizeColumnKey("  Région  "), "région");
  assert.equal(normalizeColumnKey("ROLE"), "role");
});
