"use strict";

const state = {
  token: "",
  workbook: null,
  plan: null,
  officeReady: false,
  busy: false,
  codexAvailable: false,
  pqPreview: null,
  pqWorkbookKey: "",
  sessionId: "",
  advancedMPolicy: null,
  pqRiskAcknowledgements: new Set(),
  pqResultSheetName: "",
  pqPinnedSource: null,
  pqMode: "typed",
  pqTypedPlan: null,
  pqTypedPreview: null,
  pqTypedApproval: null,
  pqTypedPreviewCache: [],
  pqTypedEditorStepId: null,
  pqTypedMarker: "localDataCopilot.pqTypedResult.v2",
  problemChainCapability: false,
  typedStepDiagnosticsCapability: false,
  problemChainSupported: false,
  problemChainHydrated: false,
  problemChainDocument: null,
  problemChainHistoryHash: null,
  problemChainViewRevisionId: null,
  problemChainDataVersion: 0,
  problemChainVersionPending: false,
  problemChainDraftAction: null,
  problemChainClarification: null,
  problemChainHistoryExpanded: false,
  expandedRevisionIds: new Set(),
  expandedStepId: null,
  checkoutRunning: false,
  pqStepDiagnosticStaging: null,
  pqStepDiagnosticCaches: new Map(),
  pqStepDiagnosticTimings: new Map(),
};

const PROBLEM_CHAIN_NAMESPACE = "urn:local-data-copilot:pq-problem-chain:v1";
const PROBLEM_CHAIN_SCHEMA_VERSION = "1.0";
const PROBLEM_CHAIN_PREVIEW_CACHE_LIMIT = 5;
const PROBLEM_CHAIN_CACHE_CELL_CHARS = 256;

// Lucide SVG icons (ISC License - see third_party/lucide/LICENSE.txt)
const LUCIDE_ICONS = {
  "chevron-down": '<path d="m6 9 6 6 6-6"/>',
  "chevron-right": '<path d="m9 18 6-6-6-6"/>',
  "git-fork": '<circle cx="6" cy="6" r="3"/><circle cx="18" cy="6" r="3"/><circle cx="12" cy="18" r="3"/><path d="M6 9v2a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1V9M12 12v3"/>',
  "square-pen": '<path d="M12 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.4 2.6a2.1 2.1 0 0 1 3 3L12 15l-4 1 1-4Z"/>',
  "trash-2": '<path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6M10 11v5M14 11v5"/>',
  "circle-dot": '<circle cx="12" cy="12" r="3" fill="currentColor" stroke="none"/>',
  "table": '<path d="M12 3v18M3 9h18M3 15h18"/><rect width="18" height="18" x="3" y="3" rx="2"/>',
  "circle-info": '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/>',
  "plus": '<path d="M5 12h14M12 5v14"/>',
  "ellipsis": '<circle cx="5" cy="12" r="1" fill="currentColor" stroke="none"/><circle cx="12" cy="12" r="1" fill="currentColor" stroke="none"/><circle cx="19" cy="12" r="1" fill="currentColor" stroke="none"/>',
  "play": '<path d="m6 4 14 8-14 8Z"/>',
  "file-text": '<path d="M8 6h13M8 12h13M8 18h13"/><path d="M3 6h.01M3 12h.01M3 18h.01"/>',
  "alert-triangle": '<path d="m21.7 18-8-14a2 2 0 0 0-3.4 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.7-3Z"/><path d="M12 9v4M12 17h.01"/>',
  "arrow-right": '<path d="M5 12h14M12 5l7 7-7 7"/>',
};

function createIcon(name, extraClass = "") {
  const content = LUCIDE_ICONS[name] || LUCIDE_ICONS["circle-info"];
  const svg = (typeof document !== "undefined" && document.createElementNS)
    ? document.createElementNS("http://www.w3.org/2000/svg", "svg")
    : document.createElement("svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("class", extraClass ? `icon ${extraClass}` : "icon");
  svg.innerHTML = content;
  return svg;
}

function createIconButton({icon, label, tooltip = "", onClick = null, disabled = false, className = "", id = ""}) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = className ? `icon-button ${className}` : "icon-button";
  if (id) button.id = id;
  button.setAttribute("aria-label", label);
  const tip = tooltip || label;
  button.title = tip;
  button.dataset.tooltip = tip;
  button.disabled = disabled;
  button.appendChild(createIcon(icon));
  if (onClick) {
    button.addEventListener("click", onClick);
  }
  return button;
}

function setProblemChainHistoryExpanded(expanded) {
  state.problemChainHistoryExpanded = expanded;
  const section = byId("pqpc-section");
  if (section) section.classList.toggle("collapsed", !expanded);
  const toggle = byId("pqpc-history-toggle");
  if (toggle) {
    toggle.setAttribute("aria-expanded", String(expanded));
    toggle.setAttribute("aria-label", expanded ? "Thu gọn lịch sử vấn đề" : "Mở lịch sử vấn đề");
  }
}

const byId = (id) => document.getElementById(id);

function setHidden(id, hidden) {
  byId(id).classList.toggle("hidden", hidden);
}

function showError(code, detail) {
  byId("error-code").textContent = code || "Lỗi";
  byId("error-detail").textContent = detail || "Đã xảy ra lỗi không xác định.";
  setHidden("error-panel", false);
}

function clearError() {
  setHidden("error-panel", true);
}

function setBusy(value, message = "") {
  state.busy = value;
  byId("refresh-button").disabled = value;
  byId("analyze-button").disabled = value || !state.officeReady || !state.workbook || !state.codexAvailable;
  byId("apply-progress").textContent = message;
  updateApplyState();
  updatePQButtons();
  updateProblemChainButtons();
}

function updatePromptCount() {
  const prompt = byId("prompt").value;
  byId("prompt-count").textContent = `${prompt.length} / 4000`;
}

function invalidatePlan(message = "Yêu cầu đã đổi. Hãy phân tích lại để tạo revision mới.") {
  if (!state.plan) return;
  state.plan = null;
  setHidden("plan-section", true);
  setHidden("preview-section", true);
  setHidden("approval-section", true);
  byId("approval-check").checked = false;
  byId("apply-progress").textContent = message;
  updateApplyState();
}

function updateApplyState() {
  const ready = state.plan && state.plan.status === "review_ready";
  const approved = byId("approval-check").checked;
  byId("apply-button").disabled = state.busy || !ready || !approved;
}

async function api(path, payload, {timeoutMs = 0} = {}) {
  const controller = timeoutMs > 0 && typeof AbortController === "function" ? new AbortController() : null;
  const timeout = controller && typeof setTimeout === "function"
    ? setTimeout(() => controller.abort(), timeoutMs) : null;
  try {
    const response = await fetch(path, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Local-Token": state.token,
      },
      body: JSON.stringify(payload),
      ...(controller ? {signal: controller.signal} : {}),
    });
    let result = {};
    try {
      if (typeof response.text === "function") {
        const responseText = await response.text();
        result = responseText ? JSON.parse(responseText) : {};
      } else {
        result = await response.json();
      }
    } catch (error) {
      if (error?.name === "AbortError") throw error;
      const failure = new Error(`Coordinator returned an unreadable response (HTTP ${response.status}).`);
      failure.code = "COORDINATOR_RESPONSE_INVALID";
      throw failure;
    }
    if (!response.ok) {
      const error = result.error || {};
      const failure = new Error(error.detail || `HTTP ${response.status}`);
      failure.code = error.code || "REQUEST_FAILED";
      if (failure.code === "CODEX_RATE_LIMITED") {
        const delay = Number(response.headers?.get?.("Retry-After"));
        const wait = Number.isFinite(delay) && delay > 0
          ? `Hãy chờ ít nhất ${Math.ceil(delay)} giây rồi thử lại một lần. `
          : "Hãy chờ trước khi thử lại một lần. ";
        failure.message = `Codex trả lỗi 429. ${wait}Nội dung bạn nhập vẫn được giữ; rút ngắn yêu cầu không đặt lại hạn mức. Nếu lỗi kéo dài, hãy kiểm tra hạn mức sử dụng của tài khoản Codex.`;
      }
      if (response.status === 404 && path.startsWith("/api/pq/v2/step-diagnostics/")) {
        failure.code = "COORDINATOR_RESTART_REQUIRED";
        failure.message = "Coordinator đang chạy bản cũ. Hãy dừng server, chạy lại coordinator và mở lại task pane.";
      }
      if ([401, 403].includes(response.status) && ["TOKEN_EXPIRED", "TOKEN_REQUIRED"].includes(failure.code)) {
        try {
          await bootstrap();
          invalidateSessionBoundState();
          failure.message = `${failure.message} Phiên mới đã được tạo; hãy bấm Đọc lại workbook rồi thử lại. Yêu cầu cũ không được tự chạy lại.`;
        } catch {
          failure.message = `${failure.message} Không thể tạo phiên mới; hãy mở lại panel.`;
        }
      }
      throw failure;
    }
    return result;
  } catch (error) {
    if (error?.name === "AbortError" && controller?.signal.aborted) {
      const failure = new Error("Coordinator không trả lời trong thời gian cho phép. Yêu cầu đã dừng ở task pane; hãy kiểm tra trạng thái coordinator trước khi thử lại.");
      failure.code = "COORDINATOR_TIMEOUT";
      throw failure;
    }
    throw error;
  } finally {
    if (timeout !== null) clearTimeout(timeout);
  }
}

function isValidAdvancedMPolicy(policy) {
  return Boolean(policy)
    && typeof policy.policyId === "string" && policy.policyId.length > 0
    && policy.mode === "trusted"
    && policy.enabled === true
    && policy.riskAcknowledgementRequired === true
    && policy.acknowledgementScope === "workbookPanelSession"
    && policy.externalConnectors === "allowed"
    && policy.previewIsolation === "temporaryWorkbookNotSandbox"
    && policy.applyToSource === "explicitConfirmation"
    && policy.backupPolicy === "none"
    && policy.autoSave === false;
}

function invalidateSessionBoundState() {
  state.plan = null;
  state.pqPreview = null;
  state.pqTypedPlan = null;
  state.pqTypedPreview = null;
  state.pqTypedApproval = null;
  state.pqTypedPreviewCache = [];
  state.problemChainHydrated = false;
  state.problemChainDataVersion = 0;
  state.problemChainVersionPending = false;
  state.problemChainDraftAction = null;
  state.problemChainClarification = null;
  state.pqStepDiagnosticStaging = null;
  state.pqStepDiagnosticCaches = new Map();
  state.pqStepDiagnosticTimings = new Map();
  setHidden("plan-section", true);
  setHidden("preview-section", true);
  setHidden("approval-section", true);
  setHidden("pq-preview-section", true);
  setHidden("pq2-plan-section", true);
  setHidden("pq2-preview-section", true);
  setHidden("pqpc-branch-editor", true);
  setHidden("pqpc-clarification", true);
  byId("pqpc-clarification-questions").replaceChildren();
  setHidden("pqpc-impact-section", true);
  byId("approval-check").checked = false;
  if (byId("pqpc-progress")) {
    byId("pqpc-progress").textContent = "Phiên coordinator đã hết hạn. Lịch sử vẫn ở workbook; hãy đọc lại trước thao tác mới. POST cũ không được tự chạy lại.";
  }
  byId("pq-progress").textContent = "Phiên coordinator đã hết hạn. Hãy chạy lại preview; yêu cầu cũ không được tự chạy lại.";
  byId("pq2-progress").textContent = "Phiên coordinator đã hết hạn. Hãy tạo lại Typed Plan.";
  updateApplyState();
  updatePQButtons();
  updateProblemChainButtons();
}

async function bootstrap() {
  const response = await fetch("/api/bootstrap", {cache: "no-store"});
  if (!response.ok) throw new Error("Local coordinator is not ready.");
  const result = await response.json();
  state.token = result.token;
  state.sessionId = result.session && typeof result.session.sessionId === "string"
    ? result.session.sessionId : "";
  state.advancedMPolicy = state.sessionId && isValidAdvancedMPolicy(result.capabilities?.advancedMPolicy)
    ? result.capabilities.advancedMPolicy : null;
  state.problemChainCapability = result.capabilities?.pqProblemChainV1 === true
    && result.capabilities?.pqProblemChainNamespace === PROBLEM_CHAIN_NAMESPACE;
  state.typedStepDiagnosticsCapability = result.capabilities?.pqTypedStepDiagnostics === true;
  if (!result.capabilities || !Object.prototype.hasOwnProperty.call(result.capabilities, "codexAnalysis")) {
    state.codexAvailable = false;
    byId("codex-status").textContent = "Coordinator đang chạy bản cũ. Dừng server ở terminal (Ctrl+C), chạy lại py -m pbip_assistant.excel_addin_server rồi mở lại panel.";
    return;
  }
  state.codexAvailable = Boolean(result.capabilities.codexAnalysis);
  if (result.capabilities.pqTypedDestinationMarker) {
    state.pqTypedMarker = result.capabilities.pqTypedDestinationMarker;
  }
  byId("pq-trusted-policy-status").textContent = state.advancedMPolicy
    ? "Trusted Mode cho phép M đọc toàn bộ workbook export, file/web/database, dùng credential Excel và có thể gây side effect ngoài workbook. Preview chạy trên workbook tạm, không phải sandbox."
    : "Advanced M đang bị khóa vì coordinator không cung cấp Trusted Mode policy hợp lệ.";
  byId("codex-status").textContent = state.codexAvailable
    ? "Codex sẵn sàng · chỉ gửi prompt và mẫu tới OpenAI khi bạn bấm Phân tích."
    : "Coordinator chưa tìm thấy lệnh codex. Kiểm tra trong terminal rồi khởi động lại server và panel.";
}

function officeDocumentUrl() {
  if (!window.Office || !Office.context || !Office.context.document) return "";
  return Office.context.document.url || "";
}

function columnLetter(index) {
  let number = index + 1;
  let label = "";
  while (number > 0) {
    number -= 1;
    label = String.fromCharCode(65 + (number % 26)) + label;
    number = Math.floor(number / 26);
  }
  return label;
}

function deterministicCheckRowOffsets(rowCount, limit = 20) {
  if (!Number.isInteger(rowCount) || rowCount <= 0) return [];
  const wanted = new Set([0, 1, 2, Math.floor(rowCount / 2) - 1,
    Math.floor(rowCount / 2), Math.floor(rowCount / 2) + 1,
    rowCount - 3, rowCount - 2, rowCount - 1]);
  const slots = Math.min(limit, rowCount);
  for (let index = 0; index < slots; index += 1) {
    wanted.add(Math.floor(index * (rowCount - 1) / Math.max(1, slots - 1)));
  }
  return [...wanted].filter((index) => index >= 0 && index < rowCount).sort((a, b) => a - b).slice(0, limit);
}

async function readWorkbook() {
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
        const range = table.getRange();
        range.load("rowIndex,columnIndex,rowCount,columnCount");
        ranges.push({sheet: entry.sheet.name, table, range});
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
      const headerRange = entry.range.getRow(0);
      headerRange.load("values");
      entry.headerRange = headerRange;
      const dataRows = Math.max(0, entry.range.rowCount - 1);
      entry.previewRows = deterministicCheckRowOffsets(dataRows).map((offset) => {
        const range = entry.range.getCell(offset + 1, 0).getResizedRange(0, entry.range.columnCount - 1);
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
        totalRows: Math.max(0, entry.range.rowCount - 1),
        totalColumns: entry.range.columnCount,
        rowIndex: entry.range.rowIndex,
        columnIndex: entry.range.columnIndex,
      })),
      sheets,
    };
  });
}

function renderWorkbook() {
  const workbook = state.workbook;
  const pqKey = workbook ? workbookIdentity(workbook) : "";
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
  byId("schema-summary").textContent = workbook
    ? `${workbook.tables.length} table · ${(workbook.sheets || []).length} sheet thường · ${[
      ...workbook.tables, ...(workbook.sheets || []),
    ].reduce((sum, source) => sum + source.headers.length, 0)} cột`
    : "—";
  const supported = window.Office && Office.context.requirements.isSetSupported("ExcelApi", "1.4");
  byId("api-version").textContent = supported ? "≥ 1.4" : "Không hỗ trợ 1.4";
  byId("workbook-message").textContent = workbook
    ? "Đã đọc trực tiếp từ Excel. Tab Trợ lý chỉ đề xuất; tab PQ chỉ ghi sheet kết quả sau xác nhận."
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
  clearError();
  setBusy(true, "Đang đọc workbook trực tiếp từ Excel…");
  try {
    state.workbook = await readWorkbook();
    renderWorkbook();
    invalidatePlan("Workbook đã đọc lại. Hãy phân tích revision mới.");
    invalidatePQPreview(true);
    invalidateTypedPlan("Workbook đã đọc lại. Hãy tạo Typed Plan mới.");
    byId("connection-badge").textContent = "EXCEL CONNECTED";
    byId("connection-badge").className = "badge badge-ready";
  } catch (error) {
    invalidatePlan("Không đọc được workbook. Kế hoạch cũ đã bị hủy.");
    invalidatePQPreview(true);
    invalidateTypedPlan("Không đọc được workbook. Typed Plan cũ đã bị hủy.");
    state.workbook = null;
    renderWorkbook();
    byId("connection-badge").textContent = "EXCEL READ FAILED";
    byId("connection-badge").className = "badge badge-failed";
    showError("OFFICE_READ_FAILED", error.message);
  } finally {
    setBusy(false, "");
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

async function copyCode(code, button) {
  try {
    if (!navigator.clipboard || !navigator.clipboard.writeText) throw new Error("Clipboard API unavailable");
    await navigator.clipboard.writeText(code);
    button.textContent = "Đã sao chép";
  } catch (error) {
    const temporary = document.createElement("textarea");
    try {
      temporary.value = code;
      temporary.style.position = "fixed";
      temporary.style.opacity = "0";
      document.body.appendChild(temporary);
      temporary.select();
      button.textContent = document.execCommand("copy") ? "Đã sao chép" : "Chọn code để copy";
    } catch (fallbackError) {
      button.textContent = "Chọn code để copy";
    } finally {
      temporary.remove();
    }
  }
}

function renderCodeCard(container, label, language, code) {
  const card = document.createElement("div");
  card.className = "code-card";
  const header = document.createElement("div");
  header.className = "code-card-header";
  const title = document.createElement("span");
  title.className = "code-card-title";
  title.textContent = `${language.toUpperCase()} · ${label}`;
  const copy = document.createElement("button");
  copy.type = "button";
  copy.className = "copy-button";
  copy.textContent = "Sao chép";
  copy.setAttribute("aria-label", `Sao chép ${label}`);
  copy.addEventListener("click", () => copyCode(code, copy));
  header.append(title, copy);
  const pre = document.createElement("pre");
  const snippet = document.createElement("code");
  snippet.textContent = code;
  pre.appendChild(snippet);
  card.append(header, pre);
  container.appendChild(card);
}

function renderOperations(operations, canApply) {
  const container = byId("operation-list");
  container.replaceChildren();
  for (const operation of operations) {
    const card = document.createElement("div");
    card.className = "operation";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = true;
    checkbox.disabled = !canApply;
    checkbox.dataset.operationId = operation.id;
    checkbox.setAttribute("aria-label", `Chọn công thức ${operation.target}`);
    checkbox.addEventListener("change", updateApplyState);
    const content = document.createElement("div");
    const target = document.createElement("strong");
    target.textContent = operation.target;
    const reason = document.createElement("p");
    reason.textContent = operation.reason;
    content.append(target, reason);
    renderCodeCard(content, operation.target, "Excel", operation.formula);
    card.append(checkbox, content);
    container.appendChild(card);
  }
}

function renderCodeBlocks(blocks) {
  const container = byId("code-list");
  container.replaceChildren();
  for (const block of blocks) renderCodeCard(container, block.label, block.language === "m" ? "Power Query M" : block.language, block.code);
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

function renderPlan(plan) {
  setHidden("plan-section", false);
  const status = byId("plan-status");
  status.textContent = plan.status === "review_ready"
    ? "Sẵn sàng để review"
    : plan.status === "needs_clarification"
      ? "Codex cần bạn làm rõ trước khi lập kế hoạch"
      : plan.status === "analysis_only"
        ? "Đề xuất Codex — chưa thể áp dụng"
        : "Bị chặn";
  status.className = plan.status === "review_ready" ? "notice notice-safe" : "notice notice-warning";
  renderOperations(plan.operations || [], plan.canApply !== false);
  renderCodeBlocks(plan.codeBlocks || []);
  setHidden("code-section", !(plan.operations || []).length && !(plan.codeBlocks || []).length);
  byId("plan-summary").textContent = plan.summary || "";
  const notes = [
    ...(plan.questions || []).map((value) => `Cần hỏi: ${value}`),
    ...(plan.assumptions || []).map((value) => `Giả định: ${value}`),
  ];
  appendTextList(byId("analysis-notes"), notes);
  setHidden("analysis-notes", !notes.length);
  const messages = [...(plan.warnings || [])];
  for (const blocker of plan.hardBlockers || []) {
    messages.push(`${blocker.code}: ${blocker.reason} ${blocker.remedy}`);
  }
  appendTextList(byId("warning-list"), messages);
  setHidden("warning-list", !messages.length);

  if (plan.preview) {
    setHidden("preview-section", false);
    byId("preview-label").textContent = "Chỉ hiển thị mẫu nguồn đọc từ Excel. Chưa chạy công thức và chưa có kết quả sau được kiểm chứng.";
    renderTable("before-table", plan.preview.beforeColumns, plan.preview.beforeRows);
  } else {
    setHidden("preview-section", true);
  }
  setHidden("approval-section", plan.status !== "review_ready" || plan.canApply === false);
  byId("approval-check").checked = false;
  updateApplyState();
}

async function analyze() {
  if (state.busy || !state.officeReady || !state.workbook || !state.codexAvailable) return;
  clearError();
  invalidatePlan("Đang đọc lại workbook để phân tích revision mới.");
  const prompt = byId("prompt").value;
  const formulaListSeparator = byId("formula-list-separator").value;
  setBusy(true, "Đang đọc trạng thái workbook mới nhất từ Excel…");
  let readCompleted = false;
  try {
    const workbook = await readWorkbook();
    state.workbook = workbook;
    renderWorkbook();
    byId("connection-badge").textContent = "EXCEL CONNECTED";
    byId("connection-badge").className = "badge badge-ready";
    readCompleted = true;
    setBusy(true, "Codex đang phân tích yêu cầu và mẫu workbook vừa đọc…");
    const plan = await api("/api/excel/analyze", {
      prompt,
      workbook,
      formulaListSeparator,
    });
    state.plan = plan;
    renderPlan(plan);
  } catch (error) {
    if (!readCompleted) {
      state.workbook = null;
      renderWorkbook();
      byId("connection-badge").textContent = "EXCEL READ FAILED";
      byId("connection-badge").className = "badge badge-failed";
    }
    showError(readCompleted ? error.code : "OFFICE_READ_FAILED", error.message);
  } finally {
    setBusy(false, "");
  }
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
      byId("apply-progress").textContent = `Đang xuất workbook ${index + 1}/${file.sliceCount}…`;
      const data = await readSlice(file, index);
      chunks.push(new Uint8Array(data));
    }
    return await blobToBase64(new Blob(chunks, {type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}));
  } finally {
    await closeFile(file);
  }
}

function selectedOperationIds() {
  return [...document.querySelectorAll("[data-operation-id]:checked")].map((item) => item.dataset.operationId);
}

function renderRuntime(result) {
  setHidden("result-section", false);
  const verified = result.status === "excel_runtime_verified";
  byId("runtime-badge").textContent = verified ? "EXCEL VERIFIED" : "RUNTIME FAILED";
  byId("runtime-badge").className = verified ? "badge badge-verified" : "badge badge-failed";
  byId("copy-path").textContent = result.copy.path;
  byId("excel-version").textContent = result.runtime.excelVersion || "—";
  byId("reconcile-status").textContent = result.reconciliation.matched ? "Khớp manifest" : "Không khớp";
  const columns = ["SaleID", "Net Revenue", "Return Rate", "Commission Value", "Sales Rank"];
  const rows = (result.runtime.rows || []).map((row) => columns.map((column) => row[column]));
  renderTable("runtime-table", columns, rows);
}

async function applyPlan() {
  clearError();
  if (!state.plan || !state.workbook || state.plan.status !== "review_ready" || !byId("approval-check").checked) return;
  setBusy(true, "Đang xuất workbook đang mở…");
  try {
    const workbookBase64 = await exportWorkbookBase64();
    byId("apply-progress").textContent = "Đang tạo copy, ghi công thức và yêu cầu Excel calculate…";
    const result = await api("/api/excel/apply", {
      prompt: byId("prompt").value,
      workbook: state.workbook,
      snapshotId: state.plan.snapshotId,
      planRevisionId: state.plan.planRevisionId,
      operationIds: selectedOperationIds(),
      workbookBase64,
    });
    renderRuntime(result);
    byId("apply-progress").textContent = result.status === "excel_runtime_verified"
      ? "Hoàn tất. Excel đã calculate và kết quả đã được đọc lại từ bản copy."
      : "Bản copy đã tạo nhưng kết quả runtime chưa đạt đối chiếu.";
  } catch (error) {
    showError(error.code, error.message);
    byId("apply-progress").textContent = "Không gắn nhãn verified. Xem lỗi bên dưới.";
  } finally {
    setBusy(false, byId("apply-progress").textContent);
  }
}

function problemChainSupported() {
  return state.problemChainCapability && Boolean(window.Office && Office.context?.requirements
    && Office.context.requirements.isSetSupported("ExcelApi", "1.5"));
}

function problemChainError(code, message) {
  return Object.assign(new Error(message), {code});
}

function canonicalProblemChainJson(value) {
  const seen = new Set();
  function normalize(item) {
    if (item === null || typeof item === "string" || typeof item === "boolean") return item;
    if (typeof item === "number") {
      if (!Number.isFinite(item)) throw problemChainError("PQPC_DOCUMENT_INVALID", "Problem Chain chứa số không hữu hạn.");
      return item;
    }
    if (Array.isArray(item)) return item.map(normalize);
    if (!item || typeof item !== "object" || seen.has(item)) {
      throw problemChainError("PQPC_DOCUMENT_INVALID", "Problem Chain không phải JSON hợp lệ.");
    }
    seen.add(item);
    const normalized = {};
    for (const key of Object.keys(item).sort()) {
      if (typeof item[key] === "undefined") throw problemChainError("PQPC_DOCUMENT_INVALID", "Problem Chain chứa giá trị undefined.");
      normalized[key] = normalize(item[key]);
    }
    seen.delete(item);
    return normalized;
  }
  return JSON.stringify(normalize(value));
}

function problemChainUtf8Bytes(value) {
  return new TextEncoder().encode(value);
}

function problemChainBase64Encode(value) {
  const bytes = problemChainUtf8Bytes(value);
  let binary = "";
  for (let offset = 0; offset < bytes.length; offset += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000));
  }
  return btoa(binary);
}

