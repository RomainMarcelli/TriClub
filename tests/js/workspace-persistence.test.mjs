import { test } from "node:test";
import assert from "node:assert/strict";
import {
  DATABASE_STATES,
  buildWorkspaceSaveEnvelope,
  evaluateWorkspacePersistence,
  getWorkspaceLoadErrorCode,
  isExplicitLastRowDeletion,
  recoveryActionAfterProbe,
} from "../../static/js/workspace-persistence.js";

const columns = [{ id: "col_name", name: "Nom", type: "text" }];

function decision(overrides = {}) {
  return evaluateWorkspacePersistence({
    workspace: { columns, rows: [{ id: "r1", values: { col_name: "Club" } }] },
    initialLoadCompleted: true,
    storageAvailable: true,
    databaseState: DATABASE_STATES.AVAILABLE,
    hydrationInProgress: false,
    workspaceStateSuspect: false,
    saveInProgress: false,
    serverWorkspaceExists: true,
    lastServerRowCount: 1498,
    emptyRowsExplicitlyAuthorized: false,
    ...overrides,
  });
}

test("un chargement initial incomplet interdit toute sauvegarde", () => {
  assert.deepEqual(decision({ initialLoadCompleted: false }), {
    allowed: false,
    reason: "initial_load_incomplete",
  });
});

test("un stockage indisponible interdit autosave et beacon", () => {
  assert.equal(decision({ storageAvailable: false }).allowed, false);
  assert.equal(decision({ storageAvailable: false, saveInProgress: true }).allowed, false);
});

test("les états Supabase en pause et reprise bloquent autosave et beacon", () => {
  assert.deepEqual(decision({ databaseState: DATABASE_STATES.SUPABASE_PAUSED }), {
    allowed: false,
    reason: "database_supabase_paused",
  });
  assert.deepEqual(decision({ databaseState: DATABASE_STATES.RESTORING }), {
    allowed: false,
    reason: "database_restoring",
  });
});

test("une reprise exige toujours un rechargement GET avant de réautoriser la persistance", () => {
  assert.deepEqual(recoveryActionAfterProbe(DATABASE_STATES.RESTORING, true), {
    action: "reload_workspace",
    persistenceAllowed: false,
  });
  assert.deepEqual(recoveryActionAfterProbe(DATABASE_STATES.RESTORING, false), {
    action: "wait",
    persistenceAllowed: false,
  });
});

test("le format historique HTTP 200 + warning reste traité comme une panne", () => {
  assert.equal(
    getWorkspaceLoadErrorCode(true, { warning: "workspace_storage_unavailable" }),
    "workspace_storage_unavailable",
  );
});

test("un workspace chargé avec 1498 lignes reste sauvegardable après édition", () => {
  assert.deepEqual(decision(), { allowed: true, reason: "ok" });
});

test("un premier workspace réellement absent peut démarrer avec zéro ligne", () => {
  assert.equal(
    decision({
      workspace: { columns, rows: [] },
      serverWorkspaceExists: false,
      lastServerRowCount: 0,
    }).allowed,
    true,
  );
});

test("un état rows vide automatique ne peut pas écraser un workspace non vide", () => {
  assert.deepEqual(decision({ workspace: { columns, rows: [] } }), {
    allowed: false,
    reason: "empty_rows_transition_not_explicit",
  });
});

test("la suppression explicite de la dernière ligne autorise la transition à zéro", () => {
  const deletionEvent = { reason: "deleteRow", previousRowCount: 1, rowCount: 0 };
  assert.equal(isExplicitLastRowDeletion(deletionEvent, 0), true);
  assert.equal(
    decision({
      workspace: { columns, rows: [] },
      emptyRowsExplicitlyAuthorized: true,
    }).allowed,
    true,
  );
});

test("une sauvegarde en cours empêche le beacon concurrent", () => {
  assert.deepEqual(decision({ saveInProgress: true }), {
    allowed: false,
    reason: "save_in_progress",
  });
});

test("l'enveloppe POST transporte la révision et l'intention de suppression", () => {
  const workspace = { columns, rows: [] };
  const payload = buildWorkspaceSaveEnvelope(workspace, {
    initialLoadCompleted: true,
    serverWorkspaceExists: true,
    baseRevision: "revision-1",
    emptyRowsExplicitlyAuthorized: true,
    csrfToken: "csrf-test",
  });

  assert.equal(payload.workspace, workspace);
  assert.equal(payload.csrfToken, "csrf-test");
  assert.deepEqual(payload.persistence, {
    initialLoadCompleted: true,
    expectedExists: true,
    baseRevision: "revision-1",
    emptyRowsIntent: "user_deleted_all_rows",
  });
});
