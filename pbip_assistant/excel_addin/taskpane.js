"use strict";

const state = {
  token: "",
  workbook: null,
  officeReady: false,
  busy: false,
  capabilities: {codexAnalysis: false},
  activeTab: "assistant",
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
  revertRunning: false,
  pqStepDiagnosticStaging: null,
  pqStepDiagnosticCaches: new Map(),
  pqStepDiagnosticTimings: new Map(),
  flow: createFlowState(),
  workbookRecord: createWorkbookRecordState(),
  preparationJourneyStep: null,
  preparationWorkbookKey: null,
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
  if (message) setExportProgress(message);
  updatePQButtons();
  updateProblemChainButtons();
  updateFlowButtons();
}

function updatePromptCount() {
  const prompt = byId("prompt").value;
  byId("prompt-count").textContent = `${prompt.length} / ${byId("prompt").maxLength || 4000}`;
}

async function api(path, payload, {timeoutMs = 0, preserveConsumedState = false} = {}) {
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
      for (const key of ["approvalConsumed", "written", "retryable"]) {
        if (typeof error[key] === "boolean") failure[key] = error[key];
      }
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
      if (!preserveConsumedState && [401, 403].includes(response.status) && ["TOKEN_EXPIRED", "TOKEN_REQUIRED"].includes(failure.code)) {
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
  resetFlowView();
  ["flow-source-section", "flow-prompt-section", "flow-understand-section", "flow-branches-section"].forEach((id) => flowSetHidden(id, true));
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
  setHidden("pq-preview-section", true);
  setHidden("pq2-plan-section", true);
  setHidden("pq2-preview-section", true);
  setHidden("pqpc-branch-editor", true);
  setHidden("pqpc-clarification", true);
  byId("pqpc-clarification-questions").replaceChildren();
  setHidden("pqpc-impact-section", true);
  if (byId("pqpc-progress")) {
    byId("pqpc-progress").textContent = "Phiên coordinator đã hết hạn. Lịch sử vẫn ở workbook; hãy đọc lại trước thao tác mới. POST cũ không được tự chạy lại.";
  }
  byId("pq-progress").textContent = "Phiên coordinator đã hết hạn. Hãy chạy lại preview; yêu cầu cũ không được tự chạy lại.";
  byId("pq2-progress").textContent = "Phiên coordinator đã hết hạn. Hãy tạo lại Typed Plan.";
  updatePQButtons();
  updateProblemChainButtons();
}

async function bootstrap() {
  const response = await fetch("/api/bootstrap", {cache: "no-store"});
  if (!response.ok) {
    const result = await response.json().catch(() => ({}));
    throw Object.assign(new Error(response.status === 429
      ? "Phiên trước đang kết thúc. Bấm Kết nối lại để tiếp tục."
      : "Chưa kết nối được bộ hỗ trợ tại máy. Bấm Kết nối lại để thử lại."),
      {code: result.error?.code || "COORDINATOR_OFFLINE"});
  }
  const result = await response.json();
  state.token = result.token;
  state.sessionId = result.session && typeof result.session.sessionId === "string"
    ? result.session.sessionId : "";
  state.advancedMPolicy = state.sessionId && isValidAdvancedMPolicy(result.capabilities?.advancedMPolicy)
    ? result.capabilities.advancedMPolicy : null;
  state.problemChainCapability = result.capabilities?.pqProblemChainV1 === true
    && result.capabilities?.pqProblemChainNamespace === PROBLEM_CHAIN_NAMESPACE;
  state.typedStepDiagnosticsCapability = result.capabilities?.pqTypedStepDiagnostics === true;
  state.flow.v2Capability = result.capabilities?.assistantFlowV2 === true;
  state.preparationReadCapability = result.capabilities?.preparationReadV1 === true;
  state.preparationFolderPicker = result.capabilities?.preparationFolderPicker === true;
  state.preparationBackupEnabled = result.capabilities?.preparationBackups !== false;
  renderFlow();
  if (!result.capabilities || !Object.prototype.hasOwnProperty.call(result.capabilities, "codexAnalysis")) {
    state.capabilities.codexAnalysis = false;
    showError("COORDINATOR_UPDATE_REQUIRED", "Coordinator đang chạy bản cũ. Chạy lại py -m pbip_assistant.excel_addin_server rồi mở lại panel.");
    return;
  }
  state.capabilities.codexAnalysis = Boolean(result.capabilities.codexAnalysis);
  if (result.capabilities.pqTypedDestinationMarker) {
    state.pqTypedMarker = result.capabilities.pqTypedDestinationMarker;
  }
  byId("pq-trusted-policy-status").textContent = state.advancedMPolicy
    ? "Trusted Mode cho phép M đọc toàn bộ workbook export, file/web/database, dùng credential Excel và có thể gây side effect ngoài workbook. Preview chạy trên workbook tạm, không phải sandbox."
    : "Advanced M đang bị khóa vì coordinator không cung cấp Trusted Mode policy hợp lệ.";

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

const FLOW_MAX_ROWS = 100000;
const FLOW_MAX_COLUMNS = 512;
const FLOW_MAX_CELLS = 400000;

function createFlowState(v2Capability = false) {
  return {stage: "new", v2Capability, rootLabel: "", snapshot: null, sources: [], tables: [],
    selectedTableIds: new Set(), csvOptions: [], requiresRename: [], errors: [], warnings: [],
    questions: [], answers: {}, understand: null, branches: [], planningHash: null, draftInputs: null, planningGeneration: 0, planSummary: "", planQuestions: [], planAssumptions: [], busy: false, pendingRequests: [],
    workbookSelections: [], sampleInfo: [], mode: null, nextId: 0,
    delta: null, engine: null, chosenBranch: null, allBlocked: false,
    spec: null, approval: null, approvalConsumed: false, handoffStatus: null,
    workbookSourceSelections: [], applyMessage: "", freshSnapshotHash: null};
}

function createWorkbookRecordState(workbookKey = "") {
  return {workbookKey, loaded: false, busy: false, persistedNode: null, persistedNodeHash: null,
    record: null, node: null, staleCheck: null, reloadRequired: false, message: "Chưa đọc Record trong workbook."};
}

function flowNowIso() { return new Date().toISOString(); }

function isoDateLocal(date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

function flowHeaderCell(value, index) {
  return (value === null || value === undefined ? "" : String(value).trim()) || columnLetter(index);
}

function flowCell(value) {
  if (value === null || value === undefined) return "";
  if (value instanceof Date) return isoDateLocal(value);
  if (typeof value === "boolean") return value ? "TRUE" : "FALSE";
  return String(value);
}

function flowCalendarFormat(format, value) {
  // Read invariant numberFormat, never localized display text. Quoted/escaped
  // literals, alignment/fill characters and elapsed-time tokens aren't dates.
  if (typeof format !== "string" || format.length > 512) {
    throw flowFailure("AF_WORKBOOK_DATE_UNSUPPORTED", "Không đọc được numberFormat có giới hạn để phân biệt ngày và số; chưa nạp nguồn.");
  }
  const sections = [""];
  const elapsedSections = [false];
  let quoted = false, malformed = false, conditional = false;
  for (let index = 0; index < format.length; index += 1) {
    const character = format[index];
    if (character === '"') { quoted = !quoted; continue; }
    if (quoted) continue;
    if (["\\", "_", "*"].includes(character)) { index += 1; continue; }
    if (character === "[") {
      const end = format.indexOf("]", index + 1);
      if (end < 0) { malformed = true; break; }
      const token = format.slice(index + 1, end);
      conditional ||= /^[<>=]/.test(token);
      elapsedSections[sections.length - 1] ||= /^[hms]+$/i.test(token);
      if (!/^(?:\$[^\]]*|Black|Blue|Cyan|Green|Magenta|Red|White|Yellow|Color\d+|[hms]+|[<>=].*)$/i.test(token)) malformed = true;
      index = end; continue;
    }
    if (character === ";") { sections.push(""); elapsedSections.push(false); }
    else sections[sections.length - 1] += character;
  }
  const calendarSection = (text, elapsed) => {
    const tokens = text.toLowerCase().replace(/am\/pm|a\/p/g, "");
    return /[yd]/.test(tokens) || (/m/.test(tokens) && !/[hs]/.test(tokens) && !elapsed);
  };
  // Conditions select sections by predicate rather than the ordinary sign rule.
  // Never guess which conditional calendar section Excel actually displayed.
  if (conditional && sections.some((text, index) => calendarSection(text, elapsedSections[index]))) {
    throw flowFailure("AF_WORKBOOK_DATE_UNSUPPORTED", "Định dạng ngày có điều kiện chưa được hỗ trợ rõ ràng; chọn định dạng ngày chuẩn trước khi đọc nguồn.");
  }
  const selectedSection = value > 0 ? 0 : value < 0 && sections.length > 1 ? 1 : value === 0 && sections.length > 2 ? 2 : 0;
  const elapsed = elapsedSections[selectedSection];
  const section = sections[selectedSection].toLowerCase();
  const stripped = section.replace(/am\/pm|a\/p/g, "");
  const calendar = calendarSection(section, elapsed);
  if (!calendar) return null;
  const excessiveToken = (stripped.match(/y+|m+|d+|h+|s+/g) || []).some((token) =>
    token.length > ({y: 4, m: 5, d: 4, h: 2, s: 2}[token[0]]));
  if (quoted || malformed || conditional || elapsed || excessiveToken || sections.length > 4 || /[^ymdhs0.,/ :+()\-]/.test(stripped)) {
    throw flowFailure("AF_WORKBOOK_DATE_UNSUPPORTED", "Định dạng ngày workbook chưa được hỗ trợ rõ ràng; chọn định dạng ngày chuẩn trước khi đọc nguồn.");
  }
  return {time: /[hs]/.test(stripped) || /am\/pm|a\/p/.test(section)};
}

function flowWorkbookCell(value, format, epoch) {
  if (typeof value !== "number") return flowCell(value);
  const calendar = flowCalendarFormat(format, value);
  if (!calendar) return flowCell(value);
  if (![1900, 1904].includes(epoch) || !Number.isFinite(value) || value < (epoch === 1900 ? 1 : 0)
      || value >= (epoch === 1900 ? 2958466 : 2957004) || (epoch === 1900 && Math.floor(value) === 60)) {
    throw flowFailure("AF_WORKBOOK_DATE_UNSUPPORTED", "Không xác định được ngày Excel an toàn (hệ ngày, serial 60 hoặc giá trị ngoài phạm vi); chưa nạp nguồn.");
  }
  let day = Math.floor(value);
  // Excel serial doubles have no timezone. Round at microsecond precision
  // (within their floating-point resolution for modern dates); don't truncate
  // fractional days or attach a fabricated UTC/local timezone.
  const exactMicros = (value - day) * 86400000000;
  let micros = Math.round(exactMicros);
  if (Math.abs(micros - exactMicros) > Math.max(0.00001, Math.abs(value) * Number.EPSILON * 86400000000)) {
    throw flowFailure("AF_WORKBOOK_DATE_UNSUPPORTED", "Thời gian ngày Excel cần độ chính xác nhỏ hơn microsecond; chưa nạp nguồn thay vì cắt mất phần thời gian.");
  }
  if (micros === 86400000000) { day += 1; micros = 0; }
  if (epoch === 1900 && day === 60) throw flowFailure("AF_WORKBOOK_DATE_UNSUPPORTED", "Serial ngày giả 29/02/1900 chưa được hỗ trợ.");
  const base = epoch === 1904 ? Date.UTC(1904, 0, 1) : Date.UTC(1899, 11, 31);
  const date = new Date(base + (day - (epoch === 1900 && day > 60 ? 1 : 0)) * 86400000);
  if (!Number.isFinite(date.getTime()) || date.getUTCFullYear() > 9999) throw flowFailure("AF_WORKBOOK_DATE_UNSUPPORTED", "Ngày Excel nằm ngoài phạm vi được hỗ trợ.");
  const dayText = date.toISOString().slice(0, 10);
  if (!micros && !calendar.time) return dayText;
  const hours = Math.floor(micros / 3600000000), minutes = Math.floor(micros / 60000000) % 60;
  const seconds = Math.floor(micros / 1000000) % 60, fraction = micros % 1000000;
  return `${dayText}T${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`
    + (fraction ? "." + String(fraction).padStart(6, "0").replace(/0+$/, "") : "");
}

function flowWorkbookRows(range, epoch, skipHeader = false) {
  return range.values.slice(skipHeader ? 1 : 0).map((row, index) => row.map((value, column) =>
    flowWorkbookCell(value, range.numberFormat?.[index + (skipHeader ? 1 : 0)]?.[column], epoch)));
}

function flowHash(text) {
  let hash = 2166136261;
  for (let index = 0; index < text.length; index += 1) {
    hash = Math.imul(hash ^ text.charCodeAt(index), 16777619) >>> 0;
  }
  return hash;
}

function flowSampleOrdinals(header, rows, totalRows) {
  if (!Number.isInteger(totalRows) || totalRows < 0) throw flowFailure("AF_INGEST_FAILED", "Số dòng nguồn không hợp lệ.");
  if (totalRows <= 20) return Array.from({length: totalRows}, (_, index) => index);
  // Same schema, dimensions and boundary rows always produce the same sample.
  let seed = flowHash(JSON.stringify([header, totalRows, header.length,
    flowHash(JSON.stringify(rows[0])), flowHash(JSON.stringify(rows[totalRows - 1]))])) || 1;
  const offsets = new Set([0, totalRows - 1]);
  while (offsets.size < 20) {
    seed ^= seed << 13;
    seed ^= seed >>> 17;
    seed ^= seed << 5;
    offsets.add(1 + ((seed >>> 0) % (totalRows - 2)));
  }
  return [...offsets].sort((left, right) => left - right);
}

function flowFailure(code, message) { return Object.assign(new Error(message), {code}); }

function flowCheckBounds(selections) {
  let rows = 0;
  let cells = 0;
  for (const selection of selections) {
    if (!Number.isInteger(selection.totalRows) || selection.totalRows < 0
        || !Number.isInteger(selection.totalColumns) || selection.totalColumns < 1) {
      throw flowFailure("AF_INGEST_FAILED", "Kích thước vùng nguồn không hợp lệ.");
    }
    rows += selection.totalRows;
    cells += selection.totalRows * selection.totalColumns;
    if (selection.totalColumns > FLOW_MAX_COLUMNS || rows > FLOW_MAX_ROWS || cells > FLOW_MAX_CELLS) {
      throw flowFailure("AF_INGEST_FAILED", `Nguồn có ${rows} dòng, ${selection.totalColumns} cột, ${cells} ô; giới hạn ${FLOW_MAX_ROWS} dòng, ${FLOW_MAX_COLUMNS} cột và ${FLOW_MAX_CELLS} ô. Hãy chọn ít bảng hoặc vùng nhỏ hơn.`);
    }
  }
}

async function flowReadOpenWorkbook(mode = "compute", selectedKeys = null, metadataOnly = false) {
  if (!["discover", "compute"].includes(mode)) throw flowFailure("INVALID_REQUEST", "Chế độ đọc không hợp lệ.");
  return Excel.run(async (context) => {
    const sheets = context.workbook.worksheets;
    sheets.load("items/name");
    await context.sync();
    for (const sheet of sheets.items) sheet.tables.load("items/name");
    await context.sync();
    const entries = [];
    for (const sheet of sheets.items) {
      if (sheet.tables.items.length) {
        for (const table of sheet.tables.items) {
          const key = JSON.stringify([sheet.name, table.name, true]);
          if (selectedKeys && !selectedKeys.has(key)) continue;
          const body = table.getDataBodyRange();
          const head = table.getHeaderRowRange();
          body.load("rowCount,columnCount");
          head.load("rowIndex,columnIndex");
          entries.push({sheet: sheet.name, name: table.name, key, body, head, table: true});
        }
      } else {
        const key = JSON.stringify([sheet.name, sheet.name, false]);
        if (selectedKeys && !selectedKeys.has(key)) continue;
        const body = sheet.getUsedRangeOrNullObject(true);
        body.load("isNullObject");
        entries.push({sheet: sheet.name, name: sheet.name, key, body, table: false});
      }
    }
    await context.sync();
    for (const entry of entries) {
      if (!entry.table && !entry.body.isNullObject) entry.body.load("rowIndex,columnIndex,rowCount,columnCount");
    }
    await context.sync();
    const available = entries.filter((entry) => !entry.body.isNullObject && (entry.table || entry.body.rowCount > 0));
    for (const entry of available) {
      entry.totalRows = entry.body.rowCount - (entry.table ? 0 : 1);
      entry.totalColumns = entry.body.columnCount;
    }
    if (metadataOnly) return available.map((entry) => ({sheet: entry.sheet, name: entry.name,
      table: entry.table, key: entry.key, totalRows: entry.totalRows, totalColumns: entry.totalColumns}));
    flowCheckBounds(available);
    // Stable ExcelApi 1.2 function evaluation respects this workbook's epoch.
    // No worksheet formula, cell write, preview API or Save is involved.
    const epochProbe = typeof context.workbook.functions?.date === "function" ? context.workbook.functions.date(1904, 1, 1) : null;
    epochProbe?.load("value,error");
    for (const entry of available) {
      const width = entry.totalColumns;
      if (!entry.table) {
        entry.head = entry.body.getCell(0, 0).getResizedRange(0, width - 1);
        entry.head.load("values");
      } else entry.head.load("values");
      if (mode === "compute") {
        entry.body.load("values,numberFormat");
      } else if (entry.totalRows > 0) {
        entry.first = entry.body.getCell(entry.table ? 0 : 1, 0).getResizedRange(0, width - 1);
        entry.last = entry.body.getCell(entry.totalRows - (entry.table ? 1 : 0), 0).getResizedRange(0, width - 1);
        entry.first.load("values,numberFormat");
        entry.last.load("values,numberFormat");
      }
    }
    await context.sync();
    const epoch = !epochProbe?.error && epochProbe?.value === 1462 ? 1900 : !epochProbe?.error && epochProbe?.value === 0 ? 1904 : null;
    for (const entry of available) {
      entry.header = (entry.head.values[0] || []).map(flowHeaderCell);
      if (entry.header.length !== entry.totalColumns) throw flowFailure("AF_INGEST_FAILED", "Header không khớp số cột nguồn.");
      if (mode === "discover") {
        const boundaryRows = [];
        if (entry.totalRows) {
          boundaryRows[0] = flowWorkbookRows(entry.first, epoch)[0];
          boundaryRows[entry.totalRows - 1] = flowWorkbookRows(entry.last, epoch)[0];
        }
        entry.sampleOrdinals = flowSampleOrdinals(entry.header, boundaryRows, entry.totalRows);
        entry.samples = entry.sampleOrdinals.map((offset) => {
          const range = entry.body.getCell(offset + (entry.table ? 0 : 1), 0).getResizedRange(0, entry.totalColumns - 1);
          range.load("values,numberFormat");
          return range;
        });
      }
    }
    if (mode === "discover") await context.sync();
    return available.map((entry) => {
      const rows = (mode === "compute"
        ? flowWorkbookRows(entry.body, epoch, !entry.table)
        : entry.samples.map((range) => flowWorkbookRows(range, epoch)[0]));
      if (rows.some((row) => row.length !== entry.totalColumns)
          || (mode === "compute" && rows.length !== entry.totalRows)) {
        throw flowFailure("AF_INGEST_FAILED", "Dữ liệu thay đổi hoặc số cột không đồng nhất. Hãy đọc lại nguồn.");
      }
      const rowIndex = entry.table ? entry.head.rowIndex : entry.body.rowIndex;
      const columnIndex = entry.table ? entry.head.columnIndex : entry.body.columnIndex;
      return {sheet: entry.sheet, name: entry.name, table: entry.table, key: entry.key,
        header: entry.header, rows, totalRows: entry.totalRows, totalColumns: entry.header.length,
        sampleOrdinals: mode === "discover" ? entry.sampleOrdinals : Array.from({length: entry.totalRows}, (_, index) => index),
        origin: `Workbook!${entry.sheet}!${entry.name}`,
        range: `${columnLetter(columnIndex)}${rowIndex + 1}:${columnLetter(columnIndex + entry.totalColumns - 1)}${rowIndex + entry.totalRows + 1}`};
    });
  });
}

function flowSetHidden(id, hidden) { byId(id)?.classList?.toggle("hidden", hidden); }

function flowCapabilityAvailable() { return state.flow.v2Capability === true; }

function resetFlowView(message = "", {explicit = false} = {}) {
  const previous = state.flow;
  state.flow = createFlowState(previous?.v2Capability === true);
  if (!explicit && previous?.approvalConsumed) Object.assign(state.flow, {approvalConsumed: true, handoffStatus: previous.handoffStatus, applyMessage: previous.applyMessage, spec: previous.spec, stage: previous.stage});
  const disclosure = byId("flow-disclosure");
  if (disclosure) disclosure.checked = false;
  renderFlow();
  if (message && byId("flow-source-status")) byId("flow-source-status").textContent = message;
}

function flowBinding() {
  return {flow: state.flow, session: state.sessionId, token: state.token,
    workbook: state.workbook ? workbookIdentity(state.workbook) : ""};
}

function flowAssertCurrent(binding) {
  if (binding.flow !== state.flow || binding.session !== state.sessionId || binding.token !== state.token
      || binding.workbook !== (state.workbook ? workbookIdentity(state.workbook) : "")) {
    throw flowFailure("AF_SPEC_STALE", "Phiên hoặc workbook đã đổi. Hãy nạp lại nguồn trước khi tiếp tục.");
  }
}

async function flowAction(action) {
  if (!flowCapabilityAvailable() || state.flow.busy) return;
  const binding = flowBinding();
  binding.flow.busy = true;
  updateFlowButtons();
  try { return await action(binding); }
  catch (error) {
    if (state.flow === binding.flow) {
      if (error.code === "AF_SPEC_STALE" && !error.preserveFlow) resetFlowView(error.message);
      showError(error.code || "AF_INGEST_FAILED", error.message);
    }
    return null;
  } finally {
    binding.flow.busy = false;
    if (state.flow === binding.flow) renderFlow();
  }
}

function flowAccept(result) {
  const flow = state.flow;
  for (const name of ["stage", "mode", "rootLabel", "snapshot", "sources", "tables", "csvOptions", "requiresRename", "errors", "warnings", "questions", "sampleInfo", "understand", "branches", "planningHash", "draftInputs", "planSummary", "planQuestions", "planAssumptions", "delta", "engine", "chosenBranch", "allBlocked", "spec", "approval", "approvalConsumed", "handoffStatus", "workbookSourceSelections"]) {
    if (Object.prototype.hasOwnProperty.call(result, name)) flow[name] = result[name];
  }
}

async function flowBindRoot() {
  return flowAction(async (binding) => {
    const root = (byId("flow-root-input")?.value || "").trim();
    binding.flow.snapshot = null;
    binding.flow.understand = null;
    binding.flow.rootLabel = "";
    const result = await api("/api/assistant/session", {root});
    flowAssertCurrent(binding);
    const capability = state.flow.v2Capability;
    state.flow = createFlowState(capability);
    flowAccept(result);
    renderFlow();
    return result;
  });
}

function flowAddFile(kind) {
  if (!flowCapabilityAvailable() || state.flow.busy || !state.flow.rootLabel) return;
  const path = (byId("flow-path-input")?.value || "").trim();
  if (!path) return showError("INVALID_REQUEST", "Nhập đường dẫn nguồn đã lưu.");
  const request = {kind, path, options: {}};
  if (kind === "xlsx") {
    const sheet = (byId("flow-sheet-input")?.value || "").trim();
    const table = (byId("flow-table-input")?.value || "").trim();
    if (sheet) request.options.sheet = sheet;
    if (table) request.options.table = table;
  }
  if (kind === "folder") request.options.pattern = (byId("flow-pattern-input")?.value || "*.csv").trim();
  const id = `file_${++state.flow.nextId}`;
  state.flow.pendingRequests.push({id, request});
  flowInvalidatePlans();
  state.flow.selectedTableIds.add(id);
  state.flow.snapshot = null;
  state.flow.understand = null;
  state.flow.questions = [];
  state.flow.stage = "new";
  renderFlow();
}

async function flowPreparedWorkbookSources(review, mode = "compute") {
  if (!review?.sources?.length || typeof review.validate !== "function")
    throw flowFailure("DP_REVIEW_STALE", "Duyệt dữ liệu workbook trước khi mở đề bài.");
  const fresh = await review.validate();
  if (fresh.observedHash !== review.observedHash)
    throw flowFailure("DP_SOURCE_STALE", "Dữ liệu đã duyệt đã thay đổi. Hãy quét và duyệt lại.");
  const selections = fresh.sources.map(source => {
    const sheet = fresh.sourceLabels[source.sourceId];
    if (!sheet || !source.sheetId) throw flowFailure("DP_SOURCE_STALE", "Không xác minh được danh tính sheet đã duyệt.");
    const header = source.headers.map(flowHeaderCell), totalRows = source.rows.length, totalColumns = header.length;
    const rows = source.rows.map((row, r) => row.map((value, c) => flowWorkbookCell(value, source.numberFormats?.[r]?.[c], Number(source.dateSystem))));
    const sampleOrdinals = mode === "discover" ? flowSampleOrdinals(header, rows, totalRows) : rows.map((_, r) => r);
    const key = JSON.stringify([source.sheetId, source.sourceId, false]);
    return {sheet, name: sheet, table: false, key, header, rows: sampleOrdinals.map(r => rows[r]), totalRows, totalColumns, sampleOrdinals,
      origin: `Workbook!${sheet}!${sheet}`,
      range: `${columnLetter(source.columnOffset)}${source.rowOffset}:${columnLetter(source.columnOffset + totalColumns - 1)}${source.rowOffset + totalRows}`};
  });
  flowCheckBounds(selections);
  return selections;
}

async function preparationBusinessHandoff(review) {
  if (!state.officeReady || !flowCapabilityAvailable() || state.flow.busy)
    throw flowFailure("COORDINATOR_BUSY", "Chờ Excel và phiên hiện tại sẵn sàng.");
  const binding = flowBinding();
  flowInvalidateSourceAuthority(binding.flow);
  binding.flow.preparationReview = null;
  binding.flow.busy = true;
  try {
    const sources = await flowPreparedWorkbookSources(review, "discover");
    flowAssertCurrent(binding);
    await api("/api/assistant/session", {sourceMode: "workbook"});
    flowAssertCurrent(binding);
    await review.validate();
    flowAssertCurrent(binding);
    const result = await api("/api/assistant/ingest", {requests: sources.map(({key, ...payload}) => ({kind: "workbook", mode: "discover", payload}))});
    flowAssertCurrent(binding);
    await review.validate();
    flowAssertCurrent(binding);
    if (!result.snapshot || result.stage === "ingest_blocked") throw flowFailure("AF_INGEST_FAILED", "Kiểm tra dữ liệu nguồn trước khi phân tích.");
    binding.flow.pendingRequests = [];
    binding.flow.workbookSelections = sources.map(source => ({...source, request: {name: source.name}}));
    binding.flow.selectedTableIds = new Set(sources.map(source => source.key));
    binding.flow.answers = {};
    flowAccept(result);
    binding.flow.preparationReview = review;
    return result;
  } catch (error) {
    flowInvalidateSourceAuthority(binding.flow);
    throw error;
  } finally {
    binding.flow.busy = false;
    if (state.flow === binding.flow) renderFlow();
  }
}

async function flowAddOpenWorkbook() {
  return flowAction(async (binding) => {
    if (!state.officeReady || !state.flow.rootLabel) throw flowFailure("OFFICE_NOT_READY", "Gắn thư mục và chờ Excel sẵn sàng trước khi đọc.");
    const selections = await flowReadOpenWorkbook("discover", null, true);
    flowAssertCurrent(binding);
    state.flow.workbookSelections = selections.map((selection) => ({...selection, request: {name: selection.name}}));
    flowInvalidatePlans();
    for (const selection of selections) state.flow.selectedTableIds.add(selection.key);
    state.flow.snapshot = null;
    state.flow.understand = null;
    state.flow.questions = [];
    state.flow.stage = "new";
    return selections;
  });
}

async function flowIngest(mode, source = null) {
  return flowAction(async (binding) => {
    if (!["discover", "compute"].includes(mode) || !state.flow.rootLabel) throw flowFailure("INVALID_REQUEST", "Gắn thư mục trước khi nạp nguồn.");
    const flow = state.flow;
    let requests = source ? [source] : flow.pendingRequests.filter((item) => flow.selectedTableIds.has(item.id)).map((item) => item.request);
    const selected = new Set(flow.workbookSelections.filter((item) => flow.selectedTableIds.has(item.key)).map((item) => item.key));
    if (!source && selected.size) {
      let selections;
      try {
        selections = flow.preparationReview
          ? (await flowPreparedWorkbookSources(flow.preparationReview, mode)).filter(item => selected.has(item.key))
          : await flowReadOpenWorkbook(mode, selected);
      } catch (error) { if (flow.preparationReview) flowInvalidateSourceAuthority(flow); throw error; }
      flowAssertCurrent(binding);
      if (selections.length !== selected.size) throw flowFailure("AF_SPEC_STALE", "Bảng đã chọn không còn trong workbook. Hãy thêm workbook lại.");
      flowCheckBounds(selections);
      requests = [...requests, ...selections.map((selection) => {
        const {key, ...payload} = selection;
        payload.name = flow.workbookSelections.find((item) => item.key === key)?.request.name || payload.name;
        return {kind: "workbook", payload};
      })];
    }
    if (!requests.length) throw flowFailure("AF_INGEST_FAILED", "Chọn ít nhất một nguồn trong danh sách.");
    flowCheckBounds(requests.filter((request) => request.kind === "workbook").map((request) => request.payload));
    requests = requests.map((request) => ({...request, mode}));
    flow.snapshot = null;
    flow.freshSnapshotHash = null;
    flow.understand = null;
    flow.questions = [];
    flow.stage = "new";
    const expectedPlanningHash = mode === "compute" ? flow.planningHash : null;
    const planningGeneration = flow.planningGeneration;
    flow.branches = [];
    flow.planningHash = null;
    const result = await api("/api/assistant/ingest", {requests, ...(expectedPlanningHash ? {expectedPlanningHash} : {})});
    flowAssertCurrent(binding);
    if (flow.preparationReview) {
      try { await flow.preparationReview.validate(); flowAssertCurrent(binding); }
      catch (error) { flowInvalidateSourceAuthority(flow); throw error; }
    }
    if (expectedPlanningHash && planningGeneration !== flow.planningGeneration) {
      throw flowFailure("AF_SPEC_STALE", "Đề bài hoặc câu trả lời đã đổi trong lúc đọc toàn bộ; hãy tạo kế hoạch lại.");
    }
    flow.understand = null;
    flow.questions = [];
    flow.answers = {};
    if (byId("flow-disclosure")) byId("flow-disclosure").checked = false;
    flowAccept(result);
    flow.freshSnapshotHash = mode === "compute" && result.snapshot ? result.snapshot.snapshotHash : null;
    flow.spec = flow.approval = null;
    flow.approvalConsumed = false;
    flow.handoffStatus = null;
    flow.applyMessage = "";
    return result;
  });
}

function flowInvalidateSourceAuthority(flow) {
  flow.snapshot = flow.understand = flow.planningHash = flow.draftInputs = flow.freshSnapshotHash = null;
  flow.branches = []; flow.questions = []; flow.delta = flow.engine = flow.chosenBranch = null;
  flow.planSummary = ""; flow.planQuestions = []; flow.planAssumptions = []; flow.allBlocked = false;
  flow.planningGeneration += 1;
  if (!flow.approvalConsumed) { flow.spec = flow.approval = null; flow.stage = "new"; }
  if (byId("flow-approve-check")) byId("flow-approve-check").checked = false;
}

async function flowUnderstand() {
  return flowAction(async (binding) => {
    const flow = binding.flow;
    if (!flow.snapshot || flow.stage === "ingest_blocked" || !(byId("prompt")?.value || "").trim()) return;
    if (flow.workbookSourceSelections?.length) {
      let fresh;
      try { fresh = await flowFreshWorkbookSources(flow); }
      catch (error) {
        flowAssertCurrent(binding); flowInvalidateSourceAuthority(flow);
        const failure = flowFailure(error.code === "AF_SPEC_STALE" ? "AF_SPEC_STALE" : "OFFICE_READ_FAILED", error.message);
        failure.preserveFlow = true; throw failure;
      }
      flowAssertCurrent(binding);
      for (const request of fresh) {
        const payload = request.payload;
        const bound = flow.snapshot.tables?.find((table) => table.name === (request.name || payload.name));
        const ordinals = flow.mode === "discover" ? bound?.sampleOrdinals : payload.sampleOrdinals;
        const rows = flow.mode === "discover" ? ordinals?.map((ordinal) => payload.rows[ordinal]) : payload.rows;
        const hash = bound && ordinals && rows?.every((row) => Array.isArray(row)) ? await flowDigest({header: payload.header,
          rows, mode: flow.mode, totalRows: payload.totalRows, sampleOrdinals: ordinals}) : null;
        flowAssertCurrent(binding);
        if (!bound || hash !== bound.contentHash) {
          flowInvalidateSourceAuthority(flow);
          const error = flowFailure("AF_SPEC_STALE", "Nguồn workbook khác snapshot đã nạp. Hãy nạp lại nguồn trước khi phân tích.");
          error.preserveFlow = true; throw error;
        }
      }
    }
    const result = await api("/api/assistant/understand", {});
    flowAssertCurrent(binding); flowAccept(result);
    return result;
  });
}

function bindFlowPromptShortcut() {
  byId("prompt")?.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || !event.ctrlKey || event.altKey || event.metaKey || event.shiftKey || event.isComposing || event.repeat) return;
    const button = byId("flow-analyze-button");
    if (!button || button.disabled) return;
    event.preventDefault(); button.click();
  });
}

