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
  const { onUploadProgress = () => {}, onExtractionProgress = () => {} } = handlers;

  return new Promise((resolve, reject) => {
    const formData = new FormData();
    formData.append("pdf_file", file);

    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/extract", true);

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
        reject(new Error(payload.error || "Extraction failed."));
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
  const columns = [
    { id: "col_nom_club", name: "Nom club", type: "text", width: 220, hidden: false, defaultValue: "", options: [] },
    { id: "col_ligue", name: "Ligue", type: "text", width: 190, hidden: false, defaultValue: "", options: [] },
    { id: "col_cd", name: "CD", type: "text", width: 130, hidden: false, defaultValue: "", options: [] },
  ];

  const sourceNomClub = cleanText(mapping["Nom club"]);
  const sourceLigue = cleanText(mapping["Ligue"]);
  const sourceCD = cleanText(mapping["CD"]);

  const safeRows = Array.isArray(rows) ? rows : [];
  const mappedRows = [];

  safeRows.forEach((sourceRow) => {
    const rowValues = {
      col_nom_club: cleanText(sourceNomClub ? sourceRow[sourceNomClub] : ""),
      col_ligue: cleanText(sourceLigue ? sourceRow[sourceLigue] : ""),
      col_cd: cleanText(sourceCD ? sourceRow[sourceCD] : ""),
    };

    const hasData = Object.values(rowValues).some((value) => value.length > 0);
    if (!hasData) {
      return;
    }

    mappedRows.push({
      id: uid("row"),
      values: rowValues,
    });
  });

  return { columns, rows: mappedRows };
}
