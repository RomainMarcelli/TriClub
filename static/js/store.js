const COLUMN_TYPES = ["text", "number", "tag", "dropdown", "checkbox", "date"];
const ALLOWED_FILTER_OPERATORS = new Set(["equals", "contains", "starts_with", "is_empty", "is_not_empty"]);

function uid(prefix = "id") {
  return `${prefix}_${Math.random().toString(36).slice(2, 9)}`;
}

function deepClone(value) {
  return JSON.parse(JSON.stringify(value));
}

function normalize(value) {
  if (value === null || value === undefined) {
    return "";
  }
  return String(value).trim().toLowerCase();
}

function asString(value) {
  if (value === null || value === undefined) {
    return "";
  }
  return String(value).trim();
}

function asNumber(value) {
  const num = Number(value);
  return Number.isFinite(num) ? num : Number.NaN;
}

function sanitizeFilterOperator(value) {
  return ALLOWED_FILTER_OPERATORS.has(value) ? value : "contains";
}

function compareValues(a, b, type) {
  if (type === "number") {
    const na = asNumber(a);
    const nb = asNumber(b);

    if (Number.isNaN(na) && Number.isNaN(nb)) {
      return 0;
    }
    if (Number.isNaN(na)) {
      return 1;
    }
    if (Number.isNaN(nb)) {
      return -1;
    }
    return na - nb;
  }

  if (type === "date") {
    const da = Date.parse(asString(a));
    const db = Date.parse(asString(b));

    if (Number.isNaN(da) && Number.isNaN(db)) {
      return 0;
    }
    if (Number.isNaN(da)) {
      return 1;
    }
    if (Number.isNaN(db)) {
      return -1;
    }
    return da - db;
  }

  return asString(a).localeCompare(asString(b), "fr", { sensitivity: "base" });
}

function evaluateFilter(value, operator, expected) {
  const text = asString(value);
  const normalizedText = normalize(text);
  const normalizedExpected = normalize(expected);

  if (operator === "equals") {
    return normalizedText === normalizedExpected;
  }
  if (operator === "contains") {
    return normalizedText.includes(normalizedExpected);
  }
  if (operator === "starts_with") {
    return normalizedText.startsWith(normalizedExpected);
  }
  if (operator === "is_empty") {
    return normalizedText.length === 0;
  }
  if (operator === "is_not_empty") {
    return normalizedText.length > 0;
  }

  return true;
}

export class WorkspaceStore {
  constructor(onChange = () => {}) {
    this.onChange = onChange;

    this.state = {
      columns: [],
      rows: [],
      filters: [],
      searchQuery: "",
      sort: null,
      views: [
        {
          id: "view_default",
          name: "Vue par defaut",
          filters: [],
          sort: null,
          hiddenColumnIds: [],
        },
      ],
      activeViewId: "view_default",
      selectedColumnId: null,
      selectedRowId: null,
    };

    this.dataVersion = 0;
    this.viewVersion = 0;
    this.cache = {
      key: "",
      rows: [],
    };
  }

  emit(reason = "update") {
    this.onChange({ reason, state: this.state });
  }

  bumpData(reason) {
    this.dataVersion += 1;
    this.cache.key = "";
    this.emit(reason);
  }

  bumpView(reason) {
    this.viewVersion += 1;
    this.cache.key = "";
    this.syncActiveViewSnapshot();
    this.emit(reason);
  }

  hasData() {
    return this.state.columns.length > 0 && this.state.rows.length > 0;
  }

  resetWorkspace(columns, rows) {
    this.state.columns = columns.map((col, index) => ({
      id: asString(col.id || uid("col")),
      name: asString(col.name || `Colonne ${index + 1}`),
      type: COLUMN_TYPES.includes(col.type) ? col.type : "text",
      width: Number.isFinite(Number(col.width)) ? Math.max(100, Math.min(600, Number(col.width))) : 180,
      hidden: Boolean(col.hidden),
      defaultValue: asString(col.defaultValue || ""),
      options: Array.isArray(col.options)
        ? col.options.map((opt) => asString(opt)).filter(Boolean)
        : [],
    }));

    this.state.rows = rows.map((row) => ({
      id: asString(row.id || uid("row")),
      values: { ...(row.values || {}) },
    }));

    this.state.filters = [];
    this.state.searchQuery = "";
    this.state.sort = null;
    this.state.views = [
      {
        id: "view_default",
        name: "Vue par defaut",
        filters: [],
        sort: null,
        hiddenColumnIds: [],
      },
    ];
    this.state.activeViewId = "view_default";
    this.state.selectedColumnId = this.state.columns[0]?.id || null;
    this.state.selectedRowId = null;

    this.dataVersion += 1;
    this.viewVersion += 1;
    this.cache.key = "";
    this.emit("resetWorkspace");
  }

