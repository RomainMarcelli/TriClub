function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function asText(value) {
  if (value === null || value === undefined) {
    return "";
  }
  return String(value);
}

export class VirtualGrid {
  constructor({ scrollEl, headEl, bodyEl, callbacks = {} }) {
    this.scrollEl = scrollEl;
    this.headEl = headEl;
    this.bodyEl = bodyEl;
    this.callbacks = {
      onCellChange: callbacks.onCellChange || (() => {}),
      onRowSelect: callbacks.onRowSelect || (() => {}),
      onColumnSelect: callbacks.onColumnSelect || (() => {}),
      onSort: callbacks.onSort || (() => {}),
      onReorderColumns: callbacks.onReorderColumns || (() => {}),
      onResizeColumn: callbacks.onResizeColumn || (() => {}),
    };

    this.rowHeight = 44;
    this.overscan = 8;

    this.columns = [];
    this.rows = [];
    this.sort = null;
    this.selectedRowId = null;
    this.selectedColumnId = null;

    this.visibleColumns = [];
    this.dragColumnId = null;
    this.pendingFocus = null;
    this.editingCellKey = null;

    this.resizing = null;
    this.handleResizeMove = this.handleResizeMove.bind(this);
    this.handleResizeEnd = this.handleResizeEnd.bind(this);

    this.scrollEl.addEventListener("scroll", () => this.renderBody());
    this.headEl.addEventListener("click", (event) => this.handleHeadClick(event));
    this.headEl.addEventListener("dragstart", (event) => this.handleHeaderDragStart(event));
    this.headEl.addEventListener("dragover", (event) => this.handleHeaderDragOver(event));
    this.headEl.addEventListener("dragleave", (event) => this.handleHeaderDragLeave(event));
    this.headEl.addEventListener("drop", (event) => this.handleHeaderDrop(event));
    this.headEl.addEventListener("mousedown", (event) => this.handleHeaderMouseDown(event));

    this.bodyEl.addEventListener("click", (event) => this.handleBodyClick(event));
    this.bodyEl.addEventListener("dblclick", (event) => this.handleBodyDoubleClick(event));
    this.bodyEl.addEventListener("focusin", (event) => this.handleBodyFocus(event));
    this.bodyEl.addEventListener("focusout", (event) => this.handleBodyFocusOut(event));
    this.bodyEl.addEventListener("change", (event) => this.handleCellMutation(event));
    this.bodyEl.addEventListener("input", (event) => this.handleCellMutation(event));
    this.bodyEl.addEventListener("keydown", (event) => this.handleCellKeydown(event));
  }

  setData({ columns, rows, sort, selectedRowId, selectedColumnId }) {
    this.columns = Array.isArray(columns) ? columns.slice() : [];
    this.rows = Array.isArray(rows) ? rows.slice() : [];
    this.sort = sort || null;
    this.selectedRowId = selectedRowId || null;
    this.selectedColumnId = selectedColumnId || null;

    this.visibleColumns = this.columns.filter((col) => !col.hidden);
    this.editingCellKey = null;
    this.renderHeader();
    this.renderBody();
  }

  renderHeader() {
    const cells = this.visibleColumns
      .map((col) => {
        const width = Number(col.width) || 180;
        const sortIndicator = this.sort && this.sort.columnId === col.id ? (this.sort.direction === "asc" ? "ASC" : "DESC") : "";
        const selectedClass = col.id === this.selectedColumnId ? "selected" : "";

        return `
          <th
            class="header-cell ${selectedClass}"
            data-col-id="${escapeHtml(col.id)}"
            draggable="true"
            style="width:${width}px;min-width:${width}px;max-width:${width}px"
          >
            <button type="button" class="header-label" data-sort-col="${escapeHtml(col.id)}">
              <span>${escapeHtml(col.name)}</span>
              <span class="sort-indicator">${sortIndicator}</span>
            </button>
            <span class="type-pill">${escapeHtml(col.type)}</span>
            <span class="col-resizer" data-resize-col="${escapeHtml(col.id)}"></span>
          </th>
        `;
      })
      .join("");

    this.headEl.innerHTML = `<tr>${cells}</tr>`;
  }

