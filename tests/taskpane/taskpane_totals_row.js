"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const taskpaneSource = require("../support/taskpane_source.js");

const script = taskpaneSource();
const headers = ["Order", "Quantity", "Amount"];

async function readTable(dataRows, totalsRow) {
  const headerRowIndex = 4;
  const columnIndex = 2;
  const sampledOffsets = [];
  const headerRange = {
    rowIndex: headerRowIndex, columnIndex, values: [headers], load() {},
  };
  const dataBodyRange = {
    rowIndex: headerRowIndex + 1, columnIndex,
    rowCount: dataRows.length, columnCount: headers.length,
    load() {},
    getCell(offset, columnOffset) {
      assert.equal(columnOffset, 0);
      assert.ok(offset >= 0 && offset < dataRows.length, "sample must stay inside the data body");
      sampledOffsets.push(offset);
      return {getResizedRange(rowDelta, columnDelta) {
        assert.equal(rowDelta, 0);
        assert.equal(columnDelta, headers.length - 1);
        return {values: [dataRows[offset]], load() {}};
      }};
    },
  };
  const table = {
    name: "Orders",
    getRange() {
      throw new Error("full table range includes the header and optional totals row");
    },
    getHeaderRowRange() { return headerRange; },
    getDataBodyRange() { return dataBodyRange; },
    // Keep the full range fixture explicit: totals are outside the data body.
    fullValues: [headers, ...dataRows, ...(totalsRow ? [totalsRow] : [])],
  };
  const sheet = {name: "Data", tables: {items: [table], load() {}}, load() {}};
  const workbook = {
    name: "synthetic-totals.xlsx", load() {},
    worksheets: {items: [sheet], load() {}, getActiveWorksheet() { return sheet; }},
    getActiveCell() { return {rowIndex: 5, columnIndex, load() {}}; },
  };
  const sandbox = {
    document: {addEventListener() {}},
    window: {},
    Excel: {run: async (callback) => callback({workbook, sync: async () => {}})},
  };
  vm.runInNewContext(script + "\nglobalThis.__readWorkbook = readWorkbook;", sandbox);
  const result = await sandbox.__readWorkbook();
  assert.equal(result.tables.length, 1);
  assert.equal(result.sheets.length, 0);
  const actual = JSON.parse(JSON.stringify(result.tables[0]));
  assert.deepEqual(actual.headers, headers);
  assert.equal(actual.totalColumns, 3);
  assert.equal(actual.rowIndex, headerRowIndex, "snapshot keeps the table header origin");
  assert.equal(actual.columnIndex, columnIndex);
  assert.deepEqual(actual.sampleOrdinals, sampledOffsets);
  return actual;
}

(async () => {
  const rows = [["A", 1, 10], ["B", 2, 20]];
  const total = ["Total", 3, 30];
  const withTotals = await readTable(rows, total);
  assert.equal(withTotals.totalRows, 2);
  assert.deepEqual(withTotals.rows, rows);
  assert.deepEqual(withTotals.sampleOrdinals, [0, 1]);
  assert.ok(!withTotals.rows.some((row) => row[0] === "Total"));

  const withoutTotals = await readTable([["C", 3, 30], ["D", 4, 40], ["E", 5, 50]], null);
  assert.equal(withoutTotals.totalRows, 3);
  assert.deepEqual(withoutTotals.rows, [["C", 3, 30], ["D", 4, 40], ["E", 5, 50]]);
  assert.deepEqual(withoutTotals.sampleOrdinals, [0, 1, 2]);

  const empty = await readTable([], null);
  assert.equal(empty.totalRows, 0);
  assert.deepEqual(empty.rows, []);
  assert.deepEqual(empty.sampleOrdinals, []);
  console.log("taskpane totals row tests passed");
})().catch((error) => { console.error(error); process.exitCode = 1; });
