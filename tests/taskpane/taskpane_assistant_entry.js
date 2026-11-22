"use strict";
// T404: single entry guards for the three-step assistant journey.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const api = require(path.join(__dirname, "../../pbip_assistant/excel_addin/assistant_entry.js"));

class Node {
  constructor() { this.hidden = false; this.disabled = false; this.textContent = ""; this.listeners = {}; this.attrs = {}; this.children = []; }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  setAttribute(name, value) { this.attrs[name] = value; }
  replaceChildren(...children) { this.children = children; }
  append(...children) { this.children.push(...children); }
  async click() { if (!this.disabled) await this.listeners.click?.(); }
}

function harness(overrides = {}) {
  const nodes = new Map();
  const document = {body: new Node(), getElementById: id => { if (!nodes.has(id)) nodes.set(id, new Node()); return nodes.get(id); }, createElement: () => new Node()};
  const calls = [];
  const options = {
    document,
    selectWorkbook: async () => { calls.push("workbook"); return true; },
    scanWorkbook: async request => { calls.push("scan"); request?.onProgress?.({message: "Đang đọc lại nguồn…"}); return {state: {sourceHash: "hash", sources: [{sheetId: "s1"}, {sheetId: "s2"}]}}; },
    onUnderstand: async () => { calls.push("measure"); return {modelView: {mode: "model", counts: {tables: 2, relationships: 1, needsConfirm: 1, warnings: 0}}}; },
    showProblem: async () => { calls.push("problem"); },
    onBrowse: options => calls.push(["browse", options]),
    onImported: () => calls.push("imported"),
    invalidateBusiness: () => calls.push("invalidated"),
    ...overrides
  };
  const entry = api.mount(options);
  return {entry, get: document.getElementById, calls};
}