function setExportProgress(message) {
  const target = byId(state.activeTab === "pq" ? (state.pqMode === "advanced" ? "pq-progress" : "pq2-progress") : "flow-apply-status");
  if (target) target.textContent = message;
}

async function flowPlanDraft() {
  return flowAction(async (binding) => {
    const flow = binding.flow;
    const prompt = (byId("prompt")?.value || "").trim();
    if (!flow.understand || !["understood", "planning", "branched"].includes(flow.stage) || !prompt) return;
    if (byId("flow-disclosure")?.checked !== true) throw flowFailure("AF_DISCLOSURE_REQUIRED", "Đồng ý gửi mẫu tới Codex trước khi tạo kế hoạch.");
    const answers = Object.keys(flow.answers).sort().filter((questionId) => String(flow.answers[questionId]).trim())
      .map((questionId) => ({questionId, answer: flow.answers[questionId]}));
    const answerBinding = JSON.stringify(answers);
    const result = await api("/api/assistant/plan-draft", {prompt, answers, acknowledged: true});
    flowAssertCurrent(binding);
    const currentAnswers = Object.keys(flow.answers).sort().filter((questionId) => String(flow.answers[questionId]).trim())
      .map((questionId) => ({questionId, answer: flow.answers[questionId]}));
    if (prompt !== (byId("prompt")?.value || "").trim() || answerBinding !== JSON.stringify(currentAnswers)
        || byId("flow-disclosure")?.checked !== true) {
      throw flowFailure("AF_SPEC_STALE", "Đề bài, câu trả lời hoặc đồng ý đã đổi. Hãy rà soát và tạo kế hoạch lại.");
    }
    flow.branches = result.branches || [];
    flow.planningHash = result.planningHash || null;
    flow.draftInputs = result.draftInputs || null;
    flow.planSummary = result.summary || "";
    flow.planQuestions = result.questions || [];
    flow.planAssumptions = result.assumptions || [];
    flow.delta = flow.engine = flow.chosenBranch = null;
    flow.allBlocked = false;
    flow.stage = result.stage;
    return result;
  });
}