function problemChainBase64Decode(value) {
  if (!/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(value)) {
    throw problemChainError("PQPC_DOCUMENT_INVALID", "Custom XML payload không phải Base64 hợp lệ.");
  }
  const binary = atob(value);
  return new TextDecoder("utf-8", {fatal: true}).decode(Uint8Array.from(binary, (character) => character.charCodeAt(0)));
}

function buildProblemChainXml(documentValue, historyHash) {
  if (!/^sha256:[0-9a-f]{64}$/.test(historyHash || "")) {
    throw problemChainError("PQPC_HASH_MISMATCH", "Coordinator không trả historyHash hợp lệ.");
  }
  const canonical = canonicalProblemChainJson(documentValue);
  if (problemChainUtf8Bytes(canonical).length > 2 * 1024 * 1024) {
    throw problemChainError("PQPC_HISTORY_LIMIT", "Lịch sử vượt giới hạn 2 MiB.");
  }
  return `<ldc:problemChain xmlns:ldc="${PROBLEM_CHAIN_NAMESPACE}" schemaVersion="${PROBLEM_CHAIN_SCHEMA_VERSION}" historyHash="${historyHash}"><ldc:payload encoding="base64">${problemChainBase64Encode(canonical)}</ldc:payload></ldc:problemChain>`;
}

function parseProblemChainXml(xml) {
  if (typeof xml !== "string" || /<!\s*(?:DOCTYPE|ENTITY)\b/i.test(xml)) {
    throw problemChainError("PQPC_DOCUMENT_INVALID", "Custom XML không hợp lệ hoặc chứa DTD/entity.");
  }
  let namespace;
  let schemaVersion;
  let historyHash;
  let payload;
  if (typeof DOMParser !== "undefined") {
    const parsed = new DOMParser().parseFromString(xml, "application/xml");
    if (parsed.getElementsByTagName("parsererror").length) throw problemChainError("PQPC_DOCUMENT_INVALID", "Custom XML không well-formed.");
    const root = parsed.documentElement;
    const children = Array.from(root.children || []);
    if (root.namespaceURI !== PROBLEM_CHAIN_NAMESPACE || root.localName !== "problemChain"
      || children.length !== 1 || children[0].namespaceURI !== PROBLEM_CHAIN_NAMESPACE
      || children[0].localName !== "payload" || children[0].getAttribute("encoding") !== "base64") {
      throw problemChainError("PQPC_DOCUMENT_INVALID", "Custom XML wrapper không đúng schema.");
    }
    namespace = root.namespaceURI;
    schemaVersion = root.getAttribute("schemaVersion");
    historyHash = root.getAttribute("historyHash");
    payload = children[0].textContent || "";
  } else {
    const match = xml.match(/^(?:<\?xml[^>]*>\s*)?<ldc:problemChain xmlns:ldc="([^"]+)" schemaVersion="([^"]+)" historyHash="([^"]+)"><ldc:payload encoding="base64">([^<]+)<\/ldc:payload><\/ldc:problemChain>$/);
    if (!match) throw problemChainError("PQPC_DOCUMENT_INVALID", "Custom XML wrapper không đúng schema.");
    [, namespace, schemaVersion, historyHash, payload] = match;
  }
  if (namespace !== PROBLEM_CHAIN_NAMESPACE || schemaVersion !== PROBLEM_CHAIN_SCHEMA_VERSION
    || !/^sha256:[0-9a-f]{64}$/.test(historyHash || "")) {
    throw problemChainError("PQPC_DOCUMENT_INVALID", "Namespace, schemaVersion hoặc historyHash không hợp lệ.");
  }
  let documentValue;
  let decoded;
  try {
    decoded = problemChainBase64Decode(payload);
    documentValue = JSON.parse(decoded);
  } catch (error) {
    if (error.code) throw error;
    throw problemChainError("PQPC_DOCUMENT_INVALID", "Custom XML payload không phải UTF-8 JSON hợp lệ.");
  }
  if (canonicalProblemChainJson(documentValue) !== decoded) {
    throw problemChainError("PQPC_DOCUMENT_INVALID", "Custom XML payload không phải canonical JSON.");
  }
  return {document: documentValue, historyHash};
}

async function readProblemChainXml() {
  if (!problemChainSupported()) {
    throw problemChainError("PQPC_EXCEL_API_UNSUPPORTED", "Problem Chain cần ExcelApi 1.5.");
  }
  return Excel.run(async (context) => {
    const parts = context.workbook.customXmlParts.getByNamespace(PROBLEM_CHAIN_NAMESPACE);
    parts.load("items/id");
    await context.sync();
    if (parts.items.length > 1) {
      throw problemChainError("PQPC_DUPLICATE_XML_PART", "Workbook có nhiều hơn một Problem Chain Custom XML part.");
    }
    if (!parts.items.length) return {document: null, historyHash: null};
    const xml = parts.items[0].getXml();
    await context.sync();
    return parseProblemChainXml(xml.value);
  });
}

async function deleteProblemChainXml() {
  if (!problemChainSupported()) {
    throw problemChainError("PQPC_EXCEL_API_UNSUPPORTED", "Problem Chain cần ExcelApi 1.5.");
  }
  return Excel.run(async (context) => {
    const parts = context.workbook.customXmlParts.getByNamespace(PROBLEM_CHAIN_NAMESPACE);
    parts.load("items/id");
    await context.sync();
    for (const part of parts.items || []) {
      part.delete();
    }
    await context.sync();
  });
}

async function clearProblemChainHistory() {
  if (state.busy) return;
  clearError();
  setBusy(true, "Đang xóa toàn bộ lịch sử Problem Chain…");
  try {
    await deleteProblemChainXml();
    state.problemChainDocument = null;
    state.problemChainHistoryHash = null;
    state.problemChainViewRevisionId = null;
    state.pqTypedPreviewCache = [];
    state.problemChainDataVersion = 0;
    state.problemChainVersionPending = false;
    state.expandedRevisionIds.clear();
    state.expandedStepId = null;
    closeProblemBranchEditor();
    renderProblemImpactReport(null);
    await hydrateProblemChain();
    byId("pqpc-progress").textContent = "Đã xóa toàn bộ lịch sử Problem Chain khỏi workbook. Hãy Save workbook để giữ thay đổi.";
  } catch (error) {
    showError(error.code || "PQPC_CLEAR_FAILED", error.message);
  } finally {
    setBusy(false, "");
    updateProblemChainButtons();
  }
}

function problemRevisionById(revisionId) {
  for (const chain of problemChainDocuments()) {
    const revision = (chain.revisions || []).find((item) => item.revisionId === revisionId);
    if (revision) return revision;
  }
  return null;
}

function problemChainDocuments() {
  const active = state.problemChainDocument;
  if (!active) return [];
  return [active, ...(active.archivedChains || [])].sort((left, right) => {
    const leftRoot = (left.revisions || []).find((item) => !item.parentRevisionId);
    const rightRoot = (right.revisions || []).find((item) => !item.parentRevisionId);
    return compareProblemRevisions(leftRoot || {}, rightRoot || {});
  });
}

function problemChainForRevision(revisionId) {
  return problemChainDocuments().find((chain) =>
    (chain.revisions || []).some((revision) => revision.revisionId === revisionId)) || null;
}

function problemRevisionLabel(revision) {
  if (!revision) return "Revision";
  if (revision.name) return revision.name;
  const chains = problemChainDocuments();
  const chainIndex = chains.findIndex((chain) =>
    (chain.revisions || []).some((item) => item.revisionId === revision.revisionId));
  if (chainIndex < 0) return "Revision";
  const chain = chains[chainIndex];
  const revisionIndex = (chain.revisions || []).findIndex((item) => item.revisionId === revision.revisionId);
  return revision.parentRevisionId
    ? `Tiếp nối ${chainIndex + 1}.${revisionIndex}` : `Vấn đề ${chainIndex + 1}`;
}

function reconcileProblemChainPreviewCache() {
  const revisions = new Map();
  for (const chain of problemChainDocuments()) {
    for (const revision of chain.revisions || []) {
      revisions.set(revision.revisionId, {reviewHash: revision.reviewHash, chainId: chain.chainId});
    }
  }
  const workbookKey = state.workbook ? workbookIdentity(state.workbook) : "";
  state.pqTypedPreviewCache = state.pqTypedPreviewCache.filter((entry) => {
    const revision = revisions.get(entry.revisionId);
    return entry.workbookKey === workbookKey && revision
      && revision.chainId === entry.chainId && revision.reviewHash === entry.reviewHash;
  });
}

function renderProblemDataVersion() {
  byId("pqpc-data-version").textContent = `Phiên bản dữ liệu: ${state.problemChainDataVersion}. Cache khác phiên bản được giữ để so sánh, không dùng để ghi.`;
}

function rememberProblemChainPreview(preview) {
  const revision = problemRevisionById(preview.revisionId);
  if (!state.problemChainSupported || !state.problemChainHydrated || !revision
    || !state.workbook || state.problemChainDocument?.headRevisionId !== preview.revisionId
    || state.pqTypedPlan?.revision?.reviewHash !== revision.reviewHash) return;
  // Only display data is cached. Never retain previewId or an approval/write token.
  const displayCell = (value) => typeof value === "string" && value.length > PROBLEM_CHAIN_CACHE_CELL_CHARS
    ? `${value.slice(0, PROBLEM_CHAIN_CACHE_CELL_CHARS - 1)}…` : value;
  const display = {
    sourceRows: preview.sourceRows, resultRows: preview.resultRows, resultColumns: preview.resultColumns,
    beforeColumns: (preview.beforeColumns || []).slice(0, 200),
    beforeRows: (preview.beforeRows || []).slice(0, 20).map((row) => row.slice(0, 200).map(displayCell)),
    afterColumns: (preview.afterColumns || []).slice(0, 200),
    afterRows: (preview.afterRows || []).slice(0, 20).map((row) => row.slice(0, 200).map(displayCell)),
    excelVersion: preview.runtimeEvidence?.excelVersion || "",
  };
  state.pqTypedPreviewCache = state.pqTypedPreviewCache.filter((entry) => entry.revisionId !== preview.revisionId);
  state.pqTypedPreviewCache.push({
    chainId: state.problemChainDocument.chainId, workbookKey: workbookIdentity(state.workbook),
    revisionId: revision.revisionId, reviewHash: revision.reviewHash,
    cachedAt: new Date().toISOString(), dataVersion: preview.runVersion ?? state.problemChainDataVersion, display,
  });
  if (state.pqTypedPreviewCache.length > PROBLEM_CHAIN_PREVIEW_CACHE_LIMIT) {
    state.pqTypedPreviewCache.shift();
  }
}

function showCachedProblemChainPreview(revisionId) {
  state.pqTypedPreview = null;
  state.pqTypedApproval = null;
  const revision = problemRevisionById(revisionId);
  const entry = revision && state.workbook && state.pqTypedPreviewCache.find((item) =>
    item.chainId === state.problemChainDocument?.chainId
    && item.workbookKey === workbookIdentity(state.workbook)
    && item.revisionId === revisionId && item.reviewHash === revision.reviewHash);
  if (!entry) {
    setHidden("pq2-preview-section", true);
    updatePQButtons();
    return false;
  }
  renderTypedPreviewContent(entry.display, true, entry.cachedAt,
    entry.dataVersion !== state.problemChainDataVersion);
  byId("pq2-progress").textContent = entry.dataVersion !== state.problemChainDataVersion
    ? "Đang xem kết quả cũ để so sánh. Chọn Quay lại bản này sẽ tính lại revision trước khi ghi."
    : "Đang xem kết quả đã lưu; khi Quay lại bản này server vẫn kiểm fingerprint nguồn trước khi ghi.";
  return true;
}

function typedPlanFromProblemRevision(revision) {
  if (!revision || !state.problemChainDocument) return null;
  const historical = revision.validationAtCreation || {};
  const hardBlockers = [...(revision.hardBlockers || historical.hardBlockers || [])];
  const parent = revision.parentRevisionId ? problemRevisionById(revision.parentRevisionId) : null;
  const noPipelineChange = parent
    && JSON.stringify(revision.steps) === JSON.stringify(parent.steps)
    && revision.finalOutputStepId === parent.finalOutputStepId;
  if (noPipelineChange) {
    hardBlockers.push({
      code: "PQPC_NO_PIPELINE_CHANGE",
      reason: "Revision này giữ nguyên các bước của revision cha.",
      remedy: "Tạo yêu cầu cụ thể hơn để thêm hoặc sửa bước xử lý.",
    });
  }
  const questions = Array.isArray(revision.questions) ? revision.questions : [];
  const planStatus = hardBlockers.length || historical.overall === "blocked" ? "blocked"
    : questions.length ? "needsClarification" : "reviewReady";
  return {
    schemaVersion: "2.0",
    planId: state.problemChainDocument.planId,
    snapshotId: revision.snapshotId,
    revision: {
      revisionId: revision.revisionId,
      parentRevisionId: revision.parentRevisionId,
      createdAt: revision.createdAt,
      changeReason: revision.changeReason,
      reviewHash: revision.reviewHash,
    },
    planStatus,
    summary: revision.summary || "",
    questions,
    assumptions: revision.assumptions || [],
    warnings: revision.warnings || [],
    hardBlockers,
    sources: revision.sources || [],
    steps: revision.steps || [],
    finalOutputStepId: revision.finalOutputStepId,
    changeSet: revision.changeSet || [],
    validation: historical.validation || historical,
    preview: null,
    approval: {status: "notRequested"},
  };
}

function problemChainHeadMatchesView() {
  const head = state.problemChainDocument?.headRevisionId || null;
  return Boolean(head && state.problemChainViewRevisionId === head);
}

function selectProblemChainRevision(revisionId) {
  const revision = problemRevisionById(revisionId);
  if (!revision) throw problemChainError("PQPC_REVISION_NOT_FOUND", "Revision không còn trong lịch sử workbook.");
  state.problemChainViewRevisionId = revisionId;
  state.pqTypedPlan = typedPlanFromProblemRevision(revision);
  state.pqTypedPreview = null;
  state.pqTypedApproval = null;
  state.pqStepDiagnosticStaging = null;
  setHidden("pq2-diagnostic-section", true);
  renderTypedPlan(state.pqTypedPlan);
  showCachedProblemChainPreview(revisionId);
  renderProblemChain();
  updatePQButtons();
}

function problemChainButton(label, handler, disabled = false) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "button button-ghost";
  button.textContent = label;
  button.disabled = disabled;
  button.addEventListener("click", handler);
  return button;
}

function compareProblemRevisions(left, right) {
  const leftTime = String(left.createdAt || "");
  const rightTime = String(right.createdAt || "");
  if (leftTime < rightTime) return -1;
  if (leftTime > rightTime) return 1;
  return String(left.revisionId).localeCompare(String(right.revisionId));
}

function problemRevisionTree(revisions) {
  const byParent = new Map();
  for (const revision of revisions) {
    const parent = revision.parentRevisionId || null;
    if (!byParent.has(parent)) byParent.set(parent, []);
    byParent.get(parent).push(revision);
  }
  for (const children of byParent.values()) children.sort(compareProblemRevisions);
  const result = [];
  const visit = (revision, depth) => {
    result.push({revision, depth});
    for (const child of byParent.get(revision.revisionId) || []) visit(child, depth + 1);
  };
  for (const root of byParent.get(null) || []) visit(root, 0);
  return result;
}

function problemRevisionSubtreeIds(revisions, revisionId) {
  const children = new Map();
  for (const revision of revisions) {
    if (!revision.parentRevisionId) continue;
    if (!children.has(revision.parentRevisionId)) children.set(revision.parentRevisionId, []);
    children.get(revision.parentRevisionId).push(revision.revisionId);
  }
  const found = new Set();
  const pending = [revisionId];
  while (pending.length) {
    const current = pending.pop();
    if (found.has(current)) continue;
    found.add(current);
    pending.push(...(children.get(current) || []));
  }
  return [...found];
}

function closeProblemBranchEditor() {
  state.problemChainDraftAction = null;
  state.problemChainClarification = null;
  setHidden("pqpc-clarification", true);
  byId("pqpc-clarification-questions").replaceChildren();
  const promptInput = byId("pqpc-branch-prompt");
  if (promptInput) promptInput.value = "";
  const legacyPrompt = byId("pqpc-prompt");
  if (legacyPrompt) legacyPrompt.value = "";
  setHidden("pqpc-branch-editor", true);
  const revisions = state.problemChainDocument?.revisions || [];
  setHidden("pqpc-empty", revisions.length > 0);
}

