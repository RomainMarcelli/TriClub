import { DEFAULT_PROSPECTION_COLUMNS } from "./schema.js";

function parseJsonResponse(text) {
  try {
    return JSON.parse(text || "{}");
  } catch (error) {
    return {};
  }
}

function cleanText(value) {
  if (value === null || value === undefined) {
    return "";
  }
  return String(value).trim();
}

function uid(prefix = "id") {
  return `${prefix}_${Math.random().toString(36).slice(2, 9)}`;
}

export function uploadPdfWithProgress(file, handlers = {}) {
  const { onUploadProgress = () => {}, onExtractionProgress = () => {}, csrfToken = "" } = handlers;

  return new Promise((resolve, reject) => {
    const formData = new FormData();
    formData.append("pdf_file", file);

    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/extract", true);
    if (csrfToken) {
      xhr.setRequestHeader("X-CSRF-Token", csrfToken);
    }

    let extractionProgress = 0;
    let extractionTick = null;

    xhr.upload.onprogress = (event) => {
      if (!event.lengthComputable) {
        return;
      }
      const percent = Math.min(100, Math.round((event.loaded / event.total) * 100));
      onUploadProgress(percent);
    };

    xhr.onloadstart = () => {
      onUploadProgress(0);
      onExtractionProgress(0);

      extractionTick = window.setInterval(() => {
        extractionProgress = Math.min(90, extractionProgress + 6);
        onExtractionProgress(extractionProgress);
      }, 130);
    };

    xhr.onload = () => {
      if (extractionTick) {
        window.clearInterval(extractionTick);
      }
      onExtractionProgress(100);

      const payload = parseJsonResponse(xhr.responseText);

      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(payload);
      } else {
        const error = new Error(payload.error || "Extraction failed.");
        error.status = xhr.status;
        error.code = payload.error || "extract_failed";
        reject(error);
      }
    };

    xhr.onerror = () => {
      if (extractionTick) {
        window.clearInterval(extractionTick);
      }
      reject(new Error("Network error during PDF upload."));
    };

    xhr.send(formData);
  });
}

export function buildWorkspaceFromImport({ rows, mapping }) {
  const columns = DEFAULT_PROSPECTION_COLUMNS.map((col) => ({
    id: col.id,
    name: col.name,
    type: col.type,
    width: col.width,
    hidden: false,
    defaultValue: col.defaultValue || "",
    options: Array.isArray(col.options) ? col.options.slice() : [],
  }));

  const sourceNomClub = cleanText(mapping["Nom club"]);
  const sourceLigue = cleanText(mapping["Ligue"]);
  const sourceCD = cleanText(mapping["CD"]);

  const safeRows = Array.isArray(rows) ? rows : [];
  const mappedRows = [];

  safeRows.forEach((sourceRow) => {
    const valueNomClub = cleanText(sourceNomClub ? sourceRow[sourceNomClub] : "");
    const valueRegion = cleanText(sourceLigue ? sourceRow[sourceLigue] : "");
    const valueDepartement = cleanText(sourceCD ? sourceRow[sourceCD] : "");

    const hasData = Boolean(valueNomClub || valueRegion || valueDepartement);
    if (!hasData) {
      return;
    }

    const rowValues = {};
    columns.forEach((col) => {
      rowValues[col.id] = col.defaultValue || "";
    });
    rowValues.col_nom_club = valueNomClub;
    rowValues.col_region = valueRegion;
    rowValues.col_departement = valueDepartement;

    mappedRows.push({
      id: uid("row"),
      values: rowValues,
    });
  });

  return { columns, rows: mappedRows };
}
