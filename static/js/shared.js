const dataElement = document.getElementById("sharedWorkspaceData");
const titleElement = document.getElementById("sharedTitle");
const searchInput = document.getElementById("sharedSearchInput");
const statsElement = document.getElementById("sharedStats");
const table = document.getElementById("sharedTable");
const tableHead = table.querySelector("thead");
const tableBody = table.querySelector("tbody");
const tableScroll = document.getElementById("sharedTableScroll");

const ROW_HEIGHT = 42;
const OVERSCAN = 8;

let workspace = {};
let rows = [];
let columns = [];
let filteredRows = [];

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function parseWorkspace() {
  try {
    workspace = JSON.parse(dataElement.textContent || "{}");
  } catch (error) {
    workspace = { error: "invalid" };
  }

  if (workspace.error) {
    titleElement.textContent = "Lien invalide ou expire";
    searchInput.disabled = true;
    tableHead.innerHTML = "";
    tableBody.innerHTML = "<tr><td>Impossible de charger cette vue partagee.</td></tr>";
    return false;
  }

  columns = Array.isArray(workspace.columns) ? workspace.columns : [];
  rows = Array.isArray(workspace.rows) ? workspace.rows : [];
  filteredRows = rows.slice();

  titleElement.textContent = workspace.name || "Vue partagee";
  return true;
}

function normalize(value) {
  if (value === null || value === undefined) {
    return "";
  }
  return String(value).toLowerCase().trim();
}

function applySearch() {
  const query = normalize(searchInput.value);

  if (!query) {
    filteredRows = rows.slice();
  } else {
    filteredRows = rows.filter((row) => {
      return columns.some((column) => normalize(row.values?.[column.id] || "").includes(query));
    });
  }

  renderBody();
  statsElement.textContent = `${filteredRows.length} ligne(s) affichee(s) / ${rows.length} total`;
}

function renderHead() {
  const headRow = columns
    .map((column) => `<th style="width:${Math.max(120, Number(column.width || 180))}px">${escapeHtml(column.name)}</th>`)
    .join("");
  tableHead.innerHTML = `<tr>${headRow}</tr>`;
}

function renderBody() {
  const total = filteredRows.length;
  const viewportHeight = tableScroll.clientHeight || 560;
  const scrollTop = tableScroll.scrollTop || 0;

  const start = Math.max(0, Math.floor(scrollTop / ROW_HEIGHT) - OVERSCAN);
  const end = Math.min(total, Math.ceil((scrollTop + viewportHeight) / ROW_HEIGHT) + OVERSCAN);

  const topHeight = start * ROW_HEIGHT;
  const bottomHeight = (total - end) * ROW_HEIGHT;
  const colSpan = Math.max(1, columns.length);

  let html = `<tr class="spacer-row"><td colspan="${colSpan}" style="height:${topHeight}px"></td></tr>`;

  for (let i = start; i < end; i += 1) {
    const row = filteredRows[i];
    const cells = columns.map((column) => `<td>${escapeHtml(row.values?.[column.id] || "")}</td>`).join("");
    html += `<tr>${cells}</tr>`;
  }

  html += `<tr class="spacer-row"><td colspan="${colSpan}" style="height:${bottomHeight}px"></td></tr>`;
  tableBody.innerHTML = html;
}

function init() {
  const ok = parseWorkspace();
  if (!ok) {
    return;
  }

  renderHead();
  applySearch();

  searchInput.addEventListener("input", applySearch);
  tableScroll.addEventListener("scroll", renderBody);
}

init();