function openProblemBranchEditor(mode, revisionId) {
  if (state.busy) {
    const progress = byId("pqpc-progress");
    if (progress) progress.textContent = "Đang xử lý thao tác trước. Hãy chờ hoàn tất rồi thử lại.";
    return;
  }
  if (!state.problemChainHydrated) {
    showError("PQPC_NOT_READY", "Lịch sử vấn đề chưa nạp xong. Hãy đợi trong giây lát rồi thử lại.");
    return;
  }
  const revisions = state.problemChainDocument?.revisions || [];
  const targetId = revisionId || (mode === "new" ? state.problemChainDocument?.headRevisionId : null);
  const revision = targetId ? problemRevisionById(targetId) : null;
  if (!new Set(["new", "newRoot"]).has(mode) && !revision) {
    showError("PQPC_REVISION_NOT_FOUND", "Revision không còn trong lịch sử workbook.");
    return;
  }
  if (mode === "editProblem" && !revision.parentRevisionId) {
    showError("PQPC_EDIT_ROOT_UNSUPPORTED", "Không thể sửa vấn đề gốc trong Phase 2 vì lịch sử chỉ được có một root. Hãy tạo nhánh từ root.");
    return;
  }
  if (mode === "editProblem" && revision.originKind !== "problem") {
    showError("PQPC_EDIT_TARGET_INVALID", "Chỉ revision được tạo từ một vấn đề người dùng mới dùng được hành động Sửa vấn đề.");
    return;
  }
  const baseRevisionId = mode === "editProblem" ? revision.parentRevisionId
    : mode === "newRoot" ? null : mode === "new" ? targetId : revision.revisionId;
  state.problemChainDraftAction = {mode, baseRevisionId, editRevisionId: mode === "editProblem" ? revision.revisionId : null};
  state.problemChainClarification = null;
  setHidden("pqpc-clarification", true);
  byId("pqpc-clarification-questions").replaceChildren();

  setProblemChainHistoryExpanded(true);

  const composer = byId("pqpc-branch-editor");
  const promptInput = byId("pqpc-branch-prompt");
  const submitBtn = byId("pqpc-branch-submit");
  const cancelBtn = byId("pqpc-branch-cancel");
  const modeLabel = byId("pqpc-branch-mode");
  const composerLabel = byId("pqpc-composer-label");
  const composerHost = byId("pqpc-composer-host");
  if (!composer || !composerHost || !promptInput || !submitBtn) {
    showError("PQPC_UI_STATE_INVALID", "Không thể mở ô nhập vấn đề. Hãy đóng rồi mở lại task pane.");
    return;
  }
  // The composer must stay outside the dynamically rendered timeline. Moving it
  // under a revision node makes timeline.replaceChildren() delete it on rerender.
  if (composer.parentElement !== composerHost) composerHost.appendChild(composer);

  const revName = revision ? problemRevisionLabel(revision) : "HEAD";

  if (mode === "branch") {
    if (modeLabel) modeLabel.textContent = "TẠO NHÁNH";
    byId("pqpc-branch-title").textContent = `Tạo nhánh từ ${revName}`;
    byId("pqpc-branch-explanation").textContent = "Revision mới sẽ dùng revision này làm cha. Nhánh và HEAD hiện tại được giữ nguyên cho tới khi candidate ghi và commit thành công.";
    if (composerLabel) composerLabel.textContent = `Yêu cầu nối tiếp ${revName}`;
    promptInput.placeholder = `Nhập yêu cầu nối tiếp ${revName}…`;
    promptInput.value = "";
    if (cancelBtn) setHidden("pqpc-branch-cancel", false);
    submitBtn.className = "button primary";
    submitBtn.setAttribute("aria-label", `Tạo nhánh từ ${revName}`);
    submitBtn.title = "Tạo nhánh (Ctrl+Enter)";
    submitBtn.dataset.tooltip = submitBtn.title;
    const branchSpan = document.createElement("span");
    branchSpan.textContent = "Tạo nhánh ";
    submitBtn.replaceChildren(branchSpan, createIcon("arrow-right", "small"));
  } else if (mode === "editProblem") {
    if (modeLabel) modeLabel.textContent = "SỬA VẤN ĐỀ";
    byId("pqpc-branch-title").textContent = `Tạo phiên bản sửa của ${revName}`;
    byId("pqpc-branch-explanation").textContent = "Revision mới sẽ là sibling của vấn đề được sửa. Các revision phía sau không tự chạy lại, không bị sửa hoặc xóa.";
    if (composerLabel) composerLabel.textContent = `Yêu cầu sửa ${revName}`;
    promptInput.placeholder = `Nhập yêu cầu sửa ${revName}…`;
    promptInput.value = revision.problemPrompt || "";
    if (cancelBtn) setHidden("pqpc-branch-cancel", false);
    submitBtn.className = "button primary";
    submitBtn.setAttribute("aria-label", `Tạo bản sửa của ${revName}`);
    submitBtn.title = "Tạo bản sửa (Ctrl+Enter)";
    submitBtn.dataset.tooltip = submitBtn.title;
    const editSpan = document.createElement("span");
    editSpan.textContent = "Tạo bản sửa ";
    submitBtn.replaceChildren(editSpan, createIcon("arrow-right", "small"));
  } else {
    const createsRoot = mode === "newRoot";
    if (modeLabel) modeLabel.textContent = createsRoot ? "VẤN ĐỀ GỐC MỚI" : (revisions.length ? "VẤN ĐỀ TIẾP THEO" : "VẤN ĐỀ ĐẦU TIÊN");
    byId("pqpc-branch-title").textContent = createsRoot ? "Tạo vấn đề gốc mới" : revisions.length ? `Vấn đề mới từ ${revName}` : "Tạo vấn đề đầu tiên";
    byId("pqpc-branch-explanation").textContent = createsRoot ? "Tạo một cây vấn đề độc lập với HEAD riêng; các cây cũ được giữ nguyên." : revisions.length ? "Revision mới sẽ nối tiếp từ HEAD." : "Vấn đề đầu tiên sẽ tạo revision gốc.";
    if (composerLabel) composerLabel.textContent = "Yêu cầu mới";
    promptInput.placeholder = createsRoot ? "Nhập một vấn đề dữ liệu độc lập…" : revisions.length ? `Nhập vấn đề mới từ ${revName}…` : "Ví dụ: Đọc bảng Sales và chuẩn hóa ProductCode…";
    promptInput.value = "";
    if (!revisions.length) {
      if (cancelBtn) setHidden("pqpc-branch-cancel", true);
      submitBtn.className = "icon-button primary send-button";
      submitBtn.setAttribute("aria-label", "Tạo vấn đề đầu tiên");
      submitBtn.title = "Tạo vấn đề đầu tiên (Ctrl+Enter)";
      submitBtn.dataset.tooltip = submitBtn.title;
      submitBtn.replaceChildren(createIcon("arrow-right"));
    } else {
      if (cancelBtn) setHidden("pqpc-branch-cancel", false);
      submitBtn.className = "button primary";
      submitBtn.setAttribute("aria-label", createsRoot ? "Tạo vấn đề gốc mới" : "Tạo vấn đề");
      submitBtn.title = createsRoot ? "Tạo vấn đề gốc mới (Ctrl+Enter)" : "Tạo vấn đề (Ctrl+Enter)";
      submitBtn.dataset.tooltip = submitBtn.title;
      const newSpan = document.createElement("span");
      newSpan.textContent = createsRoot ? "Tạo vấn đề gốc " : "Tạo vấn đề ";
      submitBtn.replaceChildren(newSpan, createIcon("arrow-right", "small"));
    }
  }

  // Clear stale progress error and hide empty hint while composer is open
  if (byId("pqpc-progress")) byId("pqpc-progress").textContent = "";
  setHidden("pqpc-empty", true);

  setHidden("pqpc-branch-editor", false);
  promptInput.focus();
}

function renderProblemImpactReport(report) {
  const hasImpact = report && ["affectedRevisionIds", "affectedStepIds", "affectedColumnIds", "issues"]
    .some((key) => Array.isArray(report[key]) && report[key].length > 0);
  setHidden("pqpc-impact-section", !hasImpact);
  if (!hasImpact) return;
  const summary = [];
  if (report.affectedRevisionIds?.length) summary.push(`${report.affectedRevisionIds.length} revision bị ảnh hưởng`);
  if (report.affectedStepIds?.length) summary.push(`${report.affectedStepIds.length} step bị ảnh hưởng`);
  if (report.affectedColumnIds?.length) summary.push(`${report.affectedColumnIds.length} cột bị ảnh hưởng`);
  byId("pqpc-impact-summary").textContent = `${summary.join(" · ") || "Có ảnh hưởng cần xem lại"}. Hệ thống không tự sửa hoặc xóa logic phía sau.`;
  const list = byId("pqpc-impact-list");
  list.replaceChildren();
  for (const issue of report.issues || []) {
    const item = document.createElement("li");
    item.textContent = typeof issue === "string" ? issue
      : [issue.code, issue.reason || issue.message, issue.remedy].filter(Boolean).join(" · ");
    list.appendChild(item);
  }
}

function renderProblemChain() {
  const documentValue = state.problemChainDocument;
  const chains = problemChainDocuments();
  const revisions = chains.flatMap((chain) => chain.revisions || []);
  const chainByRevision = new Map();
  chains.forEach((chain) => {
    for (const revision of chain.revisions || []) chainByRevision.set(revision.revisionId, chain);
  });
  const timeline = byId("pqpc-timeline");
  timeline.replaceChildren();

  const headSummary = byId("pqpc-head-summary");
  if (headSummary) {
    if (!revisions.length) {
      headSummary.textContent = "Chưa có lịch sử";
    } else {
      const headRev = problemRevisionById(documentValue?.headRevisionId);
      const headName = problemRevisionLabel(headRev);
      headSummary.textContent = `Đang làm việc: ${headName} · ${chains.length} vấn đề gốc · ${revisions.length} revision`;
    }
  }

  const pcStatus = byId("pqpc-status");
  if (pcStatus) {
    pcStatus.textContent = state.problemChainHydrated ? (revisions.length ? `${revisions.length} REVISION` : "SẴN SÀNG") : "BỊ CHẶN";
    pcStatus.className = `badge ${state.problemChainHydrated ? "badge-ready" : "badge-failed"} sr-only`;
    pcStatus.hidden = true;
  }

  const toggleBtn = byId("pqpc-history-toggle");
  if (toggleBtn) {
    toggleBtn.setAttribute("aria-expanded", String(state.problemChainHistoryExpanded));
    toggleBtn.setAttribute("aria-label", state.problemChainHistoryExpanded ? "Thu gọn lịch sử vấn đề" : "Mở lịch sử vấn đề");
    toggleBtn.title = state.problemChainHistoryExpanded ? "Thu gọn lịch sử" : "Mở lịch sử";
    if (toggleBtn.dataset) toggleBtn.dataset.tooltip = toggleBtn.title;
  }
  const newProblemBtn = byId("pqpc-new-problem");
  if (newProblemBtn) {
    newProblemBtn.setAttribute("aria-label", "Tạo vấn đề gốc mới");
    newProblemBtn.title = "Tạo một vấn đề gốc độc lập";
    if (newProblemBtn.dataset) newProblemBtn.dataset.tooltip = newProblemBtn.title;
  }
  const clearHistoryBtn = byId("pqpc-clear-history");
  if (clearHistoryBtn) {
    clearHistoryBtn.disabled = !revisions.length;
    clearHistoryBtn.setAttribute("aria-label", "Xóa sạch lịch sử");
    clearHistoryBtn.title = revisions.length
      ? `Xóa sạch toàn bộ ${revisions.length} revision trong lịch sử`
      : "Chưa có lịch sử để xóa";
    if (clearHistoryBtn.dataset) clearHistoryBtn.dataset.tooltip = clearHistoryBtn.title;
  }

  const byParent = new Map();
  for (const revision of revisions) {
    const parent = revision.parentRevisionId || null;
    if (!byParent.has(parent)) byParent.set(parent, []);
    byParent.get(parent).push(revision);
  }
  for (const children of byParent.values()) children.sort(compareProblemRevisions);

  if (state.expandedRevisionIds.size === 0 && documentValue?.headRevisionId) {
    let curr = problemRevisionById(documentValue.headRevisionId);
    while (curr && curr.parentRevisionId) {
      state.expandedRevisionIds.add(curr.parentRevisionId);
      curr = problemRevisionById(curr.parentRevisionId);
    }
  }

  function createTreeNode(revision, depth) {
    const owningChain = chainByRevision.get(revision.revisionId);
    const node = document.createElement("li");
    node.className = "node";
    node.dataset.id = revision.revisionId;
    node.dataset.revisionId = revision.revisionId;
    node.dataset.branchDepth = String(depth);
    const validationStatus = revision.validationAtCreation?.planStatus || revision.planStatus || "unknown";
    node.dataset.validationStatus = validationStatus;

    const isChainHead = revision.revisionId === owningChain?.headRevisionId;
    const isHead = owningChain?.chainId === documentValue.chainId && isChainHead;
    const isViewed = revision.revisionId === state.problemChainViewRevisionId;
    const children = byParent.get(revision.revisionId) || [];
    const hasChildren = children.length > 0;

    const isExpanded = state.expandedRevisionIds.has(revision.revisionId);
    if (hasChildren) {
      node.classList.add(isExpanded ? "expanded" : "collapsed");
    }

    const row = document.createElement("div");
    row.className = `node-row${isHead ? " head" : ""}${isViewed ? " is-viewed" : ""}`;
    row.dataset.revisionId = revision.revisionId;

    const revisionName = problemRevisionLabel(revision);

    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = `toggle${hasChildren ? "" : " leaf"}`;
    if (hasChildren) {
      toggle.setAttribute("aria-label", `Mở hoặc thu gọn ${revisionName}`);
      toggle.appendChild(createIcon("chevron-right", "chevron"));
      toggle.addEventListener("click", (e) => {
        e.stopPropagation();
        toggleTreeNode(node, revision.revisionId);
      });
    } else {
      toggle.disabled = true;
      toggle.setAttribute("aria-hidden", "true");
      toggle.appendChild(createIcon("circle-dot", "small"));
    }

    const label = document.createElement("button");
    label.type = "button";
    label.className = "node-label";
    label.setAttribute("aria-label", `Chọn ${revisionName} làm HEAD`);

    const nameSpan = document.createElement("span");
    nameSpan.className = "node-name";
    nameSpan.textContent = revisionName + " ";
    if (isChainHead) {
      const headBadge = document.createElement("span");
      headBadge.className = "head-badge";
      headBadge.textContent = isHead ? "ĐANG LÀM VIỆC" : "HEAD";
      nameSpan.appendChild(headBadge);
    }

    const summarySpan = document.createElement("span");
    summarySpan.className = "node-summary";
    const promptText = revision.problemPrompt || revision.changeReason || "Revision không có prompt.";
    summarySpan.textContent = promptText;
    summarySpan.title = `${promptText} · ${validationStatus}`;

    label.append(nameSpan, summarySpan);

    const onRowCheckout = async (e) => {
      e?.stopPropagation?.();
      if (state.busy || state.checkoutRunning) return;
      if (hasChildren && !node.classList.contains("expanded")) {
        toggleTreeNode(node, revision.revisionId, true);
      }
      await checkoutProblemRevision(revision.revisionId, owningChain?.chainId);
    };

    label.addEventListener("click", onRowCheckout);
    row.addEventListener("click", (e) => {
      if (e?.target?.closest && (e.target.closest("button") || e.target.closest(".node-actions"))) return;
      onRowCheckout(e);
    });

    const actions = document.createElement("div");
    actions.className = "node-actions";
    actions.addEventListener("click", (e) => {
      e.stopPropagation();
      const btn = e.target?.closest?.("button");
      if (btn && btn.disabled) {
        const tooltip = btn.getAttribute("title") || btn.dataset?.tooltip;
        if (tooltip) {
          byId("pqpc-progress").textContent = tooltip;
        }
      }
    });

    const branchBtn = createIconButton({
      icon: "git-fork",
      label: `Tạo nhánh từ ${revisionName}`,
      tooltip: "Tạo nhánh",
      className: "branch",
      onClick: async (e) => {
        e.stopPropagation();
        if (owningChain?.chainId !== state.problemChainDocument?.chainId) {
          const activated = await activateProblemChainRevision(owningChain.chainId, revision.revisionId);
          if (!activated) return;
        }
        openProblemBranchEditor("branch", revision.revisionId);
      },
    });

    const canEdit = revision.originKind === "problem";
    const editTooltip = !revision.parentRevisionId
      ? `Vấn đề gốc không thể sửa thành nhánh anh em vì lịch sử chỉ có một root. Bấm để tạo nhánh từ ${revisionName} hoặc xóa để tạo lại.`
      : revision.originKind !== "problem"
      ? "Revision này là chỉnh sửa step/repair, không phải một vấn đề người dùng."
      : `Sửa ${revisionName}`;
    const editBtn = createIconButton({
      icon: "square-pen",
      label: `Sửa ${revisionName}`,
      tooltip: editTooltip,
      className: "edit",
      disabled: !canEdit,
      onClick: async (e) => {
        e.stopPropagation();
        if (owningChain?.chainId !== state.problemChainDocument?.chainId) {
          const activated = await activateProblemChainRevision(owningChain.chainId, revision.revisionId);
          if (!activated) return;
        }
        if (!revision.parentRevisionId) {
          const choice = await requestPQConfirmation(state.workbook?.name || "workbook", {
            title: `Vấn đề gốc (${revisionName})`,
            detail: `Problem Chain quy định lịch sử chỉ có một root duy nhất nên không thể sửa tạo nhánh anh em. Bạn có muốn tạo một nhánh tiếp theo từ ${revisionName} không? (Hoặc bấm Hủy rồi chọn biểu tượng Thùng rác nếu muốn xóa để tạo lại).`,
            continueLabel: "Tạo nhánh từ root",
          });
          if (choice) {
            openProblemBranchEditor("branch", revision.revisionId);
          }
          return;
        }
        openProblemBranchEditor("editProblem", revision.revisionId);
      },
    });

    const deleteTooltip = !revision.parentRevisionId
      ? `Xóa vấn đề gốc (${revisionName}) và làm mới lịch sử`
      : `Xóa ${revisionName}`;
    const deleteBtn = createIconButton({
      icon: "trash-2",
      label: `Xóa ${revisionName}`,
      tooltip: deleteTooltip,
      className: "danger",
      disabled: false,
      onClick: async (e) => {
        e.stopPropagation();
        if (owningChain?.chainId !== state.problemChainDocument?.chainId) {
          const activated = await activateProblemChainRevision(owningChain.chainId, revision.revisionId);
          if (!activated) return;
        }
        deleteProblemRevision(revision.revisionId);
      },
    });

    actions.append(branchBtn, editBtn, deleteBtn);
    row.append(toggle, label, actions);
    node.appendChild(row);

    if (hasChildren) {
      const childrenUl = document.createElement("ul");
      childrenUl.className = "children";
      for (const child of children) {
        childrenUl.appendChild(createTreeNode(child, depth + 1));
      }
      node.appendChild(childrenUl);
    }

    return node;
  }

  function toggleTreeNode(node, revisionId, forceExpand) {
    const isCurrentlyExpanded = node.classList?.contains("expanded");
    const shouldExpand = forceExpand !== undefined ? forceExpand : !isCurrentlyExpanded;
    if (shouldExpand) {
      if (node.parentElement) {
        for (const sibling of node.parentElement.children || []) {
          if (sibling !== node && sibling.classList?.contains("node") && sibling.classList?.contains("expanded")) {
            sibling.classList.remove("expanded");
            sibling.classList.add("collapsed");
            if (sibling.dataset?.revisionId) {
              state.expandedRevisionIds.delete(sibling.dataset.revisionId);
            }
          }
        }
      }
      node.classList?.add("expanded");
      node.classList?.remove("collapsed");
      state.expandedRevisionIds.add(revisionId);
    } else {
      node.classList?.remove("expanded");
      node.classList?.add("collapsed");
      state.expandedRevisionIds.delete(revisionId);
    }
  }

  const rootRevisions = byParent.get(null) || [];
  if (rootRevisions.length > 0) {
    const treeUl = document.createElement("ul");
    treeUl.className = "tree";
    for (const root of rootRevisions) {
      treeUl.appendChild(createTreeNode(root, 0));
    }
    timeline.appendChild(treeUl);
  }

  setHidden("pqpc-source-changed-wrap", !revisions.length);
  setHidden("pqpc-data-version", !revisions.length);
  const composerOpen = byId("pqpc-branch-editor") && !byId("pqpc-branch-editor").classList.contains("hidden");
  setHidden("pqpc-empty", revisions.length > 0 || composerOpen);
  byId("pqpc-create-button").textContent = revisions.length ? "Tạo vấn đề gốc mới" : "Tạo vấn đề đầu tiên";
  updateProblemChainButtons();
}

async function deleteProblemRevision(revisionId) {
  if (state.busy || !state.problemChainHydrated || !state.problemChainDocument) return;
  const revision = problemRevisionById(revisionId);
  if (!revision) {
    showError("PQPC_REVISION_NOT_FOUND", "Revision không còn trong lịch sử workbook.");
    return;
  }
  const revisions = state.problemChainDocument.revisions || [];
  const revisionName = problemRevisionLabel(revision);
  if (!revision.parentRevisionId) {
    const rootCount = problemChainDocuments().length;
    const confirmed = await requestPQConfirmation(state.workbook?.name || "workbook", {
      title: rootCount > 1 ? `Xóa vấn đề gốc (${revisionName}) và toàn bộ cây con?` : `Xóa vấn đề gốc (${revisionName}) và toàn bộ lịch sử?`,
      detail: rootCount > 1
        ? `Xóa ${revisions.length} revision thuộc vấn đề gốc này. ${rootCount - 1} vấn đề gốc khác vẫn được giữ nguyên. Add-in không tự Save.`
        : `Đây là vấn đề gốc cuối cùng. Xóa vấn đề này sẽ xóa sạch toàn bộ ${revisions.length} revision khỏi workbook. Thao tác này không tự Save workbook.`,
      continueLabel: rootCount > 1 ? "Xóa cây vấn đề này" : "Xóa toàn bộ lịch sử",
    });
    if (!confirmed) return;
    if (rootCount === 1) {
      await clearProblemChainHistory();
      return;
    }
  }
  const subtreeIds = problemRevisionSubtreeIds(state.problemChainDocument.revisions, revisionId);
  if (revision.parentRevisionId && subtreeIds.length > 1) {
    const confirmed = await requestPQConfirmation(state.workbook?.name || "workbook", {
      title: `Xóa vấn đề cha và ${subtreeIds.length - 1} bản con?`,
      detail: `Thao tác này xóa ${subtreeIds.length} revision trong nhánh khỏi lịch sử nhúng trong workbook. Các nhánh anh em không bị thay đổi. Add-in không tự Save.`,
      continueLabel: "Xóa cả nhánh",
    });
    if (!confirmed) return;
  }
  clearError();
  setBusy(true, "Đang xóa vấn đề…");
  try {
    const candidate = await api("/api/pq/v2/problem-chains/problems/delete", {
      document: state.problemChainDocument,
      baseHistoryHash: state.problemChainHistoryHash,
      revisionId,
    });
    await persistProblemChainCandidate(candidate);
    reconcileProblemChainPreviewCache();
    closeProblemBranchEditor();
    renderProblemImpactReport(null);
    byId("pqpc-progress").textContent = subtreeIds.length > 1
      ? `Đã xóa nhánh gồm ${subtreeIds.length} revision. Hãy Save workbook để giữ thay đổi.`
      : "Đã xóa vấn đề cuối nhánh. Hãy Save workbook để giữ thay đổi.";
  } catch (error) {
    showError(error.code, error.message);
    byId("pqpc-progress").textContent = "Không xóa lịch sử; workbook hiện tại được giữ nguyên.";
  } finally {
    setBusy(false, "");
    updateProblemChainButtons();
  }
}

