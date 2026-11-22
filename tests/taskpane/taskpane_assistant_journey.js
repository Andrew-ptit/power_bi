"use strict";
// T404: the three-step journey (Nguồn → Hiểu dữ liệu → Đề bài) wired to the browser.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const entryApi = require(path.join(__dirname, "../../pbip_assistant/excel_addin/assistant_entry.js"));
const browserApi = require(path.join(__dirname, "../../pbip_assistant/excel_addin/assistant_browser.js"));

class Node {
  constructor() { this.hidden = false; this.disabled = false; this.textContent = ""; this.className = ""; this.type = ""; this.checked = false; this.listeners = {}; this.attrs = {}; this.children = []; }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  setAttribute(name, value) { this.attrs[name] = value; }
  replaceChildren(...children) { this.children = children; }
  append(...children) { this.children.push(...children); }
  async click() { if (!this.disabled) await this.listeners.click?.(); }
  async change(checked) { this.checked = checked; await this.listeners.change?.(); }
}

function files(list) { return list.children.filter(row => row.children[0]?.type === "checkbox"); }

function harness({scanFails = false, measureFails = false} = {}) {
  const nodes = new Map();
  const document = {body: new Node(), getElementById: id => { if (!nodes.has(id)) nodes.set(id, new Node()); return nodes.get(id); }, createElement: () => new Node()};
  const calls = {browse: [], pick: 0, probe: 0, imports: 0, scans: 0, reopen: 0, measures: 0, problems: 0};
  const bridge = {
    pickRoot: async () => { calls.pick++; return {cancelled: false, rootName: "dataset"}; },
    browse: async relativePath => {
      calls.browse.push(relativePath);
      return relativePath === ""
        ? {rootName: "dataset", relativePath: "", parentRelativePath: null, breadcrumb: [{name: "dataset", relativePath: ""}],
           entries: [{name: "sales", kind: "folder"}, {name: "root.csv", kind: "file", extension: "csv"}], truncated: false}
        : {rootName: "dataset", relativePath: "sales", parentRelativePath: "", breadcrumb: [{name: "dataset", relativePath: ""}, {name: "sales", relativePath: "sales"}],
           entries: [{name: "jan.csv", kind: "file", extension: "csv"}, {name: "bad.csv", kind: "file", extension: "csv"}], truncated: false};
    },
    probeDateSystem: async () => { calls.probe++; return "1900"; },
    importSelection: async ({items, dateSystem, onProgress}) => {
      calls.imports++;
      onProgress({processed: 1, total: 2, fileId: "f1"});
      return {status: "verified", inventory: {files: [], sheets: []},
        report: {totals: {files: 2, sheets: 2, skipped: 0, decisions: 0}, files: [
          {fileId: "f1", fileName: "jan.csv", status: "imported", decisions: [], readingDecisions: [], issues: []},
          {fileId: "f2", fileName: "bad.csv", status: "skipped", decisions: [], readingDecisions: [], issues: [{code: "CSV_COLUMN_COUNT", message: "Bad row"}]}
        ]}};
    },
    scanWorkbook: async () => { calls.scans++; if (scanFails) throw new Error("Workbook read failed"); return {state: {sourceHash: "hash", sources: [{sheetId: "s1"}]}}; }
  };
  const entry = entryApi.mount({
    document,
    selectWorkbook: async () => true,
    scanWorkbook: options => bridge.scanWorkbook(options),
    onUnderstand: async () => {
      calls.measures++;
      if (measureFails && calls.measures === 1) throw Object.assign(new Error("Không đo được cấu trúc."), {code: "AF_UNDERSTAND_INVALID"});
      return {modelView: {mode: "model", counts: {tables: 1, relationships: 1, needsConfirm: 1, warnings: 0}}};
    },
    showProblem: async () => { calls.problems++; },
    onBrowse: options => {
      if (options?.reopen) { calls.reopen++; return browser.reopen(); }
      return browser.open();
    },
    onImported: () => { calls.imported = true; }
  });
  const browser = browserApi.create({document, bridge, onImported: receipt => entry.imported(receipt)});
  return {entry, browser, bridge, calls, get: document.getElementById};
}

