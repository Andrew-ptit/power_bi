"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const taskpaneSource = require("../support/taskpane_source.js");

const sourceCode = taskpaneSource();
let sheets = [];
let active = null;
let importedValues = [];
let nextId = 1;

class Range {
  constructor(sheet, rowIndex, columnIndex, rowCount, columnCount) {
    Object.assign(this, {sheet, rowIndex, columnIndex, rowCount, columnCount});
  }
  load() {}
  get values() {
    return Array.from({length: this.rowCount}, (_, row) =>
      Array.from({length: this.columnCount}, (_, column) =>
        this.sheet.values[this.rowIndex + row]?.[this.columnIndex + column] ?? ""));
  }
  get formulas() { return this.values.map((row) => row.map(() => "")); }
  copyFrom(other, copyType) {
    assert.equal(copyType, "Values");
    const values = other.values;
    for (let row = 0; row < this.rowCount; row += 1) {
      this.sheet.values[this.rowIndex + row] ||= [];
      for (let column = 0; column < this.columnCount; column += 1) {
        this.sheet.values[this.rowIndex + row][this.columnIndex + column] = values[row][column];
      }
    }
  }
  clear(kind) {
    assert.equal(kind, "Contents");
    for (let row = 0; row < this.rowCount; row += 1) {
      this.sheet.values[this.rowIndex + row] ||= [];
      for (let column = 0; column < this.columnCount; column += 1) {
        this.sheet.values[this.rowIndex + row][this.columnIndex + column] = "";
      }
    }
  }
}

function usedDimensions(values) {
  let lastRow = -1;
  let lastColumn = -1;
  for (let row = 0; row < values.length; row += 1) {
    for (let column = 0; column < values[row].length; column += 1) {
      if (values[row][column] !== "" && values[row][column] !== null) {
        lastRow = Math.max(lastRow, row);
        lastColumn = Math.max(lastColumn, column);
      }
    }
  }
  return {rows: lastRow + 1, columns: lastColumn + 1};
}

function makeSheet(name, values, tableSpec = null) {
  const sheet = {
    id: `sheet-${nextId++}`,
    name,
    values: values.map((row) => [...row]),
    activate() { active = sheet; },
    delete() { sheets = sheets.filter((item) => item !== sheet); },
    getRangeByIndexes(row, column, rowCount, columnCount) {
      return new Range(sheet, row, column, rowCount, columnCount);
    },
    getUsedRange() {
      const size = usedDimensions(sheet.values);
      return new Range(sheet, 0, 0, size.rows, size.columns);
    },
  };
  const table = tableSpec ? {
    name: tableSpec.name, rowIndex: tableSpec.rowIndex, columnIndex: tableSpec.columnIndex,
    rowCount: tableSpec.rowCount, columnCount: tableSpec.columnCount,
    getRange() { return new Range(sheet, this.rowIndex, this.columnIndex, this.rowCount, this.columnCount); },
    resize(range) {
      this.rowIndex = range.rowIndex; this.columnIndex = range.columnIndex;
      this.rowCount = range.rowCount; this.columnCount = range.columnCount;
    },
  } : null;
  sheet.tables = {getItem(tableName) {
    if (!table || table.name !== tableName) throw new Error("Table not found");
    return table;
  }};
  sheet.table = table;
  sheets.push(sheet);
  return sheet;
}

