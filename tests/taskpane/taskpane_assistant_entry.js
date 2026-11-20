"use strict";
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

  // 1. The journey has two steps and no cleaning step.
  {
    assert(html.includes('id="assistant-step-source"'));
    assert(html.includes('id="assistant-step-problem"'));
    assert(!html.includes('id="assistant-step-clean"'), "the cleaning journey step is removed");
    assert(html.includes(">2. Đề bài<"), "the problem step is labelled 2");
    const {entry, get} = harness();
    assert.equal(entry.state().step, "source");
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

  // 3. Reading the workbook only enables Đề bài after a verified re-read.
  {
    const {entry, get, calls} = harness();
    await get("assistant-choose-workbook").click();
    assert.deepEqual(calls.filter(value => typeof value === "string"), ["workbook", "scan"]);
    assert.equal(get("assistant-step-problem").disabled, false);
    await get("assistant-step-problem").click();
    assert(calls.includes("problem"));
    assert.equal(entry.state().step, "problem");
    entry.updateWorkbook({name: "Orders", hasData: true});
    assert.equal(entry.state().step, "source");
    assert(get("assistant-step-problem").disabled);
  }

  // 4. The workbook branch re-reads and never imports or writes cells.
  {
    const writes = [];
    const {get, calls} = harness({scanWorkbook: async () => {
      calls.push("scan-only");
      return {state: {sourceHash: "hash", sources: [{sheetId: "s1"}]}};
    }, onImported: () => writes.push("import")});
    await get("assistant-choose-workbook").click();
    assert.deepEqual(calls.filter(value => value === "scan-only"), ["scan-only"]);
    assert.deepEqual(writes, [], "choosing workbook data must not import files");
    assert.equal(get("assistant-step-problem").disabled, false);
  }

  // 5. A failed re-read keeps Đề bài disabled and offers a retry.
  {
    let fail = true, reads = 0;
    const {entry, get} = harness({scanWorkbook: async () => {
      reads++;
      if (fail) throw new Error("Workbook read failed");
      return {state: {sourceHash: "hash", sources: [{sheetId: "s1"}]}};
    }});
    await get("assistant-choose-workbook").click();
    assert.equal(reads, 1);
    assert(get("assistant-step-problem").disabled);
    assert.equal(get("assistant-retry-scan").hidden, false);
    assert.match(get("assistant-source-message").textContent, /Workbook read failed/);
    fail = false;
    await get("assistant-retry-scan").click();
    assert.equal(reads, 2);
    assert.equal(get("assistant-step-problem").disabled, false);
    assert.equal(get("assistant-retry-scan").hidden, true);
    assert.equal(entry.state().canProblem, true);
  }

  // 6. An import hands the receipt to the journey, which re-reads before enabling Đề bài.
  {
    let scans = 0;
    const {entry, get} = harness({scanWorkbook: async () => {
      scans++;
      return {state: {sourceHash: "hash", sources: [{sheetId: "s1"}]}};
    }});
    await entry.imported({status: "verified"});
    assert.equal(scans, 1);
    assert.equal(get("assistant-step-problem").disabled, false);
    assert.match(get("assistant-source-message").textContent, /Đã đọc lại 1 nguồn/);
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
    entry.setBusy(false);
    assert.equal(get("assistant-choose-folder").disabled, false);
  }

  console.log("Assistant single entry guards passed");
})().catch(error => { console.error(error); process.exit(1); });