  renderBody() {
    const total = this.rows.length;
    const viewportHeight = this.scrollEl.clientHeight || 600;
    const scrollTop = this.scrollEl.scrollTop || 0;

    const start = Math.max(0, Math.floor(scrollTop / this.rowHeight) - this.overscan);
    const end = Math.min(total, Math.ceil((scrollTop + viewportHeight) / this.rowHeight) + this.overscan);

    const topHeight = start * this.rowHeight;
    const bottomHeight = (total - end) * this.rowHeight;

    const colCount = Math.max(1, this.visibleColumns.length);

    let bodyHtml = "";
    bodyHtml += `<tr class="spacer-row"><td colspan="${colCount}" style="height:${topHeight}px"></td></tr>`;

    for (let index = start; index < end; index += 1) {
      const row = this.rows[index];
      const selectedClass = row.id === this.selectedRowId ? "row-selected" : "";

      const cells = this.visibleColumns
        .map((col, colIndex) => {
          const rawValue = row.values[col.id] ?? "";
          const value = asText(rawValue);
          return `<td class="cell" data-col-id="${escapeHtml(col.id)}">${this.renderCellControl({
            rowId: row.id,
            col,
            value,
            rowIndex: index,
            colIndex,
          })}</td>`;
        })
        .join("");

      bodyHtml += `<tr class="data-row ${selectedClass}" data-row-id="${escapeHtml(row.id)}" data-row-index="${index}">${cells}</tr>`;
    }

    bodyHtml += `<tr class="spacer-row"><td colspan="${colCount}" style="height:${bottomHeight}px"></td></tr>`;
    this.bodyEl.innerHTML = bodyHtml;

    this.applyPendingFocus();
  }

  renderCellControl({ rowId, col, value, rowIndex, colIndex }) {
    const attrs = `class="cell-control" data-row-id="${escapeHtml(rowId)}" data-col-id="${escapeHtml(col.id)}" data-row-index="${rowIndex}" data-col-index="${colIndex}"`;

    if (col.type === "checkbox") {
      const checked = value === "true" ? "checked" : "";
      return `<input ${attrs} type="checkbox" ${checked} />`;
    }

    if (col.type === "dropdown") {
      const options = Array.isArray(col.options) ? col.options : [];
      const optionNodes = [`<option value=""></option>`]
        .concat(
          options.map((option) => {
            const selected = option === value ? "selected" : "";
            return `<option value="${escapeHtml(option)}" ${selected}>${escapeHtml(option)}</option>`;
          })
        )
        .join("");

      return `<select ${attrs} data-locked="true">${optionNodes}</select>`;
    }

    if (col.type === "date") {
      return `<input ${attrs} type="date" value="${escapeHtml(value)}" readonly />`;
    }

    if (col.type === "number") {
      return `<input ${attrs} type="number" value="${escapeHtml(value)}" readonly />`;
    }

    if (col.type === "tag") {
      const tagAttrs = attrs.replace('class="cell-control"', 'class="cell-control tag-control"');
      return `<input ${tagAttrs} type="text" value="${escapeHtml(value)}" readonly />`;
    }

    return `<input ${attrs} type="text" value="${escapeHtml(value)}" readonly />`;
  }

  getControlKey(control) {
    if (!control) {
      return "";
    }
    const rowId = control.dataset.rowId || "";
    const colId = control.dataset.colId || "";
    if (!rowId || !colId) {
      return "";
    }
    return `${rowId}::${colId}`;
  }

  isControlEditable(control) {
    if (!control || !control.classList?.contains("cell-control")) {
      return false;
    }
    return control.type !== "checkbox";
  }

  lockControl(control) {
    if (!control) {
      return;
    }
    if (control.tagName === "SELECT") {
      control.setAttribute("data-locked", "true");
    } else if (control.type !== "checkbox") {
      control.setAttribute("readonly", "readonly");
    }
    control.removeAttribute("data-editing");
  }

  unlockControl(control) {
    if (!control) {
      return;
    }
    if (control.tagName === "SELECT") {
      control.removeAttribute("data-locked");
    } else if (control.type !== "checkbox") {
      control.removeAttribute("readonly");
    }
    control.setAttribute("data-editing", "true");
  }