function flowInvalidatePlans() {
  state.flow.freshSnapshotHash = null;
  state.flow.planningGeneration += 1;
  state.flow.branches = [];
  state.flow.planningHash = null;
  state.flow.draftInputs = null;
  state.flow.delta = state.flow.engine = state.flow.chosenBranch = null;
  state.flow.allBlocked = false;
  if (!state.flow.approvalConsumed) {
    state.flow.spec = state.flow.approval = null;
    if (["frozen", "approved"].includes(state.flow.stage)) state.flow.stage = "understood";
  }
  if (byId("flow-approve-check")) byId("flow-approve-check").checked = false;
  state.flow.planSummary = "";
  state.flow.planQuestions = [];
  state.flow.planAssumptions = [];
  if (["planning", "branching", "branched"].includes(state.flow.stage)) state.flow.stage = "understood";
  if (byId("flow-disclosure")) byId("flow-disclosure").checked = false;
  renderFlowBranches();
  updateFlowButtons();
}

async function flowExecuteBranches() {
  return flowAction(async (binding) => {
    const flow = binding.flow;
    if (flow.mode !== "compute") throw flowFailure("AF_SAMPLE_ONLY", "Chọn Đọc toàn bộ để tính trước khi chạy A/B.");
    if (!["planning", "branched"].includes(flow.stage) || !flow.planningHash) return;
    const planningHash = flow.planningHash;
    const generation = flow.planningGeneration;
    const prompt = (byId("prompt")?.value || "").trim();
    const answers = JSON.stringify(flow.answers);
    const previousStage = flow.stage;
    flow.stage = "branching";
    renderFlowBranches();
    updateFlowButtons();
    let result;
    try { result = await api("/api/assistant/branches", {expectedPlanningHash: planningHash}); }
    catch (error) {
      if (generation === flow.planningGeneration && flow.planningHash === planningHash) flow.stage = previousStage;
      throw error;
    }
    flowAssertCurrent(binding);
    if (generation !== flow.planningGeneration || flow.planningHash !== planningHash
        || result.planningHash !== planningHash || prompt !== (byId("prompt")?.value || "").trim()
        || answers !== JSON.stringify(flow.answers)) {
      throw flowFailure("AF_SPEC_STALE", "Đề bài, câu trả lời hoặc kế hoạch đã đổi trong lúc tính A/B.");
    }
    flowAccept(result);
    flow.chosenBranch = null;
    return result;
  });
}