function updateProblemChainButtons() {
  if (!byId("pqpc-create-button") && !byId("pqpc-branch-submit")) return;
  const prompt = (byId("pqpc-branch-prompt")?.value || byId("pqpc-prompt")?.value || "").trim();
  const clarification = state.problemChainClarification;
  const answers = clarification
    ? [...byId("pqpc-clarification-questions").querySelectorAll(".clarification-answer")]
    : [];
  const answersReady = !clarification
    || (answers.length === clarification.questions.length && answers.every((input) => input.value.trim()));
  const rootNeedsSource = (!state.problemChainDocument || state.problemChainDraftAction?.mode === "newRoot")
    && !selectedPQSource();
  const disabled = state.busy || !state.problemChainSupported
    || !state.problemChainHydrated || !state.workbook || rootNeedsSource
    || !state.codexAvailable || !prompt || !answersReady;
  if (byId("pqpc-create-button")) {
    byId("pqpc-create-button").disabled = disabled;
  }
  if (byId("pqpc-branch-submit")) {
    byId("pqpc-branch-submit").disabled = disabled;
  }
  const count = (byId("pqpc-branch-prompt")?.value || byId("pqpc-prompt")?.value || "").length;
  if (byId("pqpc-prompt-count")) {
    byId("pqpc-prompt-count").textContent = `${count} / 4000`;
  }
}

function renderProblemClarification(response, originalPrompt) {
  const questions = response?.questions;
  if (!Array.isArray(questions) || !questions.length || questions.some((question) => typeof question !== "string" || !question.trim())) {
    throw problemChainError("PQPC_RESPONSE_INVALID", "Phân tích yêu cầu trả về câu hỏi không hợp lệ; HEAD được giữ nguyên.");
  }
  const previous = state.problemChainClarification;
  const rounds = previous && previous.originalPrompt === originalPrompt ? previous.rounds.slice() : [];
  if (previous && previous.originalPrompt === originalPrompt) {
    const answers = [...byId("pqpc-clarification-questions").querySelectorAll(".clarification-answer")]
      .map((input) => input.value.trim());
    previous.questions.forEach((question, index) => rounds.push({question, answer: answers[index]}));
  }
  const submit = byId("pqpc-branch-submit");
  state.problemChainClarification = {
    originalPrompt, rounds, questions,
    defaultSubmitText: previous?.defaultSubmitText || submit.textContent,
    defaultSubmitChildren: previous?.defaultSubmitChildren || [...(submit.childNodes || submit.children || [])],
  };
  const container = byId("pqpc-clarification-questions");
  container.replaceChildren();
  questions.forEach((question, index) => {
    const label = document.createElement("label");
    label.className = "clarification-question";
    const input = document.createElement("textarea");
    input.className = "clarification-answer";
    input.rows = 2;
    input.maxLength = 1000;
    input.placeholder = "Nhập câu trả lời hoặc quy tắc bạn muốn áp dụng…";
    input.setAttribute("aria-label", `Trả lời câu hỏi ${index + 1}: ${question}`);
    input.addEventListener("input", updateProblemChainButtons);
    input.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" || !event.ctrlKey || event.altKey || event.metaKey || event.shiftKey || event.isComposing || event.repeat) return;
      event.preventDefault();
      submitProblemBranchDraft();
    });
    label.textContent = `${index + 1}. ${question}`;
    label.appendChild(input);
    container.appendChild(label);
  });
  byId("pqpc-clarification-title").textContent = `Cần bạn làm rõ · ${questions.length} câu hỏi`;
  const notes = [...new Set([
    ...(response.assumptions || []).map((item) => `Giả định: ${item}`),
    ...(response.warnings || []),
  ])];
  const noteList = byId("pqpc-clarification-notes-list");
  noteList.replaceChildren();
  notes.forEach((item) => {
    const row = document.createElement("li");
    row.textContent = item;
    noteList.appendChild(row);
  });
  byId("pqpc-clarification-notes-summary").textContent = `Ghi chú khác · ${notes.length}`;
  setHidden("pqpc-clarification-notes", !notes.length);
  setHidden("pqpc-clarification", false);
  submit.textContent = "Gửi câu trả lời và phân tích tiếp";
  byId("pqpc-progress").textContent = "Chưa tạo revision; HEAD, cache và lịch sử giữ nguyên.";
  byId("pqpc-branch-status").textContent = "Trả lời các câu hỏi rồi phân tích tiếp yêu cầu đang nhập.";
  updateProblemChainButtons();
  container.querySelector(".clarification-answer")?.focus();
}

function clarifiedProblemPrompt(originalPrompt) {
  const clarification = state.problemChainClarification;
  if (!clarification) return originalPrompt;
  if (clarification.originalPrompt !== originalPrompt) {
    throw problemChainError("PQPC_CLARIFICATION_STALE", "Yêu cầu đã thay đổi. Hãy phân tích lại yêu cầu mới.");
  }
  const answers = [...byId("pqpc-clarification-questions").querySelectorAll(".clarification-answer")]
    .map((input) => input.value.trim());
  if (answers.length !== clarification.questions.length || answers.some((answer) => !answer)) {
    throw problemChainError("PQPC_ANSWER_REQUIRED", "Hãy trả lời mọi câu hỏi cần làm rõ trước khi phân tích tiếp.");
  }
  const rounds = [...clarification.rounds, ...clarification.questions.map((question, index) => ({question, answer: answers[index]}))];
  const completed = `${originalPrompt}\n\nLàm rõ yêu cầu:\n${rounds.map((item, index) => `${index + 1}. Hỏi: ${item.question}\n   Trả lời: ${item.answer}`).join("\n")}`;
  if (completed.length > 4000) {
    throw problemChainError("PROMPT_LIMIT", "Yêu cầu và các câu trả lời vượt 4000 ký tự. Hãy rút gọn nội dung rồi gửi lại.");
  }
  return completed;
}

function handleProblemPromptInput() {
  if (byId("pqpc-prompt")) byId("pqpc-prompt").value = byId("pqpc-branch-prompt").value;
  if (state.problemChainClarification) {
    const original = state.problemChainClarification;
    state.problemChainClarification = null;
    setHidden("pqpc-clarification", true);
    byId("pqpc-clarification-questions").replaceChildren();
    if (original.defaultSubmitChildren.length) {
      byId("pqpc-branch-submit").replaceChildren(...original.defaultSubmitChildren);
    } else {
      byId("pqpc-branch-submit").textContent = original.defaultSubmitText;
    }
    byId("pqpc-branch-status").textContent = "Yêu cầu đã thay đổi; hãy phân tích lại nội dung mới.";
  }
  updateProblemChainButtons();
}

async function hydrateProblemChain() {
  state.problemChainSupported = problemChainSupported();
  setHidden("pqpc-content", !state.problemChainSupported);
  setHidden("pq2-standalone-prompt-section", state.problemChainSupported);
  if (!state.problemChainSupported) {
    state.problemChainHydrated = false;
    state.pqTypedPreviewCache = [];
    const pcStatus = byId("pqpc-status");
    if (pcStatus) {
      pcStatus.textContent = "KHÔNG HỖ TRỢ";
      pcStatus.className = "badge badge-failed sr-only";
      pcStatus.hidden = true;
    }
    const supportEl = byId("pqpc-support");
    if (supportEl) {
      supportEl.textContent = "PQPC_EXCEL_API_UNSUPPORTED · Typed Steps trong phiên vẫn dùng được; Custom XML không được gọi.";
      setHidden("pqpc-support", false);
    }
    return;
  }
  const supportEl = byId("pqpc-support");
  if (supportEl) {
    supportEl.textContent = "";
    setHidden("pqpc-support", true);
  }
  try {
    const stored = await readProblemChainXml();
    const loaded = await api("/api/pq/v2/problem-chains/load", {
      document: stored.document,
      workbook: state.workbook,
    });
    const loadedDocument = Object.prototype.hasOwnProperty.call(loaded, "document") ? loaded.document : stored.document;
    const loadedHash = loaded.historyHash || stored.historyHash;
    if (stored.document && loadedHash !== stored.historyHash) {
      throw problemChainError("PQPC_HASH_MISMATCH", "Coordinator và Custom XML không thống nhất historyHash.");
    }
    state.problemChainDocument = loadedDocument;
    state.problemChainClarification = null;
    setHidden("pqpc-clarification", true);
    byId("pqpc-clarification-questions").replaceChildren();
    state.problemChainHistoryHash = loadedDocument ? loadedHash : null;
    state.problemChainDataVersion = Number.isInteger(loaded.dataVersion) ? loaded.dataVersion : 0;
    state.problemChainVersionPending = false;
    renderProblemDataVersion();
    state.problemChainViewRevisionId = loadedDocument?.headRevisionId || null;
    reconcileProblemChainPreviewCache();
    // Runtime evidence is session-only. A load (including after workbook
    // switch or token expiry) must not carry an old preview/approval forward.
    state.pqTypedPreview = null;
    state.pqTypedApproval = null;
    setHidden("pq2-preview-section", true);
    setHidden("pq2-repair-section", true);
    state.problemChainHydrated = true;
    if (supportEl) {
      supportEl.textContent = "";
      setHidden("pqpc-support", true);
    }
    if (state.problemChainViewRevisionId) {
      state.pqTypedPlan = typedPlanFromProblemRevision(problemRevisionById(state.problemChainViewRevisionId));
      renderTypedPlan(state.pqTypedPlan);
      showCachedProblemChainPreview(state.problemChainViewRevisionId);
    } else {
      state.pqTypedPlan = null;
      setHidden("pq2-plan-section", true);
      setHidden("pq2-run-section", true);
    }
    renderProblemChain();
    if (!loadedDocument || !loadedDocument.revisions?.length) {
      if (byId("pqpc-progress")) byId("pqpc-progress").textContent = "";
      setProblemChainHistoryExpanded(true);
      openProblemBranchEditor("new");
    }
  } catch (error) {
    state.problemChainHydrated = false;
    state.problemChainDocument = null;
    state.problemChainHistoryHash = null;
    state.problemChainViewRevisionId = null;
    state.pqTypedPreviewCache = [];
    state.problemChainDataVersion = 0;
    state.problemChainVersionPending = false;
    const errSupportEl = byId("pqpc-support");
    if (errSupportEl) {
      errSupportEl.textContent = `${error.code || "PQPC_DOCUMENT_INVALID"} · ${error.message}`;
      setHidden("pqpc-support", false);
    }
    byId("pqpc-progress").textContent = "Lịch sử bị chặn; add-in không chọn, xóa hoặc ghi đè Custom XML.";
    renderProblemChain();
    showError(error.code || "PQPC_DOCUMENT_INVALID", error.message);
  }
}

async function persistProblemChainCandidate(candidate) {
  if (!candidate || !candidate.mutationId || !candidate.document || !candidate.historyHash) {
    throw problemChainError("PQPC_DOCUMENT_INVALID", "Coordinator không trả candidate mutation đầy đủ.");
  }
  const expectedBase = candidate.baseHistoryHash ?? null;
  const candidateCanonical = canonicalProblemChainJson(candidate.document);
  const candidateXml = buildProblemChainXml(candidate.document, candidate.historyHash);
  const observed = await Excel.run(async (context) => {
    let parts = context.workbook.customXmlParts.getByNamespace(PROBLEM_CHAIN_NAMESPACE);
    parts.load("items/id");
    await context.sync();
    if (parts.items.length > 1) throw problemChainError("PQPC_DUPLICATE_XML_PART", "Workbook có nhiều hơn một Problem Chain Custom XML part.");
    if (expectedBase === null) {
      if (parts.items.length !== 0) throw problemChainError("PQPC_HISTORY_CONFLICT", "Lịch sử đã được tạo bởi thao tác khác.");
      context.workbook.customXmlParts.add(candidateXml);
    } else {
      if (parts.items.length !== 1) throw problemChainError("PQPC_HISTORY_CONFLICT", "Problem Chain đã bị xóa hoặc thay đổi.");
      const currentXml = parts.items[0].getXml();
      await context.sync();
      const current = parseProblemChainXml(currentXml.value);
      if (current.historyHash !== expectedBase
        || !state.problemChainDocument
        || canonicalProblemChainJson(current.document) !== canonicalProblemChainJson(state.problemChainDocument)) {
        throw problemChainError("PQPC_HISTORY_CONFLICT", "Problem Chain đã thay đổi; candidate không được ghi đè.");
      }
      parts.items[0].setXml(candidateXml);
    }
    await context.sync();
    parts = context.workbook.customXmlParts.getByNamespace(PROBLEM_CHAIN_NAMESPACE);
    parts.load("items/id");
    await context.sync();
    if (parts.items.length !== 1) throw problemChainError("PQPC_MUTATION_NOT_COMMITTED", "Custom XML read-back không có đúng một part.");
    const readBackXml = parts.items[0].getXml();
    await context.sync();
    const readBack = parseProblemChainXml(readBackXml.value);
    if (readBack.historyHash !== candidate.historyHash || canonicalProblemChainJson(readBack.document) !== candidateCanonical) {
      throw problemChainError("PQPC_HASH_MISMATCH", "Custom XML read-back không khớp candidate.");
    }
    return readBack;
  });
  let committed;
  try {
    committed = await api("/api/pq/v2/problem-chains/mutations/commit", {
      mutationId: candidate.mutationId,
      observedHistoryHash: observed.historyHash,
      workbook: state.workbook,
    });
    if ((committed.historyHash && committed.historyHash !== candidate.historyHash)
      || (committed.document && canonicalProblemChainJson(committed.document) !== candidateCanonical)) {
      throw problemChainError("PQPC_HASH_MISMATCH", "Coordinator commit không khớp Custom XML đã đọc lại.");
    }
  } catch (error) {
    state.problemChainHydrated = false;
    if (error.code === "PQPC_HASH_MISMATCH") throw error;
    throw problemChainError("PQPC_MUTATION_NOT_COMMITTED", `${error.message} Workbook là nguồn sự thật; hãy đọc lại lịch sử, thao tác cũ không được tự chạy lại.`);
  }
  state.problemChainDocument = committed.document || candidate.document;
  state.problemChainHistoryHash = committed.historyHash || candidate.historyHash;
  if (Number.isInteger(committed.dataVersion)) state.problemChainDataVersion = committed.dataVersion;
  renderProblemDataVersion();
  state.problemChainViewRevisionId = state.problemChainDocument.headRevisionId;
  state.problemChainHydrated = true;
  state.pqTypedPreview = null;
  state.pqTypedApproval = null;
  const revision = problemRevisionById(state.problemChainViewRevisionId);
  state.pqTypedPlan = typedPlanFromProblemRevision(revision);
  renderTypedPlan(state.pqTypedPlan);
  showCachedProblemChainPreview(state.problemChainViewRevisionId);
  setHidden("pq2-repair-section", true);
  renderProblemChain();
  byId("pqpc-progress").textContent = "Lịch sử đã được nhúng vào workbook. Hãy Save hoặc Save As để giữ sau khi đóng file.";
  return committed;
}

async function createProblemMutation({creationMode, baseRevisionId, editRevisionId = null, prompt}) {
  if (state.busy || !state.problemChainSupported || !state.problemChainHydrated || !prompt) return false;
  clearError();
  setBusy(true, creationMode === "newRoot" ? "Đang tạo vấn đề gốc mới…" : creationMode === "continue" ? "Đang tạo revision Problem Chain…" : "Đang tạo revision nhánh…");
  const mutationStartedAt = Date.now();
  let phase = "";
  let phaseStartedAt = Date.now();
  const reportPhase = (message) => {
    phase = message;
    phaseStartedAt = Date.now();
    byId("pqpc-progress").textContent = message;
    byId("pqpc-branch-status").textContent = message;
  };
  reportPhase("Đang đọc lại workbook để kiểm tra nguồn…");
  const progressTimer = typeof setInterval === "function"
    ? setInterval(() => {
      const elapsed = Math.floor((Date.now() - phaseStartedAt) / 1000);
      if (elapsed >= 10) {
        byId("pqpc-branch-status").textContent = `${phase} ${elapsed} giây.`;
      }
    }, 5000) : null;
  try {
    const requestPrompt = clarifiedProblemPrompt(prompt);
    const expectedWorkbookKey = workbookIdentity(state.workbook);
    let readTimer = null;
    let freshWorkbook;
    try {
      freshWorkbook = await Promise.race([
        readWorkbook(),
        new Promise((_, reject) => {
          readTimer = setTimeout(() => reject(problemChainError(
            "PQPC_WORKBOOK_READ_TIMEOUT",
            "Excel không trả lời khi đọc schema nguồn trong 45 giây. HEAD và yêu cầu đang nhập được giữ nguyên; hãy kiểm tra Excel rồi thử lại.",
          )), 45000);
        }),
      ]);
    } finally {
      if (readTimer !== null) clearTimeout(readTimer);
    }
    acceptWorkbookRead(expectedWorkbookKey, freshWorkbook);
    // Continuations already have a persisted source schema and bounded fresh
    // Office.js rows. Full-workbook profiling is for the initial source and
    // step diagnostics; repeating it for every branch needlessly exports and
    // scans the entire workbook before the planner can even start.
    if (!state.problemChainDocument || creationMode === "newRoot") {
      reportPhase("Đang kiểm tra mẫu nguồn ban đầu…");
      await loadSelectedSourceCheckSample();
    }
    renderWorkbook();
    const source = selectedPQSource();
    if ((!state.problemChainDocument || creationMode === "newRoot") && !source) {
      throw problemChainError("PQPC_SOURCE_SCHEMA_CHANGED", "Hãy chọn đúng một Table hoặc usedRange nguồn trước khi tạo vấn đề đầu tiên.");
    }
    reportPhase("Codex đang lập các bước cho nhánh. Bước này có thể mất đến 3 phút…");
    const candidate = await api("/api/pq/v2/problem-chains/problems", {
      document: state.problemChainDocument,
      baseHistoryHash: state.problemChainHistoryHash,
      prompt: requestPrompt,
      baseRevisionId,
      creationMode,
      editRevisionId,
      workbook: state.workbook,
      source,
    }, {timeoutMs: 195000});
    if (candidate?.status === "needsClarification" || (candidate?.revision?.questions || []).length) {
      if ((byId("pqpc-branch-prompt")?.value || byId("pqpc-prompt")?.value || "").trim() !== prompt) {
        throw problemChainError("PQPC_CLARIFICATION_STALE", "Yêu cầu đã thay đổi trong lúc phân tích. Hãy gửi lại nội dung mới.");
      }
      renderProblemClarification(candidate.status === "needsClarification" ? candidate : candidate.revision, prompt);
      return false;
    }
    if (!candidate?.mutationId || !candidate?.document) {
      throw problemChainError("PQPC_RESPONSE_INVALID", "Phân tích không trả về revision hợp lệ; HEAD được giữ nguyên.");
    }
    reportPhase("Đang lưu revision vào lịch sử workbook…");
    await persistProblemChainCandidate(candidate);
    renderProblemImpactReport(candidate.impactReport);
    byId("pqpc-branch-status").textContent = `Đã tạo revision trong ${Math.round((Date.now() - mutationStartedAt) / 1000)} giây. Hãy Save workbook để giữ lịch sử.`;
    return true;
  } catch (error) {
    showError(error.code, error.message);
    const failureMessage = error.code === "PQPC_HISTORY_CONFLICT"
      ? "Lịch sử đã thay đổi. Hãy đọc lại workbook; candidate không được ghi đè."
      : `${error.code || "LỖI"}: ${error.message || "Không tạo được revision mới."} HEAD hiện tại được giữ nguyên. Đã chờ ${Math.round((Date.now() - mutationStartedAt) / 1000)} giây.`;
    byId("pqpc-progress").textContent = failureMessage;
    byId("pqpc-branch-status").textContent = failureMessage;
    return false;
  } finally {
    if (progressTimer !== null) clearInterval(progressTimer);
    setBusy(false, "");
    updateProblemChainButtons();
  }
}

async function createProblemContinuation() {
  const prompt = (byId("pqpc-branch-prompt")?.value || byId("pqpc-prompt")?.value || "").trim();
  const baseRevisionId = state.problemChainDocument?.headRevisionId || null;
  const created = await createProblemMutation({creationMode: "continue", baseRevisionId, prompt});
  if (created) {
    if (byId("pqpc-prompt")) byId("pqpc-prompt").value = "";
    closeProblemBranchEditor();
  }
}

async function submitProblemBranchDraft() {
  const draft = state.problemChainDraftAction;
  const prompt = (byId("pqpc-branch-prompt")?.value || byId("pqpc-prompt")?.value || "").trim();
  if (!draft || !prompt) return;
  if (draft.mode === "new") {
    byId("pqpc-prompt").value = prompt;
    await createProblemContinuation();
    return;
  }
  if (draft.mode === "newRoot") {
    const created = await createProblemMutation({
      creationMode: "newRoot", baseRevisionId: null, prompt,
    });
    if (created) closeProblemBranchEditor();
    return;
  }
  const created = await createProblemMutation({
    creationMode: draft.mode,
    baseRevisionId: draft.baseRevisionId,
    editRevisionId: draft.editRevisionId,
    prompt,
  });
  if (created) closeProblemBranchEditor();
}

async function activateProblemChainRevision(chainId, revisionId) {
  if (state.busy || state.checkoutRunning || !state.problemChainHydrated || !state.problemChainDocument) return false;
  if (chainId === state.problemChainDocument.chainId) return true;
  state.checkoutRunning = true;
  clearError();
  setBusy(true, "Đang chuyển vấn đề đang làm việc…");
  try {
    const candidate = await api("/api/pq/v2/problem-chains/chains/activate", {
      document: state.problemChainDocument,
      baseHistoryHash: state.problemChainHistoryHash,
      chainId,
      revisionId,
    });
    await persistProblemChainCandidate(candidate);
    byId("pqpc-progress").textContent = "Đã chuyển vấn đề đang làm việc. Preview và approval cũ không được dùng lại.";
    return true;
  } catch (error) {
    showError(error.code, error.message);
    byId("pqpc-progress").textContent = "Không chuyển vấn đề đang làm việc; lịch sử hiện tại được giữ nguyên.";
    return false;
  } finally {
    state.checkoutRunning = false;
    setBusy(false, "");
    updateProblemChainButtons();
  }
}

