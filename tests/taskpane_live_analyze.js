"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../pbip_assistant/excel_addin/taskpane.js"), "utf8");
const elements = new Map();
function element(id) {
  if (!elements.has(id)) {
    const children = [];
    elements.set(id, {
      textContent: "", className: "", checked: false, disabled: false,
      classList: {toggle() {}},
      value: id === "prompt" ? "Làm sạch dữ liệu" : ";",
      get options() { return children; },
      replaceChildren() { children.length = 0; this.value = ""; },
      appendChild(child) { children.push(child); if (children.length === 1) this.value = child.value; },
    });
  }
  return elements.get(id);
}
const requests = [];
const sandbox = {
  document: {getElementById: element, addEventListener() {}, createElement: () => ({value: "", textContent: ""})},
  window: {Office: {context: {requirements: {isSetSupported: () => true}}}},
  Office: {context: {requirements: {isSetSupported: () => true}}},
  fetch: async (url, options) => {
    requests.push({url, payload: JSON.parse(options.body)});
    return {ok: true, json: async () => ({status: "analysis_only", canApply: false})};
  },
};
vm.runInNewContext(source + `
  globalThis.__state = state;
  globalThis.__analyze = analyze;
  globalThis.__setReadWorkbook = (reader) => { readWorkbook = reader; };
  renderPlan = () => {};
`, sandbox);

const state = sandbox.__state;
state.officeReady = true;
state.codexAvailable = true;
state.workbook = {name: "orders.xlsx", activeSheet: "Orders", tables: [], sheets: []};
let reads = 0;
sandbox.__setReadWorkbook(async () => {
  reads += 1;
  return {
    name: "orders.xlsx", activeSheet: "Orders", tables: [],
    sheets: [{headers: ["Ma_Don_Hang"], rows: [[`ORDER-${reads}`]]}],
  };
});

(async () => {
  await sandbox.__analyze();
  await sandbox.__analyze();
  assert.equal(reads, 2);
  assert.equal(requests.length, 2);
  assert.equal(requests[0].payload.workbook.sheets[0].rows[0][0], "ORDER-1");
  assert.equal(requests[1].payload.workbook.sheets[0].rows[0][0], "ORDER-2");
  assert.equal(state.workbook.sheets[0].rows[0][0], "ORDER-2");

  sandbox.__setReadWorkbook(async () => { throw new Error("Excel disconnected"); });
  await sandbox.__analyze();
  assert.equal(requests.length, 2, "stale workbook must never be sent after read failure");
  assert.equal(state.workbook, null);
  assert.equal(state.plan, null);
  assert.equal(element("error-code").textContent, "OFFICE_READ_FAILED");
  console.log("taskpane live analysis test passed");
})().catch((error) => { console.error(error); process.exitCode = 1; });
