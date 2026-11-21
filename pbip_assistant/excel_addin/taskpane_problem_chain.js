/* Problem-chain Custom XML: encoding, revision tree, editing, checkout and deletion. */
"use strict";
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

