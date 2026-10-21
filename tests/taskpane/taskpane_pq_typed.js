"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../../pbip_assistant/excel_addin/taskpane.js"), "utf8");
const elements = new Map();
function element(id) {
  if (!elements.has(id)) {
    const listeners = new Map();
    elements.set(id, {
      textContent: "", className: "", checked: false, disabled: false, value: "",
      classList: {toggle() {}},
      replaceChildren() {}, appendChild() {}, append() {}, setAttribute() {},
      addEventListener(name, callback) { listeners.set(name, callback); },
      click() { return listeners.get("click")?.(); }, focus() {},
    });
  }
  return elements.get(id);
}

const workbook = {
  name: "sales.xlsx", url: "file:///C:/sales.xlsx", activeSheet: "Sales",
  tables: [{name: "SalesTable", sheet: "Sales", headers: ["Sales", "Cost"], rows: [[1500, 200], [500, 100]], totalRows: 2, totalColumns: 2}],
  sheets: [], activeCell: {rowIndex: 1, columnIndex: 0},
};
const plan = {
  schemaVersion: "2.0", planId: "plan_a", snapshotId: "snap_a",
  revision: {revisionId: "rev_a", parentRevisionId: null, reviewHash: "sha256:a"},
  planStatus: "reviewReady", summary: "Filter sales", questions: [], assumptions: [], warnings: [], hardBlockers: [],
  sources: [], steps: [{stepId: "stp_source", position: 1, variableName: "SalesSource", actionDescription: "Load sales", operation: {type: "source.workbookTable", parameters: {sourceId: "src_sales"}}, inputs: [], outputContract: {kind: "table", columns: []}}],
  finalOutputStepId: "stp_source", changeSet: [], validation: {}, preview: null, approval: {status: "notRequested"},
};
const preview = {
  previewId: "prv_a", revisionId: "rev_a", snapshotId: "snap_a", status: "excelRuntimePreview",
  sourceRows: 2, resultRows: 1, resultColumns: 2, beforeColumns: ["Sales", "Cost"], beforeRows: [[1500, 200]],
  afterColumns: ["Sales", "Cost"], afterRows: [[1500, 200]], runtimeEvidence: {excelVersion: "16.0", refreshSucceeded: true},
};
const calls = [];
let writes = 0;
const sandbox = {
  document: {getElementById: element, addEventListener() {}, createElement: () => ({})},
  window: {Office: {context: {requirements: {isSetSupported: () => true}}}},
  Office: {context: {requirements: {isSetSupported: () => true}}},
};

vm.runInNewContext(source + `
  globalThis.__state = state;
  globalThis.__create = createTypedPlan;
  globalThis.__preview = previewTypedPlan;
  globalThis.__approve = approveAndApplyTyped;
  globalThis.__revision = createTypedRevision;
  readWorkbook = async () => globalThis.__workbook;
  exportWorkbookBase64 = async () => "encoded-workbook";
  applyPQValuesToOpenWorkbook = async () => {
    globalThis.__writes += 1;
    return {resultSheetName: "PQ_Typed_Result", rowCount: 1, columnCount: 2, marker: "localDataCopilot.pqTypedResult.v2"};
  };
  renderTypedPlan = (value) => { state.pqTypedPlan = value; };
  renderTypedPreview = (value) => { state.pqTypedPreview = value; };
  renderTable = () => {};
  api = async (endpoint, payload) => globalThis.__api(endpoint, payload);
`, sandbox);
sandbox.__workbook = workbook;
sandbox.__writes = writes;
sandbox.__api = async (endpoint, payload) => {
  calls.push({endpoint, payload});
  if (endpoint === "/api/pq/v2/plans") return plan;
  if (endpoint === "/api/pq/v2/previews") return preview;
  if (endpoint === "/api/pq/v2/approvals") return {approvalId: "apr_a", status: "approved", revisionId: "rev_a", previewId: "prv_a"};
  if (endpoint === "/api/pq/v2/applies/prepare") return {applyId: "apply_a", resultWorkbookBase64: "values", resultWorkbookSheetName: "PQ_Typed_Result", expectedRows: 1, expectedColumns: 2};
  if (endpoint === "/api/pq/v2/applies/complete") return {applyId: "apply_a", status: "applied"};
  if (endpoint === "/api/pq/v2/revisions") return {...plan, revision: {...plan.revision, revisionId: "rev_b", parentRevisionId: "rev_a"}};
  throw new Error(`Unexpected endpoint ${endpoint}`);
};
sandbox.__state.officeReady = true;
sandbox.__state.codexAvailable = true;
sandbox.__state.workbook = workbook;
sandbox.__state.pqTypedMarker = "localDataCopilot.pqTypedResult.v2";
element("pq2-prompt").value = "Keep Sales above 1000";

(async () => {
  await sandbox.__create();
  assert.equal(calls[0].endpoint, "/api/pq/v2/plans");
  assert.equal(sandbox.__state.pqTypedPlan.revision.revisionId, "rev_a");
  await sandbox.__preview();
  assert.equal(calls[1].endpoint, "/api/pq/v2/previews");
  assert.equal(sandbox.__writes, 0, "preview must not write the open workbook");
  await sandbox.__approve();
  assert.deepEqual(calls.slice(2, 5).map((item) => item.endpoint), [
    "/api/pq/v2/approvals", "/api/pq/v2/applies/prepare", "/api/pq/v2/applies/complete",
  ]);
  assert.equal(sandbox.__writes, 1, "only approved prepare payload may reach the Office writer");
  assert.equal(calls[4].payload.readback.marker, "localDataCopilot.pqTypedResult.v2");
  await sandbox.__revision([{type: "setFinalOutput", stepId: "stp_source"}], "Changed final output");
  assert.equal(sandbox.__state.pqTypedPlan.revision.revisionId, "rev_b");
  assert.equal(sandbox.__state.pqTypedPreview, null, "editing must invalidate the old preview");
  assert.equal(sandbox.__state.pqTypedApproval, null, "editing must invalidate the old approval");
  console.log("taskpane Typed PQ flow test passed");
})().catch((error) => { console.error(error); process.exitCode = 1; });