  getColumns({ includeHidden = true } = {}) {
    if (includeHidden) {
      return this.state.columns;
    }
    return this.state.columns.filter((col) => !col.hidden);
  }

  getColumnById(columnId) {
    return this.state.columns.find((col) => col.id === columnId) || null;
  }

  getSelectedColumn() {
    return this.getColumnById(this.state.selectedColumnId);
  }

  getSelectedRow() {
    return this.state.rows.find((row) => row.id === this.state.selectedRowId) || null;
  }

  setSearchQuery(value) {
    this.state.searchQuery = asString(value);
    this.bumpView("setSearchQuery");
  }

  addFilter() {
    const firstColumn = this.state.columns[0];
    if (!firstColumn) {
      return;
    }

    this.state.filters.push({
      id: uid("filter"),
      columnId: firstColumn.id,
      operator: "contains",
      value: "",
    });
    this.bumpView("addFilter");
  }

  updateFilter(filterId, patch) {
    const filter = this.state.filters.find((item) => item.id === filterId);
    if (!filter) {
      return;
    }

    Object.assign(filter, patch || {});
    this.bumpView("updateFilter");
  }

  removeFilter(filterId) {
    const next = this.state.filters.filter((item) => item.id !== filterId);
    if (next.length === this.state.filters.length) {
      return;
    }

    this.state.filters = next;
    this.bumpView("removeFilter");
  }

  clearFilters() {
    this.state.filters = [];
    this.bumpView("clearFilters");
  }

  setFilters(filters = []) {
    if (!Array.isArray(filters)) {
      return;
    }

    const cleaned = filters
      .map((filter) => ({
        id: asString(filter?.id || uid("filter")),
        columnId: asString(filter?.columnId || ""),
        operator: sanitizeFilterOperator(filter?.operator),
        value: asString(filter?.value || ""),
      }))
      .filter((filter) => filter.columnId);

    this.state.filters = cleaned;
    this.bumpView("setFilters");
  }

  setSort(columnId, direction = "asc") {
    const safeColumnId = asString(columnId || "");
    if (!safeColumnId || !this.getColumnById(safeColumnId)) {
      return;
    }

    this.state.sort = {
      columnId: safeColumnId,
      direction: direction === "desc" ? "desc" : "asc",
    };
    this.bumpView("setSort");
  }

  clearSort() {
    this.state.sort = null;
    this.bumpView("clearSort");
  }

  cycleSort(columnId) {
    if (!columnId) {
      return;
    }

    const current = this.state.sort;
    if (!current || current.columnId !== columnId) {
      this.state.sort = { columnId, direction: "asc" };
      this.bumpView("sortAsc");
      return;
    }

    if (current.direction === "asc") {
      this.state.sort = { columnId, direction: "desc" };
      this.bumpView("sortDesc");
      return;
    }

    this.state.sort = null;
    this.bumpView("clearSort");
  }

  setSelectedColumn(columnId) {
    if (this.state.selectedColumnId === columnId) {
      return;
    }
    this.state.selectedColumnId = columnId;
    this.emit("setSelectedColumn");
  }

  setSelectedRow(rowId) {
    if (this.state.selectedRowId === rowId) {
      return;
    }
    this.state.selectedRowId = rowId;
    this.emit("setSelectedRow");
  }

