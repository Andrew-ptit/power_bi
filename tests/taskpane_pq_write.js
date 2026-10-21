"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../pbip_assistant/excel_addin/taskpane.js"), "utf8");
const sheets = [];
let active;
let nextValues;
let importedCount = 0;
let formatClears = 0;

function makeSheet(name, values, marker = null) {
  const sheet = {
    id: `sheet-${sheets.length + importedCount + 1}`,
    name, values: values.map((row) => [...row]), marker,
    load() {},
    activate() { active = sheet; },
    delete() { sheets.splice(sheets.indexOf(sheet), 1); },
    getUsedRange(valuesOnly = false) {
      let rows = sheet.values.length;
      if (valuesOnly) {
        while (rows > 1 && (sheet.values[rows - 1] || []).every((value) => value === "" || value === null)) rows -= 1;
      }
      const columns = Math.max(0, ...sheet.values.map((row) => row.length));
      return {rowCount: rows, columnCount: columns, load() {},
        get values() { return sheet.values.map((row) => [...row]); }};
    },
    getRangeByIndexes(row, column, rowCount, columnCount) {
      return {
        load() {},
        get values() {
          return Array.from({length: rowCount}, (_, r) =>
            Array.from({length: columnCount}, (_, c) => sheet.values[row + r]?.[column + c] ?? ""));
        },
        copyFrom(other, copyType) {
          assert.equal(copyType, "Values");
          const copied = other.values;
          for (let r = 0; r < rowCount; r += 1) {
            sheet.values[row + r] ||= [];
            for (let c = 0; c < columnCount; c += 1) sheet.values[row + r][column + c] = copied[r][c];
          }
        },
        clear(kind) {
          assert.ok(["Contents", "Formats"].includes(kind));
          if (kind === "Formats") {
            formatClears += 1;
            return;
          }
          for (let r = 0; r < rowCount; r += 1) {
            sheet.values[row + r] ||= [];
            for (let c = 0; c < columnCount; c += 1) sheet.values[row + r][column + c] = "";
          }
        },
      };
    },
    customProperties: {
      getItemOrNullObject(key) {
        assert.equal(key, "LocalDataCopilotPQResult");
        return {isNullObject: sheet.marker === null, value: sheet.marker, load() {}};
      },
      add(key, value) {
        assert.equal(key, "LocalDataCopilotPQResult");
        sheet.marker = value;
      },
    },
  };
  sheets.push(sheet);
  return sheet;
}

const raw = makeSheet("Raw_Orders", [["Order"], ["A1"]]);
makeSheet("PQ_Result", [["User data"]]); // A name collision must not overwrite an unrelated sheet.
active = raw;
const worksheets = {
  get items() { return sheets; },
  load() {},
  getActiveWorksheet() { return active; },
  getItem(id) { return sheets.find((sheet) => sheet.id === id); },
};
const workbook = {
  name: "orders.xlsx", worksheets, load() {},
  insertWorksheetsFromBase64(encoded, options) {
    assert.equal(encoded, "values-only-xlsx");
    assert.equal(options.sheetNamesToInsert[0], "PQ_Result_Values");
    importedCount += 1;
    const sheet = makeSheet(`PQ_Result_Values_${importedCount}`, nextValues);
    return {value: [sheet.id]};
  },
};
const sandbox = {
  document: {addEventListener() {}},
  Office: {context: {requirements: {isSetSupported: () => true}, document: {url: "file:///C:/orders.xlsx"}}},
  window: {Office: {context: {requirements: {isSetSupported: () => true}}}},
  Excel: {RangeCopyType: {values: "Values"}, run: async (callback) => callback({workbook, sync: async () => {}})},
};
vm.runInNewContext(source + "\nglobalThis.__write = applyPQValuesToOpenWorkbook;", sandbox);
const preview = (rows, columns) => ({resultRows: rows, resultColumns: columns,
  resultWorkbookBase64: "values-only-xlsx", resultWorkbookSheetName: "PQ_Result_Values"});

(async () => {
  nextValues = [["Order", "Status"], ["A1", "ok"], ["A2", "ok"]];
  const first = await sandbox.__write(preview(2, 2), {name: workbook.name, url: "file:///C:/orders.xlsx"});
  assert.equal(first.resultSheetName, "PQ_Result_2");
  assert.equal(sheets.length, 3);
  const owned = sheets.find((sheet) => sheet.marker === "v1");
  assert.equal(active, owned, "new result sheet must be shown to the user");
  assert.deepEqual(owned.values, nextValues);
  assert.deepEqual(sheets.find((sheet) => sheet.name === "PQ_Result").values, [["User data"]]);

  nextValues = [["Order"], ["B1"]];
  const second = await sandbox.__write(preview(1, 1), {name: workbook.name, url: "file:///C:/orders.xlsx"});
  assert.equal(second.resultSheetName, "PQ_Result_2");
  assert.equal(sheets.length, 3, "temporary import must be deleted on successful rerun");
  assert.equal(sheets.find((sheet) => sheet.marker === "v1"), owned);
  assert.deepEqual(owned.values, [["Order", ""], ["B1", ""], ["", ""]], "old result tail must be cleared");
  assert.equal(active, owned, "rerun must show the same result sheet");
  assert.equal(formatClears, 1, "rerun must clear stale Text formats on the managed result range");

  // Excel getUsedRange(true) omits a trailing all-null Power Query record.
  // The server-validated result rectangle must preserve that record.
  nextValues = [["Order", "Status"], ["C1", "ok"], ["", ""]];
  const trailingBlank = await sandbox.__write(preview(2, 2), {name: workbook.name, url: "file:///C:/orders.xlsx"});
  assert.equal(trailingBlank.rowCount, 2);
  assert.deepEqual(owned.values, nextValues, "trailing all-null result row must be preserved");

  await assert.rejects(sandbox.__write(preview(1, 1), {name: "other.xlsx", url: "file:///C:/other.xlsx"}), /Workbook/);
  assert.equal(sheets.length, 3, "wrong workbook must not import a sheet");
  console.log("taskpane PQ worksheet write test passed");
})().catch((error) => { console.error(error); process.exitCode = 1; });
