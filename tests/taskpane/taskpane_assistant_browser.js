"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

let api;
try { api = require(path.join(__dirname, "../../pbip_assistant/excel_addin/assistant_browser.js")); }
catch (_) { assert.fail("Source browser is unavailable"); }

class Node {
  constructor(tag) { this.tag = tag; this.hidden = false; this.disabled = false; this.textContent = ""; this.className = ""; this.type = ""; this.checked = false; this.value = ""; this.listeners = {}; this.attrs = {}; this.children = []; }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  setAttribute(name, value) { this.attrs[name] = value; }
  replaceChildren(...children) { this.children = children; }
  append(...children) { this.children.push(...children); }
  async click() { if (!this.disabled) await this.listeners.click?.(); }
  async change(checked) { this.checked = checked; await this.listeners.change?.(); }
}

function harness(overrides = {}) {
  const nodes = new Map();
  const document = {
    getElementById: id => { if (!nodes.has(id)) nodes.set(id, new Node("div")); return nodes.get(id); },
    createElement: tag => new Node(tag)
  };
  const calls = {browse: [], pick: 0, probe: 0, imports: []};
  const bridge = {
    pickRoot: async () => { calls.pick++; return {cancelled: false, rootName: "dataset"}; },
    browse: async relativePath => {
      calls.browse.push(relativePath);
      if (relativePath === "") return {
        rootName: "dataset", relativePath: "", parentRelativePath: null,
        breadcrumb: [{name: "dataset", relativePath: ""}],
        entries: [
          {name: "sales", kind: "folder"},
          {name: "dim_products.csv", kind: "file", extension: "csv", size: 2048},
          {name: "orders.xlsx", kind: "file", extension: "xlsx", size: 40960}
        ], truncated: false};
      if (relativePath === "sales") return {
        rootName: "dataset", relativePath: "sales", parentRelativePath: "",
        breadcrumb: [{name: "dataset", relativePath: ""}, {name: "sales", relativePath: "sales"}],
        entries: [
          {name: "2026", kind: "folder"},
          {name: "jan.csv", kind: "file", extension: "csv"},
          {name: "feb.csv", kind: "file", extension: "csv"}
        ], truncated: false};
      return {rootName: "dataset", relativePath, parentRelativePath: "sales", breadcrumb: [], entries: [], truncated: false};
    },
    probeDateSystem: async () => { calls.probe++; return "1904"; },
    importSelection: async ({items, dateSystem, onProgress}) => {
      calls.imports.push({items, dateSystem});
      onProgress({processed: 1, total: 2, fileId: "f1"});
      onProgress({processed: 2, total: 2, fileId: "f2"});
      return {
        status: "verified",
        inventory: {files: [{fileId: "f1", fileName: "dim_products.csv"}, {fileId: "f2", fileName: "orders.csv"}, {fileId: "f3", fileName: "bad.csv"}], sheets: []},
        report: {
          totals: {files: 2, sheets: 3, skipped: 1, decisions: 1},
          files: [
            {fileId: "f1", fileName: "dim_products.csv", status: "imported", reading: null,
             decisions: [{column: "unit_price", columnIndex: 3, kind: "number", numberFormat: "General", reasonCode: "DECIMAL_DOT", affectedRows: 1480, samples: ["1234.56"]}],
             readingDecisions: [], issues: []},
            {fileId: "f2", fileName: "orders.csv", status: "imported", decisions: [], readingDecisions: [], issues: []},
            {fileId: "f3", fileName: "bad.csv", status: "skipped", decisions: [], readingDecisions: [],
             issues: [{code: "CSV_COLUMN_COUNT", message: "CSV rows have inconsistent column counts."}]}
          ]
        }
      };
    }
  };
  Object.assign(bridge, overrides);
  const imported = [];
  const browser = api.create({document, bridge, onImported: receipt => imported.push(receipt)});
  return {browser, bridge, calls, imported, get: document.getElementById, nodes};
}

function fileRows(list) {
  return list.children.filter(row => row.children[0]?.type === "checkbox");
}