  commitControl(control) {
    if (!control) {
      return;
    }

    const rowId = control.dataset.rowId;
    const colId = control.dataset.colId;
    if (!rowId || !colId) {
      return;
    }

    const value = control.type === "checkbox" ? (control.checked ? "true" : "false") : control.value;
    this.callbacks.onCellChange(rowId, colId, value);
  }

  beginCellEdit(control) {
    if (!this.isControlEditable(control)) {
      return;
    }

    const key = this.getControlKey(control);
    if (!key) {
      return;
    }

    if (this.editingCellKey && this.editingCellKey !== key) {
      const current = this.bodyEl.querySelector('.cell-control[data-editing="true"]');
      if (current) {
        this.commitControl(current);
        this.lockControl(current);
      }
    }

    const currentValue = control.type === "checkbox" ? (control.checked ? "true" : "false") : control.value;
    control.setAttribute("data-original-value", currentValue);
    this.unlockControl(control);
    this.editingCellKey = key;
    control.focus();
    if (control.select) {
      control.select();
    }
  }

  endCellEdit(control, { commit = true } = {}) {
    if (!control || control.getAttribute("data-editing") !== "true") {
      return;
    }

    if (commit) {
      this.commitControl(control);
    } else {
      const originalValue = control.getAttribute("data-original-value");
      if (originalValue !== null) {
        if (control.type === "checkbox") {
          control.checked = originalValue === "true";
        } else {
          control.value = originalValue;
        }
      }
    }
    control.removeAttribute("data-original-value");
    this.lockControl(control);

    if (this.getControlKey(control) === this.editingCellKey) {
      this.editingCellKey = null;
    }
  }

  handleHeadClick(event) {
    const sortBtn = event.target.closest("[data-sort-col]");
    const headerCell = event.target.closest("th[data-col-id]");

    if (sortBtn) {
      this.callbacks.onSort(sortBtn.dataset.sortCol);
      return;
    }

    if (headerCell) {
      this.callbacks.onColumnSelect(headerCell.dataset.colId);
    }
  }

  handleHeaderDragStart(event) {
    const headerCell = event.target.closest("th[data-col-id]");
    if (!headerCell) {
      return;
    }
    this.dragColumnId = headerCell.dataset.colId;
    if (event.dataTransfer) {
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", this.dragColumnId);
    }
  }

  handleHeaderDragOver(event) {
    const headerCell = event.target.closest("th[data-col-id]");
    if (!headerCell) {
      return;
    }
    event.preventDefault();
    headerCell.classList.add("drag-target");
  }

  handleHeaderDragLeave(event) {
    const headerCell = event.target.closest("th[data-col-id]");
    if (!headerCell) {
      return;
    }
    headerCell.classList.remove("drag-target");
  }

  handleHeaderDrop(event) {
    const headerCell = event.target.closest("th[data-col-id]");
    if (!headerCell) {
      return;
    }
    event.preventDefault();

    const targetId = headerCell.dataset.colId;
    headerCell.classList.remove("drag-target");

    if (this.dragColumnId && targetId && this.dragColumnId !== targetId) {
      this.callbacks.onReorderColumns(this.dragColumnId, targetId);
    }

    this.dragColumnId = null;
  }

  handleHeaderMouseDown(event) {
    const handle = event.target.closest("[data-resize-col]");
    if (!handle) {
      return;
    }

    const colId = handle.dataset.resizeCol;
    const col = this.columns.find((item) => item.id === colId);
    if (!col) {
      return;
    }

    event.preventDefault();
    this.resizing = {
      colId,
      startX: event.clientX,
      startWidth: Number(col.width) || 180,
    };

    window.addEventListener("mousemove", this.handleResizeMove);
    window.addEventListener("mouseup", this.handleResizeEnd);
  }

  handleResizeMove(event) {
    if (!this.resizing) {
      return;
    }

    const delta = event.clientX - this.resizing.startX;
    const nextWidth = Math.max(100, Math.min(600, this.resizing.startWidth + delta));
    this.callbacks.onResizeColumn(this.resizing.colId, Math.round(nextWidth));
  }

  handleResizeEnd() {
    this.resizing = null;
    window.removeEventListener("mousemove", this.handleResizeMove);
    window.removeEventListener("mouseup", this.handleResizeEnd);
  }

  handleBodyClick(event) {
    const rowEl = event.target.closest("tr[data-row-id]");
    if (!rowEl) {
      return;
    }
    this.callbacks.onRowSelect(rowEl.dataset.rowId);
  }