async function checkoutProblemRevision(revisionId, chainId = state.problemChainDocument?.chainId) {
  if (chainId && chainId !== state.problemChainDocument?.chainId) {
    await activateProblemChainRevision(chainId, revisionId);
    return;
  }
  if (state.busy || state.checkoutRunning || !state.problemChainHydrated || !problemRevisionById(revisionId)) return;
  if (state.problemChainVersionPending) {
    showError("PQPC_RESULT_CACHE_STALE", "Chưa ghi nhận được phiên bản nguồn mới. Hãy đánh dấu lại thay đổi trước khi khôi phục cache.");
    return;
  }
  if (state.problemChainDocument?.headRevisionId === revisionId) {
    if (state.problemChainViewRevisionId !== revisionId) {
      selectProblemChainRevision(revisionId);
    }
    return;
  }
  state.checkoutRunning = true;
  clearError();
  setBusy(true, "Đang chuyển HEAD…");
  let committed = false;
  let writeAttempted = false;
  let shouldPreview = false;
  try {
    const candidate = await api("/api/pq/v2/problem-chains/checkout", {
      document: state.problemChainDocument,
      baseHistoryHash: state.problemChainHistoryHash,
      revisionId,
    });
    await persistProblemChainCandidate(candidate);
    committed = true;
    state.workbook = await readWorkbook();
    renderWorkbook();
    const prepared = await api("/api/pq/v2/problem-chains/cached-results/prepare", {
      revisionId, baseHistoryHash: state.problemChainHistoryHash,
      sourceDataChanged: false, workbook: state.workbook,
      workbookBase64: await exportWorkbookBase64(),
      destinationMarker: state.pqTypedMarker,
    });
    const expectedWorkbook = {name: state.workbook.name, url: state.workbook.url};
    writeAttempted = true;
    await writeTypedPrepared(prepared, expectedWorkbook, selectedPQSource());
    byId("pq2-result-badge").textContent = "ĐÃ GHI TỪ CACHE";
    byId("pqpc-progress").textContent = `Đã khôi phục ${revisionId.slice(0, 16)} vào ${state.pqResultSheetName} từ kết quả đầy đủ đã lưu. Add-in không tự Save.`;
  } catch (error) {
    showError(error.code, error.message);
    shouldPreview = committed && !writeAttempted
      && ["PQPC_RESULT_CACHE_MISS", "PQPC_RESULT_CACHE_STALE"].includes(error.code);
    byId("pqpc-progress").textContent = writeAttempted
      ? "Ghi từ cache có thể đã bắt đầu nhưng read-back chưa hoàn tất; không tự retry hoặc tuyên bố rollback."
      : committed
      ? "HEAD đã đổi nhưng cache không còn hợp lệ. Sẽ chạy Preview mới; hãy xem rồi duyệt ghi."
      : "Không đổi HEAD; revision và approval hiện tại không được tự sử dụng lại.";
  } finally {
    state.checkoutRunning = false;
    setBusy(false, "");
  }
  if (shouldPreview) await previewTypedPlan();
}

async function markProblemSourceChanged() {
  if (!byId("pqpc-source-changed").checked || state.busy) return;
  if (!state.problemChainHydrated || !state.problemChainDocument?.headRevisionId) {
    byId("pqpc-source-changed").checked = false;
    return;
  }
  state.problemChainVersionPending = true;
  clearError();
  setBusy(true, "Đang đánh dấu phiên bản dữ liệu mới…");
  try {
    state.workbook = await readWorkbook();
    renderWorkbook();
    const response = await api("/api/pq/v2/problem-chains/data-version/increment", {
      revisionId: state.problemChainDocument.headRevisionId,
      baseHistoryHash: state.problemChainHistoryHash,
      workbook: state.workbook,
    });
    if (!Number.isInteger(response.dataVersion) || response.dataVersion <= state.problemChainDataVersion) {
      throw problemChainError("PQPC_RESULT_CACHE_STALE", "Coordinator không xác nhận phiên bản dữ liệu mới.");
    }
    state.problemChainDataVersion = response.dataVersion;
    state.problemChainVersionPending = false;
    byId("pqpc-source-changed").checked = false;
    renderProblemDataVersion();
    if (state.problemChainViewRevisionId) showCachedProblemChainPreview(state.problemChainViewRevisionId);
    byId("pqpc-progress").textContent = `Nguồn v${response.dataVersion}: năm cache cũ vẫn giữ để so sánh. Revision nào được chọn mới chạy lại Preview.`;
  } catch (error) {
    showError(error.code, error.message);
    byId("pqpc-progress").textContent = "Chưa đánh dấu được nguồn mới; khôi phục từ cache bị khóa cho đến khi thử lại.";
  } finally {
    setBusy(false, "");
  }
}

const PQ2_OPERATIONS = [
  "source.workbookTable", "source.usedRange", "table.filterRows", "table.selectColumns",
  "table.removeColumns", "table.renameColumns", "table.changeTypes", "table.addColumn",
  "table.sortRows", "table.distinctRows", "table.groupRows", "table.aggregateRows",
  "table.appendTables", "table.mergeTables", "table.expandTableColumn",
];

function invalidateTypedPlan(message = "Yêu cầu đã đổi. Hãy tạo Typed Plan mới.") {
  state.pqTypedPlan = null;
  state.pqTypedPreview = null;
  state.pqTypedApproval = null;
  state.pqTypedEditorStepId = null;
  state.pqStepDiagnosticStaging = null;
  if (!byId("pq2-plan-section")) return;
  setHidden("pq2-plan-section", true);
  setHidden("pq2-preview-section", true);
  setHidden("pq2-repair-section", true);
  setHidden("pq2-editor", true);
  setHidden("pq2-diagnostic-section", true);
  byId("pq2-progress").textContent = message;
  updatePQButtons();
}

function switchPQMode(mode) {
  state.pqMode = mode;
  setHidden("pq2-mode", mode !== "typed");
  setHidden("pq-advanced-mode", mode !== "advanced");
  byId("pq2-mode-button").classList.toggle("active", mode === "typed");
  byId("pq2-mode-button").setAttribute("aria-selected", String(mode === "typed"));
  byId("pq-advanced-mode-button").classList.toggle("active", mode === "advanced");
  byId("pq-advanced-mode-button").setAttribute("aria-selected", String(mode === "advanced"));
  clearError();
  updatePQButtons();
}

function appendOption(select, value, label, selected = false) {
  const option = document.createElement("option");
  option.value = value;
  option.textContent = label;
  option.selected = selected;
  select.appendChild(option);
}

function typedInputSteps() {
  const select = byId("pq2-inputs");
  return Array.from(select.options || []).filter((option) => option.selected).map((option) => option.value);
}

function typedStepById(stepId) {
  return (state.pqTypedPlan?.steps || []).find((step) => step.stepId === stepId);
}

function typedColumnsForStep(stepId) {
  return typedStepById(stepId)?.outputContract?.columns || [];
}

function typedSelectedInputColumns(inputIndex = 0) {
  return typedColumnsForStep(typedInputSteps()[inputIndex]);
}

function typedControl(container, id, label, kind = "text", options = [], value = "") {
  const wrapper = document.createElement("div");
  const caption = document.createElement("label");
  caption.htmlFor = id;
  caption.textContent = label;
  let control;
  if (kind === "select" || kind === "multi") {
    control = document.createElement("select");
    if (kind === "multi") {
      control.multiple = true;
      control.size = Math.min(6, Math.max(3, options.length));
    }
    for (const item of options) appendOption(control, item.value, item.label, Array.isArray(value) ? value.includes(item.value) : item.value === value);
  } else {
    control = document.createElement("input");
    control.type = kind;
    control.value = value ?? "";
  }
  control.id = id;
  wrapper.append(caption, control);
  container.appendChild(wrapper);
  return control;
}

function typedColumnOptions(columns) {
  return columns.map((column) => ({value: column.columnId, label: `${column.name} · ${column.inferredType}`}));
}

function renderTypedParameterFields(step = null) {
  const container = byId("pq2-parameters");
  container.replaceChildren();
  const operation = byId("pq2-operation").value;
  const params = step?.operation?.parameters || {};
  const inputs = typedInputSteps();
  const columns = typedColumnsForStep(inputs[0]);
  const columnOptions = typedColumnOptions(columns);
  if (operation.startsWith("source.")) {
    const sourceKind = operation === "source.workbookTable" ? "excelTable" : "usedRange";
    const sources = (state.pqTypedPlan?.sources || []).filter((source) => source.kind === sourceKind)
      .map((source) => ({value: source.sourceId, label: `${source.sheetName}${source.objectName ? ` · ${source.objectName}` : " · usedRange"}`}));
    typedControl(container, "pq2-param-source", "Workbook source", "select", sources, params.sourceId || "");
  } else if (operation === "table.filterRows") {
    const predicate = params.predicate || {};
    typedControl(container, "pq2-param-column", "Column", "select", columnOptions, predicate.left?.columnId || "");
    typedControl(container, "pq2-param-operator", "Operator", "select", ["eq", "ne", "gt", "gte", "lt", "lte", "contains", "startsWith", "endsWith", "isNull", "isNotNull"].map((value) => ({value, label: value})), predicate.operator || "eq");
    typedControl(container, "pq2-param-value", "Comparison value", "text", [], predicate.right?.value ?? "");
    typedControl(container, "pq2-param-error", "On evaluation error", "select", ["block", "keepRow", "dropRow"].map((value) => ({value, label: value})), params.onEvaluationError || "block");
  } else if (["table.selectColumns", "table.removeColumns"].includes(operation)) {
    typedControl(container, "pq2-param-columns", "Columns", "multi", columnOptions, params.columnIds || []);
  } else if (operation === "table.renameColumns") {
    const rename = params.renames?.[0] || {};
    typedControl(container, "pq2-param-column", "Column", "select", columnOptions, rename.columnId || "");
    typedControl(container, "pq2-param-name", "New name", "text", [], rename.newName || "");
  } else if (operation === "table.changeTypes") {
    const conversion = params.conversions?.[0] || {};
    typedControl(container, "pq2-param-column", "Column", "select", columnOptions, conversion.columnId || "");
    typedControl(container, "pq2-param-type", "Target type", "select", ["any", "text", "number", "integer", "logical", "date", "datetime", "datetimezone", "time", "duration"].map((value) => ({value, label: value})), conversion.targetType || "text");
    typedControl(container, "pq2-param-culture", "Culture (optional)", "text", [], conversion.culture || "");
  } else if (operation === "table.addColumn") {
    const expression = params.expression || {};
    typedControl(container, "pq2-param-name", "New column name", "text", [], params.newColumnName || "");
    typedControl(container, "pq2-param-type", "Data type", "select", ["any", "text", "number", "integer", "logical", "date", "datetime"].map((value) => ({value, label: value})), params.dataType || "number");
    typedControl(container, "pq2-param-left", "Left column", "select", columnOptions, expression.left?.columnId || "");
    typedControl(container, "pq2-param-arithmetic", "Calculation", "select", ["add", "subtract", "multiply", "safeDivide"].map((value) => ({value, label: value})), expression.kind === "safeDivide" ? "safeDivide" : expression.operator || "subtract");
    typedControl(container, "pq2-param-right", "Right column", "select", columnOptions, expression.right?.columnId || expression.denominator?.columnId || "");
    typedControl(container, "pq2-param-zero", "safeDivide on zero", "select", ["error", "null", "zero"].map((value) => ({value, label: value})), expression.onZero || "null");
    typedControl(container, "pq2-param-error", "On evaluation error", "select", ["block", "null"].map((value) => ({value, label: value})), params.onEvaluationError || "block");
  } else if (operation === "table.sortRows") {
    const key = params.keys?.[0] || {};
    typedControl(container, "pq2-param-column", "Sort column", "select", columnOptions, key.columnId || "");
    typedControl(container, "pq2-param-direction", "Direction", "select", ["ascending", "descending"].map((value) => ({value, label: value})), key.direction || "ascending");
  } else if (operation === "table.distinctRows") {
    typedControl(container, "pq2-param-scope", "Distinct scope", "select", [{value: "all", label: "All columns"}, {value: "columns", label: "Selected columns"}], params.scope || "all");
    typedControl(container, "pq2-param-columns", "Key columns", "multi", columnOptions, params.columnIds || []);
  } else if (["table.groupRows", "table.aggregateRows"].includes(operation)) {
    if (operation === "table.groupRows") typedControl(container, "pq2-param-columns", "Group keys", "multi", columnOptions, params.keyColumnIds || []);
    const agg = params.aggregations?.[0] || {};
    typedControl(container, "pq2-param-agg", "Aggregation", "select", ["rowCount", "countNonNull", "countDistinct", "sum", "average", "min", "max"].map((value) => ({value, label: value})), agg.function || "rowCount");
    typedControl(container, "pq2-param-column", "Aggregation column", "select", [{value: "", label: "Not required for rowCount"}, ...columnOptions], agg.columnId || "");
    typedControl(container, "pq2-param-name", "Output name", "text", [], agg.outputName || "RowCount");
  } else if (operation === "table.appendTables") {
    typedControl(container, "pq2-param-mode", "Schema mode", "select", [{value: "strict", label: "Strict"}, {value: "union", label: "Union with nulls"}], params.schemaMode || "strict");
  } else if (operation === "table.mergeTables") {
    const pair = params.keyPairs?.[0] || {};
    typedControl(container, "pq2-param-left", "Left key", "select", typedColumnOptions(typedColumnsForStep(inputs[0])), pair.leftColumnId || "");
    typedControl(container, "pq2-param-right", "Right key", "select", typedColumnOptions(typedColumnsForStep(inputs[1])), pair.rightColumnId || "");
    typedControl(container, "pq2-param-join", "Join kind", "select", ["inner", "leftOuter", "rightOuter", "fullOuter", "leftAnti", "rightAnti"].map((value) => ({value, label: value})), params.joinKind || "leftOuter");
    typedControl(container, "pq2-param-name", "Nested column name", "text", [], params.nestedColumnName || "JoinedRows");
  } else if (operation === "table.expandTableColumn") {
    const nestedColumns = columns.filter((column) => column.inferredType === "table");
    const nested = nestedColumns.find((column) => column.columnId === params.nestedColumnId) || nestedColumns[0];
    typedControl(container, "pq2-param-nested", "Nested table column", "select", typedColumnOptions(nestedColumns), params.nestedColumnId || "");
    typedControl(container, "pq2-param-column", "Nested source column", "select", typedColumnOptions(nested?.nestedSchema || []), params.columns?.[0]?.sourceColumnId || "");
    typedControl(container, "pq2-param-name", "Expanded output name", "text", [], params.columns?.[0]?.newName || "");
  }
}

function selectedValues(id) {
  return Array.from(byId(id).options || []).filter((option) => option.selected).map((option) => option.value);
}

function collectTypedParameters(operation) {
  const value = (id) => byId(id)?.value || "";
  if (operation.startsWith("source.")) return {sourceId: value("pq2-param-source")};
  if (operation === "table.filterRows") {
    const operator = value("pq2-param-operator");
    const left = {kind: "columnRef", columnId: value("pq2-param-column")};
    const predicate = {kind: "compare", operator, left};
    if (!["isNull", "isNotNull"].includes(operator)) {
      const raw = value("pq2-param-value");
      const numeric = raw !== "" && Number.isFinite(Number(raw));
      predicate.right = {kind: "literal", valueType: numeric ? "number" : "text", value: numeric ? Number(raw) : raw};
    }
    return {predicate, onEvaluationError: value("pq2-param-error")};
  }
  if (["table.selectColumns", "table.removeColumns"].includes(operation)) return {columnIds: selectedValues("pq2-param-columns")};
  if (operation === "table.renameColumns") return {renames: [{columnId: value("pq2-param-column"), newName: value("pq2-param-name")}]};
  if (operation === "table.changeTypes") return {conversions: [{columnId: value("pq2-param-column"), targetType: value("pq2-param-type"), culture: value("pq2-param-culture") || null}]};
  if (operation === "table.addColumn") {
    const arithmetic = value("pq2-param-arithmetic");
    const left = {kind: "columnRef", columnId: value("pq2-param-left")};
    const right = {kind: "columnRef", columnId: value("pq2-param-right")};
    const expression = arithmetic === "safeDivide"
      ? {kind: "safeDivide", numerator: left, denominator: right, onZero: value("pq2-param-zero")}
      : {kind: "arithmetic", operator: arithmetic, left, right};
    return {newColumnName: value("pq2-param-name"), dataType: value("pq2-param-type"), expression, onEvaluationError: value("pq2-param-error")};
  }
  if (operation === "table.sortRows") return {keys: [{columnId: value("pq2-param-column"), direction: value("pq2-param-direction")}]};
  if (operation === "table.distinctRows") return {scope: value("pq2-param-scope"), columnIds: selectedValues("pq2-param-columns")};
  if (["table.groupRows", "table.aggregateRows"].includes(operation)) {
    const aggregation = {function: value("pq2-param-agg"), outputName: value("pq2-param-name")};
    if (aggregation.function !== "rowCount") aggregation.columnId = value("pq2-param-column");
    return {keyColumnIds: operation === "table.groupRows" ? selectedValues("pq2-param-columns") : [], aggregations: [aggregation]};
  }
  if (operation === "table.appendTables") return {schemaMode: value("pq2-param-mode")};
  if (operation === "table.mergeTables") return {keyPairs: [{leftColumnId: value("pq2-param-left"), rightColumnId: value("pq2-param-right")}], joinKind: value("pq2-param-join"), nestedColumnName: value("pq2-param-name")};
  if (operation === "table.expandTableColumn") return {nestedColumnId: value("pq2-param-nested"), columns: [{columnId: value("pq2-param-column"), newName: value("pq2-param-name")}]};
  return {};
}

function openTypedEditor(stepId = null) {
  state.pqTypedEditorStepId = stepId;
  const step = typedStepById(stepId);
  byId("pq2-editor-title").textContent = step ? `Sửa ${step.variableName}` : "Thêm step có kiểu";
  byId("pq2-variable").value = step?.variableName || "NewStep";
  byId("pq2-description").value = step?.actionDescription || "Mô tả thao tác.";
  const operation = byId("pq2-operation");
  operation.replaceChildren();
  for (const value of PQ2_OPERATIONS) appendOption(operation, value, value, value === step?.operation?.type);
  const inputs = byId("pq2-inputs");
  inputs.replaceChildren();
  for (const candidate of state.pqTypedPlan.steps) {
    if (candidate.stepId === stepId) continue;
    appendOption(inputs, candidate.stepId, `${candidate.position}. ${candidate.variableName}`, (step?.inputs || []).some((item) => item.ref === candidate.stepId));
  }
  setHidden("pq2-editor", false);
  renderTypedParameterFields(step);
}

async function saveTypedEditor() {
  const operationType = byId("pq2-operation").value;
  const stepDraft = {
    variableName: byId("pq2-variable").value,
    actionDescription: byId("pq2-description").value,
    operationType, inputs: typedInputSteps().map((ref) => ({kind: "step", ref})),
    parameters: collectTypedParameters(operationType),
  };
  const editing = state.pqTypedEditorStepId;
  const changes = editing
    ? [{type: "updateStep", stepId: editing, stepDraft}]
    : [{type: "insertStep", afterStepId: state.pqTypedPlan.steps.at(-1)?.stepId || null, stepDraft}];
  if (await createTypedRevision(changes, editing ? "Edited typed step" : "Added typed step")) {
    setHidden("pq2-editor", true);
  }
}

async function createTypedRevision(changes, changeReason) {
  if (state.problemChainSupported) {
    if (state.busy || !state.problemChainHydrated || !state.problemChainDocument
      || !state.pqTypedPlan || !problemChainHeadMatchesView()
      || state.pqTypedPlan.revision.revisionId !== state.problemChainDocument.headRevisionId) {
      showError("PQPC_HEAD_MISMATCH", "Chỉ revision HEAD đã lưu trong workbook mới được chỉnh step.");
      return false;
    }
    clearError();
    setBusy(true, "Đang tạo revision chỉnh step…");
    try {
      state.workbook = await readWorkbook();
      renderWorkbook();
      const candidate = await api("/api/pq/v2/problem-chains/revisions", {
        document: state.problemChainDocument,
        baseHistoryHash: state.problemChainHistoryHash,
        baseRevisionId: state.problemChainDocument.headRevisionId,
        changes, changeReason,
        workbook: state.workbook,
      });
      await persistProblemChainCandidate(candidate);
      return true;
    } catch (error) {
      showError(error.code, error.message);
      byId("pqpc-progress").textContent = !state.problemChainHydrated
        ? "Custom XML có thể đã đổi; hãy đọc lại lịch sử. Không tự chạy lại thao tác."
        : "Không tạo revision chỉnh step; HEAD cũ được giữ nguyên.";
      return false;
    } finally {
      setBusy(false, "");
    }
  }
  clearError();
  setBusy(true, "Đang validation revision mới…");
  try {
    const revision = await api("/api/pq/v2/revisions", {
      baseRevisionId: state.pqTypedPlan.revision.revisionId, changes, changeReason,
    });
    state.pqTypedPlan = revision;
    state.pqTypedPreview = null;
    state.pqTypedApproval = null;
    state.pqStepDiagnosticStaging = null;
    setHidden("pq2-diagnostic-section", true);
    renderTypedPlan(revision);
    setHidden("pq2-preview-section", true);
    return true;
  } catch (error) {
    showError(error.code, error.message);
    return false;
  } finally {
    setBusy(false, "");
  }
}

function typedActionButton(label, handler, disabled = false) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "button button-ghost";
  button.textContent = label;
  button.disabled = disabled;
  button.addEventListener("click", handler);
  return button;
}

