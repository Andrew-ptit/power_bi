"use strict";

// Independent reviewer oracle for Trusted Advanced M.  It drives the real
// task-pane functions through policy/session/workbook changes and separate
// source-Apply attempts; no production function is replaced except external
// Office/server boundaries.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../pbip_assistant/excel_addin/taskpane.js"), "utf8");
const elements = new Map();
let decisions = [];
let dialogs = 0;

function element(id) {
  if (!elements.has(id)) {
    const listeners = new Map();
    const options = [];
    elements.set(id, {
      textContent: "", className: "", checked: false, disabled: false, value: "",
      classList: {toggle(_name, hidden) {
        if (id === "pq-confirm-overlay" && !hidden) {
          dialogs += 1;
          const accepted = decisions.shift();
          setImmediate(() => element(accepted ? "pq-confirm-continue" : "pq-confirm-cancel").click());
        }
      }},
      get options() { return options; },
      replaceChildren() { options.length = 0; },
      appendChild(option) { options.push(option); },
      addEventListener(name, callback) { listeners.set(name, callback); },
      removeEventListener(name, callback) { if (listeners.get(name) === callback) listeners.delete(name); },
      click() { listeners.get("click")?.(); },
      focus() {}, setAttribute() {}, append() {},
    });
  }
  return elements.get(id);
}

const policy = (id) => ({
  policyId: id, mode: "trusted", enabled: true,
  riskAcknowledgementRequired: true, acknowledgementScope: "workbookPanelSession",
  externalConnectors: "allowed", previewIsolation: "temporaryWorkbookNotSandbox",
  applyToSource: "explicitConfirmation", backupPolicy: "none", autoSave: false,
});
const workbook = (name) => ({
  name, url: `file:///C:/${name}`, activeSheet: "Data", tables: [],
  sheets: [{name: "Data", headers: ["ID"], rows: [[1]]}],
});

let liveWorkbook = workbook("A.xlsx");
const apiCalls = [];
let writes = 0;
let workbookReads = 0;
const sandbox = {
  document: {
    getElementById: element, addEventListener() {}, removeEventListener() {},
    createElement: () => ({append() {}, setAttribute() {}}), querySelectorAll: () => [],
  },
  window: {Office: {context: {requirements: {isSetSupported: () => true}}}, addEventListener() {}},
  Office: {context: {requirements: {isSetSupported: () => true}}},
  fetch: async () => { throw new Error("Unexpected fetch"); },
};

vm.runInNewContext(source + `
  globalThis.__state = state;
  globalThis.__preview = previewPQ;
  globalThis.__apply = applyPQPreviewToSource;
  readWorkbook = async () => globalThis.__liveWorkbook();
  exportWorkbookBase64 = async () => "encoded";
  renderWorkbook = () => {};
  renderTable = () => {};
  applyPQValuesToOpenWorkbook = async () => ({resultSheetName: "PQ_Result", afterColumns: ["ID"], afterRows: [[1]]});
  applyPQValuesToSource = async () => { globalThis.__write(); return {sourceSheetName: "Data", rowCount: 1, columnCount: 1, afterColumns: ["ID"], afterRows: [[1]]}; };
  api = async (endpoint, payload) => globalThis.__api(endpoint, payload);
`, sandbox);

sandbox.__liveWorkbook = () => { workbookReads += 1; return liveWorkbook; };
sandbox.__write = () => { writes += 1; };
sandbox.__api = async (endpoint, payload) => {
  apiCalls.push({endpoint, payload});
  if (endpoint === "/api/pq/run-sheet") return {
    status: "ready_for_open_workbook", resultWorkbookBase64: "values", resultWorkbookSheetName: "PQ_Result_Values",
    sourceFingerprint: "f".repeat(64), sourceRows: 1, resultRows: 1, resultColumns: 1,
    beforeColumns: ["ID"], beforeRows: [[1]], afterColumns: ["ID"], afterRows: [[1]],
  };
  if (endpoint === "/api/pq/check-source") return {unchanged: true};
  throw new Error(`Unexpected endpoint ${endpoint}`);
};

async function preview() {
  sandbox.__state.workbook = liveWorkbook;
  sandbox.__state.pqPinnedSource = {kind: "sheet", sheet: "Data", headerRow: 1};
  element("pq-code").value = "let Source = Excel.CurrentWorkbook() in Source";
  await sandbox.__preview();
}

(async () => {
  sandbox.__state.officeReady = true;
  sandbox.__state.codexAvailable = true;
  sandbox.__state.sessionId = "session-1";
  sandbox.__state.advancedMPolicy = policy("advanced-m-trusted-v1");
  decisions = [true, true, true, false];

  await preview();
  await preview();
  assert.equal(dialogs, 1, "same session/policy/workbook must reuse acknowledgement");

  sandbox.__state.advancedMPolicy = policy("advanced-m-trusted-v2");
  await preview();
  assert.equal(dialogs, 2, "policy version change must require a new acknowledgement");
  assert.equal(apiCalls.filter((call) => call.endpoint === "/api/pq/run-sheet").at(-1).payload.riskPolicyId, "advanced-m-trusted-v2");

  sandbox.__state.sessionId = "session-2";
  await preview();
  assert.equal(dialogs, 3, "session change must require a new acknowledgement");

  liveWorkbook = workbook("B.xlsx");
  const runCount = apiCalls.filter((call) => call.endpoint === "/api/pq/run-sheet").length;
  const readsBeforeCancel = workbookReads;
  await preview();
  assert.equal(dialogs, 4);
  assert.equal(apiCalls.filter((call) => call.endpoint === "/api/pq/run-sheet").length, runCount, "cancel must not call run-sheet");
  assert.equal(workbookReads, readsBeforeCancel, "cancel must happen before any new Excel workbook read");

  liveWorkbook = workbook("A.xlsx");
  sandbox.__state.advancedMPolicy = policy("advanced-m-trusted-v2");
  const previewRecord = {
    status: "ready_for_open_workbook", code: element("pq-code").value,
    expectedWorkbook: {name: liveWorkbook.name, url: liveWorkbook.url},
    source: {kind: "sheet", sheet: "Data", headerRow: 1}, sourceFingerprint: "f".repeat(64),
    previewSheetName: "PQ_Result", resultRows: 1, resultColumns: 1, applied: false,
  };
  decisions = [true, false, true];
  for (const expectedWrites of [1, 1, 2]) {
    sandbox.__state.pqPreview = {...previewRecord};
    await sandbox.__apply();
    assert.equal(writes, expectedWrites);
  }
  assert.equal(dialogs, 7, "every source Apply attempt must show its own confirmation");
  console.log("taskpane Advanced M independent cross-check passed");
})().catch((error) => { console.error(error); process.exitCode = 1; });
