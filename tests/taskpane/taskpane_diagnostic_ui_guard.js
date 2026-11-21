"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const taskpaneSource = require("../support/taskpane_source.js");

const source = taskpaneSource();

function makeElement(id = "") {
  const children = [];
  const classes = new Set();
  const attributes = new Map();
  return {
    id, children, textContent: "", className: "", value: "", checked: false, disabled: false,
    options: [], dataset: {}, style: {},
    classList: {
      toggle(name, enabled) { if (enabled) classes.add(name); else classes.delete(name); },
      add(name) { classes.add(name); },
      remove(name) { classes.delete(name); },
      contains(name) { return classes.has(name); },
    },
    addEventListener() {},
    setAttribute(name, value) { attributes.set(name, value); },
    getAttribute(name) { return attributes.get(name); },
    focus() {}, remove() {},
    append(...items) { children.push(...items); },
    appendChild(item) { children.push(item); return item; },
    replaceChildren(...items) { children.splice(0, children.length, ...items); },
  };
}

const elements = new Map();
function element(id) {
  if (!elements.has(id)) elements.set(id, makeElement(id));
  return elements.get(id);
}

const workbookA = {
  name: "A.xlsx", url: "file:///C:/A.xlsx", activeSheet: "Sales",
  activeCell: {rowIndex: 1, columnIndex: 0}, sheets: [],
  tables: [{name: "tblSales", sheet: "Sales", headers: ["OrderID"], rows: [["A-1"]],
    totalRows: 1, totalColumns: 1, rowIndex: 0, columnIndex: 0}],
};
const workbookB = {...workbookA, name: "B.xlsx", url: "file:///C:/B.xlsx"};
const revision = {
  revisionId: "rev_head", parentRevisionId: null, reviewHash: "sha256:review",
  changeReason: "Root", problemPrompt: "Load Sales", steps: [],
};
const plan = {
  schemaVersion: "2.0", planId: "plan_a", snapshotId: "snap_a",
  revision, planStatus: "reviewReady", summary: "Load Sales", questions: [], assumptions: [],
  warnings: [], hardBlockers: [], sources: [], finalOutputStepId: "stp_source", changeSet: [],
  steps: [{
    stepId: "stp_source", position: 1, variableName: "SalesSource", actionDescription: "Load Sales",
    operation: {type: "source.workbookTable", parameters: {sourceId: "src_sales"}}, inputs: [],
    outputContract: {kind: "table", columns: [{columnId: "col_order", name: "OrderID", type: "text"}]},
  }],
};

const calls = [];
const sandbox = {
  document: {
    getElementById: element,
    addEventListener() {},
    createElement(tag) { return makeElement(tag); },
  },
  window: {
    Office: {context: {requirements: {isSetSupported: () => true}}},
    addEventListener() {},
  },
  Office: {context: {requirements: {isSetSupported: () => true}}},
  console, setTimeout, clearTimeout,
};

vm.runInNewContext(source + `
  globalThis.__state = state;
  globalThis.__renderPlan = renderTypedPlan;
  globalThis.__createProblem = createProblemContinuation;
  globalThis.__acceptWorkbookRead = acceptWorkbookRead;
  globalThis.__callApi = api;
  api = async (endpoint, payload) => globalThis.__api(endpoint, payload);
  readWorkbook = async () => globalThis.__freshWorkbook;
  loadSelectedSourceCheckSample = async () => {};
`, sandbox);

sandbox.__api = async (endpoint, payload) => {
  calls.push({endpoint, payload});
  throw new Error(`Unexpected endpoint ${endpoint}`);
};

function findButton(root, label) {
  if ((root?.textContent === label || root?.getAttribute?.("aria-label") === label) && root?.type === "button") return root;
  for (const child of root?.children || []) {
    const found = findButton(child, label);
    if (found) return found;
  }
  return null;
}

(async () => {
  sandbox.__state.officeReady = true;
  sandbox.__state.capabilities.codexAnalysis = true;
  sandbox.__state.sessionId = "ses_test";
  sandbox.__state.workbook = workbookA;
  sandbox.__state.pqWorkbookKey = "file:///C:/A.xlsx\u0000A.xlsx";
  sandbox.__state.problemChainSupported = true;
  sandbox.__state.problemChainHydrated = true;
  sandbox.__state.problemChainDocument = {
    chainId: "chain_a", headRevisionId: revision.revisionId, revisions: [revision],
  };
  sandbox.__state.problemChainHistoryHash = "sha256:history";
  sandbox.__state.problemChainViewRevisionId = revision.revisionId;
  sandbox.__state.pqTypedPlan = plan;

  // A new task-pane asset against an older coordinator must fail closed.
  sandbox.__state.typedStepDiagnosticsCapability = false;
  sandbox.__renderPlan(plan);
  const diagnosticButton = findButton(element("pq2-step-list"), "Chạy đến SalesSource");
  assert.ok(diagnosticButton, "diagnostic action must be rendered explicitly");
  assert.equal(diagnosticButton.disabled, true, "missing bootstrap capability must disable diagnostic action");
  assert.equal(calls.length, 0, "rendering a disabled action must not call an unavailable endpoint");

  // If Excel switches A -> B while a continuation is starting, the old chain
  // must be dropped and the POST must not be replayed against workbook B.
  sandbox.__freshWorkbook = workbookB;
  element("pqpc-prompt").value = "Continue old chain";
  await sandbox.__createProblem();
  assert.equal(calls.length, 0, "workbook switch must stop before problem/diagnostic API calls");
  assert.equal(sandbox.__state.workbook.name, "B.xlsx");
  assert.equal(sandbox.__state.problemChainHydrated, false);
  assert.equal(sandbox.__state.problemChainDocument, null);
  assert.equal(sandbox.__state.problemChainHistoryHash, null);
  assert.equal(sandbox.__state.pqTypedPlan, null);
  assert.equal(element("error-code").textContent, "PQPC_WORKBOOK_CHANGED");
  assert.match(element("error-detail").textContent, /Workbook đã đổi/);

  // Stale Python coordinator and malformed proxy responses should produce
  // actionable, stable codes rather than leaking JSON/SyntaxError details.
  sandbox.fetch = async () => ({
    ok: false, status: 404,
    async text() { return JSON.stringify({error: {code: "NOT_FOUND", detail: "Endpoint not found"}}); },
  });
  await assert.rejects(
    () => sandbox.__callApi("/api/pq/v2/step-diagnostics/runs", {}),
    (error) => error.code === "COORDINATOR_RESTART_REQUIRED" && /chạy bản cũ/.test(error.message),
  );
  sandbox.fetch = async () => ({ok: false, status: 502, async text() { return "<html>bad gateway</html>"; }});
  await assert.rejects(
    () => sandbox.__callApi("/api/pq/v2/step-diagnostics/runs", {}),
    (error) => error.code === "COORDINATOR_RESPONSE_INVALID" && /HTTP 502/.test(error.message),
  );

  console.log("taskpane diagnostic UI guard tests passed");
})().catch((error) => { console.error(error); process.exitCode = 1; });