  addColumn({ name, type = "text", defaultValue = "", options = [] }) {
    const finalName = asString(name || "");
    if (!finalName) {
      return null;
    }

    const column = {
      id: uid("col"),
      name: finalName,
      type: COLUMN_TYPES.includes(type) ? type : "text",
      width: 180,
      hidden: false,
      defaultValue: asString(defaultValue),
      options: Array.isArray(options) ? options.map((opt) => asString(opt)).filter(Boolean) : [],
    };

    this.state.columns.push(column);

    const fillValue = column.type === "checkbox" ? "false" : column.defaultValue;
    this.state.rows.forEach((row) => {
      row.values[column.id] = fillValue;
    });

    this.state.selectedColumnId = column.id;
    this.bumpData("addColumn");
    return column;
  }

  updateColumn(columnId, patch) {
    const column = this.getColumnById(columnId);
    if (!column) {
      return;
    }

    if (patch.name !== undefined) {
      const nextName = asString(patch.name);
      if (nextName) {
        column.name = nextName;
      }
    }

    if (patch.type !== undefined && COLUMN_TYPES.includes(patch.type)) {
      column.type = patch.type;
    }

    if (patch.defaultValue !== undefined) {
      column.defaultValue = asString(patch.defaultValue);
    }

    if (patch.hidden !== undefined) {
      column.hidden = Boolean(patch.hidden);
    }

    if (patch.width !== undefined) {
      const width = Number(patch.width);
      if (Number.isFinite(width)) {
        column.width = Math.max(100, Math.min(600, Math.round(width)));
      }
    }

    if (patch.options !== undefined && Array.isArray(patch.options)) {
      column.options = patch.options.map((opt) => asString(opt)).filter(Boolean);
    }

    this.bumpData("updateColumn");
  }

  deleteColumn(columnId) {
    const nextColumns = this.state.columns.filter((col) => col.id !== columnId);
    if (nextColumns.length === this.state.columns.length) {
      return;
    }

    this.state.columns = nextColumns;
    this.state.rows.forEach((row) => {
      delete row.values[columnId];
    });

    this.state.selectedColumnId = this.state.columns[0]?.id || null;
    this.bumpData("deleteColumn");
  }

  reorderColumns(sourceId, targetId) {
    if (!sourceId || !targetId || sourceId === targetId) {
      return;
    }

    const columns = this.state.columns.slice();
    const sourceIndex = columns.findIndex((col) => col.id === sourceId);
    const targetIndex = columns.findIndex((col) => col.id === targetId);

    if (sourceIndex < 0 || targetIndex < 0) {
      return;
    }

    const [moved] = columns.splice(sourceIndex, 1);
    columns.splice(targetIndex, 0, moved);

    this.state.columns = columns;
    this.bumpData("reorderColumns");
  }

  updateCell(rowId, columnId, value) {
    const row = this.state.rows.find((item) => item.id === rowId);
    const column = this.getColumnById(columnId);
    if (!row || !column) {
      return;
    }

    let nextValue = value;
    if (column.type === "checkbox") {
      nextValue = value === true || value === "true" ? "true" : "false";
    } else {
      nextValue = asString(value);
    }

    row.values[columnId] = nextValue;
    this.bumpData("updateCell");
  }

  updateRowValues(rowId, patchValues) {
    const row = this.state.rows.find((item) => item.id === rowId);
    if (!row || !patchValues || typeof patchValues !== "object") {
      return;
    }

    Object.keys(patchValues).forEach((columnId) => {
      this.updateCell(rowId, columnId, patchValues[columnId]);
    });
  }

  saveCurrentView(name) {
    const viewName = asString(name || "");
    if (!viewName) {
      return null;
    }

    const view = {
      id: uid("view"),
      name: viewName,
      filters: deepClone(this.state.filters),
      sort: this.state.sort ? { ...this.state.sort } : null,
      hiddenColumnIds: this.state.columns.filter((col) => col.hidden).map((col) => col.id),
    };

    this.state.views.push(view);
    this.state.activeViewId = view.id;
    this.bumpView("saveCurrentView");
    return view;
  }

  applyView(viewId) {
    const view = this.state.views.find((item) => item.id === viewId);
    if (!view) {
      return;
    }

    this.state.activeViewId = view.id;
    this.state.filters = deepClone(view.filters || []);
    this.state.sort = view.sort ? { ...view.sort } : null;

    const hiddenIds = new Set(view.hiddenColumnIds || []);
    this.state.columns.forEach((col) => {
      col.hidden = hiddenIds.has(col.id);
    });

    this.bumpView("applyView");
  }