function typedDiagnosticSourceRows() {
  const source = selectedPQSource();
  if (!source || !state.workbook) return null;
  if (source.kind === "table") {
    const table = (state.workbook.tables || []).find((item) => item.name === source.name && item.sheet === source.sheet);
    return Number.isInteger(table?.totalRows) ? table.totalRows : null;
  }
  const sheet = (state.workbook.sheets || []).find((item) => item.name === source.sheet);
  return Number.isInteger(sheet?.totalRows) ? sheet.totalRows : null;
}

function typedDiagnosticEstimate(step) {
  const sourceRows = typedDiagnosticSourceRows();
  const samples = state.pqStepDiagnosticTimings.get(step.operation.type) || [];
  if (!samples.length || !Number.isInteger(sourceRows)) return "Thời gian ước tính: chưa đủ dữ liệu";
  const perRow = samples.reduce((sum, item) => sum + (item.elapsedMs / Math.max(1, item.inputRows)), 0) / samples.length;
  const milliseconds = Math.max(1, Math.round(perRow * Math.max(1, sourceRows)));
  const time = milliseconds < 1000 ? `${milliseconds} ms` : `${(milliseconds / 1000).toFixed(1)} giây`;
  return `Khoảng ${sourceRows.toLocaleString("vi-VN")} dòng · thời gian ước tính ${time}`;
}

function rememberTypedDiagnosticTiming(step, result) {
  if (!step || !Number.isFinite(result?.elapsedMs) || !Number.isInteger(result?.inputRows) || result.inputRows < 0) return;
  const values = state.pqStepDiagnosticTimings.get(step.operation.type) || [];
  values.push({elapsedMs: result.elapsedMs, inputRows: result.inputRows});
  state.pqStepDiagnosticTimings.set(step.operation.type, values.slice(-5));
}

function typedDiagnosticMetric(value, metricStatus) {
  return metricStatus === "unavailable" || value === null || typeof value === "undefined"
    ? "không đo được"
    : Number(value).toLocaleString("vi-VN");
}

function renderTypedDiagnostic(result, mode = "staging") {
  const step = typedStepById(result.selectedStepId);
  setHidden("pq2-diagnostic-section", false);
  byId("pq2-diagnostic-title").textContent = `Chẩn đoán · ${step?.variableName || result.selectedStepId}`;
  const badge = byId("pq2-diagnostic-badge");
  badge.textContent = mode === "cache" ? "CACHE ĐÃ XÁC NHẬN" : "STAGING · CHƯA LƯU CACHE";
  badge.className = `badge ${mode === "cache" ? "badge-ready" : "badge-simulated"}`;
  const metricStatus = result.metricStatus || "available";
  byId("pq2-diagnostic-counts").textContent = [
    `${Number(result.inputRows || 0).toLocaleString("vi-VN")} → ${Number(result.outputRows || 0).toLocaleString("vi-VN")} dòng`,
    `${Number(result.outputColumns || 0).toLocaleString("vi-VN")} cột`,
    `${typedDiagnosticMetric(result.blankCells, metricStatus)} ô rỗng`,
    `${typedDiagnosticMetric(result.errorCells, metricStatus)} ô lỗi`,
    `${Number(result.elapsedMs || 0).toLocaleString("vi-VN")} ms`,
    `Excel ${result.excelVersion || "—"}`,
  ].join(" · ");
  const errorSamples = result.errorSamples || [];
  const errorList = byId("pq2-diagnostic-errors");
  errorList.replaceChildren();
  for (const item of errorSamples.slice(0, 5)) {
    const row = document.createElement("li");
    row.textContent = `Dòng ${item.ordinal ?? item.rowOrdinal ?? "—"} · cột ${item.column || item.columnName || item.columnOrdinal || "—"}: ${item.error || item.message || "Lỗi Power Query"}`;
    errorList.appendChild(row);
  }
  setHidden("pq2-diagnostic-error-block", errorSamples.length === 0);
  renderTable("pq2-diagnostic-table", result.columns || result.afterColumns || [], result.rows || result.afterRows || []);
  setHidden("pq2-diagnostic-confirm", mode !== "staging");
  setHidden("pq2-diagnostic-cancel", mode !== "staging");
  byId("pq2-diagnostic-confirm").disabled = state.busy || mode !== "staging";
  byId("pq2-diagnostic-cancel").disabled = state.busy || mode !== "staging";
}

function clearTypedDiagnosticStaging({showConfirmed = true} = {}) {
  const selectedStepId = state.pqStepDiagnosticStaging?.selectedStepId;
  state.pqStepDiagnosticStaging = null;
  const cached = showConfirmed && selectedStepId ? state.pqStepDiagnosticCaches.get(selectedStepId) : null;
  if (cached) renderTypedDiagnostic(cached, "cache");
  else setHidden("pq2-diagnostic-section", true);
  updatePQButtons();
}

async function runTypedStepDiagnostic(stepId) {
  const plan = state.pqTypedPlan;
  if (state.busy || !state.typedStepDiagnosticsCapability
    || !plan || plan.planStatus !== "reviewReady" || !state.problemChainSupported
    || !state.problemChainHydrated || !problemChainHeadMatchesView()
    || plan.revision.revisionId !== state.problemChainDocument?.headRevisionId) return;
  clearError();
  setBusy(true, "Đang chuẩn bị chẩn đoán đến step đã chọn…");
  setHidden("pq2-diagnostic-section", false);
  byId("pq2-diagnostic-title").textContent = `Chẩn đoán · ${typedStepById(stepId)?.variableName || stepId}`;
  byId("pq2-diagnostic-badge").textContent = "ĐANG CHẠY";
  byId("pq2-diagnostic-counts").textContent = "Đang xác định quy mô và dependency của step…";
  setHidden("pq2-diagnostic-error-block", true);
  setHidden("pq2-diagnostic-confirm", true);
  setHidden("pq2-diagnostic-cancel", true);
  renderTable("pq2-diagnostic-table", [], []);
  byId("pq2-diagnostic-progress").textContent = "Đang chuẩn bị dependency và kiểm tra nguồn…";
  try {
    const expectedWorkbookKey = workbookIdentity(state.workbook);
    const freshWorkbook = await readWorkbook();
    acceptWorkbookRead(expectedWorkbookKey, freshWorkbook);
    renderWorkbook();
    byId("pq2-diagnostic-progress").textContent = "Excel đang chạy toàn bộ dữ liệu trên workbook tạm…";
    const result = await api("/api/pq/v2/step-diagnostics/runs", {
      revisionId: plan.revision.revisionId,
      selectedStepId: stepId,
      baseHistoryHash: state.problemChainHistoryHash,
      workbook: state.workbook,
      workbookBase64: await exportWorkbookBase64(),
    });
    if (result.status !== "ready") throw Object.assign(new Error("Coordinator không trả diagnostic staging sẵn sàng."), {code: "TSD_EXCEL_FAILED"});
    state.pqStepDiagnosticStaging = result;
    rememberTypedDiagnosticTiming(typedStepById(stepId), result);
    renderTypedDiagnostic(result, "staging");
    renderTypedPlan(plan);
    byId("pq2-diagnostic-progress").textContent = "Đã chạy xong. Hãy xem số liệu và mẫu lỗi; Xác nhận chỉ lưu cache step, không ghi sheet.";
  } catch (error) {
    showError(error.code, error.message);
    byId("pq2-diagnostic-progress").textContent = "Chẩn đoán thất bại; cache đã xác nhận và workbook đang mở không thay đổi.";
  } finally {
    setBusy(false, "");
    if (state.pqTypedPlan) renderTypedPlan(state.pqTypedPlan);
  }
}

async function confirmTypedStepDiagnostic() {
  const staging = state.pqStepDiagnosticStaging;
  if (state.busy || !staging || !state.pqTypedPlan) return;
  clearError();
  setBusy(true, "Đang kiểm tra lại nguồn trước khi lưu cache step…");
  try {
    state.workbook = await readWorkbook();
    renderWorkbook();
    const confirmed = await api("/api/pq/v2/step-diagnostics/confirms", {
      stagingId: staging.stagingId,
      revisionId: staging.revisionId,
      selectedStepId: staging.selectedStepId,
      baseHistoryHash: state.problemChainHistoryHash,
      workbook: state.workbook,
      workbookBase64: await exportWorkbookBase64(),
    });
    if (confirmed.status !== "confirmed") throw Object.assign(new Error("Coordinator không xác nhận cache step."), {code: "TSD_STAGING_STALE"});
    const cache = {...staging, ...confirmed};
    state.pqStepDiagnosticCaches.delete(staging.selectedStepId);
    state.pqStepDiagnosticCaches.set(staging.selectedStepId, cache);
    while (state.pqStepDiagnosticCaches.size > 5) state.pqStepDiagnosticCaches.delete(state.pqStepDiagnosticCaches.keys().next().value);
    state.pqStepDiagnosticStaging = null;
    renderTypedDiagnostic(cache, "cache");
    renderTypedPlan(state.pqTypedPlan);
    byId("pq2-diagnostic-progress").textContent = "Đã lưu cache chẩn đoán của step. PQ_Typed_Result và sheet nguồn không bị ghi.";
  } catch (error) {
    showError(error.code, error.message);
    byId("pq2-diagnostic-progress").textContent = "Không thể xác nhận staging; cache cũ giữ nguyên.";
  } finally {
    setBusy(false, "");
    if (state.pqTypedPlan) renderTypedPlan(state.pqTypedPlan);
  }
}

async function cancelTypedStepDiagnostic() {
  const staging = state.pqStepDiagnosticStaging;
  if (state.busy || !staging) return;
  clearError();
  setBusy(true, "Đang hủy diagnostic staging…");
  try {
    await api("/api/pq/v2/step-diagnostics/cancels", {stagingId: staging.stagingId});
    clearTypedDiagnosticStaging();
    byId("pq2-diagnostic-progress").textContent = "Đã hủy staging. Cache cũ và workbook đang mở không thay đổi.";
  } catch (error) {
    showError(error.code, error.message);
  } finally {
    setBusy(false, "");
  }
}

const PQ2_OPERATION_LABELS = {
  "source.workbookTable": "Nguồn bảng",
  "source.usedRange": "Nguồn vùng",
  "table.filterRows": "Lọc dòng",
  "table.selectColumns": "Chọn cột",
  "table.removeColumns": "Bỏ cột",
  "table.renameColumns": "Đổi tên cột",
  "table.changeTypes": "Đổi kiểu",
  "table.addColumn": "Thêm cột",
  "table.sortRows": "Sắp xếp",
  "table.distinctRows": "Bỏ trùng",
  "table.groupRows": "Gộp nhóm",
  "table.aggregateRows": "Tổng hợp",
  "table.appendTables": "Nối bảng",
  "table.mergeTables": "Kết hợp",
  "table.expandTableColumn": "Mở rộng",
};

function friendlyOperationLabel(opType) {
  return PQ2_OPERATION_LABELS[opType] || opType || "Thao tác";
}

function renderTypedPlan(plan) {
  setHidden("pq2-plan-section", false);
  if (plan.planStatus === "needsClarification") {
    byId("pq2-progress").textContent = `Revision còn ${(plan.questions || []).length} câu hỏi cần làm rõ. Xem phần ghi chú bên dưới, rồi tạo vấn đề mới với quy tắc cụ thể trước khi Preview.`;
  }
  byId("pq2-summary").textContent = plan.summary || "";
  byId("pq2-revision").textContent = `Revision ${plan.revision.revisionId.slice(0, 16)} · ${plan.revision.changeReason}`;
  const status = byId("pq2-status");
  if (status) {
    status.textContent = plan.planStatus;
    status.className = `badge ${plan.planStatus === "reviewReady" ? "badge-ready" : "badge-failed"} sr-only`;
    status.hidden = true;
  }

  const stepCount = (plan.steps || []).length;
  const countEl = byId("pq2-step-count");
  if (countEl) countEl.textContent = `${stepCount} bước`;

  const ownerEl = byId("pq2-revision-owner");
  if (ownerEl) {
    const headId = state.problemChainDocument?.headRevisionId;
    const isHead = plan.revision.revisionId === headId;
    const revName = problemRevisionLabel(problemRevisionById(plan.revision.revisionId));
    ownerEl.textContent = `${revName} · ${isHead ? "HEAD" : "Bản cũ"}`;
  }

  const notes = [...new Set([...(plan.questions || []).map((item) => `Cần làm rõ: ${item}`), ...(plan.assumptions || []).map((item) => `Giả định: ${item}`), ...(plan.warnings || [])])];
  appendTextList(byId("pq2-notes"), notes);
  setHidden("pq2-notes", !notes.length);

  const hasAlerts = notes.length > 0;
  setHidden("pq2-info-alert", !hasAlerts);

  const blockers = (plan.hardBlockers || []).map((item) => `${item.code} · ${item.reason} · ${item.remedy}`);
  appendTextList(byId("pq2-blockers"), blockers);
  if (blockers.length && !state.problemChainSupported) {
    byId("pq2-blockers").appendChild(typedActionButton("Đề xuất sửa", requestTypedRepair));
  }
  setHidden("pq2-blockers", !blockers.length);

  const manualEditBlocked = state.problemChainSupported
    && (!state.problemChainHydrated || !problemChainHeadMatchesView());

  const infoBtn = byId("pq2-revision-info");
  if (infoBtn) {
    infoBtn.setAttribute("aria-label", "Thông tin revision");
    infoBtn.title = "Xem tóm tắt và ghi chú revision";
    if (infoBtn.dataset) infoBtn.dataset.tooltip = infoBtn.title;
  }

  const addStepBtn = byId("pq2-add-step");
  if (addStepBtn) {
    addStepBtn.disabled = manualEditBlocked;
    addStepBtn.setAttribute("aria-label", "Thêm bước");
    addStepBtn.title = "Thêm bước";
    if (addStepBtn.dataset) addStepBtn.dataset.tooltip = addStepBtn.title;
  }

  const list = byId("pq2-step-list");
  list.replaceChildren();

  for (const step of plan.steps || []) {
    const card = document.createElement("li");
    card.className = "step typed-step-card";
    card.dataset.step = step.variableName;
    card.dataset.stepId = step.stepId;

    const isOpen = state.expandedStepId === step.stepId;
    if (isOpen) card.classList.add("open");

    const isFinal = plan.finalOutputStepId === step.stepId;
    const columns = step.outputContract?.columns || [];
    const columnCount = columns.length;

    const mainBtn = document.createElement("button");
    mainBtn.type = "button";
    mainBtn.className = "step-main";
    mainBtn.setAttribute("aria-expanded", String(isOpen));

    const indexSpan = document.createElement("span");
    indexSpan.className = "step-index";
    indexSpan.textContent = String(step.position);

    const textSpan = document.createElement("span");
    const nameSpan = document.createElement("span");
    nameSpan.className = "step-name";
    nameSpan.textContent = step.variableName + " ";

    const opBadge = document.createElement("span");
    opBadge.className = "operation";
    opBadge.textContent = friendlyOperationLabel(step.operation.type);
    nameSpan.appendChild(opBadge);

    if (isFinal) {
      const finalBadge = document.createElement("span");
      finalBadge.className = "final";
      finalBadge.textContent = "FINAL";
      nameSpan.appendChild(finalBadge);
    }

    const summarySpan = document.createElement("span");
    summarySpan.className = "step-summary";
    summarySpan.textContent = `${step.actionDescription} · ${columnCount} cột`;

    textSpan.append(nameSpan, summarySpan);

    const chevron = createIcon("chevron-down", "step-chevron");
    mainBtn.append(indexSpan, textSpan, chevron);

    mainBtn.addEventListener("click", () => {
      const willOpen = !card.classList.contains("open");
      for (const other of list.children) {
        if (other !== card && other.classList?.contains("step")) {
          other.classList.remove("open");
          const otherMain = other.querySelector?.(".step-main");
          if (otherMain) otherMain.setAttribute("aria-expanded", "false");
          const otherMenu = other.querySelector?.(".menu-pop");
          if (otherMenu) otherMenu.hidden = true;
        }
      }
      card.classList.toggle("open", willOpen);
      mainBtn.setAttribute("aria-expanded", String(willOpen));
      state.expandedStepId = willOpen ? step.stepId : null;
      const feedback = byId("pq2-step-feedback");
      if (feedback) {
        feedback.textContent = willOpen ? `Đang xem ${step.variableName}.` : "Đã thu gọn chi tiết bước.";
      }
    });

    const detail = document.createElement("div");
    detail.className = "step-detail";

    const facts = document.createElement("div");
    facts.className = "facts";

    const inputNames = step.inputs.map((item) => typedStepById(item.ref)?.variableName || item.ref).join(", ");
    const factsLabel = document.createElement("span");
    factsLabel.textContent = `${inputNames ? `Sau ${inputNames}` : "workbook"} → ${columnCount} cột`;

    const structureLink = document.createElement("button");
    structureLink.type = "button";
    structureLink.className = "link-button";
    structureLink.textContent = "Xem cấu trúc";

    facts.append(factsLabel, structureLink);

    const structureDiv = document.createElement("div");
    structureDiv.className = "step-structure";
    structureDiv.hidden = true;
    structureDiv.textContent = columns.length
      ? `Các cột (${columnCount}): ${columns.map((c) => c.name).join(", ")}`
      : "Không có cột đầu ra.";

    structureLink.addEventListener("click", (e) => {
      e.stopPropagation();
      structureDiv.hidden = !structureDiv.hidden;
      structureLink.textContent = structureDiv.hidden ? "Xem cấu trúc" : "Ẩn cấu trúc";
    });

    const diagnosticCache = state.pqStepDiagnosticCaches.get(step.stepId);
    const diagnosticCacheStale = Boolean(diagnosticCache) && (diagnosticCache.revisionId !== plan.revision.revisionId
      || diagnosticCache.runVersion !== state.problemChainDataVersion);
    let diagnosticBadge = null;
    if (diagnosticCache) {
      diagnosticBadge = document.createElement("span");
      diagnosticBadge.className = `typed-step-cache ${diagnosticCacheStale ? "is-stale" : "is-cached"}`;
      diagnosticBadge.textContent = diagnosticCacheStale ? "Cache step cũ" : "Cache step đã xác nhận";
    }

    const estimate = document.createElement("p");
    estimate.className = "typed-step-estimate";
    estimate.textContent = typedDiagnosticEstimate(step);

    const actions = document.createElement("div");
    actions.className = "step-actions";

    const diagnosticBlocked = manualEditBlocked || state.busy || !state.problemChainSupported
      || !state.typedStepDiagnosticsCapability
      || plan.planStatus !== "reviewReady" || (plan.hardBlockers || []).length > 0
      || step.outputContract?.kind !== "table" || Boolean(state.pqStepDiagnosticStaging);

    const editBtn = createIconButton({
      icon: "square-pen",
      label: `Sửa ${step.variableName}`,
      tooltip: "Sửa bước",
      disabled: manualEditBlocked,
      onClick: (e) => {
        e.stopPropagation();
        openTypedEditor(step.stepId);
      },
    });

    const menuWrap = document.createElement("div");
    menuWrap.className = "menu";

    const menuPop = document.createElement("div");
    menuPop.className = "menu-pop";
    menuPop.hidden = true;

    const moreBtn = createIconButton({
      icon: "ellipsis",
      label: "Thêm thao tác",
      tooltip: "Thêm thao tác",
      className: "more",
      onClick: (e) => {
        e.stopPropagation();
        if (list.querySelectorAll) {
          for (const otherMenu of list.querySelectorAll(".menu-pop")) {
            if (otherMenu !== menuPop) otherMenu.hidden = true;
          }
        }
        menuPop.hidden = !menuPop.hidden;
      },
    });

    const setFinalBtn = document.createElement("button");
    setFinalBtn.type = "button";
    setFinalBtn.textContent = "Đặt làm kết quả cuối";
    setFinalBtn.disabled = manualEditBlocked || isFinal;
    setFinalBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      menuPop.hidden = true;
      createTypedRevision([{type: "setFinalOutput", stepId: step.stepId}], `Set ${step.variableName} as final output`);
    });

    const moveUpBtn = document.createElement("button");
    moveUpBtn.type = "button";
    moveUpBtn.textContent = "Di chuyển lên";
    moveUpBtn.disabled = manualEditBlocked || step.position <= 1;
    moveUpBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      menuPop.hidden = true;
      createTypedRevision([{type: "moveStep", stepId: step.stepId, position: Math.max(1, step.position - 1)}], `Moved ${step.variableName}`);
    });

    const moveDownBtn = document.createElement("button");
    moveDownBtn.type = "button";
    moveDownBtn.textContent = "Di chuyển xuống";
    moveDownBtn.disabled = manualEditBlocked || step.position >= (plan.steps || []).length;
    moveDownBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      menuPop.hidden = true;
      createTypedRevision([{type: "moveStep", stepId: step.stepId, position: Math.min(plan.steps.length, step.position + 1)}], `Moved ${step.variableName}`);
    });

    const deleteStepBtn = document.createElement("button");
    deleteStepBtn.type = "button";
    deleteStepBtn.className = "danger";
    deleteStepBtn.textContent = "Xóa bước";
    deleteStepBtn.disabled = manualEditBlocked;
    deleteStepBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      menuPop.hidden = true;
      createTypedRevision([{type: "deleteStep", stepId: step.stepId}], `Deleted ${step.variableName}`);
    });

    menuPop.append(setFinalBtn, moveUpBtn, moveDownBtn, deleteStepBtn);
    menuWrap.append(moreBtn, menuPop);

    const runBtn = createIconButton({
      icon: "play",
      label: `Chạy đến ${step.variableName}`,
      tooltip: "Chạy đến bước này",
      className: "run-button",
      disabled: diagnosticBlocked,
      onClick: (e) => {
        e.stopPropagation();
        runTypedStepDiagnostic(step.stepId);
      },
    });

    actions.append(editBtn, menuWrap, runBtn);

    detail.append(facts, structureDiv);
    if (diagnosticBadge) detail.appendChild(diagnosticBadge);
    detail.append(estimate, actions);

    card.append(mainBtn, detail);
    list.appendChild(card);
  }

  updatePQButtons();
}

