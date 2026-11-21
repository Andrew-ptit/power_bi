"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const taskpaneSource = require("../support/taskpane_source.js");

const source = taskpaneSource();
const elements = new Map();
const pageEvents = new Map();
let confirmationCount = 0;
let confirmationDecisions = [];
let workbookReads = 0;
let workbookExports = 0;

function element(id) {
  if (!elements.has(id)) {
    const listeners = new Map();
    const options = [];
    elements.set(id, {
      textContent: "", className: "", checked: false, disabled: false, value: "",
      classList: {toggle(_name, hidden) {
        if (id === "pq-confirm-overlay" && !hidden) {
          confirmationCount += 1;
          const accepted = confirmationDecisions.shift();
          setImmediate(() => element(accepted ? "pq-confirm-continue" : "pq-confirm-cancel").click());
        }
      }},
      get options() { return options; },
      replaceChildren() { options.length = 0; },
      appendChild(option) { options.push(option); },
      addEventListener(name, callback) { listeners.set(name, callback); },
      removeEventListener(name, callback) { if (listeners.get(name) === callback) listeners.delete(name); },
      click() { listeners.get("click")?.(); },
      focus() {}, setAttribute() {},
    });
  }
  return elements.get(id);
}

const policy = {
  policyId: "advanced-m-trusted-v1", mode: "trusted", enabled: true,
  riskAcknowledgementRequired: true, acknowledgementScope: "workbookPanelSession",
  externalConnectors: "allowed", previewIsolation: "temporaryWorkbookNotSandbox",
  applyToSource: "explicitConfirmation", backupPolicy: "none", autoSave: false,
};
const workbook = (name) => ({
  name, url: `file:///C:/${name}`, activeSheet: "Data", tables: [],
  sheets: [{name: "Data", headers: ["ID"], rows: [[1]]}],
});
const apiCalls = [];
let liveWorkbook = workbook("A.xlsx");
let closeRequest = null;
let fetchHandler = async (_path, options = {}) => {
  if (options.keepalive) {
    closeRequest = options;
    return {ok: true, json: async () => ({})};
  }
  throw new Error("Unexpected fetch");
};

const sandbox = {
  document: {
    getElementById: element, addEventListener() {}, removeEventListener() {}, createElement: () => ({setAttribute() {}, replaceChildren() {}, appendChild() {}}),
    querySelectorAll: () => [],
  },
  window: {
    Office: {context: {requirements: {isSetSupported: () => true}}},
    addEventListener(name, callback) { pageEvents.set(name, callback); },
  },
  Office: {context: {requirements: {isSetSupported: () => true}}},
  fetch: (...args) => fetchHandler(...args),
};

vm.runInNewContext(source + `
  globalThis.__state = state;
  globalThis.__bootstrap = bootstrap;
  globalThis.__apiCall = api;
  globalThis.__realApi = api;
  globalThis.__validPolicy = isValidAdvancedMPolicy;
  globalThis.__renderWorkbook = renderWorkbook;
  globalThis.__preview = previewPQ;
  globalThis.__updateButtons = updatePQButtons;
  readWorkbook = async () => { globalThis.__countWorkbookRead(); return globalThis.__liveWorkbook(); };
  exportWorkbookBase64 = async () => { globalThis.__countWorkbookExport(); return "encoded"; };
  applyPQValuesToOpenWorkbook = async () => ({resultSheetName: "PQ_Result", afterColumns: ["ID"], afterRows: [[1]]});
  renderTable = () => {};
  api = async (endpoint, payload) => globalThis.__mockApi(endpoint, payload);
`, sandbox);

sandbox.__liveWorkbook = () => liveWorkbook;
sandbox.__countWorkbookRead = () => { workbookReads += 1; };
sandbox.__countWorkbookExport = () => { workbookExports += 1; };
sandbox.__mockApi = async (endpoint, payload) => {
  apiCalls.push({endpoint, payload});
  if (endpoint === "/api/pq/run-sheet") return {
    status: "ready_for_open_workbook", resultWorkbookBase64: "values", sourceFingerprint: "f".repeat(64),
    sourceRows: 1, resultRows: 1, resultColumns: 1, beforeColumns: ["ID"], beforeRows: [[1]],
    afterColumns: ["ID"], afterRows: [[1]],
  };
  if (endpoint === "/api/pq/check-source") return {unchanged: true};
  throw new Error(`Unexpected API ${endpoint}`);
};

async function previewCurrent() {
  sandbox.__state.workbook = liveWorkbook;
  sandbox.__renderWorkbook();
  element("pq-code").value = "let Source = 1 in Source";
  await sandbox.__preview();
}

