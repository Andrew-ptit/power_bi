/* State, DOM helpers, the network seam and bootstrap. Loaded first. */
"use strict";

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

// Substitution seam: every network read/write in this file goes through one of
// these four bindings, so a test can replace a dependency instead of reaching
// into the script's scope. The trampolines keep the real implementations named
// and keep call sites unchanged.
let api = (...args) => apiImpl(...args);
let readWorkbook = () => readWorkbookImpl();
let applyPQValuesToOpenWorkbook = (...args) => applyPQValuesToOpenWorkbookImpl(...args);
let applyPQValuesToSource = (...args) => applyPQValuesToSourceImpl(...args);

async function apiImpl(path, payload, {timeoutMs = 0, preserveConsumedState = false} = {}) {
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

