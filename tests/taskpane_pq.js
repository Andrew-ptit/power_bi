"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../pbip_assistant/excel_addin/taskpane.js"), "utf8");
const elements = new Map();
let confirmations = 0;
const decisions = [false, true, true, true];
function element(id) {
  if (!elements.has(id)) {
    const options = [];
    const listeners = new Map();
    elements.set(id, {
      textContent: "", className: "", checked: false, disabled: false, value: "",
      classList: {toggle(_name, hidden) {
        if (id === "pq-confirm-overlay" && !hidden) {
          confirmations += 1;
          const choice = decisions.shift();
          setImmediate(() => element(choice ? "pq-confirm-continue" : "pq-confirm-cancel").click());
        }
      }},
      get options() { return options; },
      replaceChildren() { options.length = 0; this.value = ""; },
      appendChild(option) { options.push(option); if (options.length === 1) this.value = option.value; },
      addEventListener(name, callback) { listeners.set(name, callback); },
      removeEventListener(name, callback) { if (listeners.get(name) === callback) listeners.delete(name); },
      click() { listeners.get("click")?.(); },
      focus() {},
    });
  }
  return elements.get(id);
}
const workbook = {
  name: "orders.xlsx", url: "file:///C:/orders.xlsx", activeSheet: "Raw_Orders", tables: [],
  sheets: [{name: "Raw_Orders", headers: ["Ma_Don_Hang"], rows: [["A1"]]}],
};
const calls = [];
let writes = 0;
let previewCopies = 0;
const sandbox = {
  document: {getElementById: element, addEventListener() {}, removeEventListener() {}, createElement: () => ({})},
  window: {Office: {context: {requirements: {isSetSupported: () => true}}}, confirm: () => { throw new Error("window.confirm is unsupported"); }},
  Office: {context: {requirements: {isSetSupported: () => true}}},
};
vm.runInNewContext(source + `
  globalThis.__state = state;
  globalThis.__renderWorkbook = renderWorkbook;
  globalThis.__selectedPQSource = selectedPQSource;
  globalThis.__proposePQ = proposePQ;
  globalThis.__previewPQ = previewPQ;
  globalThis.__applyPQPreview = applyPQPreviewToSource;
  globalThis.__invalidatePQPreview = invalidatePQPreview;
  globalThis.__applyPlan = applyPlan;
  readWorkbook = async () => globalThis.__liveWorkbook;
  exportWorkbookBase64 = async () => "encoded-workbook";
  applyPQValuesToOpenWorkbook = async () => globalThis.__copyPreview();
  applyPQValuesToSource = async () => globalThis.__applyPQ();
  renderTable = () => {};
  api = async (endpoint, payload) => globalThis.__api(endpoint, payload);
`, sandbox);
sandbox.__liveWorkbook = workbook;
sandbox.__copyPreview = async () => {
  previewCopies += 1;
  return {resultSheetName: "PQ_Result", afterColumns: ["Ma_Don_Hang"],
    afterRows: [["FABRICATED"]], rowCount: 2, columnCount: 1};
};
sandbox.__applyPQ = async () => {
  writes += 1;
  return {sourceSheetName: "Raw_Orders", sourceKind: "sheet", sourceName: "Raw_Orders",
    afterColumns: ["Ma_Don_Hang"], afterRows: [["A1"], ["A2"]], rowCount: 2, columnCount: 1};
};
sandbox.__api = async (endpoint, payload) => {
  calls.push({endpoint, payload});
  if (endpoint === "/api/pq/propose") return {mCode: "let Source = 1 in Source", summary: "Đề xuất", warnings: []};
  if (endpoint === "/api/pq/run-sheet") return {
    status: "ready_for_open_workbook", resultWorkbookBase64: "static-values", sourceFingerprint: "f".repeat(64),
    sourceRows: 4, resultRows: 2, resultColumns: 1,
    beforeColumns: ["Ma_Don_Hang"], beforeRows: [["A1"]],
    afterColumns: ["Ma_Don_Hang"], afterRows: [["FABRICATED"]],
    previewLimited: false,
  };
  if (endpoint === "/api/pq/check-source") return {unchanged: true};
  throw new Error("Unexpected endpoint");
};
const normalApi = sandbox.__api;
sandbox.__state.officeReady = true;
sandbox.__state.codexAvailable = true;
sandbox.__state.sessionId = "ses-test";
sandbox.__state.advancedMPolicy = {
  policyId: "advanced-m-trusted-v1", mode: "trusted", enabled: true,
  riskAcknowledgementRequired: true, acknowledgementScope: "workbookPanelSession",
  externalConnectors: "allowed", previewIsolation: "temporaryWorkbookNotSandbox",
  applyToSource: "explicitConfirmation", backupPolicy: "none", autoSave: false,
};
sandbox.__state.workbook = workbook;
sandbox.__renderWorkbook();
element("pq-prompt").value = "Bỏ dòng trùng";

