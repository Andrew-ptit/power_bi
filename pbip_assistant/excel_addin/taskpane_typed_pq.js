/* Typed Power Query editor, step diagnostics and the preview/approve/apply path. */
"use strict";
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

async function applyPQValuesToOpenWorkbookImpl(preview, expectedWorkbook, resultOptions = {}) {
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

async function applyPQValuesToSourceImpl(preview, expectedWorkbook, source) {
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