async function createTypedPlan() {
  if (state.busy || !state.officeReady || !state.codexAvailable) return;
  clearError();
  setBusy(true, "Codex đang tạo typed operations…");
  try {
    state.workbook = await readWorkbook();
    await loadSelectedSourceCheckSample();
    renderWorkbook();
    const plan = await api("/api/pq/v2/plans", {
      prompt: byId("pq2-prompt").value, workbook: state.workbook, source: selectedPQSource(),
    });
    state.pqTypedPlan = plan;
    state.pqTypedPreview = null;
    state.pqTypedApproval = null;
    renderTypedPlan(plan);
    byId("pq2-progress").textContent = plan.planStatus === "reviewReady" ? "Plan đã qua static validation; chưa chạy Excel." : "Plan cần xử lý blocker/câu hỏi trước khi preview.";
  } catch (error) {
    showError(error.code, error.message);
    byId("pq2-progress").textContent = "Không tạo được Typed Plan.";
  } finally {
    setBusy(false, "");
  }
}

function renderTypedPreviewContent(preview, cached = false, cachedAt = "", stale = false) {
  setHidden("pq2-preview-section", false);
  byId("pq2-approve-button").textContent = state.problemChainSupported
    ? "Xác nhận: ghi values và lưu cache"
    : "Duyệt revision và ghi values";
  byId("pq2-result-badge").textContent = cached
    ? stale ? "BẢN CŨ · CHỈ SO SÁNH" : "BẢN XEM ĐÃ LƯU"
    : state.problemChainSupported ? "STAGING · CHƯA LƯU CACHE" : "RUNTIME PREVIEW";
  setHidden("pq2-cancel-preview-button", cached || !state.problemChainSupported);
  const excelVersion = cached ? preview.excelVersion : preview.runtimeEvidence?.excelVersion;
  const age = cached ? ` · Lưu lúc ${new Date(cachedAt).toLocaleString("vi-VN")}` : "";
  byId("pq2-counts").textContent = `Nguồn ${preview.sourceRows} dòng · kết quả ${preview.resultRows} dòng × ${preview.resultColumns} cột · Excel ${excelVersion || "—"}${age}`;
  renderTable("pq2-before-table", preview.beforeColumns, preview.beforeRows);
  renderTable("pq2-after-table", preview.afterColumns, preview.afterRows);
  updatePQButtons();
}

function renderTypedPreview(preview) {
  state.pqTypedPreview = preview;
  state.pqTypedApproval = null;
  if (!state.problemChainSupported) rememberProblemChainPreview(preview);
  renderTypedPreviewContent(preview);
}

async function previewTypedPlan() {
  if (!state.pqTypedPlan || state.pqTypedPlan.planStatus !== "reviewReady") return;
  if (state.problemChainSupported && (!state.problemChainHydrated || !problemChainHeadMatchesView()
    || state.pqTypedPlan.revision.revisionId !== state.problemChainDocument?.headRevisionId)) {
    showError("PQPC_HEAD_MISMATCH", "Chỉ revision đang là HEAD mới được preview.");
    return;
  }
  clearError();
  state.pqTypedPreview = null;
  state.pqTypedApproval = null;
  updatePQButtons();
  setBusy(true, "Excel đang chạy compiled M trên workbook tạm…");
  try {
    state.workbook = await readWorkbook();
    renderWorkbook();
    const preview = await api("/api/pq/v2/previews", {
      revisionId: state.pqTypedPlan.revision.revisionId,
      workbook: state.workbook, workbookBase64: await exportWorkbookBase64(),
    });
    renderTypedPreview(preview);
    byId("pq2-progress").textContent = state.problemChainSupported
      ? `Preview staging của dữ liệu v${preview.runVersion} đã sẵn sàng. Xác nhận mới ghi sheet và thay cache; Hủy giữ cache cũ.`
      : "Excel runtime preview đã sẵn sàng. Review kết quả trước khi duyệt ghi.";
  } catch (error) {
    showError(error.code, error.message);
    if (!state.problemChainSupported || !state.problemChainViewRevisionId
      || !showCachedProblemChainPreview(state.problemChainViewRevisionId)) {
      setHidden("pq2-preview-section", true);
    }
    byId("pq2-progress").textContent = "Preview thất bại; workbook đang mở chưa bị ghi.";
  } finally {
    setBusy(false, "");
  }
}

async function approveAndApplyTyped() {
  if (!state.pqTypedPlan || !state.pqTypedPreview) return;
  if (state.problemChainSupported && (!state.problemChainHydrated || !problemChainHeadMatchesView()
    || state.pqTypedPlan.revision.revisionId !== state.problemChainDocument?.headRevisionId)) {
    showError("PQPC_HEAD_MISMATCH", "Revision đang xem không còn là HEAD; approval/apply bị chặn.");
    return;
  }
  let writeAttempted = false;
  clearError();
  setBusy(true, "Đang bind approval với revision và preview…");
  try {
    const approval = await api("/api/pq/v2/approvals", {
      revisionId: state.pqTypedPlan.revision.revisionId,
      previewId: state.pqTypedPreview.previewId,
      destinationMarker: state.pqTypedMarker,
    });
    state.pqTypedApproval = approval;
    const expectedWorkbook = {name: state.workbook.name, url: state.workbook.url};
    const prepared = await api("/api/pq/v2/applies/prepare", {
      approvalId: approval.approvalId, workbookBase64: await exportWorkbookBase64(),
      destination: {marker: state.pqTypedMarker},
    });
    writeAttempted = true;
    const completed = await writeTypedPrepared(prepared, expectedWorkbook, selectedPQSource());
    if (state.problemChainSupported && completed.resultCached) rememberProblemChainPreview(state.pqTypedPreview);
    byId("pq2-progress").textContent = `${completed.status}: đã ghi values vào ${state.pqResultSheetName}. Add-in không tự Save workbook.`;
    if (state.problemChainSupported) {
      byId("pq2-result-badge").textContent = completed.resultCached ? "ĐÃ XÁC NHẬN · ĐÃ LƯU CACHE" : "ĐÃ XÁC NHẬN · CACHE QUÁ LỚN";
      setHidden("pq2-cancel-preview-button", true);
    }
    byId("pq2-approve-button").disabled = true;
  } catch (error) {
    showError(error.code, error.message);
    if (writeAttempted && state.problemChainSupported) {
      state.pqTypedPreview = null;
      state.pqTypedApproval = null;
      updatePQButtons();
    }
    byId("pq2-progress").textContent = writeAttempted
      ? "Apply có thể đã bắt đầu nhưng read-back chưa hoàn tất; không tuyên bố rollback."
      : "Approval/apply bị chặn; workbook đang mở chưa bị ghi.";
  } finally {
    setBusy(false, "");
  }
}

async function cancelProblemPreview() {
  const preview = state.pqTypedPreview;
  if (state.busy || !state.problemChainSupported || !preview || !problemChainHeadMatchesView()) return;
  clearError();
  setBusy(true, "Đang hủy Preview staging…");
  try {
    await api("/api/pq/v2/problem-chains/previews/cancel", {
      revisionId: preview.revisionId, previewId: preview.previewId,
      baseHistoryHash: state.problemChainHistoryHash,
    });
    state.pqTypedPreview = null;
    state.pqTypedApproval = null;
    showCachedProblemChainPreview(preview.revisionId);
    byId("pq2-progress").textContent = "Đã hủy Preview mới. Cache cũ giữ nguyên; workbook đang mở chưa bị ghi.";
  } catch (error) {
    showError(error.code, error.message);
  } finally {
    setBusy(false, "");
  }
}

async function writeTypedPrepared(prepared, expectedWorkbook, approvedSource) {
  const readback = await applyPQValuesToOpenWorkbook({
    resultWorkbookBase64: prepared.resultWorkbookBase64,
    resultWorkbookSheetName: prepared.resultWorkbookSheetName,
    resultRows: prepared.expectedRows, resultColumns: prepared.expectedColumns,
  }, expectedWorkbook, {
    propertyName: "LocalDataCopilotPQTypedResult", markerValue: "v2",
    baseName: "PQ_Typed_Result", destinationMarker: state.pqTypedMarker,
  });
  const completed = await api("/api/pq/v2/applies/complete", {
    applyId: prepared.applyId,
    readback: {marker: state.pqTypedMarker, sheetName: readback.resultSheetName,
      rowCount: readback.rowCount, columnCount: readback.columnCount},
  });
  state.pqPinnedSource = approvedSource;
  state.pqResultSheetName = readback.resultSheetName;
  return completed;
}

async function requestTypedRepair() {
  if (!state.pqTypedPlan || !(state.pqTypedPlan.hardBlockers || []).length) return;
  if (state.problemChainSupported) {
    showError("PQPC_REPAIR_PATCH_UNAVAILABLE", "Problem Chain chưa hỗ trợ áp dụng repair patch; hãy chỉnh step HEAD qua form có kiểu.");
    return;
  }
  const blocker = state.pqTypedPlan.hardBlockers[0];
  try {
    const repair = await api("/api/pq/v2/repairs", {
      baseRevisionId: state.pqTypedPlan.revision.revisionId,
      snapshotId: state.pqTypedPlan.snapshotId,
      error: {code: blocker.code, message: blocker.reason, failedStepId: blocker.target?.startsWith("stp_") ? blocker.target : null},
    });
    renderTypedRepair(repair);
  } catch (error) {
    showError(error.code, error.message);
  }
}

function renderTypedRepair(repair) {
  setHidden("pq2-repair-section", false);
  byId("pq2-diagnosis").textContent = repair.diagnosis?.rootCause || (repair.questions || []).join(" · ");
  const list = byId("pq2-patch-list");
  list.replaceChildren();
  for (const patch of repair.patchOptions || []) {
    const card = document.createElement("article");
    card.className = "typed-step-card";
    const title = document.createElement("strong");
    title.textContent = `${patch.rank}. ${patch.label}`;
    const detail = document.createElement("p");
    detail.className = "typed-step-description";
    detail.textContent = `${patch.rationale} Tác động: ${patch.semanticImpact} Rủi ro: ${(patch.risks || []).join("; ")}`;
    const apply = typedActionButton(patch.patchId === repair.recommendedPatchId ? "Chọn khuyến nghị" : "Chọn phương án", async () => {
      if (state.problemChainSupported) {
        showError("PQPC_REPAIR_PATCH_UNAVAILABLE", "Repair patch cần revision Problem Chain; không áp dụng qua Typed session cũ.");
        return;
      }
      clearError();
      setBusy(true, "Đang tạo revision từ patch…");
      try {
        const revision = await api("/api/pq/v2/revisions", {
          baseRevisionId: state.pqTypedPlan.revision.revisionId,
          patchId: patch.patchId, changeReason: `Applied repair proposal ${patch.patchId}`,
        });
        state.pqTypedPlan = revision;
        state.pqTypedPreview = null;
        state.pqTypedApproval = null;
        renderTypedPlan(revision);
        setHidden("pq2-repair-section", true);
        setHidden("pq2-preview-section", true);
      } catch (error) { showError(error.code, error.message); }
      finally { setBusy(false, ""); }
    });
    card.append(title, detail, apply);
    list.appendChild(card);
  }
}

function selectedPQSource() {
  const workbook = state.workbook;
  if (!workbook) return null;
  if (workbook.activeSheet === state.pqResultSheetName && state.pqPinnedSource) return state.pqPinnedSource;
  if (workbook.activeSheet.startsWith("PQ_Result")) return null;
  const tables = workbook.tables.filter((table) => table.sheet === workbook.activeSheet);
  if (tables.length === 1) return {kind: "table", sheet: workbook.activeSheet, name: tables[0].name};
  if (tables.length > 1) {
    const cell = workbook.activeCell || {};
    const selected = tables.filter((table) => Number.isInteger(table.rowIndex) && Number.isInteger(table.columnIndex)
      && cell.rowIndex >= table.rowIndex && cell.rowIndex < table.rowIndex + table.totalRows + 1
      && cell.columnIndex >= table.columnIndex && cell.columnIndex < table.columnIndex + table.totalColumns);
    return selected.length === 1 ? {kind: "table", sheet: workbook.activeSheet, name: selected[0].name} : null;
  }
  return (workbook.sheets || []).some((sheet) => sheet.name === workbook.activeSheet)
    ? {kind: "sheet", sheet: workbook.activeSheet} : null;
}

async function loadSelectedSourceCheckSample() {
  if (!state.typedStepDiagnosticsCapability || !state.workbook || !state.sessionId) return;
  const source = selectedPQSource();
  if (!source) return;
  if (source.kind === "sheet") return;
  byId("pq2-progress").textContent = "Đang tạo mẫu kiểm tra: đầu/giữa/cuối, ngẫu nhiên cố định và các dòng khó…";
  const sampled = await api("/api/pq/v2/step-diagnostics/samples", {
    workbook: state.workbook,
    workbookBase64: await exportWorkbookBase64(),
    source,
    chainId: state.problemChainDocument?.chainId || null,
  }, {timeoutMs: 120000});
  const target = source.kind === "table"
    ? (state.workbook.tables || []).find((item) => item.sheet === source.sheet && item.name === source.name)
    : (state.workbook.sheets || []).find((item) => item.name === source.sheet);
  if (!target || !Array.isArray(sampled.sampleRows)) return;
  target.rows = sampled.sampleRows.map((item) => Array.isArray(item.values) ? item.values : []);
  target.sampleOrdinals = sampled.sampleRows.map((item) => item.ordinal);
  target.sampleReasonCodes = sampled.sampleRows.map((item) => item.reasonCodes || []);
  target.samplerPolicyVersion = sampled.samplerPolicyVersion;
  target.sampleProfileIncomplete = sampled.profileIncomplete === true;
  target.sampleCacheHit = sampled.cacheHit === true;
  if (Array.isArray(sampled.columnTypes) && sampled.columnTypes.length === target.headers.length) {
    target.inferredTypes = sampled.columnTypes;
  }
}

function invalidatePQPreview() {
  state.pqPreview = null;
  setHidden("pq-preview-section", true);
  updatePQButtons();
}

function updatePQButtons() {
  const ready = !state.busy && state.officeReady && Boolean(state.workbook);
  const advancedReady = ready && Boolean(state.sessionId) && Boolean(state.advancedMPolicy);
  byId("pq-propose-button").disabled = !advancedReady || !state.codexAvailable || !selectedPQSource();
  byId("pq-preview-button").disabled = !advancedReady || !selectedPQSource()
    || !byId("pq-code").value.trim();
  byId("pq-apply-source-button").disabled = !advancedReady || !state.pqPreview || state.pqPreview.applied === true;
  byId("pq2-plan-button").disabled = state.problemChainSupported || !ready || !state.codexAvailable || !byId("pq2-prompt").value.trim();
  byId("pq2-preview-button").disabled = !ready || !state.pqTypedPlan
    || state.pqTypedPlan.planStatus !== "reviewReady"
    || (state.problemChainSupported && (!state.problemChainHydrated || !problemChainHeadMatchesView()));
  byId("pq2-approve-button").disabled = !ready || !state.pqTypedPreview
    || state.pqTypedApproval?.status === "approved"
    || (state.problemChainSupported && (!state.problemChainHydrated || !problemChainHeadMatchesView()));
  byId("pq2-cancel-preview-button").disabled = !ready || !state.problemChainSupported
    || !state.pqTypedPreview || !problemChainHeadMatchesView();
  if (byId("pq2-diagnostic-confirm")) {
    byId("pq2-diagnostic-confirm").disabled = !ready || !state.pqStepDiagnosticStaging
      || !problemChainHeadMatchesView();
    byId("pq2-diagnostic-cancel").disabled = !ready || !state.pqStepDiagnosticStaging;
  }
  byId("pq2-add-step").disabled = !ready || !state.pqTypedPlan
    || (state.problemChainSupported && (!state.problemChainHydrated || !problemChainHeadMatchesView()));
  setHidden("pq2-run-section", !state.pqTypedPlan);
  updateProblemChainButtons();
}

function switchTab(name) {
  setHidden("tab-assistant", name !== "assistant");
  setHidden("tab-pq", name !== "pq");
  for (const [tab, id] of [["assistant", "tab-assistant-button"], ["pq", "tab-pq-button"]]) {
    byId(id).classList.toggle("active", name === tab);
    byId(id).setAttribute("aria-selected", String(name === tab));
  }
  clearError();
}

async function proposePQ() {
  if (state.busy || !state.officeReady || !state.codexAvailable || !state.advancedMPolicy) return;
  const prompt = byId("pq-prompt").value;
  clearError();
  setBusy(true, "Đang đọc lại workbook để đề xuất M…");
  try {
    state.workbook = await readWorkbook();
    renderWorkbook();
    const source = selectedPQSource();
    if (!source) throw new Error("Chọn sheet hoặc Table trước khi đề xuất M.");
    const editorBefore = byId("pq-code").value;
    byId("pq-progress").textContent = "Codex đang đề xuất M từ mẫu dữ liệu…";
    const proposal = await api("/api/pq/propose", {prompt, workbook: state.workbook, source});
    if (prompt !== byId("pq-prompt").value || editorBefore !== byId("pq-code").value
      || JSON.stringify(source) !== JSON.stringify(selectedPQSource())) {
      throw new Error("Yêu cầu, nguồn hoặc code M đã đổi trong lúc Codex phân tích. Đề xuất cũ không được chèn vào editor.");
    }
    byId("pq-code").value = proposal.mCode;
    byId("pq-proposal-note").textContent = proposal.summary || "Codex đã đề xuất M; hãy review trước khi chạy.";
    byId("pq-warnings").textContent = (proposal.warnings || []).join(" · ");
    setHidden("pq-warnings", !(proposal.warnings || []).length);
    invalidatePQPreview(true);
    byId("pq-progress").textContent = "M mới chỉ là đề xuất; chưa chạy Excel.";
  } catch (error) {
    showError(error.code, error.message);
    byId("pq-progress").textContent = "Không tạo được đề xuất M.";
  } finally {
    setBusy(false, "");
  }
}

function renderPQPreview(preview) {
  state.pqPreview = preview;
  setHidden("pq-preview-section", false);
  byId("pq-counts").textContent = `Excel refresh trên bản tạm: nguồn ${preview.sourceRows} dòng, kết quả ${preview.resultRows} dòng · ${preview.resultColumns} cột.`;
  renderTable("pq-before-table", preview.beforeColumns, preview.beforeRows);
  renderTable("pq-after-table", preview.afterColumns, preview.afterRows);
  const target = preview.source?.kind === "table"
    ? `Table ${preview.source.name} trên sheet ${preview.source.sheet}`
    : `usedRange của sheet ${preview.source?.sheet || "nguồn"}`;
  byId("pq-apply-source-button").textContent = preview.applied ? `Đã áp dụng vào ${target}` : `Áp dụng vào ${target}`;
  byId("pq-preview-note").textContent = preview.applied
    ? `Đã đọc lại ${preview.afterRows.length} dòng đầu từ nguồn sau khi ghi values. Add-in không tự Save workbook.`
    : `Kết quả preview đã được copy values-only vào sheet ${preview.previewSheetName || "PQ_Result"}. Sheet nguồn chưa bị ghi; nếu duyệt, nút Apply sẽ thay ${target} mà không tạo backup.`;
  updatePQButtons();
}

function requestPQConfirmation(workbookName, options = {}) {
  byId("pq-confirm-title").textContent = options.title || "Chạy M trên workbook tạm?";
  byId("pq-confirm-detail").textContent = options.detail || "M có thể đọc toàn bộ workbook export, file/web/database, dùng credential Excel hoặc gây side effect ngoài workbook. Workbook tạm không phải sandbox. Sau khi chạy, add-in copy values kết quả vào sheet PQ_Result để review nhưng chưa ghi sheet nguồn.";
  byId("pq-confirm-continue").textContent = options.continueLabel || "Đồng ý, chạy thử";
  byId("pq-confirm-workbook").textContent = `Workbook: ${workbookName}`;
  setHidden("pq-confirm-overlay", false);
  const proceed = byId("pq-confirm-continue");
  const cancel = byId("pq-confirm-cancel");
  return new Promise((resolve) => {
    const finish = (accepted) => {
      proceed.removeEventListener("click", accept);
      cancel.removeEventListener("click", decline);
      document.removeEventListener("keydown", onKeyDown);
      setHidden("pq-confirm-overlay", true);
      resolve(accepted);
    };
    const accept = () => finish(true);
    const decline = () => finish(false);
    const onKeyDown = (event) => {
      if (event.key === "Escape") finish(false);
    };
    proceed.addEventListener("click", accept);
    cancel.addEventListener("click", decline);
    document.addEventListener("keydown", onKeyDown);
    proceed.focus();
  });
}