(async () => {
  assert.equal(sandbox.__validPolicy(policy), true);
  assert.equal(sandbox.__validPolicy({...policy, backupPolicy: "required"}), false);

  sandbox.__state.officeReady = true;
  sandbox.__state.capabilities.codexAnalysis = true;
  sandbox.__state.sessionId = "ses-1";
  sandbox.__state.advancedMPolicy = policy;
  confirmationDecisions = [true, true, false, true];

  await previewCurrent();
  liveWorkbook = workbook("B.xlsx");
  await previewCurrent();
  liveWorkbook = workbook("A.xlsx");
  await previewCurrent();
  assert.equal(confirmationCount, 2, "A -> B -> A must acknowledge only A and B");
  assert.equal(apiCalls.filter((call) => call.endpoint === "/api/pq/run-sheet").length, 3);
  assert.ok(apiCalls.filter((call) => call.endpoint === "/api/pq/run-sheet")
    .every((call) => call.payload.riskPolicyId === policy.policyId));

  liveWorkbook = workbook("C.xlsx");
  const callsBeforeCancel = apiCalls.length;
  const readsBeforeCancel = workbookReads;
  await previewCurrent();
  assert.equal(apiCalls.length, callsBeforeCancel, "cancel must make zero server calls");
  assert.equal(workbookReads, readsBeforeCancel, "cancel must make zero readWorkbook/Excel API calls");
  await previewCurrent();
  assert.equal(confirmationCount, 4, "cancelled acknowledgement must be requested again");

  const cachedD = workbook("D.xlsx");
  liveWorkbook = workbook("E.xlsx");
  sandbox.__state.workbook = cachedD;
  sandbox.__renderWorkbook();
  element("pq-code").value = "let Source = 1 in Source";
  confirmationDecisions = [true, false];
  const exportsBeforeStaleIdentity = workbookExports;
  const callsBeforeStaleIdentity = apiCalls.length;
  await sandbox.__preview();
  assert.equal(workbookExports, exportsBeforeStaleIdentity,
    "identity changed after re-read and cancelled must not export workbook");
  assert.equal(apiCalls.length, callsBeforeStaleIdentity,
    "identity changed after re-read and cancelled must not run M");
  confirmationDecisions = [true];
  await previewCurrent();
  assert.equal(apiCalls.filter((call) => call.endpoint === "/api/pq/run-sheet").length, 5,
    "cancelled acknowledgement for re-read identity must not be remembered");

  sandbox.__state.advancedMPolicy = null;
  sandbox.__updateButtons();
  assert.equal(element("pq-propose-button").disabled, true);
  assert.equal(element("pq-preview-button").disabled, true);
  assert.equal(element("pq-apply-source-button").disabled, true);

  sandbox.__state.advancedMPolicy = policy;
  sandbox.__state.sessionId = "";
  sandbox.__updateButtons();
  assert.equal(element("pq-preview-button").disabled, true, "missing authoritative session must fail closed");

  sandbox.__state.token = "secret-token";
  pageEvents.get("pagehide")();
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(closeRequest.keepalive, true);
  assert.equal(closeRequest.headers["X-Local-Token"], "secret-token");

  let expiredPosts = 0;
  let bootstraps = 0;
  fetchHandler = async (requestPath, options = {}) => {
    if (requestPath === "/api/example") {
      expiredPosts += 1;
      return {ok: false, status: 401, json: async () => ({error: {code: "TOKEN_EXPIRED", detail: "Expired"}})};
    }
    if (requestPath === "/api/bootstrap") {
      bootstraps += 1;
      return {ok: true, json: async () => ({
        token: "new-token", session: {sessionId: "ses-2"},
        capabilities: {codexAnalysis: true, advancedMPolicy: policy},
      })};
    }
    throw new Error(`Unexpected fetch ${requestPath}`);
  };
  await assert.rejects(sandbox.__realApi("/api/example", {value: 1}), (error) => {
    assert.equal(error.code, "TOKEN_EXPIRED");
    assert.match(error.message, /không được tự chạy lại/);
    return true;
  });
  assert.equal(expiredPosts, 1, "expired POST must never be replayed");
  assert.equal(bootstraps, 1);
  assert.equal(sandbox.__state.token, "new-token");
  assert.equal(sandbox.__state.sessionId, "ses-2");

  let missingTokenPosts = 0;
  fetchHandler = async (requestPath) => {
    if (requestPath === "/api/example") {
      missingTokenPosts += 1;
      return {ok: false, status: 403, json: async () => ({error: {code: "TOKEN_REQUIRED", detail: "Missing token"}})};
    }
    if (requestPath === "/api/bootstrap") {
      bootstraps += 1;
      return {ok: true, json: async () => ({
        token: "recovered-token", session: {sessionId: "ses-3"},
        capabilities: {codexAnalysis: true, advancedMPolicy: policy},
      })};
    }
    throw new Error(`Unexpected fetch ${requestPath}`);
  };
  await assert.rejects(sandbox.__realApi("/api/example", {value: 2}), (error) => {
    assert.equal(error.code, "TOKEN_REQUIRED");
    assert.match(error.message, /Đọc lại workbook/);
    return true;
  });
  assert.equal(missingTokenPosts, 1, "missing-token POST must never be replayed");
  assert.equal(bootstraps, 2);
  assert.equal(sandbox.__state.token, "recovered-token");

  fetchHandler = async (requestPath) => {
    if (requestPath === "/api/example") return {
      ok: false, status: 429,
      headers: {get: (name) => name === "Retry-After" ? "60" : null},
      json: async () => ({error: {code: "CODEX_RATE_LIMITED", detail: "Codex rate limit was reached"}}),
    };
    throw new Error(`Unexpected fetch ${requestPath}`);
  };
  await assert.rejects(sandbox.__realApi("/api/example", {value: 3}), (error) => {
    assert.equal(error.code, "CODEX_RATE_LIMITED");
    assert.match(error.message, /60 giây/);
    return true;
  });

  sandbox.AbortController = AbortController;
  sandbox.setTimeout = (callback) => { callback(); return 1; };
  sandbox.clearTimeout = () => {};
  fetchHandler = async (_requestPath, options) => {
    assert.equal(options.signal.aborted, true);
    const error = new Error("aborted");
    error.name = "AbortError";
    throw error;
  };
  await assert.rejects(sandbox.__realApi("/api/example", {value: 4}, {timeoutMs: 1000}), (error) => {
    assert.equal(error.code, "COORDINATOR_TIMEOUT");
    return true;
  });
  console.log("taskpane Advanced M policy test passed");
})().catch((error) => { console.error(error); process.exitCode = 1; });