(async () => {
  const html = fs.readFileSync(path.join(__dirname, "../../pbip_assistant/excel_addin/taskpane.html"), "utf8");

  // 1. Journey has exactly three steps: Nguồn → Hiểu dữ liệu → Đề bài.
  {
    assert(html.includes('id="assistant-step-source"'));
    assert(html.includes('id="assistant-step-understand"'));
    assert(html.includes('id="assistant-step-problem"'));
    assert(!html.includes('id="assistant-step-clean"'));
    assert(html.includes(">2. Hiểu dữ liệu<") && html.includes(">3. Đề bài<"));
    assert(!html.includes(">2. Làm sạch<"));
  }

  // 2. No cleaning wizard DOM anywhere in the page.
  {
    for (const id of ["preparation-wizard", "preparation-date-system", "preparation-scan", "preparation-inventory", "preparation-panel"]) {
      assert(!html.includes(`id="${id}"`), `#${id} is gone`);
    }
  }

  // 3. Import → re-read → automatic measure → understand step; Đề bài stays off.
  {
    const {get, calls} = harness();
    await get("assistant-choose-folder").click();
    assert.equal(calls.pick, 1);
    await get("assistant-select-all").click();
    await get("assistant-import-selected").click();
    assert.equal(calls.imports, 1);
    assert.equal(calls.scans, 1, "the import triggers a verified re-read");
    assert.equal(calls.measures, 1, "a successful re-read measures automatically");
    assert.equal(calls.problems, 0, "Đề bài is not opened before the understand step");
    assert.equal(get("assistant-understand-section").hidden, false, "the understand step is shown");
    assert.equal(get("flow-source-title").textContent, "Dữ liệu của bạn trông như thế nào?");
    assert.equal(get("assistant-step-problem").disabled, false, "a measured modelView enables Đề bài");
    assert.equal(get("assistant-step-understand").disabled, false);
    // Continue opens Đề bài.
    await get("assistant-understand-continue").click();
    assert.equal(calls.problems, 1);
    assert.equal(get("flow-source-title").textContent, "Đề bài");
  }

  // 4. Workbook choice re-reads, never imports, then measures.
  {
    const {get, calls} = harness();
    await get("assistant-choose-workbook").click();
    assert.equal(calls.imports, 0, "choosing workbook data must not import files");
    assert.equal(calls.scans, 1);
    assert.equal(calls.measures, 1);
    assert.equal(get("assistant-step-problem").disabled, false);
    await get("assistant-step-problem").click();
    assert.equal(calls.problems, 1);
    assert.equal(get("flow-source-title").textContent, "Đề bài");
  }

  // 5. A failed re-read keeps the steps disabled and offers a retry without advancing.
  {
    const {get, calls} = harness({scanFails: true});
    await get("assistant-choose-workbook").click();
    assert(get("assistant-step-understand").disabled);
    assert(get("assistant-step-problem").disabled);
    assert.equal(get("assistant-retry-scan").hidden, false);
    assert.equal(calls.measures, 0);
    assert.match(get("assistant-source-message").textContent, /Workbook read failed/);
  }

  // 6. A failed measure shows Đo lại/Về Nguồn and never enables Đề bài; retry succeeds.
  {
    const {get, calls} = harness({measureFails: true});
    await get("assistant-choose-workbook").click();
    assert.equal(calls.measures, 1);
    assert(get("assistant-step-problem").disabled, "a failed measure never enables Đề bài");
    assert.equal(get("assistant-understand-retry").hidden, false, "Đo lại is offered");
    assert.equal(get("assistant-understand-continue").disabled, true);
    assert.match(get("assistant-source-message").textContent, /Không đo được cấu trúc/);
    await get("assistant-understand-retry").click();
    assert.equal(calls.measures, 2, "Đo lại re-measures exactly once");
    assert.equal(get("assistant-step-problem").disabled, false, "a successful retry enables Đề bài");
    // Về Nguồn returns to the source step.
    await get("assistant-understand-back").click();
    assert.equal(get("assistant-understand-section").hidden, true);
    assert.equal(get("assistant-source-choice").hidden, false);
  }

  // 7. + Thêm nguồn reopens the browser on the same folder and keeps the pending selection.
  {
    const {get, calls} = harness();
    await get("assistant-choose-folder").click();
    await get("assistant-browser-list").children[0].children[0].click();
    assert.equal(calls.browse.at(-1), "sales");
    await get("assistant-select-all").click();
    await get("assistant-import-selected").click();
    assert.equal(get("assistant-import-skipped").hidden, false, "the skipped file is reported");
    const summaryBefore = get("assistant-selected-summary").textContent;
    assert.match(summaryBefore, /^Đã chọn 1 file/, "the skipped file stays selected for retry");
    await get("assistant-add-source").click();
    assert.equal(calls.reopen, 1, "add source returns to the browser without a new folder dialog");
    assert.equal(calls.pick, 1);
    assert.deepEqual(calls.browse.at(-1), "sales", "the previous folder is retained");
  }

  // 8. A changed workbook returns to Nguồn and drops the measured modelView.
  {
    const {get, entry} = harness();
    await get("assistant-choose-workbook").click();
    assert.equal(entry.state().step, "understand");
    entry.updateWorkbook({name: "Other.xlsx", hasData: true});
    assert.equal(entry.state().step, "source");
    assert.equal(entry.state().understandReady, false);
    assert(get("assistant-step-problem").disabled);
  }

  console.log("assistant journey: 8 cases passed");
})().catch(error => { console.error(error); process.exit(1); });