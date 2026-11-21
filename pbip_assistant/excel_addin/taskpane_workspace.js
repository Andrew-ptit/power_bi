/* Workbook reading, workbook rendering and file compression helpers. */
"use strict";
async function readWorkbookImpl() {
  return Excel.run(async (context) => {
    const workbook = context.workbook;
    const activeSheet = workbook.worksheets.getActiveWorksheet();
    const activeCell = workbook.getActiveCell();
    const worksheets = workbook.worksheets;
    workbook.load("name");
    activeSheet.load("name");
    activeCell.load("rowIndex,columnIndex");
    worksheets.load("items/name");
    await context.sync();

    const tableEntries = [];
    for (const sheet of worksheets.items) {
      const tables = sheet.tables;
      tables.load("items/name");
      tableEntries.push({sheet, tables});
    }
    await context.sync();

    const ranges = [];
    const usedEntries = [];
    for (const entry of tableEntries) {
      if (entry.tables.items.length === 0) {
        const used = entry.sheet.getUsedRangeOrNullObject(true);
        used.load("isNullObject");
        usedEntries.push({sheet: entry.sheet.name, used});
      }
      for (const table of entry.tables.items) {
        const range = table.getDataBodyRange();
        const headerRange = table.getHeaderRowRange();
        range.load("rowIndex,columnIndex,rowCount,columnCount");
        headerRange.load("rowIndex,columnIndex,values");
        ranges.push({sheet: entry.sheet.name, table, range, headerRange});
      }
    }
    await context.sync();

    for (const entry of usedEntries) {
      if (!entry.used.isNullObject) entry.used.load("rowIndex,columnIndex,rowCount,columnCount");
    }
    await context.sync();

    for (const entry of usedEntries) {
      if (entry.used.isNullObject) continue;
      const columnCount = Math.min(entry.used.columnCount, 200);
      if (entry.used.rowCount === 0 || columnCount === 0) continue;
      entry.headerSample = entry.used.getCell(0, 0).getResizedRange(0, columnCount - 1);
      entry.headerSample.load("values");
      entry.sampleRows = deterministicCheckRowOffsets(Math.max(0, entry.used.rowCount - 1)).map((offset) => {
        const range = entry.used.getCell(offset + 1, 0).getResizedRange(0, columnCount - 1);
        range.load("values");
        return {offset, range};
      });
    }

    for (const entry of ranges) {
      const dataRows = entry.range.rowCount;
      entry.previewRows = deterministicCheckRowOffsets(dataRows).map((offset) => {
        const range = entry.range.getCell(offset, 0).getResizedRange(0, entry.range.columnCount - 1);
        range.load("values");
        return {offset, range};
      });
    }
    await context.sync();

    const sheets = usedEntries.filter((entry) => entry.headerSample).map((entry) => {
      const header = entry.headerSample.values[0] || [];
      if (!header.some((value) => value !== null && value !== "")) return null;
      const letters = header.map((_, index) => columnLetter(entry.used.columnIndex + index));
      const headers = header.map((value, index) =>
        value === null || value === "" ? letters[index] : String(value));
      return {
        name: entry.sheet,
        headerRow: entry.used.rowIndex + 1,
        columnLetters: letters,
        headers,
        rows: entry.sampleRows.map((item) => item.range.values[0] || []),
        sampleOrdinals: entry.sampleRows.map((item) => item.offset),
        totalRows: Math.max(0, entry.used.rowCount - 1),
        totalColumns: entry.used.columnCount,
      };
    }).filter(Boolean);

    return {
      name: workbook.name,
      url: officeDocumentUrl(),
      activeSheet: activeSheet.name,
      activeCell: {rowIndex: activeCell.rowIndex, columnIndex: activeCell.columnIndex},
      tables: ranges.map((entry) => ({
        sheet: entry.sheet,
        name: entry.table.name,
        headers: entry.headerRange.values[0] || [],
        rows: entry.previewRows.map((item) => item.range.values[0] || []),
        sampleOrdinals: entry.previewRows.map((item) => item.offset),
        totalRows: entry.range.rowCount,
        totalColumns: entry.range.columnCount,
        rowIndex: entry.headerRange.rowIndex,
        columnIndex: entry.headerRange.columnIndex,
      })),
      sheets,
    };
  });
}

