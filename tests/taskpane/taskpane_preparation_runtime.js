"use strict";
const assert = require("node:assert/strict");
const path = require("node:path");
let api;
try { api = require(path.join(__dirname, "../../pbip_assistant/excel_addin/preparation_runtime.js")); }
catch (_) { assert.fail("Preparation read adapter is unavailable"); }
function environment({supported = true, huge = false, noFormulas = false} = {}) {
  const loads = [];
  const block = {rowIndex: 6, columnIndex: 3, rowCount: 1, columnCount: 1, load() {}};
  const special = {isNullObject: noFormulas, load() {}, areas: {items: [block], load() {}}};
  const range = {rowIndex: 5, columnIndex: 2, rowCount: huge ? 100002 : 3, columnCount: 2,
    values: [["Code", "Date"], ["00123", "03/04/2026"], ["=literal", " X "]],
    numberFormat: [["General", "General"], ["@", "General"], ["@", "General"]],
    load(properties) { loads.push(properties); }, getSpecialCellsOrNullObject(kind) { assert.equal(kind, "Formulas"); return special; }};
  const sheet = {id: "{synthetic_sheet}", name: "Orders", load() {}};
  const workbook = {name: "Synthetic", load() {}, getSelectedRange: () => range,
    worksheets: {getActiveWorksheet: () => sheet}};
  return {loads, Office: {context: {requirements: {isSetSupported: () => supported}}},
    Excel: {SpecialCellType: {formulas: "Formulas"}, run: async callback => callback({workbook, sync: async () => {}})}};
}
(async () => {
  let env = environment();
  const book = await api.describeWorkbook(env);
  assert.deepEqual(book, {workbookName: "Synthetic", sheetId: "{synthetic_sheet}"});
  assert.equal(env.loads.length, 0, "folder inventory only needs workbook metadata");
  const result = await api.readSelection(env, "1904");
  assert.deepEqual(result.snapshot.formulaCells, [[0, 1]]);
  assert.equal(result.snapshot.rowOffset, 6);
  assert.equal(result.snapshot.columnOffset, 2);
  assert.equal(result.snapshot.dateSystem, "1904");
  assert.deepEqual(result.snapshot.rows, [["00123", "03/04/2026"], ["=literal", " X "]]);
  assert.deepEqual(result.snapshot.headers, ["Code", "Date"]);
  assert.equal(api.apply, undefined);
  assert.equal(api.undo, undefined);
  const clean = await api.readSelection(environment({noFormulas: true}), "1900");
  assert.deepEqual(clean.snapshot.formulaCells, []);
  await assert.rejects(api.readSelection(environment({supported: false}), "1900"), /ExcelApi 1.9/);
  await assert.rejects(api.readSelection(environment(), ""), /hệ ngày/);
  env = environment({huge: true});
  await assert.rejects(api.readSelection(env, "1900"), /giới hạn/);
  assert(!env.loads.some(p => p.includes("values")), "budget guard precedes full cell read");
  function activeRange(isNull, rows) {
    const range = {isNullObject: isNull, rowCount: rows, columnCount: 2, load() {}, selected: false,
      select() { this.selected = true; }};
    return {range, host: {Excel: {run: async callback => callback({sync: async () => {},
      workbook: {worksheets: {getActiveWorksheet: () => ({getUsedRangeOrNullObject: () => range})}}})}}};
  }
  for (const [empty, rows, expected] of [[true, 0, false], [false, 1, false], [false, 2, true]]) {
    const host = activeRange(empty, rows);
    assert.equal(await api.selectActiveSource(host.host), expected);
    assert.equal(host.range.selected, expected);
  }
  console.log("Preparation runtime read guards passed");
})().catch(error => { console.error(error); process.exitCode = 1; });
