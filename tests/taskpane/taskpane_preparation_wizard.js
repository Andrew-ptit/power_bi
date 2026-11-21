"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const api = require(path.join(__dirname, "../../pbip_assistant/excel_addin/preparation_controller.js"));

const html = fs.readFileSync(path.join(__dirname, "../../pbip_assistant/excel_addin/taskpane.html"), "utf8");
// T306: the cleaning wizard UI is removed; the controller stays mounted headless so the
// bridge can keep ownership of wizard.state and the workbook re-read.
for (const id of ["preparation-wizard", "preparation-date-system", "preparation-scan", "preparation-inventory", "preparation-panel"]) {
  assert(!html.includes(`id="${id}"`), `#${id} must not exist`);
}

function node() {
  return {hidden: false, disabled: false, textContent: "", className: "", value: "", open: false,
    listeners: {}, setAttribute() {}, append() {}, replaceChildren() {}, addEventListener() {}};
}

(async () => {
  const document = {getElementById: () => null, createElement: node};
  const calls = [];
  const controller = api.mount({document, environment: {}, post: async action => { calls.push(action); return {}; },
    runtime: {}, deferOpen: true, scanWorkbook: async ({onProgress} = {}) => {
      onProgress?.({message: "Đang quét sheet 1/1"});
      return {state: {sourceHash: "hash", sources: [{sourceId: "s", sheetId: "id"}], questions: [], answers: {}}, sourceLabels: {s: "Data"}, warnings: [], dateSystem: "1904"};
    }});
  assert(controller, "headless mount still returns the state owner");
  assert.equal(controller.wizard.state, null);
  const state = await controller.scanWorkbook();
  assert.equal(state.sourceHash, "hash");
  assert.equal(state.sources.length, 1);
  assert.equal(controller.wizard.state.sourceHash, "hash", "the scanned state stays owned by the controller");
  controller.acceptState({sourceHash: "newer", sources: [{sourceId: "s", sheetId: "id2"}]});
  assert.equal(controller.wizard.state.sourceHash, "newer");
  controller.show({});
  assert.equal(typeof controller.inventoryRoot, "function");
  console.log("Preparation headless controller passed");
})().catch(error => { console.error(error); process.exit(1); });