(async () => {
  await sandbox.__proposePQ();
  assert.equal(calls[0].endpoint, "/api/pq/propose");
  assert.equal(calls[0].payload.source.kind, "sheet");
  assert.equal(element("pq-code").value, "let Source = 1 in Source");
  await sandbox.__previewPQ();
  assert.equal(confirmations, 1, "first attempt must ask before running M");
  assert.equal(calls.length, 1, "cancel must not run M or write Excel");
  assert.equal(writes, 0);
  await sandbox.__previewPQ();
  assert.equal(confirmations, 2, "cancelled confirmation must be asked again");
  assert.equal(calls[1].endpoint, "/api/pq/run-sheet");
  assert.equal(calls[1].payload.riskAccepted, true);
  assert.equal(calls[1].payload.riskPolicyId, "advanced-m-trusted-v1");
  assert.equal(JSON.stringify(calls[1].payload.ignoredSheetNames), "[]");
  assert.equal(calls[2].endpoint, "/api/pq/check-source");
  assert.equal(calls[2].payload.sourceFingerprint, "f".repeat(64));
  assert.equal(writes, 0, "preview must not write the source");
  assert.equal(previewCopies, 1, "preview must create or update the managed result sheet");
  assert.equal(sandbox.__state.pqPreview.afterRows[0][0], "FABRICATED");
  assert.match(element("pq-preview-note").textContent, /PQ_Result/);
  await sandbox.__applyPQPreview();
  assert.equal(confirmations, 3, "source overwrite requires a separate explicit confirmation");
  assert.equal(calls[3].endpoint, "/api/pq/check-source");
  assert.equal(JSON.stringify(calls[3].payload.ignoredSheetNames), '["PQ_Result"]');
  assert.equal(writes, 1);
  assert.equal(sandbox.__state.pqPreview.applied, true);
  assert.equal(sandbox.__state.pqPreview.afterRows[0][0], "A1", "applied display must use source readback");
  assert.match(element("pq-preview-note").textContent, /sau khi ghi values/);
  await sandbox.__previewPQ();
  assert.equal(confirmations, 3, "second preview on same workbook must not repeat the arbitrary-M warning");
  assert.equal(calls[4].payload.source.sheet, "Raw_Orders");
  assert.equal(JSON.stringify(calls[4].payload.ignoredSheetNames), '["PQ_Result"]');
  assert.equal(writes, 1, "a new preview must still not write the source");
  assert.equal(previewCopies, 2, "a new preview updates the managed result sheet");
  element("pq-code").value += " ";
  await sandbox.__applyPQPreview();
  assert.equal(confirmations, 3, "stale code must be rejected before asking for overwrite confirmation");
  assert.equal(writes, 1, "editing M after preview must block applying the stale result");
  assert.equal(sandbox.__state.pqPreview, null, "editing M invalidates the retained preview");
  element("pq-code").value = element("pq-code").value.trimEnd();
  sandbox.__api = normalApi;
  await sandbox.__previewPQ();
  sandbox.__api = async (endpoint) => {
    assert.equal(endpoint, "/api/pq/check-source");
    return {unchanged: false};
  };
  await sandbox.__applyPQPreview();
  assert.equal(confirmations, 4, "each source overwrite attempt requires explicit confirmation");
  assert.equal(writes, 1, "a source changed after preview must block the source write");
  assert.equal(sandbox.__state.pqPreview, null, "a changed source invalidates the retained preview");
  sandbox.__api = async (endpoint) => endpoint === "/api/pq/run-sheet"
    ? {status: "ready_for_open_workbook", sourceFingerprint: "f".repeat(64)} : {unchanged: false};
  await sandbox.__previewPQ();
  assert.equal(writes, 1, "changed workbook data must block preview acceptance and any write");
  assert.equal(sandbox.__state.pqPreview, null);
  sandbox.__api = async (endpoint) => {
    assert.equal(endpoint, "/api/pq/run-sheet");
    const error = new Error("Excel failed at refresh-query");
    error.code = "PQ_REFRESH_FAILED";
    throw error;
  };
  await sandbox.__previewPQ();
  assert.equal(writes, 1, "failed M refresh must not start an Office worksheet write");
  assert.equal(sandbox.__state.pqPreview, null, "failed refresh must not retain a previous result");
  assert.match(element("pq-progress").textContent, /chưa ghi gì vào workbook đang mở/);
  sandbox.__api = async () => ({status: "excel_preview", resultRows: 2});
  await sandbox.__previewPQ();
  assert.equal(writes, 1, "a response without checked value sheet must not write Excel");
  assert.equal(sandbox.__state.pqPreview, null);
  sandbox.__invalidatePQPreview();
  assert.equal(sandbox.__state.pqPreview, null);
  sandbox.__state.plan = {status: "review_ready"};
  const callCount = calls.length;
  await sandbox.__applyPlan();
  assert.equal(calls.length, callCount, "main assistant apply still requires its explicit approval checkbox");
  console.log("taskpane PQ flow test passed");
})().catch((error) => { console.error(error); process.exitCode = 1; });