async function applyPQValuesToOpenWorkbook(preview, expectedWorkbook, resultOptions = {}) {
  if (!Office.context.requirements.isSetSupported("ExcelApi", "1.13")) {
    throw new Error("Excel này chưa hỗ trợ nhập worksheet (ExcelApi 1.13); workbook chưa bị ghi.");
  }
  return Excel.run(async (context) => {
    const workbook = context.workbook;
    const worksheets = workbook.worksheets;
    workbook.load("name");
    worksheets.load("items/name");
    await context.sync();
    if (workbook.name !== expectedWorkbook.name || officeDocumentUrl() !== expectedWorkbook.url) {
      throw new Error("Workbook đang mở đã đổi; chưa ghi kết quả. Hãy chạy thử lại.");
    }
    const markerProperty = resultOptions.propertyName || "LocalDataCopilotPQResult";
    const markerValue = resultOptions.markerValue || "v1";
    const baseName = resultOptions.baseName || "PQ_Result";
    const candidates = worksheets.items.map((sheet) => ({
      sheet, marker: sheet.customProperties.getItemOrNullObject(markerProperty),
    }));
    for (const candidate of candidates) candidate.marker.load("isNullObject");
    await context.sync();
    for (const candidate of candidates) {
      if (!candidate.marker.isNullObject) candidate.marker.load("value");
    }
    await context.sync();
    const owned = candidates.filter((candidate) => !candidate.marker.isNullObject && candidate.marker.value === markerValue);
    if (owned.length > 1) throw new Error("Có nhiều sheet kết quả do add-in quản lý; chưa ghi để tránh ghi đè nhầm.");
    const inserted = workbook.insertWorksheetsFromBase64(preview.resultWorkbookBase64, {
      sheetNamesToInsert: [preview.resultWorkbookSheetName],
    });
    await context.sync();
    if (!Array.isArray(inserted.value) || inserted.value.length !== 1) {
      throw new Error("Excel không nhập đúng một sheet kết quả; chưa cập nhật sheet cũ.");
    }
    const imported = worksheets.getItem(inserted.value[0]);
    if (!Number.isInteger(preview.resultRows) || preview.resultRows < 0
      || !Number.isInteger(preview.resultColumns) || preview.resultColumns < 1) {
      imported.delete();
      await context.sync();
      throw new Error("Sheet nhập vào có kích thước khác kết quả Power Query; sheet cũ chưa bị ghi.");
    }
    // The server already validates the values-only package row elements and
    // header width. Do not use getUsedRange(true) here: Excel deliberately
    // drops trailing all-null rows from a values-only used range even though
    // those rows are valid Power Query records.
    const importedRange = imported.getRangeByIndexes(
      0, 0, preview.resultRows + 1, preview.resultColumns,
    );
    const importedRowCount = preview.resultRows + 1;
    const importedColumnCount = preview.resultColumns;
    let resultSheet = imported;
    if (owned.length === 1) {
      resultSheet = owned[0].sheet;
      const oldRange = resultSheet.getUsedRange(true);
      oldRange.load("rowCount,columnCount");
      await context.sync();
      const destinationRange = resultSheet.getRangeByIndexes(
        0, 0, importedRowCount, importedColumnCount,
      );
      // Older result sheets may still be formatted as Text. Clear only the
      // managed result range's formats so numeric/date variants stay typed.
      destinationRange.clear("Formats");
      destinationRange.copyFrom(importedRange, Excel.RangeCopyType.values);
      await context.sync();
      if (oldRange.rowCount > importedRowCount) {
        resultSheet.getRangeByIndexes(importedRowCount, 0,
          oldRange.rowCount - importedRowCount, oldRange.columnCount).clear("Contents");
      }
      if (oldRange.columnCount > importedColumnCount) {
        resultSheet.getRangeByIndexes(0, importedColumnCount,
          Math.min(oldRange.rowCount, importedRowCount), oldRange.columnCount - importedColumnCount).clear("Contents");
      }
      await context.sync();
      imported.delete();
      await context.sync();
    } else {
      const existingNames = new Set(worksheets.items.map((sheet) => sheet.name));
      let name = baseName;
      for (let index = 2; existingNames.has(name); index += 1) name = `${baseName}_${index}`;
      imported.name = name;
      imported.customProperties.add(markerProperty, markerValue);
      await context.sync();
    }
    resultSheet.load("name");
    const readback = resultSheet.getRangeByIndexes(0, 0,
      Math.min(preview.resultRows + 1, 21), Math.min(preview.resultColumns, 200));
    readback.load("values");
    resultSheet.activate();
    await context.sync();
    return {
      resultSheetName: resultSheet.name,
      afterColumns: (readback.values[0] || []).map(String),
      afterRows: readback.values.slice(1),
      rowCount: preview.resultRows,
      columnCount: preview.resultColumns,
      marker: resultOptions.destinationMarker || "localDataCopilot.pqAdvancedResult.v1",
    };
  });
}

async function applyPQValuesToSource(preview, expectedWorkbook, source) {
  const blockBeforeWrite = (message) => {
    const error = new Error(message);
    error.sourceWriteStarted = false;
    throw error;
  };
  if (!Office.context.requirements.isSetSupported("ExcelApi", "1.13")) {
    blockBeforeWrite("Excel này chưa hỗ trợ nhập worksheet (ExcelApi 1.13); sheet nguồn chưa bị ghi.");
  }
  if (!source || !["table", "sheet"].includes(source.kind)) {
    blockBeforeWrite("Nguồn đã preview không còn hợp lệ; hãy chạy thử lại.");
  }
  return Excel.run(async (context) => {
    const workbook = context.workbook;
    const worksheets = workbook.worksheets;
    workbook.load("name");
    worksheets.load("items/name");
    await context.sync();
    if (workbook.name !== expectedWorkbook.name || officeDocumentUrl() !== expectedWorkbook.url) {
      blockBeforeWrite("Workbook đang mở đã đổi; sheet nguồn chưa bị ghi. Hãy chạy thử lại.");
    }
    if (!worksheets.items.some((sheet) => sheet.name === source.sheet)) {
      blockBeforeWrite("Sheet nguồn không còn tồn tại; hãy chạy thử lại.");
    }

    const sourceSheet = worksheets.getItem(source.sheet);
    let oldRange;
    let sourceTable = null;
    if (source.kind === "table") {
      sourceTable = sourceSheet.tables.getItem(source.name);
      oldRange = sourceTable.getRange();
    } else {
      oldRange = sourceSheet.getUsedRange(true);
    }
    oldRange.load("rowIndex,columnIndex,rowCount,columnCount");
    await context.sync();

    const inserted = workbook.insertWorksheetsFromBase64(preview.resultWorkbookBase64, {
      sheetNamesToInsert: [preview.resultWorkbookSheetName],
    });
    await context.sync();
    if (!Array.isArray(inserted.value) || inserted.value.length !== 1) {
      blockBeforeWrite("Excel không nhập đúng một sheet preview; sheet nguồn chưa bị ghi.");
    }
    const imported = worksheets.getItem(inserted.value[0]);
    if (!Number.isInteger(preview.resultRows) || preview.resultRows < 0
      || !Number.isInteger(preview.resultColumns) || preview.resultColumns < 1) {
      imported.delete();
      await context.sync();
      blockBeforeWrite("Payload preview có kích thước không hợp lệ; sheet nguồn chưa bị ghi.");
    }
    const importedRange = imported.getRangeByIndexes(
      0, 0, preview.resultRows + 1, preview.resultColumns,
    );

    const newRows = preview.resultRows + 1;
    const newColumns = preview.resultColumns;
    const targetRange = sourceSheet.getRangeByIndexes(oldRange.rowIndex, oldRange.columnIndex, newRows, newColumns);

    if (sourceTable && (newRows > oldRange.rowCount || newColumns > oldRange.columnCount)) {
      targetRange.load("values,formulas");
      await context.sync();
      for (let row = 0; row < newRows; row += 1) {
        for (let column = 0; column < newColumns; column += 1) {
          if (row < oldRange.rowCount && column < oldRange.columnCount) continue;
          const value = targetRange.values?.[row]?.[column];
          const formula = targetRange.formulas?.[row]?.[column];
          if ((value !== null && value !== "") || (formula !== null && formula !== "")) {
            imported.delete();
            await context.sync();
            blockBeforeWrite("Kết quả cần mở rộng Table nhưng vùng kế bên đang có dữ liệu/công thức; chưa ghi để tránh ghi đè ngoài Table.");
          }
        }
      }
    }

    if (sourceTable) sourceTable.resize(targetRange);
    targetRange.copyFrom(importedRange, Excel.RangeCopyType.values);
    await context.sync();

    if (oldRange.rowCount > newRows) {
      sourceSheet.getRangeByIndexes(
        oldRange.rowIndex + newRows, oldRange.columnIndex,
        oldRange.rowCount - newRows, oldRange.columnCount,
      ).clear("Contents");
    }
    if (oldRange.columnCount > newColumns) {
      sourceSheet.getRangeByIndexes(
        oldRange.rowIndex, oldRange.columnIndex + newColumns,
        Math.min(oldRange.rowCount, newRows), oldRange.columnCount - newColumns,
      ).clear("Contents");
    }
    await context.sync();
    imported.delete();
    await context.sync();

    const readback = sourceSheet.getRangeByIndexes(
      oldRange.rowIndex, oldRange.columnIndex,
      Math.min(newRows, 21), Math.min(newColumns, 200),
    );
    readback.load("values");
    sourceSheet.activate();
    await context.sync();
    return {
      sourceSheetName: source.sheet,
      sourceKind: source.kind,
      sourceName: source.kind === "table" ? source.name : source.sheet,
      afterColumns: (readback.values[0] || []).map(String),
      afterRows: readback.values.slice(1),
      rowCount: preview.resultRows,
      columnCount: preview.resultColumns,
    };
  });
}

async function previewPQ() {
  if (state.busy || !state.advancedMPolicy || !byId("pq-code").value.trim()) return;
  const code = byId("pq-code").value;
  const cachedAcknowledgementKey = advancedMAcknowledgementKey(state.workbook);
  if (!cachedAcknowledgementKey) {
    showError("PQ_RISK_POLICY_STALE", "Trusted Mode policy hoặc workbook identity không hợp lệ; Advanced M đã bị khóa.");
    return;
  }
  if (!state.pqRiskAcknowledgements.has(cachedAcknowledgementKey)) {
    const confirmed = await requestPQConfirmation(state.workbook.name);
    if (!confirmed) {
      byId("pq-progress").textContent = "Đã hủy trước khi đọc hoặc xuất workbook; chưa chạy M và chưa ghi workbook.";
      return;
    }
    state.pqRiskAcknowledgements.add(cachedAcknowledgementKey);
  }
  clearError();
  invalidatePQPreview();
  setBusy(true, "Đang đọc workbook để chạy Power Query…");
  byId("pq-progress").textContent = "Đang đọc workbook hiện hành…";
  try {
    state.workbook = await readWorkbook();
    renderWorkbook();
    const source = selectedPQSource();
    if (!source) throw new Error("Mở sheet nguồn trong Excel; nếu có nhiều Table, chọn một ô trong Table cần xử lý.");
    const expectedWorkbook = {name: state.workbook.name, url: state.workbook.url};
    const acknowledgementKey = advancedMAcknowledgementKey(state.workbook);
    if (!acknowledgementKey) throw new Error("Trusted Mode policy không hợp lệ; Advanced M đã bị khóa.");
    if (!state.pqRiskAcknowledgements.has(acknowledgementKey)) {
      const confirmed = await requestPQConfirmation(state.workbook.name);
      if (!confirmed) {
        byId("pq-progress").textContent = "Workbook đã đổi sau lần xác nhận ban đầu. Đã hủy trước khi xuất workbook hoặc chạy M.";
        return;
      }
      state.pqRiskAcknowledgements.add(acknowledgementKey);
    }
    const workbookBase64 = await exportWorkbookBase64();
    byId("pq-progress").textContent = "Excel đang tính M trên bản tạm; chưa ghi workbook đang mở…";
    const preview = await api("/api/pq/run-sheet", {
      workbook: state.workbook, source, mCode: code, riskAccepted: true, workbookBase64,
      riskPolicyId: state.advancedMPolicy.policyId,
      ignoredSheetNames: state.pqResultSheetName ? [state.pqResultSheetName] : [],
    });
    if (preview.status !== "ready_for_open_workbook") {
      throw new Error("Power Query chưa tạo được sheet giá trị đã kiểm tra; chưa ghi workbook đang mở.");
    }
    if (code !== byId("pq-code").value || JSON.stringify(source) !== JSON.stringify(selectedPQSource())) {
      throw new Error("M hoặc nguồn đã đổi trong lúc chạy. Hãy chạy thử lại.");
    }
    const currentWorkbookBase64 = await exportWorkbookBase64();
    const sourceCheck = await api("/api/pq/check-source", {
      sourceFingerprint: preview.sourceFingerprint, workbookBase64: currentWorkbookBase64,
      ignoredSheetNames: state.pqResultSheetName ? [state.pqResultSheetName] : [],
    });
    if (sourceCheck.unchanged !== true) {
      throw new Error("Dữ liệu hoặc cấu trúc workbook đã đổi trong lúc Power Query chạy; chưa ghi kết quả. Hãy chạy thử lại.");
    }
    const previewSheet = await applyPQValuesToOpenWorkbook(preview, expectedWorkbook, {
      propertyName: "LocalDataCopilotPQResult", markerValue: "v1",
      baseName: "PQ_Result", destinationMarker: "localDataCopilot.pqAdvancedPreview.v1",
    });
    state.pqPinnedSource = source;
    state.pqResultSheetName = previewSheet.resultSheetName;
    renderPQPreview({
      ...preview, ...previewSheet, source, code, expectedWorkbook,
      previewSheetName: previewSheet.resultSheetName, applied: false,
    });
    byId("pq-progress").textContent = `Đã tạo/cập nhật sheet ${previewSheet.resultSheetName} để review. Sheet nguồn chưa bị ghi; bấm Apply nếu chấp nhận kết quả.`;
  } catch (error) {
    showError(error.code, error.message);
    byId("pq-progress").textContent = "M chưa chạy thử thành công; chưa ghi gì vào workbook đang mở. Kiểm tra code M và chạy lại.";
  } finally {
    setBusy(false, "");
  }
}

async function applyPQPreviewToSource() {
  const preview = state.pqPreview;
  if (state.busy || !state.advancedMPolicy || !preview || preview.applied) return;
  clearError();
  if (preview.code !== byId("pq-code").value) {
    invalidatePQPreview();
    showError("PQ_PREVIEW_STALE", "Code M đã đổi sau preview. Hãy chạy thử lại trước khi áp dụng.");
    return;
  }
  const target = preview.source.kind === "table"
    ? `Table ${preview.source.name} trên sheet ${preview.source.sheet}`
    : `usedRange của sheet ${preview.source.sheet}`;
  const confirmed = await requestPQConfirmation(preview.expectedWorkbook.name, {
    title: `Ghi đè ${target}?`,
    detail: `Kết quả preview sẽ thay trực tiếp ${target} bằng values. Không tạo backup, không bảo đảm Ctrl+Z và add-in không tự Save workbook.`,
    continueLabel: "Áp dụng vào nguồn",
  });
  if (!confirmed) {
    byId("pq-progress").textContent = "Đã hủy Apply; sheet nguồn chưa bị ghi.";
    return;
  }

  let writeAttempted = false;
  setBusy(true, `Đang kiểm tra lại ${target} trước khi ghi…`);
  try {
    state.workbook = await readWorkbook();
    if (workbookIdentity(state.workbook) !== workbookIdentity(preview.expectedWorkbook)) {
      throw new Error("Workbook đang mở đã đổi. Hãy chạy thử lại.");
    }
    const currentWorkbookBase64 = await exportWorkbookBase64();
    const sourceCheck = await api("/api/pq/check-source", {
      sourceFingerprint: preview.sourceFingerprint, workbookBase64: currentWorkbookBase64,
      ignoredSheetNames: preview.previewSheetName ? [preview.previewSheetName] : [],
    });
    if (sourceCheck.unchanged !== true) {
      throw new Error("Dữ liệu hoặc cấu trúc workbook đã đổi sau preview; chưa ghi kết quả. Hãy chạy thử lại.");
    }
    if (preview.code !== byId("pq-code").value) {
      throw new Error("Code M đã đổi sau preview. Hãy chạy thử lại.");
    }
    writeAttempted = true;
    const readback = await applyPQValuesToSource(preview, preview.expectedWorkbook, preview.source);
    const applied = {...preview, ...readback, applied: true};
    delete applied.resultWorkbookBase64;
    renderPQPreview(applied);
    byId("pq-progress").textContent = `Đã thay ${target} bằng values và đọc lại kích thước. Add-in không tự Save workbook.`;
    try {
      state.workbook = await readWorkbook();
      renderWorkbook();
    } catch {
      byId("pq-progress").textContent += " Không đọc lại được workbook; dùng Đọc lại trước lần chạy tiếp theo.";
    }
  } catch (error) {
    const mayHaveWritten = writeAttempted && error.sourceWriteStarted !== false;
    if (!mayHaveWritten) invalidatePQPreview();
    showError(error.code, error.message);
    byId("pq-progress").textContent = mayHaveWritten
      ? "Apply có thể đã ghi một phần nhưng read-back chưa hoàn tất; không tuyên bố rollback. Kiểm tra sheet nguồn trước khi chạy lại."
      : "Apply bị chặn trước khi ghi; sheet nguồn chưa bị thay đổi.";
  } finally {
    setBusy(false, "");
  }
}

function bindEvents() {
  byId("tab-assistant-button").addEventListener("click", () => switchTab("assistant"));
  byId("tab-pq-button").addEventListener("click", () => switchTab("pq"));
  byId("pq-propose-button").addEventListener("click", proposePQ);
  byId("pq-preview-button").addEventListener("click", previewPQ);
  byId("pq-apply-source-button").addEventListener("click", applyPQPreviewToSource);
  byId("pq-code").addEventListener("input", invalidatePQPreview);
  byId("pq2-mode-button").addEventListener("click", () => switchPQMode("typed"));
  byId("pq-advanced-mode-button").addEventListener("click", () => switchPQMode("advanced"));
  byId("pq2-plan-button").addEventListener("click", createTypedPlan);
  byId("pq2-preview-button").addEventListener("click", previewTypedPlan);
  byId("pq2-approve-button").addEventListener("click", approveAndApplyTyped);
  byId("pq2-cancel-preview-button").addEventListener("click", cancelProblemPreview);
  byId("pq2-diagnostic-confirm").addEventListener("click", confirmTypedStepDiagnostic);
  byId("pq2-diagnostic-cancel").addEventListener("click", cancelTypedStepDiagnostic);
  byId("pq2-add-step").addEventListener("click", () => openTypedEditor());
  byId("pq2-editor-cancel").addEventListener("click", () => setHidden("pq2-editor", true));
  byId("pq2-editor-save").addEventListener("click", saveTypedEditor);
  byId("pq2-operation").addEventListener("change", renderTypedParameterFields);
  byId("pq2-inputs").addEventListener("change", renderTypedParameterFields);
  byId("pq2-prompt").addEventListener("input", () => {
    invalidateTypedPlan("Typed request changed. Create a new plan.");
    updatePQButtons();
  });
  byId("pq2-prompt").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && event.ctrlKey && !event.altKey && !event.metaKey && !event.shiftKey && !event.isComposing && !event.repeat && !byId("pq2-plan-button").disabled) {
      event.preventDefault();
      byId("pq2-plan-button").click();
    }
  });
  byId("pq-prompt").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && event.ctrlKey && !event.altKey && !event.metaKey && !event.shiftKey && !event.isComposing && !event.repeat && !byId("pq-propose-button").disabled) {
      event.preventDefault();
      byId("pq-propose-button").click();
    }
  });
  byId("refresh-button").addEventListener("click", async () => {
    await refreshWorkbook();
    if (state.problemChainSupported) await hydrateProblemChain();
  });
  byId("analyze-button").addEventListener("click", analyze);
  byId("approval-check").addEventListener("change", updateApplyState);
  byId("apply-button").addEventListener("click", applyPlan);
  byId("prompt").addEventListener("input", () => {
    updatePromptCount();
    invalidatePlan();
  });
  byId("prompt").addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || !event.ctrlKey || event.altKey || event.metaKey || event.shiftKey || event.isComposing || event.repeat) return;
    const button = byId("analyze-button");
    if (button.disabled) return;
    event.preventDefault();
    button.click();
  });
  byId("formula-list-separator").addEventListener("change", () => invalidatePlan());
  byId("pqpc-history-toggle")?.addEventListener("click", () => {
    setProblemChainHistoryExpanded(!state.problemChainHistoryExpanded);
  });
  byId("pqpc-clear-history")?.addEventListener("click", async () => {
    if (state.busy || !state.problemChainDocument || !state.problemChainDocument.revisions?.length) return;
    const count = state.problemChainDocument.revisions.length;
    const confirmed = await requestPQConfirmation(state.workbook?.name || "workbook", {
      title: "Xóa sạch toàn bộ lịch sử Problem Chain?",
      detail: `Thao tác này sẽ xóa toàn bộ ${count} revision và nhánh khỏi workbook. Workbook sẽ trở về trạng thái chưa có Problem Chain. Hãy Save workbook sau khi xóa để lưu lại.`,
      continueLabel: "Xóa sạch lịch sử",
    });
    if (!confirmed) return;
    await clearProblemChainHistory();
  });
  byId("pqpc-new-problem")?.addEventListener("click", () => {
    openProblemBranchEditor(state.problemChainDocument ? "newRoot" : "new");
  });
  byId("pq2-revision-info")?.addEventListener("click", () => {
    const panel = byId("pq2-info-panel");
    if (!panel) return;
    const isHidden = panel.hidden;
    panel.hidden = !isHidden;
    byId("pq2-revision-info")?.setAttribute("aria-expanded", String(!isHidden));
  });
  byId("pqpc-create-button").addEventListener("click", createProblemContinuation);
  byId("pqpc-branch-submit").addEventListener("click", submitProblemBranchDraft);
  byId("pqpc-branch-cancel").addEventListener("click", closeProblemBranchEditor);
  byId("pqpc-branch-prompt").addEventListener("input", handleProblemPromptInput);
  byId("pqpc-branch-prompt").addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || !event.ctrlKey || event.altKey || event.metaKey || event.shiftKey || event.isComposing || event.repeat) return;
    event.preventDefault();
    submitProblemBranchDraft();
  });
  byId("pqpc-source-changed").addEventListener("change", markProblemSourceChanged);
  byId("pqpc-prompt").addEventListener("input", updateProblemChainButtons);
  byId("pqpc-prompt").addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || !event.ctrlKey || event.altKey || event.metaKey || event.shiftKey || event.isComposing || event.repeat) return;
    const button = byId("pqpc-create-button");
    if (button.disabled) return;
    event.preventDefault();
    button.click();
  });
  document.addEventListener("click", (event) => {
    if (!event.target?.closest?.(".menu")) {
      document.querySelectorAll?.(".menu-pop").forEach((pop) => {
        pop.hidden = true;
      });
    }
  });
  updatePromptCount();
  switchPQMode("typed");
  updatePQButtons();
}

function closeCoordinatorSession() {
  if (!state.token) return;
  try {
    fetch("/api/session/close", {
      method: "POST",
      headers: {"Content-Type": "application/json", "X-Local-Token": state.token},
      body: "{}",
      keepalive: true,
    }).catch(() => {});
  } catch {
    // Page teardown is best-effort; never block Excel from closing the pane.
  }
}

async function start() {
  bindEvents();
  try {
    await bootstrap();
  } catch (error) {
    showError("COORDINATOR_OFFLINE", error.message);
    return;
  }
  if (!window.Office) {
    showError("OFFICE_NOT_READY", "Trang này phải được mở từ Excel task pane, không phải browser thường.");
    return;
  }
  Office.onReady(async (info) => {
    if (info.host !== Office.HostType.Excel) {
      showError("OFFICE_NOT_READY", "Add-in hiện không chạy trong Excel.");
      return;
    }
    state.officeReady = true;
    await refreshWorkbook();
    await hydrateProblemChain();
  });
}

document.addEventListener("DOMContentLoaded", start);
if (typeof window !== "undefined" && window.addEventListener) {
  window.addEventListener("pagehide", closeCoordinatorSession);
}