async function flowDigest(value) {
  const cryptoApi = globalThis.crypto || window.crypto;
  if (!cryptoApi?.subtle) throw flowFailure("AF_WRITE_PARTIAL", "WebCrypto chưa sẵn sàng để kiểm tra read-back; chưa ghi workbook.");
  const digest = await cryptoApi.subtle.digest("SHA-256", new TextEncoder().encode(canonicalProblemChainJson(value)));
  return "sha256:" + Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function flowCurrentWorkbookIdentity() {
  const expected = state.workbook;
  if (!expected || !state.officeReady) throw flowFailure("ASSISTANT_WORKBOOK_REQUIRED", "Đọc workbook đang mở trước khi chốt hoặc ghi.");
  const name = await Excel.run(async (context) => {
    context.workbook.load("name");
    await context.sync();
    return context.workbook.name;
  });
  const url = officeDocumentUrl();
  if (name !== expected.name || url !== expected.url) throw flowFailure("AF_SPEC_STALE", "Workbook đang mở đã đổi; hãy nạp lại nguồn.");
  return {name, documentHash: await flowDigest(url)};
}

async function flowFreshWorkbookSources(flow) {
  if (flow.preparationReview) {
    const full = await flowPreparedWorkbookSources(flow.preparationReview, "compute");
    return full.filter(item => flow.selectedTableIds.has(item.key)).map(({key, ...payload}) => {
      const selection = (flow.workbookSourceSelections || []).find(item => item.origin === payload.origin && item.table === false);
      if (selection) payload.name = selection.name;
      return {kind: "workbook", mode: "compute", payload, ...(selection?.alias ? {name: selection.alias} : {})};
    });
  }
  const selections = flow.workbookSourceSelections || [];
  if (!selections.length) return [];
  const metadata = await flowReadOpenWorkbook("compute", null, true);
  const selected = metadata.filter((entry) => selections.some((selection) =>
    selection.origin === `Workbook!${entry.sheet}!${entry.name}` && selection.table === entry.table));
  if (selected.length !== selections.length) throw flowFailure("AF_SPEC_STALE", "Một nguồn workbook đã đổi tên hoặc không còn tồn tại.");
  const full = await flowReadOpenWorkbook("compute", new Set(selected.map((entry) => entry.key)));
  return full.map((entry) => {
    const selection = selections.find((item) => item.origin === entry.origin && item.table === entry.table);
    if (!selection) throw flowFailure("AF_SPEC_STALE", "Danh sách nguồn workbook đã đổi.");
    const {key, ...payload} = entry;
    payload.name = selection.name;
    return {kind: "workbook", mode: "compute", payload, ...(selection.alias ? {name: selection.alias} : {})};
  });
}

function flowReviewedSpec(spec) {
  return {expectedSpecFingerprint: spec.fingerprint, expectedPreviewHash: spec.previewHash, expectedResultDigest: spec.resultDigest};
}

async function flowFreeze() {
  return flowAction(async (binding) => {
    const flow = binding.flow;
    const branch = flow.branches.find((item) => item.id === flow.chosenBranch);
    if (!branch?.selectable || flow.approvalConsumed) return;
    const generation = flow.planningGeneration;
    const workbookIdentity = await flowCurrentWorkbookIdentity();
    flowAssertCurrent(binding);
    if (generation !== flow.planningGeneration) throw flowFailure("AF_SPEC_STALE", "Kế hoạch đã đổi trước khi chốt.");
    const result = await api("/api/assistant/freeze", {branchId: branch.id, createdAt: flowNowIso(), workbookIdentity,
      acknowledgeMissingControl: byId("flow-control-ack")?.checked === true,
      expectedPlanningHash: flow.planningHash, expectedPreviewHash: branch.previewHash, expectedResultDigest: branch.resultDigest});
    flowAssertCurrent(binding);
    if (generation !== flow.planningGeneration) throw flowFailure("AF_SPEC_STALE", "Đề bài đã đổi trong khi chốt; chưa duyệt ghi.");
    flowAccept(result);
    flow.approval = null;
    if (byId("flow-approve-check")) byId("flow-approve-check").checked = false;
    return result;
  });
}

async function flowApprove() {
  return flowAction(async (binding) => {
    const flow = binding.flow, spec = flow.spec;
    if (!spec || flow.approvalConsumed || byId("flow-approve-check")?.checked !== true) return;
    const workbookIdentity = await flowCurrentWorkbookIdentity();
    const workbookSources = await flowFreshWorkbookSources(flow);
    flowAssertCurrent(binding);
    if (flow.spec !== spec || byId("flow-approve-check")?.checked !== true) throw flowFailure("AF_SPEC_STALE", "Spec hoặc xác nhận duyệt đã đổi.");
    const result = await api("/api/assistant/approvals", {approvedAt: flowNowIso(), acknowledged: true,
      workbookIdentity, workbookSources, ...flowReviewedSpec(spec)});
    flowAssertCurrent(binding);
    if (flow.spec !== spec || byId("flow-approve-check")?.checked !== true) throw flowFailure("AF_SPEC_STALE", "Xác nhận duyệt đã đổi trong khi xử lý.");
    flowAccept(result);
    return result;
  });
}

async function flowWriteResult(handoff, expectedWorkbook) {
  const {columns, rows} = handoff.result;
  if (!Array.isArray(columns) || !columns.length || !Array.isArray(rows) || (rows.length + 1) * columns.length > FLOW_MAX_CELLS
      || handoff.result.truncated !== false || rows.some((row) => !Array.isArray(row) || row.length !== columns.length)) {
    throw flowFailure("AF_WRITE_PARTIAL", "Kết quả bàn giao không đầy đủ hoặc vượt giới hạn ghi.");
  }
  if (await flowDigest({columns, rows}) !== handoff.resultDigest) throw flowFailure("AF_WRITE_PARTIAL", "Digest bàn giao không khớp; chưa ghi worksheet.");
  return Excel.run(async (context) => {
    const workbook = context.workbook;
    workbook.load("name");
    workbook.worksheets.load("items/name");
    await context.sync();
    if (workbook.name !== expectedWorkbook.name || officeDocumentUrl() !== expectedWorkbook.url) throw flowFailure("AF_WRITE_PARTIAL", "Workbook đã đổi sau khi bàn giao; chưa ghi kết quả.");
    const target = handoff.apply.target.sheet;
    if (workbook.worksheets.items.some((sheet) => sheet.name.toLocaleLowerCase() === target.toLocaleLowerCase())) throw flowFailure("AF_WRITE_PARTIAL", "Sheet đích đã tồn tại; không ghi đè.");
    const sheet = workbook.worksheets.add(target);
    await context.sync();
    const matrix = [columns.map((column) => column.name), ...rows.map((row) => row.map((value) => value === null ? "" : value))];
    const batchSize = Math.max(1, Math.floor(10000 / columns.length));
    for (let start = 0; start < matrix.length; start += batchSize) {
      const chunk = matrix.slice(start, start + batchSize);
      const range = sheet.getRangeByIndexes(start, 0, chunk.length, columns.length);
      range.numberFormat = chunk.map((row) => row.map(() => "@"));
      await context.sync();
      range.values = chunk;
      await context.sync();
    }
    const markerRange = sheet.getRangeByIndexes(rows.length + 2, 0, 1, 1);
    markerRange.numberFormat = [["@"]];
    await context.sync();
    markerRange.values = [[handoff.marker]];
    await context.sync();
    const readback = sheet.getRangeByIndexes(0, 0, matrix.length, columns.length);
    readback.load("values,formulas");
    markerRange.load("values,formulas");
    await context.sync();
    if (readback.values.length !== matrix.length || readback.values.some((row) => row.length !== columns.length)
        || canonicalProblemChainJson(readback.values[0]) !== canonicalProblemChainJson(matrix[0])
        || markerRange.values?.[0]?.[0] !== handoff.marker) throw flowFailure("AF_WRITE_PARTIAL", "Header, kích thước hoặc marker đọc lại không khớp.");
    // Excel represents null cells as empty strings. Recover null only after
    // independently checking that the actual cell is empty; every other value
    // must be exactly equal, including all decimal digits and literal strings.
    const actualRows = readback.values.slice(1).map((row, index) => row.map((value, column) =>
      rows[index][column] === null && value === "" ? null : value));
    if (canonicalProblemChainJson(actualRows) !== canonicalProblemChainJson(rows)
        || await flowDigest({columns, rows: actualRows}) !== handoff.resultDigest) throw flowFailure("AF_WRITE_PARTIAL", "Dữ liệu đọc lại khác kết quả đã chốt.");
    // formulas echoes literal values too, so use the formula-local API only
    // through getSpecialCellsOrNullObject, which distinguishes literal '=...'.
    if (typeof readback.getSpecialCellsOrNullObject !== "function") throw flowFailure("AF_WRITE_PARTIAL", "Excel chưa hỗ trợ kiểm ô formula sau ghi.");
    const formulas = readback.getSpecialCellsOrNullObject("Formulas");
    const markerFormulas = markerRange.getSpecialCellsOrNullObject("Formulas");
    formulas.load("isNullObject"); markerFormulas.load("isNullObject");
    await context.sync();
    if (!formulas.isNullObject || !markerFormulas.isNullObject) throw flowFailure("AF_WRITE_PARTIAL", "Sheet kết quả có formula ngoài hợp đồng values-only.");
    return {...handoff.receiptBinding, verified: true};
  });
}

async function flowApply() {
  return flowAction(async (binding) => {
    const flow = binding.flow, spec = flow.spec;
    if (!spec || flow.stage !== "approved" || flow.approvalConsumed || byId("flow-approve-check")?.checked !== true) return;
    let requested = false, handoff = null;
    try {
      if (!window.Office || !Office.context.requirements.isSetSupported("ExcelApi", "1.9")) throw flowFailure("AF_WRITE_PARTIAL", "Excel chưa hỗ trợ đầy đủ ghi và kiểm tra values-only (ExcelApi 1.9); chưa ghi workbook.");
      const expectedWorkbook = {name: state.workbook.name, url: state.workbook.url};
      const workbookIdentity = await flowCurrentWorkbookIdentity();
      const workbookBase64 = await exportWorkbookBase64();
      const workbookSources = await flowFreshWorkbookSources(flow);
      flowAssertCurrent(binding);
      if (flow.spec !== spec) throw flowFailure("AF_SPEC_STALE", "Spec đã đổi trước khi gửi ghi.");
      await flowCurrentWorkbookIdentity();
      // A lost response may already have consumed the capability. Disable
      // repeat attempts before the request; only an explicit false can undo it.
      requested = true;
      flow.approvalConsumed = true;
      handoff = await api("/api/assistant/apply", {workbookBase64, appliedAt: flowNowIso(), workbookIdentity,
        workbookSources, ...flowReviewedSpec(spec)}, {preserveConsumedState: true});
      flowAssertCurrent(binding);
      flow.stage = "handoff";
      flow.handoffStatus = "partial-unknown";
      if (flow.spec !== spec) throw flowFailure("AF_WRITE_PARTIAL", "Spec đã đổi sau khi bàn giao; không ghi.");
      if (handoff.stage !== "handoff" || handoff.resultDigest !== spec.resultDigest || handoff.apply?.target?.sheet !== spec.target.sheet
          || handoff.receiptBinding?.specFingerprint !== spec.fingerprint || handoff.receiptBinding?.previewHash !== spec.previewHash
          || handoff.receiptBinding?.resultDigest !== spec.resultDigest || handoff.receiptBinding?.sheet !== spec.target.sheet
          || handoff.receiptBinding?.marker !== handoff.marker || handoff.receiptBinding?.rowCount !== handoff.result?.rows?.length
          || handoff.receiptBinding?.columnCount !== handoff.result?.columns?.length) throw flowFailure("AF_WRITE_PARTIAL", "Bàn giao không khớp revision Spec được duyệt; không ghi.");
      await flowCurrentWorkbookIdentity();
      const freshSources = await flowFreshWorkbookSources(flow);
      if (canonicalProblemChainJson(freshSources) !== canonicalProblemChainJson(workbookSources)) throw flowFailure("AF_WRITE_PARTIAL", "Nguồn workbook đổi trong lúc bàn giao; không ghi kết quả.");
      const receipt = await flowWriteResult(handoff, expectedWorkbook);
      flowAssertCurrent(binding);
      const afterSources = await flowFreshWorkbookSources(flow);
      if (canonicalProblemChainJson(afterSources) !== canonicalProblemChainJson(workbookSources)) throw flowFailure("AF_WRITE_PARTIAL", "Nguồn workbook đổi trong lúc ghi; kết quả chưa được xác nhận.");
      const result = await api("/api/assistant/apply", {receipt, appliedAt: flowNowIso()}, {preserveConsumedState: true});
      flowAssertCurrent(binding);
      flowAccept(result);
      flow.handoffStatus = "readback-verified";
      flow.applyMessage = "Đã ghi sheet mới và đọc lại toàn bộ kết quả khớp digest. Workbook chưa lưu. Số Decimal được giữ dạng văn bản để bảo toàn độ chính xác.";
      return result;
    } catch (error) {
      const consumed = requested && error.approvalConsumed !== false;
      if (state.flow === flow) {
        flow.approvalConsumed = consumed;
        if (consumed) {
          flow.stage = "partial";
          flow.handoffStatus = "partial-unknown";
          flow.applyMessage = "Quyền ghi đã hoặc có thể đã dùng. Workbook có thể được ghi một phần; trạng thái chưa biết, không tự thử lại. Workbook chưa lưu.";
          if (handoff?.receiptBinding) {
            try { await api("/api/assistant/apply", {receipt: {...handoff.receiptBinding, verified: false}, appliedAt: flowNowIso()}, {preserveConsumedState: true}); } catch (_) { /* State is conservatively partial even if reporting fails. */ }
          }
        } else flow.applyMessage = "Chưa ghi kết quả; quyền ghi chưa tiêu thụ. " + error.message;
        showError(consumed ? "AF_WRITE_PARTIAL" : error.code || "AF_WRITE_PARTIAL", error.message);
      }
      return null;
    }
  });
}

async function flowLoadState() {
  return flowAction(async (binding) => {
    binding.flow.freshSnapshotHash = null;
    const generation = binding.flow.planningGeneration;
    const result = await api("/api/assistant/state", {});
    flowAssertCurrent(binding);
    if (result.planningHash) {
      const inputs = result.draftInputs;
      const prompt = (byId("prompt")?.value || "").trim();
      const answers = Object.keys(state.flow.answers).sort().filter((id) => String(state.flow.answers[id]).trim())
        .map((questionId) => ({questionId, answer: state.flow.answers[questionId]}));
      if (inputs && !prompt && !answers.length && !state.flow.snapshot && generation === state.flow.planningGeneration) {
        byId("prompt").value = inputs.prompt;
        state.flow.answers = Object.fromEntries((inputs.answers || []).map((answer) => [answer.questionId, answer.answer]));
      } else if (!inputs || prompt !== inputs.prompt || JSON.stringify(answers) !== JSON.stringify(inputs.answers)
          || generation !== state.flow.planningGeneration) {
        result.branches = [];
        result.planningHash = null;
        result.draftInputs = null;
        result.stage = result.understand ? "understood" : "ingested";
      }
    }
    flowAccept(result);
    if (result.record && result.node && result.spec) {
      const identity = await flowCurrentWorkbookIdentity();
      flowAssertCurrent(binding);
      if (canonicalProblemChainJson(identity) === canonicalProblemChainJson(result.spec.workbookIdentity)
          && result.record.hash === result.node.recordHash && await flowRecordHelper().verifyAssistantRecordHash(result.node)) {
        const basis = Object.fromEntries(result.record.hashBasis.map((key) => [key, result.record[key]]));
        if (await flowDigest(basis) !== result.record.hash) throw flowFailure("AF_RECORD_INVALID", "Hash Record khôi phục không khớp.");
        flowAssertCurrent(binding);
        const key = workbookIdentity(state.workbook);
        if (state.workbookRecord.workbookKey !== key) state.workbookRecord = createWorkbookRecordState(key);
        Object.assign(state.workbookRecord, {record: result.record, node: result.node, staleCheck: result.staleCheck});
      }
    }
    if (result.snapshotHash && !state.flow.snapshot) state.flow.stage = "new";
    return result;
  });
}

async function flowReset() {
  return flowAction(async (binding) => {
    const result = await api("/api/assistant/reset", {});
    flowAssertCurrent(binding);
    resetFlowView("Đã bắt đầu lại. Gắn thư mục và nạp nguồn mới.", {explicit: true});
    return result;
  });
}

function flowRecordHelper() {
  const helper = globalThis.AssistantRecordXml;
  if (!helper) throw flowFailure("AF_RECORD_INVALID", "Chưa tải được helper Record; hãy mở lại pane.");
  return helper;
}

function flowRecordCurrent(recordState) {
  if (state.workbookRecord !== recordState || !state.workbook || recordState.workbookKey !== workbookIdentity(state.workbook)) {
    throw flowFailure("AF_SPEC_STALE", "Workbook đã đổi; đọc Record của workbook hiện tại trước khi lưu.");
  }
}

async function flowReadRecord() {
  if (!state.officeReady || !state.workbook || state.flow.busy || state.workbookRecord.busy) return null;
  const binding = flowBinding();
  const key = workbookIdentity(state.workbook);
  if (state.workbookRecord.workbookKey !== key) state.workbookRecord = createWorkbookRecordState(key);
  const recordState = state.workbookRecord;
  recordState.busy = true;
  updateFlowButtons();
  try {
    if (!state.officeReady || !state.workbook) throw flowFailure("OFFICE_NOT_READY", "Chờ workbook sẵn sàng để đọc Record.");
    await flowCurrentWorkbookIdentity();
    const observed = await flowRecordHelper().readAssistantRecord({name: state.workbook.name, url: state.workbook.url || ""});
    flowAssertCurrent(binding);
    flowRecordCurrent(recordState);
    await flowCurrentWorkbookIdentity();
    recordState.persistedNode = observed;
    recordState.persistedNodeHash = observed?.hash ?? null;
    recordState.loaded = true;
    recordState.reloadRequired = false;
    recordState.message = observed ? `Đã đọc metadata ${observed.id} · ${observed.hash}. Chỉ khôi phục metadata; chưa xác minh Record đầy đủ hoặc nguồn hiện tại.`
      : "Workbook chưa có metadata Record. Workbook chưa lưu.";
    if (observed && recordState.node && observed.hash !== recordState.node.hash) recordState.message +=
      ` Metadata hiện có khác Record chờ lưu ${recordState.node.id} · ${recordState.node.hash}. Bấm Lưu sẽ thay metadata hiện có bằng Record chờ lưu.`;
    renderFlowRecord();
    return observed;
  } catch (error) {
    if (state.workbookRecord === recordState) {
      recordState.loaded = false;
      recordState.reloadRequired = true;
      recordState.message = "Không đọc được metadata Record. " + error.message;
      showError(error.code || "AF_RECORD_INVALID", error.message);
    }
    return null;
  } finally {
    recordState.busy = false;
    renderFlowRecord();
    updateFlowButtons();
  }
}

async function flowCreateRecord() {
  return flowAction(async (binding) => {
    const flow = binding.flow;
    if (!["applied", "recorded"].includes(flow.stage) || flow.handoffStatus !== "readback-verified" || !flow.approvalConsumed || !flow.spec) {
      throw flowFailure("AF_STAGE_INVALID", "Tạo Record sau khi đã ghi và kiểm tra đầy đủ kết quả.");
    }
    const spec = flow.spec;
    const identity = await flowCurrentWorkbookIdentity();
    if (canonicalProblemChainJson(identity) !== canonicalProblemChainJson(spec.workbookIdentity)) throw flowFailure("AF_SPEC_STALE", "Workbook không khớp Spec đã áp dụng.");
    const result = await api("/api/assistant/record", {});
    flowAssertCurrent(binding);
    await flowCurrentWorkbookIdentity();
    if (!result.record || result.recordHash !== result.record.hash || result.node?.recordHash !== result.recordHash
        || result.node.spec !== spec.fingerprint || result.node.snapshot !== spec.snapshotHash
        || !(await flowRecordHelper().verifyAssistantRecordHash(result.node))) throw flowFailure("AF_RECORD_INVALID", "Record hoặc metadata không khớp Spec.");
    const basis = Object.fromEntries(result.record.hashBasis.map((key) => [key, result.record[key]]));
    if (await flowDigest(basis) !== result.recordHash) throw flowFailure("AF_RECORD_INVALID", "Hash Decision Record đầy đủ không khớp.");
    flowAssertCurrent(binding);
    if (flow.spec !== spec) throw flowFailure("AF_SPEC_STALE", "Spec đã đổi trong lúc tạo Record.");
    const key = workbookIdentity(state.workbook);
    if (state.workbookRecord.workbookKey !== key) state.workbookRecord = createWorkbookRecordState(key);
    Object.assign(state.workbookRecord, {record: result.record, node: result.node, staleCheck: result.staleCheck});
    flowAccept(result);
    return result;
  });
}

async function flowPersistRecord() {
  return flowAction(async (binding) => {
    const recordState = state.workbookRecord;
    flowRecordCurrent(recordState);
    if (!recordState.loaded || recordState.reloadRequired || !recordState.node || !recordState.record) throw flowFailure("PQPC_HISTORY_CONFLICT", "Đọc metadata workbook trước khi lưu; sau xung đột phải bấm Đọc lại Record.");
    const identity = await flowCurrentWorkbookIdentity();
    if (recordState.node.spec !== binding.flow.spec?.fingerprint || canonicalProblemChainJson(identity) !== canonicalProblemChainJson(binding.flow.spec?.workbookIdentity)) {
      throw flowFailure("AF_SPEC_STALE", "Record không thuộc Spec của workbook đang mở.");
    }
    flowAssertCurrent(binding);
    flowRecordCurrent(recordState);
    try {
      // Pin the hash observed by Read. Never adopt a newer hash before writing.
      const expectedHash = recordState.persistedNodeHash;
      await flowRecordHelper().writeAssistantRecord(recordState.node, expectedHash, {name: state.workbook.name, url: state.workbook.url || ""});
      flowAssertCurrent(binding);
      flowRecordCurrent(recordState);
      await flowCurrentWorkbookIdentity();
      recordState.persistedNode = recordState.node;
      recordState.persistedNodeHash = recordState.node.hash;
      recordState.message = "Đã ghi và đọc lại metadata trong workbook. Workbook chưa lưu; cần lưu workbook để giữ sau khi đóng.";
      return {written: true, workbookSaved: false};
    } catch (error) {
      recordState.reloadRequired = true;
      recordState.message = error.code === "PQPC_HISTORY_CONFLICT" ? "Record đã đổi. Bấm Đọc lại Record và rà soát trước khi lưu tiếp."
        : "Ghi metadata partial/unknown. Bấm Đọc lại Record trước thao tác tiếp theo; workbook chưa lưu.";
      throw error;
    }
  });
}

function flowDownloadRecord() {
  const record = state.workbookRecord.record;
  if (!record) return;
  const blob = new Blob([JSON.stringify(record, null, 2)], {type: "application/json;charset=utf-8"});
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = record.id + ".json";
  anchor.click();
  URL.revokeObjectURL(url);
}

function renderFlowRecord() {
  const recordState = state.workbookRecord;
  const node = recordState.node || recordState.persistedNode;
  const sameWorkbook = !!state.workbook && recordState.workbookKey === workbookIdentity(state.workbook);
  flowSetHidden("flow-result-section", !node && !["applied", "recorded"].includes(state.flow.stage));
  const set = (id, value) => { if (byId(id)) byId(id).textContent = value; };
  set("flow-record-id", node?.id || "Chưa tạo Record");
  set("flow-record-hash", node?.recordHash || "—");
  set("flow-record-labels", node ? (node.labels.join(", ") || "không có nhãn") : "—");
  set("flow-record-persist", recordState.message);
  set("flow-workbook-saved", "Workbook đã lưu: Chưa. Add-in không gọi Save.");
  const record = recordState.record;
  set("flow-record-delta", record ? `${record.delta.rowsIn} → ${record.delta.rowsOut} dòng · trùng ${record.delta.duplicatesBefore} → ${record.delta.duplicatesAfter} · ${record.delta.changedColumns.length} biến đổi cột`
    : node ? "Chỉ có metadata; Record đầy đủ không nằm trong workbook." : "");
  set("flow-record-null-profile", record ? `Ô trống trước: ${JSON.stringify(record.delta.nullsBefore || {})} · sau: ${JSON.stringify(record.delta.nullsAfter || {})}` : "");
  flowTextList("flow-record-column-changes", record?.delta.changedColumns || []);
  let freshness = "Chưa nạp lại đầy đủ nguồn; độ mới hiện tại: unknown.";
  const fullSnapshot = sameWorkbook && state.flow.mode === "compute" && state.flow.snapshot
    && state.flow.freshSnapshotHash === state.flow.snapshot.snapshotHash;
  const sourceChanged = node && fullSnapshot && state.flow.snapshot.snapshotHash !== node.snapshot;
  if (sourceChanged || recordState.staleCheck?.stale === true) freshness = "STALE · Nguồn đã đổi so với Record. Record lịch sử được giữ nguyên; hãy nạp và tính lại trước khi dùng kết quả.";
  else if (node && fullSnapshot) freshness = "Nguồn đầy đủ vừa nạp khớp snapshot của Record; đây là kiểm tra tại lần đọc này.";
  else if (recordState.staleCheck?.freshness === "matches") freshness = "Nguồn file đã đọc lại và khớp tại lần tạo Record; workbook hiện tại chưa được kiểm tra lại.";
  set("flow-record-stale", freshness);
}

function flowTextList(id, values) {
  const container = byId(id);
  if (!container?.replaceChildren) return;
  container.replaceChildren();
  for (const value of values) {
    const item = document.createElement("p");
    item.textContent = typeof value === "string" ? value : value.message || value.detail || value.statement || JSON.stringify(value);
    container.appendChild(item);
  }
}

function renderFlowNavigator() {
  const container = byId("flow-navigator");
  if (!container?.replaceChildren) return;
  container.replaceChildren();
  const flow = state.flow;
  const items = [...flow.pendingRequests.map((item) => ({id: item.id, label: item.request.name || item.request.path})),
    ...flow.workbookSelections.map((item) => ({id: item.key, label: `${item.sheet} · ${item.request.name} · ${item.totalRows} dòng · ${item.totalColumns} cột`}))];
  for (const item of items) {
    const label = document.createElement("label");
    label.className = "flow-selection";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = flow.selectedTableIds.has(item.id);
    checkbox.disabled = flow.busy;
    checkbox.addEventListener("change", () => {
      if (flow !== state.flow || flow.busy) return;
      if (checkbox.checked) flow.selectedTableIds.add(item.id); else flow.selectedTableIds.delete(item.id);
      flowInvalidatePlans();
      flow.snapshot = null;
      flow.understand = null;
      flow.questions = [];
      flow.stage = "new";
      renderFlow();
    });
    const text = document.createElement("span");
    text.textContent = item.label;
    label.appendChild(checkbox);
    label.appendChild(text);
    container.appendChild(label);
  }
}

function flowRequestForSource(sourceId, origin = null) {
  const source = state.flow.sources.find((item) => item.id === sourceId);
  const locator = origin || source?.origin;
  return state.flow.pendingRequests.find((item) => item.request.path === locator || item.request.path === source?.name
    || (locator && item.request.path.replace(/\\/g, "/").endsWith("/" + locator)))
    || state.flow.workbookSelections.find((item) => source?.origin === `Workbook!${item.sheet}!${item.name}`);
}

function renderFlowConditions() {
  flowTextList("flow-error-list", [...state.flow.errors, ...state.flow.warnings]);
  const csv = byId("flow-csv-options");
  const renames = byId("flow-rename-list");
  if (!csv?.replaceChildren || !renames?.replaceChildren) return;
  csv.replaceChildren();
  renames.replaceChildren();
  for (const option of state.flow.csvOptions.filter((item) => item.needsClarification)) {
    const pending = flowRequestForSource(option.sourceId, option.origin);
    const group = document.createElement("div");
    const title = document.createElement("p");
    title.textContent = "CSV cần chọn dấu phân cách, encoding và dòng header trước khi nạp lại.";
    group.appendChild(title);
    for (const [key, values] of [["delimiter", [...new Set((option.candidates || []).map((item) => item.delimiter).filter(Boolean))]],
      ["encoding", [option.encoding || "utf-8", "utf-8-sig", "cp1258"]]]) {
      const label = document.createElement("label");
      label.textContent = key === "delimiter" ? "Dấu phân cách" : "Encoding";
      const select = document.createElement("select");
      select.disabled = !pending || state.flow.busy;
      const placeholder = document.createElement("option");
      placeholder.value = "";
      placeholder.textContent = "Chọn…";
      select.appendChild(placeholder);
      for (const value of values) {
        const item = document.createElement("option");
        item.value = value;
        item.textContent = value === "\t" ? "Tab" : value;
        select.appendChild(item);
      }
      select.value = pending?.request.options[key] || option[key] || "";
      select.addEventListener("change", () => { if (pending && !state.flow.busy) pending.request.options[key] = select.value; });
      label.appendChild(select);
      group.appendChild(label);
    }
    const headerLabel = document.createElement("label");
    headerLabel.textContent = "Dòng header";
    const header = document.createElement("input");
    header.type = "number";
    header.min = "1";
    header.value = String(pending?.request.options.header_row || option.headerRow || 1);
    header.disabled = !pending || state.flow.busy;
    header.addEventListener("change", () => { if (pending && !state.flow.busy) pending.request.options.header_row = Number(header.value); });
    headerLabel.appendChild(header);
    group.appendChild(headerLabel);
    csv.appendChild(group);
  }
  for (const conflict of state.flow.requiresRename) {
    for (const sourceId of conflict.sources || []) {
      const pending = flowRequestForSource(sourceId);
      const label = document.createElement("label");
      label.textContent = `Đổi tên bảng trùng ${conflict.tableName}: `;
      const input = document.createElement("input");
      input.type = "text";
      input.value = pending?.request.name || conflict.tableName;
      input.disabled = !pending || state.flow.busy;
      input.addEventListener("change", () => { if (pending && !state.flow.busy) pending.request.name = input.value.trim(); });
      label.appendChild(input);
      renames.appendChild(label);
    }
  }
}

function renderFlowQuestions() {
  const container = byId("flow-questions");
  if (!container?.replaceChildren) return;
  container.replaceChildren();
  for (const question of state.flow.questions) {
    const label = document.createElement("label");
    label.textContent = `${question.question} ${question.whyItMatters || ""}`;
    const input = document.createElement(question.kind === "single_choice" ? "select" : "input");
    if (question.kind === "single_choice") {
      const placeholder = document.createElement("option");
      placeholder.value = "";
      placeholder.textContent = "Chọn câu trả lời…";
      input.appendChild(placeholder);
      for (const option of question.options || []) {
        const node = document.createElement("option");
        node.value = typeof option === "string" ? option : option.value || option.label;
        node.textContent = typeof option === "string" ? option : option.label || option.value;
        input.appendChild(node);
      }
    } else input.type = "text";
    input.value = state.flow.answers[question.id] || "";
    input.disabled = state.flow.busy;
    input.addEventListener("change", () => {
      if (!state.flow.busy) {
        if (input.value.trim()) state.flow.answers[question.id] = input.value;
        else delete state.flow.answers[question.id];
        flowInvalidatePlans();
      }
    });
    label.appendChild(input);
    const evidence = document.createElement("p");
    evidence.className = "hint";
    evidence.textContent = (question.evidence || []).map((item) => item.value || item.kind).join(" · ");
    label.appendChild(evidence);
    container.appendChild(label);
  }
}

function renderFlowUnderstand() {
  const understand = state.flow.understand;
  if (!understand) return;
  const roles = understand.roles || [];
  const relationships = understand.relationships || [];
  byId("flow-understand-summary").textContent = `Engine đã đo cấu trúc: ${state.flow.snapshot?.tables?.length ?? state.flow.tables.length} bảng, ${relationships.length} quan hệ · ${understand.pack?.id || "generic"}`;
  flowTextList("flow-role-list", roles.map((item) => `${item.tableId} · ${item.structural} · ${item.domainLabel || ""}`));
  flowTextList("flow-relationship-list", relationships.map((item) => `${item.fromTable} → ${item.toTable} · ${item.cardinality} · ${item.status} · fan-out: ${item.fanOutRisk}`));
  flowTextList("flow-assumption-list", [...(understand.assumptions || []), ...(understand.warnings || []), ...(understand.pack?.notice ? [understand.pack.notice] : [])]);
}

function updateFlowButtons() {
  const flow = state.flow;
  if (!flow) return;
  const blocked = !flowCapabilityAvailable() || flow.busy;
  const set = (id, disabled) => { const node = byId(id); if (node) node.disabled = disabled; };
  set("flow-root-button", blocked);
  for (const id of ["flow-add-csv", "flow-add-xlsx", "flow-add-folder"]) set(id, blocked || !flow.rootLabel);
  set("flow-add-workbook", blocked || !flow.rootLabel || !state.officeReady);
  for (const id of ["flow-ingest-sample", "flow-ingest-full"]) set(id, blocked || !flow.rootLabel || !flow.selectedTableIds.size);
  set("flow-analyze-button", blocked || !flow.snapshot || flow.stage === "ingest_blocked" || !(byId("prompt")?.value || "").trim());
  set("flow-reset-button", blocked);
  set("flow-disclosure", blocked);
  set("flow-plan-button", blocked || !flow.understand || !["understood", "planning", "branched"].includes(flow.stage)
    || !(byId("prompt")?.value || "").trim() || byId("flow-disclosure")?.checked !== true);
  set("flow-branches-button", blocked || flow.mode !== "compute" || !flow.planningHash || !["planning", "branched"].includes(flow.stage));
  const selectedBranch = flow.branches.find((branch) => branch.id === flow.chosenBranch);
  const missingControl = selectedBranch?.reconciliation?.controlTotalApplicable === false;
  set("flow-control-ack", blocked || !missingControl || flow.approvalConsumed);
  set("flow-freeze-button", blocked || !state.officeReady || !selectedBranch?.selectable || flow.approvalConsumed
    || !["branched", "frozen", "approved"].includes(flow.stage) || (missingControl && byId("flow-control-ack")?.checked !== true));
  set("flow-approve-check", blocked || !["frozen", "approved"].includes(flow.stage) || !flow.spec || flow.approvalConsumed);
  set("flow-approve-button", blocked || flow.stage !== "frozen" || !flow.spec || flow.approvalConsumed || byId("flow-approve-check")?.checked !== true);
  set("flow-apply-button", blocked || !state.officeReady || flow.stage !== "approved" || !flow.approval || flow.approvalConsumed || byId("flow-approve-check")?.checked !== true);
  const recordState = state.workbookRecord;
  const recordWorkbookCurrent = !!state.workbook && recordState.workbookKey === workbookIdentity(state.workbook);
  set("flow-record-build", blocked || !["applied", "recorded"].includes(flow.stage) || flow.handoffStatus !== "readback-verified" || !flow.approvalConsumed);
  set("flow-record-reload", flow.busy || recordState.busy || !state.officeReady);
  set("flow-record-save", blocked || recordState.busy || !state.officeReady || !recordWorkbookCurrent || !recordState.loaded || recordState.reloadRequired || !recordState.record || !recordState.node || !flow.spec || recordState.node.spec !== flow.spec.fingerprint);
  set("flow-record-download", blocked || !recordWorkbookCurrent || !recordState.record);
  for (const id of ["flow-workbook-section", "flow-source-section", "flow-prompt-section", "flow-understand-section", "flow-branches-section", "flow-spec-section", "flow-apply-section", "flow-result-section"]) {
    const section = byId(id);
    if (section?.dataset) section.dataset.state = flow.stage;
    const chip = byId(id + "-status");
    if (chip) {
      const warning = flow.stage === "partial" || flow.stage === "ingest_blocked" || flow.allBlocked;
      const ready = id === "flow-workbook-section" ? state.officeReady && !!state.workbook : !!flow.snapshot;
      const label = flow.busy ? "Đang xử lý" : warning ? "Cần xử lý" : ready ? "Đã nạp · " + flow.stage : "Chưa nạp";
      chip.className = ["flow-workbook-section", "flow-source-section"].includes(id) ? "sr-only"
        : "badge " + (warning ? "badge-failed" : ready ? "badge-ready" : "badge-wait");
      const text = document.createElement("span"); text.textContent = id === "flow-workbook-section"
        ? state.officeReady && state.workbook ? "Đã kết nối workbook" : "Chưa đọc workbook" : label;
      chip.replaceChildren(createIcon(warning ? "alert-triangle" : "circle-info"), text);
    }
  }
}

function flowReviewStep(step) {
  const row = document.createElement("li");
  row.textContent = `${step.label || step.actionDescription || step.variableName || step.stepId || "Bước"} · ${step.operation?.type || step.operationType || ""}`;
  if (step.operation) {
    const details = document.createElement("details");
    const summary = document.createElement("summary");
    summary.textContent = "Xem tham số, đầu vào và điều kiện chính xác";
    const code = document.createElement("pre");
    code.className = "flow-algorithm";
    code.textContent = JSON.stringify(step, null, 2);
    details.appendChild(summary); details.appendChild(code); row.appendChild(details);
  }
  return row;
}

function flowReviewOutput(list, contract) {
  if (!contract) return;
  const row = document.createElement("li"), details = document.createElement("details");
  const summary = document.createElement("summary"), code = document.createElement("pre");
  summary.textContent = "Schema kết quả cuối của nhánh";
  code.className = "flow-algorithm";
  code.textContent = JSON.stringify(contract, null, 2);
  details.appendChild(summary); details.appendChild(code); row.appendChild(details); list.appendChild(row);
}

function renderFlowBranches() {
  const flow = state.flow;
  flowSetHidden("flow-branches-section", !flow.branches.length || !flow.snapshot || !flow.understand);
  const container = byId("flow-branches");
  if (!container) return;
  container.replaceChildren();
  if (byId("flow-plan-summary")) byId("flow-plan-summary").textContent = flow.planSummary;
  if (byId("flow-branch-engine")) byId("flow-branch-engine").textContent = flow.engine?.parityChecked === "none"
    ? "Bản này tính bằng engine nội bộ, chưa đối chiếu với Power Query trên máy bạn." : "";
  if (byId("flow-branch-status")) byId("flow-branch-status").textContent = flow.stage === "branching" ? "Đang tính A/B trên cùng snapshot…"
    : flow.allBlocked ? "Cả hai nhánh bị chặn. Quay lại cách hiểu hoặc tạo kế hoạch để sửa điều kiện." : "";
  if (byId("flow-branch-delta")) byId("flow-branch-delta").textContent = flow.delta?.applicable
    ? `A ${flow.delta.a} − B ${flow.delta.b} = ${flow.delta.value} · số do engine tính`
    : flow.delta?.reason || "";
  flowTextList("flow-plan-questions", flow.planQuestions);
  flowTextList("flow-plan-assumptions", flow.planAssumptions);
  for (const branch of flow.branches) {
    const card = document.createElement("article");
    card.id = `flow-branch-${branch.id}`;
    card.dataset.branchId = branch.id;
    const title = document.createElement("h3");
    title.textContent = `${branch.id} · ${branch.label}`;
    const rationale = document.createElement("p");
    rationale.textContent = branch.rationale;
    const badge = document.createElement("span");
    badge.className = "badge";
    badge.textContent = branch.reconciliation ? branch.warningCount ? "Đã tính · có cảnh báo" : "Đã tính bằng engine" : "chưa tính số";
    const steps = document.createElement("ol");
    for (const step of branch.normalizedSteps || branch.steps || []) steps.appendChild(flowReviewStep(step));
    flowReviewOutput(steps, branch.finalOutputContract);
    const choose = document.createElement(branch.reconciliation ? "input" : "button");
    choose.type = branch.reconciliation ? "radio" : "button";
    choose.textContent = "Chọn nhánh";
    choose.setAttribute("aria-label", `Chọn nhánh ${branch.id}`);
    choose.name = "flow-chosen-branch";
    choose.value = branch.id;
    choose.checked = flow.chosenBranch === branch.id;
    choose.disabled = !branch.reconciliation || branch.selectable !== true || flow.busy || flow.approvalConsumed;
    choose.addEventListener("change", () => {
      if (flow !== state.flow || flow.busy || branch.selectable !== true || !choose.checked) return;
      flow.chosenBranch = branch.id;
      flow.spec = flow.approval = null;
      flow.stage = "branched";
      if (byId("flow-control-ack")) byId("flow-control-ack").checked = false;
      if (byId("flow-approve-check")) byId("flow-approve-check").checked = false;
      renderFlowBranches();
      renderFlowFreeze();
      updateFlowButtons();
    });
    for (const child of [title, rationale, badge, steps, choose]) card.appendChild(child);
    container.appendChild(card);
    if (branch.reconciliation) {
      const banner = document.createElement("p");
      banner.setAttribute("role", "status");
      banner.textContent = branch.reconciliation.passed ? branch.warningCount
        ? "Đối soát tổng đạt; có cảnh báo chuyển đổi dữ liệu cần rà soát." : "Đối soát đạt."
        : branch.selectable ? "Chưa có đối soát tổng kiểm soát cho nhánh này. Cần xác nhận tường minh trước khi duyệt."
          : `Bị chặn: ${branch.error?.code || "AF_RECONCILE_FAILED"} · ${branch.error?.detail || "Đối soát chưa đạt."}`;
      card.appendChild(banner);
      if (!branch.reconciliation.controlTotalApplicable && !branch.selectable) {
        const unavailable = document.createElement("p");
        unavailable.textContent = "Chưa có đối soát tổng kiểm soát cho nhánh này.";
        card.appendChild(unavailable);
      }
      const reason = document.createElement("p");
      reason.textContent = branch.reconciliation.controlTotalReason || "";
      card.appendChild(reason);
      if (branch.warningCount) {
        const warningTitle = document.createElement("p"), warnings = document.createElement("ul");
        warningTitle.className = "notice notice-warning";
        warningTitle.textContent = `${branch.warningCount} nhóm cảnh báo chuyển đổi. Tổng tiền khớp không xác nhận từng ô dữ liệu đúng.`;
        card.appendChild(warningTitle);
        for (const warning of branch.warnings || []) {
          const item = document.createElement("li");
          item.textContent = `${warning.code} · ${warning.path} · ${warning.message}`;
          warnings.appendChild(item);
        }
        card.appendChild(warnings);
      }
      const dimensions = document.createElement("div");
      dimensions.id = `flow-branch-${branch.id}-counts`;
      card.appendChild(dimensions);
      renderTable(dimensions.id, ["Giai đoạn", "Dòng", "Cột"], [
        ["Trước", branch.counts.before.rows, branch.counts.before.cols], ["Sau", branch.counts.after.rows, branch.counts.after.cols]]);
      const preview = document.createElement("div");
      preview.id = `flow-branch-${branch.id}-preview`;
      card.appendChild(preview);
      renderTable(preview.id, (branch.columns || []).map((column) => column.name), (branch.rows || []).slice(0, 200));
      const detail = document.createElement("p");
      detail.className = "hint";
      detail.textContent = `${Math.min(branch.rows?.length || 0, 200)}/${branch.totalRows} dòng${branch.truncated ? " · xem trước đã giới hạn" : ""} · ${branch.elapsedMs} ms${branch.cached ? " · dùng cache kết quả" : ""}`;
      card.appendChild(detail);
    }
  }
}

function renderFlowFreeze() {
  const flow = state.flow;
  flowSetHidden("flow-spec-section", !flow.spec);
  flowSetHidden("flow-apply-section", !flow.spec && !flow.approvalConsumed);
  const spec = flow.spec;
  if (byId("flow-spec-summary")) byId("flow-spec-summary").textContent = spec
    ? `Nhánh ${spec.branchId} · ${spec.fingerprint} · đích ${spec.target.sheet} · nhãn ${(spec.labels || []).join(", ") || "không có"}` : "";
  const review = byId("flow-spec-steps");
  if (review) {
    review.replaceChildren();
    const list = document.createElement("ol");
    for (const step of spec?.steps || []) list.appendChild(flowReviewStep(step));
    review.appendChild(list);
  }
  const writeWorkbook = flow.approvalConsumed && spec?.workbookIdentity?.name
    ? `Lần ghi vào workbook «${spec.workbookIdentity.name}»: ` : "";
  if (byId("flow-apply-status")) byId("flow-apply-status").textContent = writeWorkbook + (flow.applyMessage || (flow.approvalConsumed
    ? flow.handoffStatus === "readback-verified" ? "Đã ghi và đọc lại toàn bộ khớp digest. Workbook chưa lưu."
      : "Quyền ghi đã dùng; chưa có xác nhận đọc lại đầy đủ. Trạng thái partial/unknown, không tự thử lại."
    : flow.approval ? "Đã duyệt đúng Spec. Chưa ghi workbook." : "Rà soát và duyệt Spec trước khi ghi."));
}

function renderFlow() {
  const flow = state.flow;
  flowSetHidden("flow-source-section", false);
  flowSetHidden("flow-prompt-section", !flow.snapshot);
  flowSetHidden("flow-understand-section", !flow.understand);
  const status = byId("flow-source-status");
  if (status) status.textContent = !flowCapabilityAvailable()
    ? "Coordinator cũ — chạy lại server để dùng luồng Trợ lý v2."
    : flow.busy ? "Đang xử lý nguồn…" : flow.stage === "ingest_blocked" ? "Nguồn bị chặn. Giải quyết các điều kiện rồi nạp lại."
      : flow.snapshot ? "Đã nạp nguồn cục bộ. Chỉ gửi mẫu tới Codex sau hành động và đồng ý của bạn." : "Gắn thư mục, thêm nguồn và chọn chế độ nạp.";
  if (byId("flow-root-label")) byId("flow-root-label").textContent = flow.rootLabel;
  if (byId("flow-mode-badge")) byId("flow-mode-badge").textContent = flow.mode === "compute" ? "TOÀN BỘ" : flow.mode === "discover" ? "MẪU 20 dòng" : "CHƯA NẠP";
  if (byId("flow-sample-info")) byId("flow-sample-info").textContent = flow.sampleInfo.map((item) =>
    `${item.name}: ${item.rowCount}/${item.totalRows} dòng · dòng: ${(item.sampleOrdinals || []).slice(0, 20).join(", ")}${item.mode === "compute" ? " · dữ liệu đầy đủ" : " · cùng bảng ⇒ cùng mẫu"}`).join("; ");
  if (flowCapabilityAvailable()) {
    flowTextList("flow-source-list", flow.sources.map((item) => `${item.name} · ${item.type} · ${(item.hash || "").slice(0, 20)}`));
    renderFlowNavigator();
    renderFlowConditions();
    renderFlowQuestions();
    renderFlowUnderstand();
    renderFlowBranches();
    renderFlowFreeze();
  }
  renderFlowRecord();
  updateFlowButtons();
  if (state.preparationJourneyStep !== null) {
    const business = state.preparationJourneyStep === "problem";
    flowSetHidden("flow-source-section", business);
    for (const id of ["flow-prompt-section", "flow-understand-section", "flow-branches-section", "flow-spec-section", "flow-apply-section", "flow-result-section"]) {
      if (!business) flowSetHidden(id, true);
    }
    if (business) flowSetHidden("flow-prompt-section", false);
  }
}

function bindFlowEvents() {
  const bind = (id, action) => byId(id)?.addEventListener("click", action);
  bind("flow-root-button", flowBindRoot);
  bind("flow-add-csv", () => flowAddFile("csv"));
  bind("flow-add-xlsx", () => flowAddFile("xlsx"));
  bind("flow-add-folder", () => flowAddFile("folder"));
  bind("flow-add-workbook", flowAddOpenWorkbook);
  bind("flow-ingest-sample", () => flowIngest("discover"));
  bind("flow-ingest-full", () => flowIngest("compute"));
  bind("flow-analyze-button", flowUnderstand);
  bind("flow-plan-button", flowPlanDraft);
  bind("flow-branches-button", flowExecuteBranches);
  bind("flow-freeze-button", flowFreeze);
  bind("flow-approve-button", flowApprove);
  bind("flow-apply-button", flowApply);
  bind("flow-record-build", flowCreateRecord);
  bind("flow-record-reload", flowReadRecord);
  bind("flow-record-save", flowPersistRecord);
  bind("flow-record-download", flowDownloadRecord);
  byId("flow-control-ack")?.addEventListener("change", updateFlowButtons);
  byId("flow-approve-check")?.addEventListener("change", updateFlowButtons);
  byId("flow-disclosure")?.addEventListener("change", updateFlowButtons);
  bind("flow-reset-button", flowReset);
  bind("flow-understand-toggle", () => {
    const toggle = byId("flow-understand-toggle");
    const expanded = toggle.getAttribute("aria-expanded") !== "true";
    toggle.setAttribute("aria-expanded", String(expanded));
    flowSetHidden("flow-understand-body", !expanded);
  });
  byId("prompt")?.addEventListener("input", flowInvalidatePlans);
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
    ? "Đang xem kết quả cũ để so sánh. Bấm Quay về trên bản này để chuyển HEAD; kết quả cũ không đủ điều kiện để ghi nên hệ thống sẽ chạy Preview mới trước khi duyệt."
    : "Đang xem kết quả đã lưu. Bấm Quay về trên bản này để chuyển HEAD và ghi lại đúng kết quả này; server vẫn kiểm fingerprint nguồn trước khi ghi.";
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

    const revertBtn = document.createElement("button");
    revertBtn.type = "button";
    revertBtn.className = "node-revert";
    revertBtn.textContent = "Quay về";
    revertBtn.disabled = isChainHead;
    const revertTitle = isChainHead
      ? `${revisionName} đang là HEAD; không cần quay về.`
      : `Quay về ${revisionName}`;
    revertBtn.title = revertTitle;
    revertBtn.setAttribute("aria-label", revertTitle);
    revertBtn.addEventListener("click", async (e) => {
      e.stopPropagation();
      if (owningChain?.chainId !== state.problemChainDocument?.chainId) {
        const activated = await activateProblemChainRevision(owningChain.chainId, revision.revisionId);
        if (!activated) return;
      }
      await revertToProblemRevision(revision.revisionId, owningChain?.chainId);
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

    actions.append(revertBtn, branchBtn, editBtn, deleteBtn);
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

function problemRevisionDirectChildIds(revisions, revisionId) {
  return (revisions || [])
    .filter((item) => item.parentRevisionId === revisionId)
    .map((item) => item.revisionId);
}

async function revertToProblemRevision(revisionId, chainId = state.problemChainDocument?.chainId) {
  if (state.busy || state.checkoutRunning || state.revertRunning) return;
  if (chainId && chainId !== state.problemChainDocument?.chainId) {
    await activateProblemChainRevision(chainId, revisionId);
    return;
  }
  if (!state.problemChainHydrated || !state.problemChainDocument) return;
  const revision = problemRevisionById(revisionId);
  if (!revision) {
    showError("PQPC_REVISION_NOT_FOUND", "Revision không còn trong lịch sử workbook.");
    return;
  }
  if (state.problemChainDocument.headRevisionId === revisionId) {
    selectProblemChainRevision(revisionId);
    byId("pqpc-progress").textContent = "Bản này đang là HEAD; không có gì để quay về.";
    return;
  }
  const revisionName = problemRevisionLabel(revision);
  const descendantCount = problemRevisionSubtreeIds(state.problemChainDocument.revisions, revisionId)
    .filter((item) => item !== revisionId).length;
  // Deleting descendants is never implicit: the user picks it as a second,
  // separate action inside the same dialog (PC-FR-028).
  const choice = await requestPQConfirmation(state.workbook?.name || "workbook", descendantCount ? {
    title: `Quay về ${revisionName}?`,
    detail: `HEAD sẽ chuyển về ${revisionName}. ${descendantCount} bản phía sau vẫn được giữ để so sánh, hoặc bạn có thể xoá hẳn chúng khỏi lịch sử nhúng trong workbook. Add-in không tự Save.`,
    continueLabel: `Quay về, giữ ${descendantCount} bản sau`,
    altLabel: `Quay về và xoá ${descendantCount} bản sau`,
  } : {
    title: `Quay về ${revisionName}?`,
    detail: "HEAD sẽ chuyển về bản này. Không có bản nào phía sau để xoá. Add-in không tự Save.",
    continueLabel: "Quay về",
  });
  if (!choice) return;
  const alsoDelete = choice === "alt";
  state.revertRunning = true;
  clearError();
  try {
    await checkoutProblemRevision(revisionId);
    if (state.problemChainDocument?.headRevisionId !== revisionId) {
      byId("pqpc-progress").textContent = "Chưa quay về được; HEAD cũ được giữ nguyên và không có bản nào bị xoá.";
      return;
    }
    if (!alsoDelete) {
      byId("pqpc-progress").textContent = `Đã quay về ${revisionName}. ${descendantCount} bản phía sau vẫn được giữ để so sánh.`;
      return;
    }
    setBusy(true, "Đang xoá các bản phía sau…");
    let deletedCount = 0;
    const childIds = problemRevisionDirectChildIds(state.problemChainDocument?.revisions || [], revisionId);
    for (const childId of childIds) {
      const candidate = await api("/api/pq/v2/problem-chains/problems/delete", {
        document: state.problemChainDocument,
        baseHistoryHash: state.problemChainHistoryHash,
        revisionId: childId,
      });
      deletedCount += Array.isArray(candidate?.deletedRevisionIds)
        ? candidate.deletedRevisionIds.length : 1;
      await persistProblemChainCandidate(candidate);
      reconcileProblemChainPreviewCache();
    }
    closeProblemBranchEditor();
    renderProblemImpactReport(null);
    byId("pqpc-progress").textContent = deletedCount
      ? `Đã quay về ${revisionName} và xoá ${deletedCount} bản phía sau. Hãy Save workbook để giữ thay đổi.`
      : `Đã quay về ${revisionName}; không còn bản phía sau để xoá.`;
  } catch (error) {
    showError(error.code, error.message);
    byId("pqpc-progress").textContent = alsoDelete
      ? "Quay về có thể đã đổi HEAD nhưng chưa xoá hết bản phía sau; thao tác không tự chạy lại. Hãy kiểm tra lịch sử rồi thử lại."
      : "Chưa quay về được; HEAD cũ được giữ nguyên.";
  } finally {
    state.revertRunning = false;
    setBusy(false, "");
    updateProblemChainButtons();
    updatePQButtons();
  }
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
    || !state.capabilities.codexAnalysis || !prompt || !answersReady;
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
  if (state.busy || !state.officeReady || !state.capabilities.codexAnalysis) return;
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

// The correction box is the primary way to fix steps: describe what is wrong and
// let Codex re-analyse instead of hand-editing operations (which stays available
// through the step editor and its own revision path).
async function submitTypedCorrection() {
  const input = byId("pq2-correction-prompt");
  const text = (input?.value || "").trim();
  if (state.busy || !state.pqTypedPlan || !text) return;
  if (!state.problemChainSupported) {
    const promptBox = byId("pq2-prompt");
    const current = (promptBox?.value || "").trim();
    promptBox.value = current ? `${current}\n\nYêu cầu chỉnh sửa: ${text}` : `Yêu cầu chỉnh sửa: ${text}`;
    input.value = "";
    await createTypedPlan();
    return;
  }
  if (!state.problemChainHydrated || !state.problemChainDocument) {
    showError("PQPC_NOT_READY", "Lịch sử vấn đề chưa nạp xong; chưa gọi Codex.");
    return;
  }
  const headRevisionId = state.problemChainDocument.headRevisionId;
  if (state.pqTypedPlan?.revision?.revisionId !== headRevisionId || !problemChainHeadMatchesView()) {
    showError("PQPC_HEAD_MISMATCH", "Chỉ revision HEAD đã lưu mới được phân tích lại. Hãy chọn lại HEAD trước.");
    return;
  }
  const revision = problemRevisionById(headRevisionId);
  const replacesHead = Boolean(revision?.parentRevisionId) && revision?.originKind === "problem";
  const mode = replacesHead ? "editProblem" : "new";
  // Open the composer first so a clarification response stays visible; the
  // revision still comes from a single click here.
  state.problemChainDraftAction = null;
  openProblemBranchEditor(mode, headRevisionId);
  if (state.problemChainDraftAction?.mode !== mode) return;
  byId("pqpc-branch-prompt").value = text;
  const created = await createProblemMutation({
    creationMode: replacesHead ? "editProblem" : "continue",
    baseRevisionId: replacesHead ? revision.parentRevisionId : headRevisionId,
    editRevisionId: replacesHead ? revision.revisionId : null,
    prompt: text,
  });
  if (!created) return;
  input.value = "";
  closeProblemBranchEditor();
  byId("pqpc-progress").textContent = replacesHead
    ? "Đã tạo bản sửa từ yêu cầu chỉnh bước; bản cũ được giữ để so sánh. Chưa chạy Excel preview."
    : "Đã tạo revision mới từ yêu cầu chỉnh bước. Chưa chạy Excel preview.";
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
  byId("pq-propose-button").disabled = !advancedReady || !state.capabilities.codexAnalysis || !selectedPQSource();
  byId("pq-preview-button").disabled = !advancedReady || !selectedPQSource()
    || !byId("pq-code").value.trim();
  byId("pq-apply-source-button").disabled = !advancedReady || !state.pqPreview || state.pqPreview.applied === true;
  byId("pq2-plan-button").disabled = state.problemChainSupported || !ready || !state.capabilities.codexAnalysis || !byId("pq2-prompt").value.trim();
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
  const correctionPrompt = byId("pq2-correction-prompt");
  setHidden("pq2-correction", !state.pqTypedPlan);
  byId("pq2-correction-submit").disabled = !ready || !state.pqTypedPlan || !state.capabilities.codexAnalysis
    || !(correctionPrompt?.value || "").trim()
    || (state.problemChainSupported && (!state.problemChainHydrated || !problemChainHeadMatchesView()));
  if (byId("pq2-correction-note")) {
    byId("pq2-correction-note").textContent = state.problemChainSupported
      ? "Codex phân tích lại và tạo revision mới từ yêu cầu này; bản đang xem được giữ để so sánh. Chưa chạy Excel preview."
      : "Codex lập lại plan từ yêu cầu chỉnh sửa này; plan cũ không được giữ. Chưa chạy Excel preview.";
  }
  updateProblemChainButtons();
}

function switchTab(name) {
  state.activeTab = name;
  setHidden("tab-assistant", name !== "assistant");
  setHidden("tab-pq", name !== "pq");
  for (const [tab, id] of [["assistant", "tab-assistant-button"], ["pq", "tab-pq-button"]]) {
    byId(id).classList.toggle("active", name === tab);
    byId(id).setAttribute("aria-selected", String(name === tab));
  }
  clearError();
}

async function proposePQ() {
  if (state.busy || !state.officeReady || !state.capabilities.codexAnalysis || !state.advancedMPolicy) return;
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

// Resolves `true` (continue), `false` (cancel) or `"alt"` when the caller supplied
// `options.altLabel` and the user picked that second action instead.
function requestPQConfirmation(workbookName, options = {}) {
  byId("pq-confirm-title").textContent = options.title || "Chạy M trên workbook tạm?";
  byId("pq-confirm-detail").textContent = options.detail || "M có thể đọc toàn bộ workbook export, file/web/database, dùng credential Excel hoặc gây side effect ngoài workbook. Workbook tạm không phải sandbox. Sau khi chạy, add-in copy values kết quả vào sheet PQ_Result để review nhưng chưa ghi sheet nguồn.";
  byId("pq-confirm-continue").textContent = options.continueLabel || "Đồng ý, chạy thử";
  byId("pq-confirm-workbook").textContent = `Workbook: ${workbookName}`;
  const alt = byId("pq-confirm-alt");
  const hasAlt = Boolean(options.altLabel);
  if (alt) {
    alt.textContent = hasAlt ? options.altLabel : "";
    setHidden("pq-confirm-alt", !hasAlt);
  }
  setHidden("pq-confirm-overlay", false);
  const proceed = byId("pq-confirm-continue");
  const cancel = byId("pq-confirm-cancel");
  return new Promise((resolve) => {
    const finish = (accepted) => {
      proceed.removeEventListener("click", accept);
      cancel.removeEventListener("click", decline);
      alt?.removeEventListener?.("click", chooseAlt);
      document.removeEventListener("keydown", onKeyDown);
      setHidden("pq-confirm-overlay", true);
      if (alt) setHidden("pq-confirm-alt", true);
      resolve(accepted);
    };
    const accept = () => finish(true);
    const decline = () => finish(false);
    const chooseAlt = () => finish("alt");
    const onKeyDown = (event) => {
      if (event.key === "Escape") finish(false);
    };
    proceed.addEventListener("click", accept);
    cancel.addEventListener("click", decline);
    if (hasAlt && alt) alt.addEventListener("click", chooseAlt);
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
  bindFlowEvents();
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
  byId("pq2-correction-submit").addEventListener("click", submitTypedCorrection);
  byId("pq2-correction-prompt").addEventListener("input", updatePQButtons);
  byId("pq2-correction-prompt").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && event.ctrlKey && !event.altKey && !event.metaKey && !event.shiftKey && !event.isComposing && !event.repeat && !byId("pq2-correction-submit").disabled) {
      event.preventDefault();
      byId("pq2-correction-submit").click();
    }
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
  byId("prompt").addEventListener("input", updatePromptCount);
  bindFlowPromptShortcut();
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
  if (typeof state.preparationDetach === "function") {
    try {
      const detaching = state.preparationDetach();
      if (detaching) { Promise.resolve(detaching).catch(() => {}); return; }
    } catch { return; }
  }
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

let startupInProgress = false;
async function connectTaskpane() {
  if (startupInProgress) return;
  startupInProgress = true;
  const reconnect = byId("assistant-reconnect");
  if (reconnect) { reconnect.disabled = true; reconnect.hidden = true; }
  for (const id of ["assistant-choose-folder", "assistant-choose-workbook"]) byId(id).disabled = true;
  byId("assistant-source-message").textContent = "Đang kết nối với Excel…";
  clearError();
  try {
    await bootstrap();
  if (!window.Office) {
    throw Object.assign(new Error("Trang này phải được mở từ Excel task pane, không phải browser thường."), {code: "OFFICE_NOT_READY"});
  }
  const info = await Office.onReady();
    if (info.host !== Office.HostType.Excel) {
      throw Object.assign(new Error("Add-in hiện không chạy trong Excel."), {code: "OFFICE_NOT_READY"});
    }
    state.officeReady = true;
    if (!state.preparationReadCapability || !window.ReqwisePreparation || !window.ReqwisePreparationRuntime
        || !window.ReqwisePreparationBridge || !window.ReqwiseAssistantEntry || !window.ReqwiseAssistantBrowser) {
      throw Object.assign(new Error("Chưa tải đủ bộ hỗ trợ trợ lý. Bấm Kết nối lại; nếu vẫn lỗi, mở lại panel."), {code: "ASSISTANT_STARTUP_FAILED"});
    }
    if (state.preparationReadCapability && window.ReqwisePreparation && window.ReqwisePreparationRuntime) {
      const preparationPost = async (action, fields) => {
          const response = await fetch("/api/preparation/" + action, {method: "POST",
            headers: {"Content-Type": "application/json", "X-Local-Token": state.token},
            body: JSON.stringify({schemaVersion: 1, action, ...fields}), keepalive: action === "detach"});
          const result = await response.json();
          if (!response.ok) {
            const code = result.error?.code;
            const detail = code === "INVALID_REQUEST" ? "Không thể đọc lựa chọn hiện tại. Hãy chọn lại nguồn dữ liệu."
              : code === "DP_SOURCE_STALE" ? "Nguồn đã thay đổi hoặc không đọc được. Hãy chọn lại."
              : result.error?.detail || result.detail || "Không thể xử lý chuẩn bị dữ liệu.";
            throw Object.assign(new Error(detail), {code});
          }
          return result;
        };
      let preparation = null, bridge = null, browser = null;
      const updatePreparation = value => preparation?.acceptState(value);
      const unavailable = () => { throw flowFailure("DP_UNSUPPORTED_PRESERVATION", "Bộ hỗ trợ chuẩn bị dữ liệu chưa được cập nhật. Hãy mở lại panel."); };
      preparation = window.ReqwisePreparation.mount({document, environment: window,
        runtime: window.ReqwisePreparationRuntime, post: preparationPost, deferOpen: !!window.ReqwiseAssistantEntry,
        scanWorkbook: options => bridge ? bridge.scanWorkbook(options) : unavailable(),
        applyCleanup: options => bridge ? bridge.applyCleanup(options) : unavailable(),
        undo: options => bridge ? bridge.undo(options) : unavailable(),
        redo: options => bridge ? bridge.redo(options) : unavailable(),
        onApplied: receipt => window.ReqwiseAssistantEntryUI?.cleaningComplete(receipt),
        onDirty: () => { window.ReqwiseAssistantEntryUI?.invalidate(); flowInvalidateSourceAuthority(state.flow); renderFlow(); },
        onBusy: value => window.ReqwiseAssistantEntryUI?.setBusy(value)});
      if (window.ReqwisePreparationBridge && preparation) {
        bridge = window.ReqwisePreparationBridge.create({post: preparationPost, runtime: window.ReqwisePreparationRuntime,
          backupEnabled: state.preparationBackupEnabled,
          environment: window, getState: () => preparation.wizard.state, setState: updatePreparation});
        state.preparationDetach = () => preparation.wizard.state ? bridge.detach() : null;
      }
      if (window.ReqwiseAssistantEntry && preparation) {
        window.ReqwiseAssistantEntryUI = window.ReqwiseAssistantEntry.mount({document,
          onBrowse: () => browser?.open(),
          chooseFolder: () => {
            if (!state.preparationFolderPicker) throw new Error("Bộ hỗ trợ chọn thư mục chưa được cập nhật. Hãy đóng rồi mở lại panel.");
            return preparationPost("pick-folder", {});
          }, inventory: async root => {
            if (bridge) await bridge.attach();
            const inventory = await preparation.inventoryRoot(root);
            return bridge ? bridge.mapInventory(inventory) : inventory;
          },
          // Scan every worksheet; a blank active sheet does not exclude data on other sheets.
          selectWorkbook: async () => true,
          canImport: () => preparation.wizard.state?.writeEnabled === true,
          importBlocker: () => "Chưa xác nhận được workbook đích hoặc phiên đã hết hạn. Hãy chọn lại nguồn.",
          importFiles: options => bridge ? bridge.importFiles(options) : unavailable(),
          restartSession: () => bridge ? bridge.restart() : unavailable(),
          canRestartAfterPartial: state.preparationBackupEnabled === false,
          scanWorkbook: options => preparation.scanWorkbook(options),
          showCleaning: options => preparation.show(options),
          showProblem: async () => {
            window.ReqwiseAssistantEntryUI.setBusy(true);
            try { await preparationBusinessHandoff(await bridge.businessSources()); }
            catch (error) { showError(error.code || "AF_INGEST_FAILED", error.message); throw error; }
            finally { window.ReqwiseAssistantEntryUI.setBusy(false); renderFlow(); }
          },
          invalidateBusiness: () => { flowInvalidateSourceAuthority(state.flow); renderFlow(); },
          onStepChange: step => { state.preparationJourneyStep = step; renderFlow(); }});
        if (window.ReqwiseAssistantBrowser && bridge) {
          browser = window.ReqwiseAssistantBrowser.create({document, bridge,
            onImported: receipt => window.ReqwiseAssistantEntryUI?.imported(receipt)});
        }
      }
    }
    await refreshWorkbook();
    if (flowCapabilityAvailable()) {
      await flowLoadState();
    }
    await hydrateProblemChain();
    byId("assistant-source-message").textContent = "";
  } catch (error) {
    byId("assistant-source-message").textContent = error.message || "Chưa khởi tạo được trợ lý. Bấm Kết nối lại để thử lại.";
    byId("assistant-workbook-summary").textContent = "Workbook · Chưa kết nối";
    for (const id of ["assistant-choose-folder", "assistant-choose-workbook"]) byId(id).disabled = true;
    if (reconnect) reconnect.hidden = false;
    showError(error.code || "ASSISTANT_STARTUP_FAILED", error.message);
  } finally {
    startupInProgress = false;
    if (reconnect) reconnect.disabled = false;
  }
}

async function start() {
  bindEvents();
  byId("assistant-reconnect")?.addEventListener("click", connectTaskpane);
  await connectTaskpane();
}

document.addEventListener("DOMContentLoaded", start);
if (typeof window !== "undefined" && window.addEventListener) {
  window.addEventListener("pagehide", closeCoordinatorSession);
}