(async () => {
  const html = fs.readFileSync(path.join(__dirname, "../../pbip_assistant/excel_addin/taskpane.html"), "utf8");

  // 1. The journey has three steps and no cleaning step.
  {
    assert(html.includes('id="assistant-step-source"'));
    assert(html.includes('id="assistant-step-understand"'));
    assert(html.includes('id="assistant-step-problem"'));
    assert(!html.includes('id="assistant-step-clean"'), "the cleaning journey step is removed");
    assert(html.includes(">2. Hiểu dữ liệu<") && html.includes(">3. Đề bài<"), "the understand step is labelled 2");
    const {entry, get} = harness();
    assert.equal(entry.state().step, "source");
    assert(get("assistant-step-understand").disabled);
    assert(get("assistant-step-problem").disabled);
    assert.deepEqual(get("assistant-step-source").attrs["aria-current"], "step");
  }

  // 2. No cleaning wizard DOM is left in the assistant tab.
  {
    for (const id of ["preparation-wizard", "preparation-date-system", "preparation-scan", "preparation-inventory", "preparation-panel", "preparation-message", "assistant-folder-result", "assistant-import-actions", "assistant-selected-count"]) {
      assert(!html.includes(`id="${id}"`), `#${id} must be removed`);
    }
    assert(!html.includes(">2. Làm sạch<"), "no cleaning step label");
  }

  // 3. Reading the workbook measures automatically and lands on the understand step.
  {
    const {entry, get, calls} = harness();
    await get("assistant-choose-workbook").click();
    assert.deepEqual(calls.filter(value => typeof value === "string"), ["workbook", "scan", "invalidated", "measure"]);
    assert.equal(entry.state().step, "understand");
    assert.equal(entry.state().understandReady, true);
    assert.equal(get("assistant-understand-section").hidden, false);
    assert.equal(get("assistant-step-problem").disabled, false);
    assert.equal(get("assistant-understand-continue").disabled, false);
    // No plan-draft request exists anywhere in this flow.
    assert.equal(calls.filter(value => value === "problem").length, 0);
    entry.updateWorkbook({name: "Orders", hasData: true});
    assert.equal(entry.state().step, "source");
    assert(get("assistant-step-understand").disabled);
    assert(get("assistant-step-problem").disabled);
  }

  // 4. The workbook branch re-reads and never imports or writes cells.
  {
    const writes = [];
    const {get, calls, entry} = harness({scanWorkbook: async () => {
      calls.push("scan-only");
      return {state: {sourceHash: "hash", sources: [{sheetId: "s1"}]}};
    }, onImported: () => writes.push("import")});
    await get("assistant-choose-workbook").click();
    assert.deepEqual(calls.filter(value => value === "scan-only"), ["scan-only"]);
    assert.deepEqual(writes, [], "choosing workbook data must not import files");
    assert.equal(calls.filter(value => value === "measure").length, 1);
    assert.equal(entry.state().step, "understand");
    // Continue moves to Đề bài exactly once.
    await get("assistant-understand-continue").click();
    assert.equal(calls.filter(value => value === "problem").length, 1);
    assert.equal(entry.state().step, "problem");
  }

  // 5. A failed re-read keeps both gates disabled and offers a retry.
  {
    let fail = true, reads = 0;
    const {entry, get, calls} = harness({scanWorkbook: async () => {
      reads++;
      if (fail) throw new Error("Workbook read failed");
      return {state: {sourceHash: "hash", sources: [{sheetId: "s1"}]}};
    }});
    await get("assistant-choose-workbook").click();
    assert.equal(reads, 1);
    assert(get("assistant-step-understand").disabled);
    assert(get("assistant-step-problem").disabled);
    assert.equal(get("assistant-retry-scan").hidden, false);
    assert.match(get("assistant-source-message").textContent, /Workbook read failed/);
    assert.equal(calls.includes("problem"), false, "a failed read never opens Đề bài");
    fail = false;
    await get("assistant-retry-scan").click();
    assert.equal(reads, 2);
    assert.equal(calls.filter(value => value === "measure").length, 1);
    assert.equal(get("assistant-step-problem").disabled, false);
    assert.equal(entry.state().step, "understand");
  }

  // 6. An import hands the receipt to the journey, which re-reads and measures.
  {
    let scans = 0;
    const {entry, get} = harness({scanWorkbook: async () => {
      scans++;
      return {state: {sourceHash: "hash", sources: [{sheetId: "s1"}]}};
    }});
    await entry.imported({status: "verified"});
    assert.equal(scans, 1);
    assert.equal(entry.state().step, "understand");
    assert.equal(entry.state().understandReady, true);
  }

  // 7. + Thêm nguồn returns to the browser without losing the folder.
  {
    const {get, calls} = harness();
    await get("assistant-add-source").click();
    assert.deepEqual(calls.at(-1), ["browse", {reopen: true}]);
  }

  // 8. Busy state keeps the actions disabled.
  {
    const {entry, get} = harness();
    entry.setBusy(true);
    assert(get("assistant-choose-folder").disabled);
    assert(get("assistant-choose-workbook").disabled);
    assert(get("assistant-step-understand").disabled);
    entry.setBusy(false);
    assert.equal(get("assistant-choose-folder").disabled, false);
  }

  // 9. No usable workbook data keeps the gates off and explains why (S13).
  {
    const {entry, get, calls} = harness({
      selectWorkbook: async () => { calls.push("workbook"); return false; },
      scanWorkbook: async () => { throw new Error("the scan must not run without usable data"); }
    });
    await get("assistant-choose-workbook").click();
    assert.deepEqual(calls.filter(value => typeof value === "string"), ["workbook"]);
    assert(get("assistant-step-understand").disabled);
    assert(get("assistant-step-problem").disabled);
    assert.equal(get("assistant-retry-scan").hidden, true, "missing data is not a scan failure");
    assert.match(get("assistant-source-message").textContent, /Workbook chưa có dữ liệu phù hợp/);
    assert.equal(entry.state().canUnderstand, false);
  }

  // 10. A failed measure leaves Đề bài off; Đo lại retries and Về Nguồn returns.
  {
    let fail = true;
    const {entry, get, calls} = harness({onUnderstand: async () => {
      calls.push("measure");
      if (fail) throw Object.assign(new Error("Chưa đo được cấu trúc."), {code: "AF_UNDERSTAND_INVALID"});
      return {modelView: {mode: "model"}};
    }});
    await get("assistant-choose-workbook").click();
    assert.equal(entry.state().step, "understand");
    assert.equal(entry.state().understandReady, false);
    assert(get("assistant-step-problem").disabled);
    assert.equal(get("assistant-understand-continue").disabled, true);
    fail = false;
    await get("assistant-understand-retry").click();
    assert.equal(entry.state().understandReady, true);
    assert.equal(get("assistant-step-problem").disabled, false);
    await get("assistant-understand-back").click();
    assert.equal(entry.state().step, "source");
  }

  console.log("Assistant single entry guards passed");
})().catch(error => { console.error(error); process.exit(1); });