const worksheets = {
  get items() { return sheets; },
  load() {},
  getItem(reference) {
    const sheet = sheets.find((item) => item.name === reference || item.id === reference);
    if (!sheet) throw new Error(`Sheet not found: ${reference}`);
    return sheet;
  },
};
const workbook = {
  name: "orders.xlsx", worksheets, load() {},
  insertWorksheetsFromBase64(encoded, options) {
    assert.equal(encoded, "values-only-xlsx");
    assert.equal(options.sheetNamesToInsert[0], "PQ_Result_Values");
    const imported = makeSheet(`Imported_${nextId}`, importedValues);
    return {value: [imported.id]};
  },
};
const sandbox = {
  document: {addEventListener() {}},
  Office: {context: {requirements: {isSetSupported: () => true}, document: {url: "file:///C:/orders.xlsx"}}},
  window: {Office: {context: {requirements: {isSetSupported: () => true}}}},
  Excel: {RangeCopyType: {values: "Values"}, run: async (callback) => callback({workbook, sync: async () => {}})},
};
vm.runInNewContext(sourceCode + "\nglobalThis.__applyToSource = applyPQValuesToSource;", sandbox);

const expectedWorkbook = {name: "orders.xlsx", url: "file:///C:/orders.xlsx"};
const preview = (rows, columns) => ({
  resultRows: rows, resultColumns: columns,
  resultWorkbookBase64: "values-only-xlsx", resultWorkbookSheetName: "PQ_Result_Values",
});

(async () => {
  const tableSheet = makeSheet("Orders", [
    ["OrderID", "Status", "", "KEEP"],
    ["A1", "Pending", "", "KEEP"],
    ["A2", "Done", "", "KEEP"],
    ["A3", "Done", "", "KEEP"],
  ], {name: "OrdersTable", rowIndex: 0, columnIndex: 0, rowCount: 4, columnCount: 2});
  importedValues = [["OrderID", "Status"], ["A1", "Done"], ["A2", "Done"]];
  const tableResult = await sandbox.__applyToSource(
    preview(2, 2), expectedWorkbook, {kind: "table", sheet: "Orders", name: "OrdersTable"},
  );
  assert.equal(tableSheet.table.rowCount, 3);
  assert.equal(tableSheet.table.columnCount, 2);
  assert.deepEqual(tableSheet.values.slice(0, 3).map((row) => row.slice(0, 2)), importedValues);
  assert.deepEqual(tableSheet.values[3].slice(0, 2), ["", ""], "shrunk Table tail must be cleared");
  assert.equal(tableSheet.values[0][3], "KEEP", "cells outside the Table must be preserved");
  assert.equal(tableResult.sourceName, "OrdersTable");
  assert.equal(active, tableSheet);
  assert.equal(sheets.filter((sheet) => sheet.name.startsWith("Imported_")).length, 0);

  const blockedSheet = makeSheet("Blocked", [["ID", "Value", "DO NOT OVERWRITE"], ["A", 1, ""]],
    {name: "BlockedTable", rowIndex: 0, columnIndex: 0, rowCount: 2, columnCount: 2});
  importedValues = [["ID", "Value", "Extra"], ["A", 1, "x"]];
  await assert.rejects(
    sandbox.__applyToSource(preview(1, 3), expectedWorkbook, {kind: "table", sheet: "Blocked", name: "BlockedTable"}),
    /vùng kế bên đang có dữ liệu\/công thức/,
  );
  assert.equal(blockedSheet.table.columnCount, 2, "blocked expansion must not resize the Table");
  assert.equal(blockedSheet.values[0][2], "DO NOT OVERWRITE");
  assert.equal(sheets.filter((sheet) => sheet.name.startsWith("Imported_")).length, 0);

  const rangeSheet = makeSheet("Raw", [["ID", "Value", "Old"], ["A", 1, "x"], ["B", 2, "y"]]);
  importedValues = [["ID"], ["Z"]];
  const rangeResult = await sandbox.__applyToSource(
    preview(1, 1), expectedWorkbook, {kind: "sheet", sheet: "Raw"},
  );
  assert.equal(rangeResult.sourceKind, "sheet");
  assert.deepEqual(rangeSheet.values, [["ID", "", ""], ["Z", "", ""], ["", "", ""]]);
  assert.equal(sheets.filter((sheet) => sheet.name.startsWith("Imported_")).length, 0);
  console.log("taskpane PQ source apply test passed");
})().catch((error) => { console.error(error); process.exitCode = 1; });
