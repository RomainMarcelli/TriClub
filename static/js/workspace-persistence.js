export const WORKSPACE_LOAD_STATES = Object.freeze({
  NOT_STARTED: "not_started",
  LOADING: "loading",
  LOADED_EXISTING: "loaded_existing",
  LOADED_ABSENT: "loaded_absent",
  STORAGE_UNAVAILABLE: "storage_unavailable",
  CONFLICT: "conflict",
});

export const DATABASE_STATES = Object.freeze({
  CHECKING: "checking",
  AVAILABLE: "available",
  UNAVAILABLE: "unavailable",
  SUPABASE_PAUSED: "supabase_paused",
  RESTORING: "restoring",
  CONFLICT: "conflict",
});

export function getWorkspaceLoadErrorCode(responseOk, data) {
  if (data?.error) {
    return String(data.error);
  }
  if (data?.warning === "workspace_storage_unavailable") {
    return "workspace_storage_unavailable";
  }
  if (!responseOk) {
    return "workspace_load_failed";
  }
  return null;
}

export function evaluateWorkspacePersistence({
  workspace,
  initialLoadCompleted,
  storageAvailable,
  databaseState,
  hydrationInProgress,
  workspaceStateSuspect,
  saveInProgress = false,
  serverWorkspaceExists,
  lastServerRowCount,
  emptyRowsExplicitlyAuthorized,
}) {
  if (databaseState && databaseState !== DATABASE_STATES.AVAILABLE) {
    return { allowed: false, reason: `database_${databaseState}` };
  }
  if (!initialLoadCompleted) {
    return { allowed: false, reason: "initial_load_incomplete" };
  }
  if (!storageAvailable) {
    return { allowed: false, reason: "storage_unavailable" };
  }
  if (hydrationInProgress) {
    return { allowed: false, reason: "hydration_in_progress" };
  }
  if (workspaceStateSuspect) {
    return { allowed: false, reason: "workspace_state_suspect" };
  }
  if (saveInProgress) {
    return { allowed: false, reason: "save_in_progress" };
  }
  if (!workspace || !Array.isArray(workspace.columns) || !Array.isArray(workspace.rows)) {
    return { allowed: false, reason: "workspace_payload_invalid" };
  }
  if (workspace.columns.length === 0) {
    return { allowed: false, reason: "workspace_without_columns" };
  }
  if (
    serverWorkspaceExists &&
    Number(lastServerRowCount) > 0 &&
    workspace.rows.length === 0 &&
    !emptyRowsExplicitlyAuthorized
  ) {
    return { allowed: false, reason: "empty_rows_transition_not_explicit" };
  }
  return { allowed: true, reason: "ok" };
}

export function buildWorkspaceSaveEnvelope(workspace, {
  initialLoadCompleted,
  serverWorkspaceExists,
  baseRevision,
  emptyRowsExplicitlyAuthorized,
  csrfToken,
}) {
  return {
    workspace,
    csrfToken: csrfToken || null,
    persistence: {
      initialLoadCompleted: initialLoadCompleted === true,
      expectedExists: serverWorkspaceExists === true,
      baseRevision: baseRevision || null,
      emptyRowsIntent: emptyRowsExplicitlyAuthorized ? "user_deleted_all_rows" : null,
    },
  };
}

export function getSupabaseResumeButtonState(databaseState, inProgress) {
  const loading = inProgress === true;
  return {
    visible:
      databaseState === DATABASE_STATES.SUPABASE_PAUSED ||
      (loading && databaseState === DATABASE_STATES.RESTORING),
    disabled: loading,
    loading,
    label: loading ? "Réactivation en cours…" : "Réactiver Supabase",
  };
}

export function isExplicitLastRowDeletion(event, currentRowCount) {
  return (
    event?.reason === "deleteRow" &&
    Number(event.previousRowCount) === 1 &&
    Number(currentRowCount) === 0
  );
}