(async () => {
  // 1. Folders render before files and the breadcrumb is text.
  {
    const {browser, get} = harness();
    await browser.open();
    assert.equal(get("assistant-browser").hidden, false);
    assert.equal(get("assistant-browser-path").textContent, "dataset");
    const list = get("assistant-browser-list");
    assert.equal(list.children[0].children[0].className, "button button-ghost assistant-browser-folder");
    assert.equal(list.children[0].children[0].textContent, "sales");
    const rows = fileRows(list);
    assert.equal(rows.length, 2);
    assert.equal(rows[0].children[1].textContent, "dim_products.csv · CSV");
    assert.equal(rows[1].children[1].textContent, "orders.xlsx · XLSX (nhập toàn bộ nhóm)");
  }

  // 2. Navigate into a folder and up again without losing selection.
  {
    const {browser, get, calls} = harness();
    await browser.open();
    await fileRows(get("assistant-browser-list"))[0].children[0].change(true);
    assert.equal(browser.state().selection.length, 1);
    await get("assistant-browser-list").children[0].children[0].click();
    assert.deepEqual(calls.browse, ["", "sales"]);
    assert.equal(get("assistant-browser-path").textContent, "dataset / sales");
    await fileRows(get("assistant-browser-list"))[0].children[0].change(true);
    assert.equal(browser.state().selection.length, 2);
    await get("assistant-browser-up").click();
    assert.equal(calls.browse.at(-1), "");
    assert.equal(fileRows(get("assistant-browser-list"))[0].children[0].checked, true, "root selection survives navigation");
    assert.equal(browser.state().selection.length, 2);
  }

  // 3. Select-all only covers files of the current folder.
  {
    const {browser, get} = harness();
    await browser.open();
    await get("assistant-browser-list").children[0].children[0].click();
    await get("assistant-select-all").click();
    assert.equal(browser.state().selection.length, 2, "subfolder contents are not selected recursively");
    assert(get("assistant-import-selected").disabled === false);
    await get("assistant-select-all").click();
    assert.equal(browser.state().selection.length, 0, "second press clears the folder selection");
  }

  // 4. The footer counts files; the report counts the created sheets.
  {
    const {browser, get} = harness();
    await browser.open();
    await get("assistant-select-all").click();
    assert.equal(get("assistant-selected-summary").textContent, "Đã chọn 2 file · nhập để xem số sheet sẽ tạo");
    await get("assistant-import-selected").click();
    assert.equal(get("assistant-import-summary").textContent, "Đã nhập 2 file → 3 sheet");
    assert.equal(get("assistant-import-report").hidden, false);
  }

  // 5. Import posts exact items and the probed date system, with per-file progress.
  {
    const {browser, get, calls, imported} = harness();
    await browser.open();
    await get("assistant-select-all").click();
    get("assistant-browser-status").textContent = "";
    await get("assistant-import-selected").click();
    assert.equal(calls.probe, 1);
    assert.deepEqual(calls.imports[0].dateSystem, "1904");
    assert.deepEqual(calls.imports[0].items, [
      {relativePath: "", fileName: "dim_products.csv"},
      {relativePath: "", fileName: "orders.xlsx"}
    ]);
    assert.equal(imported.length, 1, "the browser hands the receipt to onImported");
    assert.match(get("assistant-browser-status").textContent, /^Đã nhập xong\. Còn 1 file bị bỏ qua\.$/);
  }

  // 6. A failed date-system probe blocks the import with a clear Vietnamese reason.
  {
    const {browser, get, calls} = harness({probeDateSystem: async () => { throw new Error("Không xác định được hệ ngày của workbook (1900/1904)."); }});
    await browser.open();
    await get("assistant-select-all").click();
    await get("assistant-import-selected").click();
    assert.equal(calls.imports.length, 0, "no import happens when the date system is unknown");
    assert.match(get("assistant-browser-status").textContent, /hệ ngày/);
    assert.equal(get("assistant-import-selected").disabled, false, "the user can retry after the workbook is fixed");
  }

  // 7. Report labels exceptions and skips without raw cell values or paths.
  {
    const {browser, get} = harness();
    await browser.open();
    await get("assistant-select-all").click();
    await get("assistant-import-selected").click();
    const exceptions = get("assistant-import-exceptions");
    assert.equal(exceptions.hidden, false);
    assert.equal(exceptions.children[0].textContent, "Ngoại lệ đã tự xử lý (1)");
    assert.equal(exceptions.children[1].children[0].textContent,
      "dim_products.csv · unit_price: số · dấu chấm thập phân → Number · 1.480 ô");
    const skipped = get("assistant-import-skipped");
    assert.equal(skipped.children[0].textContent, "Bỏ qua (1)");
    assert.match(skipped.children[1].children[0].textContent, /CSV rows have inconsistent column counts\./);
    const rendered = JSON.stringify(get("assistant-import-report"));
    assert(!rendered.includes("1234.56"), "samples are never rendered");
    assert(!rendered.includes("C:\\\\"), "no absolute paths are rendered");
  }

  // 8. No preview or question DOM exists in the new source UI.
  {
    const html = fs.readFileSync(path.join(__dirname, "../../pbip_assistant/excel_addin/taskpane.html"), "utf8");
    const browserSource = fs.readFileSync(path.join(__dirname, "../../pbip_assistant/excel_addin/assistant_browser.js"), "utf8");
    assert(!html.includes("Xem trước"), "the assistant tab has no preview button");
    assert(html.includes('id="assistant-browser"'));
    for (const id of ["assistant-browser-path", "assistant-browser-up", "assistant-browser-list", "assistant-browser-status", "assistant-selected-summary", "assistant-import-selected", "assistant-select-all", "assistant-import-summary", "assistant-import-exceptions", "assistant-import-skipped"]) {
      assert(html.includes(`id="${id}"`), `missing #${id}`);
    }
    assert(!/innerHTML/.test(browserSource), "browser never writes HTML strings");
    assert(!/preview|question/i.test(browserSource), "no preview/question concepts in the browser");
  }

  // 9. Vietnamese status strings for cancel and empty folder.
  {
    const {browser, get} = harness({pickRoot: async () => ({cancelled: true})});
    await browser.open();
    assert.equal(get("assistant-browser-status").textContent, "Chưa chọn thư mục.");
    const empty = harness({browse: async () => ({rootName: "dataset", relativePath: "", parentRelativePath: null, breadcrumb: [{name: "dataset", relativePath: ""}], entries: [], truncated: false})});
    await empty.browser.open();
    assert.equal(empty.get("assistant-browser-status").textContent, "Thư mục này không có file .csv hoặc .xlsx.");
  }

  // 10. File names are rendered as text, never as markup.
  {
    const hostile = '<img src=x onerror="alert(1)">.csv';
    const {browser, get} = harness({browse: async () => ({rootName: "dataset", relativePath: "", parentRelativePath: null,
      breadcrumb: [{name: "dataset", relativePath: ""}], entries: [{name: hostile, kind: "file", extension: "csv"}], truncated: false})});
    await browser.open();
    const span = fileRows(get("assistant-browser-list"))[0].children[1];
    assert.equal(span.textContent, `${hostile} · CSV`);
    assert.equal(span.innerHTML, undefined, "no HTML was parsed into the row");
  }

  console.log("assistant browser: 10 cases passed");
})().catch(error => { console.error(error); process.exit(1); });