  syncActiveViewSnapshot() {
    const view = this.state.views.find((item) => item.id === this.state.activeViewId);
    if (!view) {
      return;
    }

    view.filters = deepClone(this.state.filters);
    view.sort = this.state.sort ? { ...this.state.sort } : null;
    view.hiddenColumnIds = this.state.columns.filter((col) => col.hidden).map((col) => col.id);
  }

  getProcessedRows() {
    const key = `${this.dataVersion}:${this.viewVersion}`;
    if (this.cache.key === key) {
      return this.cache.rows;
    }

    const { rows, columns, filters, searchQuery, sort } = this.state;
    const columnsById = new Map(columns.map((col) => [col.id, col]));

    let output = rows.slice();

    if (filters.length > 0) {
      output = output.filter((row) => {
        return filters.every((filter) => {
          const col = columnsById.get(filter.columnId);
          if (!col) {
            return true;
          }
          const value = row.values[col.id] ?? "";
          return evaluateFilter(value, filter.operator, filter.value);
        });
      });
    }

    const globalQuery = normalize(searchQuery);
    if (globalQuery) {
      output = output.filter((row) => {
        return columns.some((column) => normalize(row.values[column.id] ?? "").includes(globalQuery));
      });
    }

    if (sort && sort.columnId) {
      const sortColumn = columnsById.get(sort.columnId);
      if (sortColumn) {
        output = output.slice().sort((a, b) => {
          const result = compareValues(a.values[sortColumn.id] ?? "", b.values[sortColumn.id] ?? "", sortColumn.type);
          return sort.direction === "desc" ? -result : result;
        });
      }
    }

    this.cache = {
      key,
      rows: output,
    };
    return output;
  }

  getActiveViewName() {
    const view = this.state.views.find((item) => item.id === this.state.activeViewId);
    return view?.name || "Vue par defaut";
  }

  hydrateWorkspace(snapshot) {
    if (!snapshot || typeof snapshot !== "object") {
      return;
    }

    const allowedOps = new Set(["equals", "contains", "starts_with", "is_empty", "is_not_empty"]);
    const rawColumns = Array.isArray(snapshot.columns) ? snapshot.columns : [];
    const rawRows = Array.isArray(snapshot.rows) ? snapshot.rows : [];
    const rawFilters = Array.isArray(snapshot.filters) ? snapshot.filters : [];
    const rawViews = Array.isArray(snapshot.views) ? snapshot.views : [];

    const columns = rawColumns
      .map((col, index) => ({
        id: asString(col?.id || uid("col")),
        name: asString(col?.name || `Colonne ${index + 1}`),
        type: COLUMN_TYPES.includes(col?.type) ? col.type : "text",
        width: Number.isFinite(Number(col?.width)) ? Math.max(100, Math.min(600, Number(col.width))) : 180,
        hidden: Boolean(col?.hidden),
        defaultValue: asString(col?.defaultValue || ""),
        options: Array.isArray(col?.options) ? col.options.map((opt) => asString(opt)).filter(Boolean) : [],
      }))
      .filter((col) => col.id && col.name);

    const rows = rawRows.map((row) => ({
      id: asString(row?.id || uid("row")),
      values: row?.values && typeof row.values === "object" ? { ...row.values } : {},
    }));

    const filters = rawFilters
      .map((filter) => ({
        id: asString(filter?.id || uid("filter")),
        columnId: asString(filter?.columnId || ""),
        operator: allowedOps.has(filter?.operator) ? filter.operator : "contains",
        value: asString(filter?.value || ""),
      }))
      .filter((filter) => filter.columnId);

    const sanitizeSort = (value) => {
      if (!value || typeof value !== "object") {
        return null;
      }
      const columnId = asString(value.columnId || "");
      const direction = value.direction === "desc" ? "desc" : "asc";
      if (!columnId) {
        return null;
      }
      return { columnId, direction };
    };

    const sort = sanitizeSort(snapshot.sort);

    let views = rawViews
      .map((view, index) => ({
        id: asString(view?.id || uid("view")),
        name: asString(view?.name || `Vue ${index + 1}`),
        filters: Array.isArray(view?.filters)
          ? view.filters
              .map((filter) => ({
                id: asString(filter?.id || uid("filter")),
                columnId: asString(filter?.columnId || ""),
                operator: allowedOps.has(filter?.operator) ? filter.operator : "contains",
                value: asString(filter?.value || ""),
              }))
              .filter((filter) => filter.columnId)
          : [],
        sort: sanitizeSort(view?.sort),
        hiddenColumnIds: Array.isArray(view?.hiddenColumnIds)
          ? view.hiddenColumnIds.map((id) => asString(id)).filter(Boolean)
          : [],
      }))
      .filter((view) => view.id && view.name);

    if (!views.length) {
      views = [
        {
          id: "view_default",
          name: "Vue par defaut",
          filters: [],
          sort: null,
          hiddenColumnIds: [],
        },
      ];
    }

    const activeViewId = asString(snapshot.activeViewId || "");
    const hasActive = views.some((view) => view.id === activeViewId);

    this.state.columns = columns;
    this.state.rows = rows;
    this.state.filters = filters;
    this.state.searchQuery = asString(snapshot.searchQuery || "");
    this.state.sort = sort;
    this.state.views = views;
    this.state.activeViewId = hasActive ? activeViewId : views[0].id;
    this.state.selectedColumnId = asString(snapshot.selectedColumnId || this.state.columns[0]?.id || "");
    this.state.selectedRowId = asString(snapshot.selectedRowId || "");

    if (!this.state.columns.some((col) => col.id === this.state.selectedColumnId)) {
      this.state.selectedColumnId = this.state.columns[0]?.id || null;
    }
    if (!this.state.rows.some((row) => row.id === this.state.selectedRowId)) {
      this.state.selectedRowId = null;
    }

    this.dataVersion += 1;
    this.viewVersion += 1;
    this.cache.key = "";
    this.emit("hydrateWorkspace");
  }

