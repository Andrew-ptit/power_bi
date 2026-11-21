"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const crypto = require("node:crypto");
const root = path.join(__dirname, "../../pbip_assistant/excel_addin");

async function exerciseStartup() {
  const html = fs.readFileSync(path.join(root, "taskpane.html"), "utf8");
  const nodes = new Map();
  function node() {
    return {children: [], dataset: {}, value: "", disabled: false, hidden: false, textContent: "", listeners: {},
      classList: {toggle() {}, add() {}, remove() {}},
      setAttribute() {}, append(...children) { this.children.push(...children); },
      appendChild(child) { this.children.push(child); }, replaceChildren(...children) { this.children = children; },
      addEventListener(name, listener) { (this.listeners[name] ||= []).push(listener); },
      async click() { if (!this.disabled) for (const listener of this.listeners.click || []) await listener(); }};
  }
  for (const match of html.matchAll(/<[^>]+\bid="([^"]+)"[^>]*>/g)) {
    const el = node(); el.disabled = /\bdisabled\b/.test(match[0]); el.hidden = /\bhidden\b/.test(match[0]);
    nodes.set(match[1], el);
  }
  const get = id => nodes.get(id) || null;
  assert(get("assistant-choose-folder").disabled, "source actions must wait for initialization in the actual HTML");
  assert(get("assistant-reconnect"), "a failed bootstrap must have a visible recovery action");
  let bootstrapCount = 0, pickerCount = 0, reads = 0;
  const sandbox = {console, TextEncoder, crypto: crypto.webcrypto,
    document: {getElementById: get, body: node(), createElement: node, addEventListener() {}}, addEventListener() {},
    Office: {HostType: {Excel: "Excel"}, onReady: async () => ({host: "Excel"}),
      context: {requirements: {isSetSupported: () => true}}}, Excel: {},
    fetch: async url => {
      if (url === "/api/bootstrap") {
        bootstrapCount++;
        if (bootstrapCount === 1) return {ok: false, status: 429, json: async () => ({error: {code: "COORDINATOR_BUSY", detail: "Session is closing"}})};
        return {ok: true, json: async () => ({token: "synthetic", session: {sessionId: "synthetic"},
          capabilities: {preparationReadV1: true, preparationFolderPicker: true, assistantFlowV2: true, codexAnalysis: false}})};
      }
      assert.equal(url, "/api/preparation/pick-folder"); pickerCount++;
      return {ok: true, json: async () => ({cancelled: true})};
    }};
  sandbox.window = sandbox;
  vm.createContext(sandbox);
  for (const filename of ["assistant_custom_xml.js", "preparation_runtime.js", "preparation_session.js",
    "preparation_bridge.js", "preparation_controller.js", "assistant_entry.js",
    "taskpane_core.js", "taskpane_flow.js", "taskpane_workspace.js", "taskpane_problem_chain.js",
    "taskpane_typed_pq.js", "taskpane.js"]) {
    vm.runInContext(fs.readFileSync(path.join(root, filename), "utf8"), sandbox, {filename});
  }
  sandbox.readSyntheticWorkbook = async () => { reads++; };
  // Other pane bindings and workbook reads are outside this startup regression.
  vm.runInContext("bindEvents=()=>{};refreshWorkbook=readSyntheticWorkbook;flowLoadState=async()=>{};hydrateProblemChain=async()=>{};globalThis.boot=start;", sandbox);
  await sandbox.boot();
  assert.equal(reads, 0, "a failed bootstrap cannot read a workbook or present a ready journey");
  assert(get("assistant-choose-folder").disabled);
  assert.equal(get("assistant-reconnect").hidden, false);
  assert(get("assistant-source-message").textContent.length > 0);
  await get("assistant-reconnect").click();
  assert.equal(bootstrapCount, 2, "recovery explicitly retries bootstrap once");
  assert.equal(reads, 1);
  assert.equal(get("assistant-reconnect").hidden, true);
  assert.equal(get("assistant-choose-folder").disabled, false);
  await get("assistant-choose-folder").click();
  assert.equal(pickerCount, 1, "the recovered actual taskpane sends exactly one picker request");
  assert.equal(get("assistant-choose-folder").disabled, false, "cancel releases the source action");
  assert.equal((get("assistant-choose-folder").listeners.click || []).length, 1, "retry must not duplicate bindings");
}
exerciseStartup().then(() => console.log("preparation startup recovery passed")).catch(error => { console.error(error); process.exitCode = 1; });