function renderWorkbook() {
  const workbook = state.workbook;
  const pqKey = workbook ? workbookIdentity(workbook) : "";
  if (state.workbookRecord.workbookKey !== pqKey) {
    state.workbookRecord = createWorkbookRecordState(pqKey);
    renderFlowRecord();
    updateFlowButtons();
  }
  if (pqKey !== state.pqWorkbookKey) {
    state.pqWorkbookKey = pqKey;
    state.pqTypedPreviewCache = [];
    state.pqStepDiagnosticStaging = null;
    state.pqStepDiagnosticCaches = new Map();
    state.pqStepDiagnosticTimings = new Map();
    state.pqResultSheetName = "";
    state.pqPinnedSource = null;
    state.pqPreview = null;
    invalidateTypedPlan("Workbook đã đổi. Hãy tạo Typed Plan mới.");
    setHidden("pq-preview-section", true);
  }
  byId("workbook-name").textContent = workbook ? workbook.name : "—";
  byId("active-sheet").textContent = workbook ? workbook.activeSheet : "—";
  if (window.ReqwiseAssistantEntryUI && state.preparationWorkbookKey !== (workbook ? workbookIdentity(workbook) : "")) {
    state.preparationWorkbookKey = workbook ? workbookIdentity(workbook) : "";
    window.ReqwiseAssistantEntryUI.updateWorkbook({name: workbook?.name || "Workbook",
      hasData: !!workbook && [...(workbook.tables || []), ...(workbook.sheets || [])]
        .some(source => (source.totalRows ?? source.rows?.length ?? 0) > 0)});
  }
  byId("schema-summary").textContent = workbook
    ? `${workbook.tables.length} table · ${(workbook.sheets || []).length} sheet thường · ${[
      ...workbook.tables, ...(workbook.sheets || []),
    ].reduce((sum, source) => sum + source.headers.length, 0)} cột`
    : "—";
  const supported = window.Office && Office.context.requirements.isSetSupported("ExcelApi", "1.4");
  byId("api-version").textContent = supported ? "≥ 1.4" : "Không hỗ trợ 1.4";
  byId("workbook-message").textContent = workbook
    ? "Đã đọc trực tiếp từ Excel. Trợ lý tính A/B cục bộ và chỉ ghi sheet kết quả mới sau khi duyệt đúng Spec; PQ_Code-M dùng xác nhận riêng cho từng thao tác ghi."
    : "Chưa đọc được workbook đang mở.";
  renderPQSourceContext();
}

function workbookIdentity(workbook) {
  return `${workbook.url || ""}\u0000${workbook.name || ""}`;
}

function acceptWorkbookRead(expectedKey, workbook) {
  const actualKey = workbookIdentity(workbook);
  if (!expectedKey || actualKey === expectedKey) {
    state.workbook = workbook;
    return;
  }
  state.workbook = workbook;
  renderWorkbook();
  state.problemChainHydrated = false;
  state.problemChainDocument = null;
  state.problemChainHistoryHash = null;
  state.problemChainViewRevisionId = null;
  state.pqTypedPlan = null;
  state.pqTypedPreview = null;
  state.pqTypedApproval = null;
  throw problemChainError(
    "PQPC_WORKBOOK_CHANGED",
    "Workbook đã đổi trong lúc xử lý. Thao tác cũ đã dừng; hãy bấm Đọc lại workbook rồi thử lại.",
  );
}

function advancedMAcknowledgementKey(workbook) {
  if (!state.sessionId || !state.advancedMPolicy || !workbook) return "";
  return `${state.sessionId}\u0000${state.advancedMPolicy.policyId}\u0000${workbookIdentity(workbook)}`;
}