  getPersistencePayload() {
    return deepClone({
      columns: this.state.columns,
      rows: this.state.rows,
      filters: this.state.filters,
      searchQuery: this.state.searchQuery,
      sort: this.state.sort,
      views: this.state.views,
      activeViewId: this.state.activeViewId,
      selectedColumnId: this.state.selectedColumnId,
      selectedRowId: this.state.selectedRowId,
    });
  }

  buildExportPayload({ filteredOnly = false, includeHidden = true, filename = "export_numbers" } = {}) {
    const columns = includeHidden ? this.state.columns.slice() : this.getColumns({ includeHidden: false });
    const sourceRows = filteredOnly ? this.getProcessedRows() : this.state.rows;

    const payloadRows = sourceRows.map((row) => {
      const values = {};
      columns.forEach((col) => {
        values[col.id] = asString(row.values[col.id] ?? "");
      });
      return { id: row.id, values };
    });

    return {
      filename,
      columns: columns.map((col) => ({
        id: col.id,
        name: col.name,
        type: col.type,
        width: col.width,
        hidden: col.hidden,
        options: col.options,
        defaultValue: col.defaultValue,
      })),
      rows: payloadRows,
    };
  }

  buildSharePayload() {
    const visibleColumns = this.getColumns({ includeHidden: false });
    const rows = this.getProcessedRows();

    return {
      name: this.getActiveViewName(),
      generatedAt: new Date().toISOString(),
      columns: visibleColumns.map((col) => ({
        id: col.id,
        name: col.name,
        type: col.type,
        width: col.width,
        hidden: false,
        options: col.options,
      })),
      rows: rows.map((row) => {
        const values = {};
        visibleColumns.forEach((col) => {
          values[col.id] = asString(row.values[col.id] ?? "");
        });
        return { id: row.id, values };
      }),
    };
  }

  getColumnTypes() {
    return COLUMN_TYPES.slice();
  }
}

export const FILTER_OPERATORS = [
  { value: "equals", label: "egal a" },
  { value: "contains", label: "contient" },
  { value: "starts_with", label: "commence par" },
  { value: "is_empty", label: "est vide" },
  { value: "is_not_empty", label: "n'est pas vide" },
];