  handleBodyDoubleClick(event) {
    const control =
      event.target.closest(".cell-control") ||
      event.target.closest("td")?.querySelector(".cell-control");
    if (!control) {
      return;
    }

    const rowId = control.dataset.rowId;
    if (rowId) {
      this.callbacks.onRowSelect(rowId);
    }

    this.beginCellEdit(control);
  }

  handleBodyFocus(event) {
    const input = event.target.closest(".cell-control");
    if (!input) {
      return;
    }

    const rowId = input.dataset.rowId;
    if (rowId) {
      this.callbacks.onRowSelect(rowId);
    }
  }

  handleCellMutation(event) {
    const input = event.target.closest(".cell-control");
    if (!input) {
      return;
    }

    if (event.type === "input") {
      return;
    }

    if (input.type !== "checkbox") {
      return;
    }

    const rowId = input.dataset.rowId;
    const colId = input.dataset.colId;

    if (!rowId || !colId) {
      return;
    }

    const value = input.type === "checkbox" ? (input.checked ? "true" : "false") : input.value;
    this.callbacks.onCellChange(rowId, colId, value);
  }

  handleBodyFocusOut(event) {
    const control = event.target.closest(".cell-control");
    if (!control) {
      return;
    }

    if (control.getAttribute("data-editing") !== "true") {
      return;
    }

    window.setTimeout(() => {
      const active = document.activeElement;
      if (active === control) {
        return;
      }
      this.endCellEdit(control, { commit: true });
    }, 0);
  }

  handleCellKeydown(event) {
    const input = event.target.closest(".cell-control");
    if (!input) {
      return;
    }

    const isEditing = input.getAttribute("data-editing") === "true";

    if (isEditing) {
      if (event.key === "Enter") {
        event.preventDefault();
        this.endCellEdit(input, { commit: true });
        return;
      }

      if (event.key === "Escape") {
        event.preventDefault();
        this.endCellEdit(input, { commit: false });
      }
      return;
    }

    if (event.key === "Enter" && this.isControlEditable(input)) {
      event.preventDefault();
      this.beginCellEdit(input);
      return;
    }

    const rowIndex = Number(input.dataset.rowIndex);
    const colIndex = Number(input.dataset.colIndex);

    if (!Number.isFinite(rowIndex) || !Number.isFinite(colIndex)) {
      return;
    }

    let nextRow = rowIndex;
    let nextCol = colIndex;

    if (event.key === "ArrowDown" || event.key === "Enter") {
      nextRow += 1;
    } else if (event.key === "ArrowUp") {
      nextRow -= 1;
    } else if (event.key === "ArrowRight") {
      nextCol += 1;
    } else if (event.key === "ArrowLeft") {
      nextCol -= 1;
    } else {
      return;
    }

    event.preventDefault();

    const maxRow = this.rows.length - 1;
    const maxCol = this.visibleColumns.length - 1;

    if (nextRow < 0 || nextCol < 0 || nextRow > maxRow || nextCol > maxCol) {
      return;
    }

    this.focusCell(nextRow, nextCol);
  }

  focusCell(rowIndex, colIndex) {
    this.pendingFocus = { rowIndex, colIndex };

    const targetTop = rowIndex * this.rowHeight;
    const targetBottom = targetTop + this.rowHeight;
    const viewportTop = this.scrollEl.scrollTop;
    const viewportBottom = viewportTop + this.scrollEl.clientHeight;

    if (targetTop < viewportTop) {
      this.scrollEl.scrollTop = targetTop;
    } else if (targetBottom > viewportBottom) {
      this.scrollEl.scrollTop = targetBottom - this.scrollEl.clientHeight;
    }

    this.renderBody();
  }

  applyPendingFocus() {
    if (!this.pendingFocus) {
      return;
    }

    const { rowIndex, colIndex } = this.pendingFocus;
    const selector = `.cell-control[data-row-index="${rowIndex}"][data-col-index="${colIndex}"]`;
    const control = this.bodyEl.querySelector(selector);

    if (control) {
      control.focus();
      if (control.select && control.type !== "checkbox" && control.tagName !== "SELECT") {
        control.select();
      }
      this.pendingFocus = null;
    }
  }
}
