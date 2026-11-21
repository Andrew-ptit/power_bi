"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const taskpaneSource = require("../support/taskpane_source.js");

const script = taskpaneSource();
const header = ["Date", "Raw ID", "Weight", "Prefix", "Order ID", "Suffix"];
const rows = Array.from({length: 20}, (_, index) => ["2024-10-15", `A-${index}`, 123, "", "", ""]);
const values = [header, ...rows];
const rangeValue = (rowIndex, rowCount) => ({values: values.slice(rowIndex, rowIndex + rowCount), load() {}});
const usedRange = {
  isNullObject: false,
  rowIndex: 0,
  columnIndex: 0,
  rowCount: 200,
  columnCount: 6,
  load() {},
  getCell(rowIndex) { return {getResizedRange(rowDelta) { return rangeValue(rowIndex, rowDelta + 1); }}; },
};
const sheet = {
  name: "Raw_Orders",
  tables: {items: [], load() {}},
  load() {},
  getUsedRangeOrNullObject(valuesOnly) {
    assert.equal(valuesOnly, true);
    return usedRange;
  },
};
const workbook = {
  name: "synthetic.xlsx",
  worksheets: {items: [sheet], load() {}, getActiveWorksheet() { return sheet; }},
  getActiveCell() { return {rowIndex: 1, columnIndex: 1, load() {}}; },
  load() {},
};
const codexStatus = {textContent: "", classList: {toggle() {}}, replaceChildren() {}, setAttribute() {}};
const sandbox = {
  document: {addEventListener() {}, getElementById() { return codexStatus; }, createElement() { return {setAttribute() {}, replaceChildren() {}, appendChild() {}}; }},
  Office: {context: {document: {url: "https://tenant.example/synthetic.xlsx"}}},
  window: {Office: {context: {document: {url: "https://tenant.example/synthetic.xlsx"}}}},
  Excel: {run: async (callback) => callback({workbook, sync: async () => {}})},
  fetch: async () => ({ok: true, json: async () => ({token: "test", capabilities: {officeJsRead: true}})}),
};
vm.runInNewContext(script + "\nglobalThis.__readWorkbook = readWorkbook; globalThis.__bootstrap = bootstrap;", sandbox);

(async () => {
  const result = await sandbox.__readWorkbook();
  assert.equal(result.tables.length, 0);
  assert.equal(result.sheets.length, 1);
  assert.equal(result.sheets[0].name, "Raw_Orders");
  assert.equal(result.sheets[0].headerRow, 1);
  assert.deepEqual(Array.from(result.sheets[0].columnLetters), ["A", "B", "C", "D", "E", "F"]);
  assert.equal(result.sheets[0].rows.length, 20);
  assert.equal(result.sheets[0].rows[0][1], "A-0");
  assert.equal(result.activeCell.rowIndex, 1);
  await sandbox.__bootstrap();
  assert.match(codexStatus.textContent, /bản cũ/);
  console.log("taskpane usedRange test passed");
})().catch((error) => { console.error(error); process.exitCode = 1; });