function renderPQSourceContext() {
  const source = selectedPQSource();
  byId("pq2-source-context").textContent = state.workbook
    ? `Workbook ${state.workbook.name}: ${(state.workbook.tables || []).length} Table, ${(state.workbook.sheets || []).length} usedRange.`
    : "Typed Steps only uses Table/usedRange from the open workbook.";
  byId("pq-source-context").textContent = source
    ? `Nguồn hiện hành: ${state.workbook.name} · ${source.sheet}${source.kind === "table" ? ` · Table ${source.name}` : " · usedRange"}`
    : "Mở sheet dữ liệu trong Excel; nếu có nhiều Table, chọn một ô trong Table cần xử lý.";
  updatePQButtons();
}

async function refreshWorkbook() {
  resetFlowView();
  clearError();
  setBusy(true, "Đang đọc workbook trực tiếp từ Excel…");
  try {
    state.workbook = await readWorkbook();
    renderWorkbook();
    await flowReadRecord();
    invalidatePQPreview(true);
    invalidateTypedPlan("Workbook đã đọc lại. Hãy tạo Typed Plan mới.");
    byId("connection-badge").textContent = "EXCEL CONNECTED";
    byId("connection-badge").className = "badge badge-ready";
  } catch (error) {
    invalidatePQPreview(true);
    invalidateTypedPlan("Không đọc được workbook. Typed Plan cũ đã bị hủy.");
    state.workbook = null;
    renderWorkbook();
    byId("connection-badge").textContent = "EXCEL READ FAILED";
    byId("connection-badge").className = "badge badge-failed";
    showError("OFFICE_READ_FAILED", error.message);
  } finally {
    setBusy(false, "");
    if (state.flow.approvalConsumed) renderFlowFreeze();
  }
}

function appendTextList(container, values) {
  container.replaceChildren();
  const list = document.createElement("ul");
  for (const value of values) {
    const item = document.createElement("li");
    item.textContent = value;
    list.appendChild(item);
  }
  container.appendChild(list);
}

function renderTable(containerId, columns, rows) {
  const container = byId(containerId);
  container.replaceChildren();
  const table = document.createElement("table");
  const head = document.createElement("thead");
  const headRow = document.createElement("tr");
  for (const column of columns) {
    const cell = document.createElement("th");
    cell.textContent = column;
    headRow.appendChild(cell);
  }
  head.appendChild(headRow);
  table.appendChild(head);
  const body = document.createElement("tbody");
  for (const row of rows) {
    const rowElement = document.createElement("tr");
    for (const value of row) {
      const cell = document.createElement("td");
      cell.textContent = value === null || value === undefined ? "" : String(value);
      rowElement.appendChild(cell);
    }
    body.appendChild(rowElement);
  }
  table.appendChild(body);
  container.appendChild(table);
}

function readSlice(file, index) {
  return new Promise((resolve, reject) => {
    file.getSliceAsync(index, (result) => {
      if (result.status === Office.AsyncResultStatus.Succeeded) resolve(result.value.data);
      else reject(new Error(result.error.message));
    });
  });
}

function closeFile(file) {
  return new Promise((resolve) => file.closeAsync(() => resolve()));
}

function blobToBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",", 2)[1]);
    reader.onerror = () => reject(reader.error || new Error("Không đọc được workbook export."));
    reader.readAsDataURL(blob);
  });
}

function getCompressedFile() {
  return new Promise((resolve, reject) => {
    Office.context.document.getFileAsync(
      Office.FileType.Compressed,
      {sliceSize: 1024 * 1024},
      (result) => {
        if (result.status === Office.AsyncResultStatus.Succeeded) resolve(result.value);
        else reject(new Error(result.error.message));
      },
    );
  });
}

async function exportWorkbookBase64() {
  const file = await getCompressedFile();
  try {
    const chunks = [];
    for (let index = 0; index < file.sliceCount; index += 1) {
      setExportProgress(`Đang xuất workbook ${index + 1}/${file.sliceCount}…`);
      const data = await readSlice(file, index);
      chunks.push(new Uint8Array(data));
    }
    return await blobToBase64(new Blob(chunks, {type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}));
  } finally {
    await closeFile(file);
  }
}

