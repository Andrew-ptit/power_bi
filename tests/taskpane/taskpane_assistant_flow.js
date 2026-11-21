"use strict";

process.env.TZ = "Asia/Saigon";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const crypto = require("node:crypto");
const taskpaneSource = require("../support/taskpane_source.js");
const source = taskpaneSource();
const elements = new Map();
function node(tag = "div") {
  const listeners = new Map();
  const attributes = new Map();
  const hiddenClasses = new Set();
  return {tag, children: [], dataset: {}, textContent: "", value: "", checked: false, disabled: false,
    classList: {toggle(name, hidden) { if (hidden) hiddenClasses.add(name); else hiddenClasses.delete(name); }, contains(name) { return hiddenClasses.has(name); }},
    appendChild(child) { this.children.push(child); if (child.id) elements.set(child.id, child); },
    replaceChildren(...children) { this.children = children; },
    setAttribute(name, value) { attributes.set(name, value); },
    getAttribute(name) { return attributes.get(name); },
    addEventListener(name, callback) { const all = listeners.get(name) || []; all.push(callback); listeners.set(name, all); },
    async emit(name, event = {}) { for (const callback of listeners.get(name) || []) await callback(event); },
    async click() { if (!this.disabled) await this.emit("click"); },
  };
}
function element(id) { if (!elements.has(id)) elements.set(id, node()); return elements.get(id); }
function renderedText(value) { return [value.textContent || "", ...(value.children || []).map(renderedText)].join("\n"); }
const plain = (value) => JSON.parse(JSON.stringify(value));
let host;
const calls = [];
let responseHandler = async () => ({});
const sandbox = {
  Date, console, TextEncoder, crypto: crypto.webcrypto,
  document: {getElementById: element, addEventListener() {}, createElement: node},
  window: {},
  Excel: {run: async (callback) => callback({workbook: host.workbook, sync: async () => {}})},
  fetch: async (url, options) => {
    const request = {url, payload: JSON.parse(options.body), headers: options.headers};
    calls.push(request);
    const result = await responseHandler(request);
    if (result?.__httpStatus) return {ok: false, status: result.__httpStatus, json: async () => ({error: result.error})};
    return {ok: true, json: async () => result};
  },
};
vm.runInNewContext(source + `
  globalThis.__preparationBusinessHandoff = preparationBusinessHandoff;
  globalThis.__state = state;
  globalThis.__closeCoordinatorSession = closeCoordinatorSession;
  globalThis.__isoDateLocal = isoDateLocal;
  globalThis.__flowCell = flowCell;
  globalThis.__flowNowIso = flowNowIso;
  globalThis.__flowReadOpenWorkbook = flowReadOpenWorkbook;
  globalThis.__flowSampleOrdinals = flowSampleOrdinals;
  globalThis.__flowBindRoot = flowBindRoot;
  globalThis.__flowAddFile = flowAddFile;
  globalThis.__flowAddOpenWorkbook = flowAddOpenWorkbook;
  globalThis.__flowIngest = flowIngest;
  globalThis.__flowUnderstand = flowUnderstand;
  globalThis.__flowPlanDraft = flowPlanDraft;
  globalThis.__flowExecuteBranches = flowExecuteBranches;
  globalThis.__renderFlowBranches = renderFlowBranches;
  globalThis.__renderFlowFreeze = renderFlowFreeze;
  globalThis.__flowFreeze = flowFreeze;
  globalThis.__flowApprove = flowApprove;
  globalThis.__flowApply = flowApply;
  globalThis.__flowDigest = flowDigest;
  globalThis.__flowFreshWorkbookSources = flowFreshWorkbookSources;
  globalThis.__setFlowExport = (callback) => { exportWorkbookBase64 = callback; };
  globalThis.__flowLoadState = flowLoadState;
  globalThis.__flowReset = flowReset;
  globalThis.__flowCreateRecord = flowCreateRecord;
  globalThis.__flowReadRecord = flowReadRecord;
  globalThis.__flowPersistRecord = flowPersistRecord;
  globalThis.__renderFlowRecord = renderFlowRecord;
  globalThis.__createWorkbookRecordState = createWorkbookRecordState;
  globalThis.__renderWorkbook = renderWorkbook;
  globalThis.__resetFlowView = resetFlowView;
  globalThis.__bindFlowEvents = bindFlowEvents;
  globalThis.__bindFlowPromptShortcut = bindFlowPromptShortcut;
  globalThis.__refreshWorkbook = refreshWorkbook;
  globalThis.__setReadWorkbook = (callback) => { readWorkbook = callback; };
  globalThis.__updateFlowButtons = updateFlowButtons;
`, sandbox);

function makeHost(definitions, {epochProbe = 1462, epochError = "", probeUnavailable = false} = {}) {
  const reads = [];
  const workbook = {worksheets: {items: [], load() {}}};
  if (!probeUnavailable) workbook.functions = {date(year, month, day) {
    assert.deepEqual([year, month, day], [1904, 1, 1]);
    reads.push({kind: "epoch-probe"});
    return {value: epochProbe, error: epochError, load(properties) { assert.ok(properties.includes("value")); }};
  }};
  for (const definition of definitions) {
    const {sheet: name, name: tableName = name, header, rows, table = true} = definition;
    const rowIndex = 3, columnIndex = 2;
    const allValues = table ? rows : [header, ...rows];
    const formats = definition.numberFormats || rows.map(() => header.map(() => "General"));
    const allFormats = table ? formats : [header.map(() => "General"), ...formats];
    const body = {
      isNullObject: false, rowIndex: rowIndex + (table ? 1 : 0), columnIndex,
      rowCount: definition.rowCount ?? allValues.length, columnCount: header.length, values: allValues, numberFormat: allFormats,
      load(properties) {
        if (properties.split(",").includes("values")) reads.push({kind: "full", name: tableName});
        if (properties.split(",").includes("numberFormat")) reads.push({kind: "formats", name: tableName});
      },
      getCell(offset, column) {
        assert.equal(column, 0);
        assert.ok(offset >= 0 && offset < allValues.length);
        reads.push({kind: "sample", name: tableName, offset});
        return {getResizedRange(rowDelta, columnDelta) {
          assert.equal(rowDelta, 0);
          assert.equal(columnDelta, header.length - 1);
          return {values: [allValues[offset]], numberFormat: [allFormats[offset]], load() {}};
        }};
      },
    };
    const head = {rowIndex, columnIndex, values: [header], load() {}};
    const fakeTable = {name: tableName,
      getRange() { throw new Error("totals row must never be read"); },
      getDataBodyRange() { reads.push({kind: "body", name: tableName}); return body; },
      getHeaderRowRange() { reads.push({kind: "header", name: tableName}); return head; },
    };
    const sheet = {name, tables: {items: table ? [fakeTable] : [], load() {}},
      getUsedRangeOrNullObject(valuesOnly) { assert.equal(valuesOnly, true); return body; }};
    workbook.worksheets.items.push(sheet);
  }
  return {workbook, reads};
}

function readyFlow() {
  sandbox.__state.flow.v2Capability = true;
  sandbox.__resetFlowView("", {explicit: true});
  sandbox.__state.flow.rootLabel = "synthetic";
  sandbox.__state.sessionId = "session-test";
  sandbox.__state.token = "token-test";
  sandbox.__state.officeReady = true;
  sandbox.__state.workbook = {name: "synthetic.xlsx", url: ""};
  element("prompt").value = "Summarize synthetic values";
  return sandbox.__state.flow;
}

function writeHost({corrupt = false, formula = false, collision = false} = {}) {
  const existing = makeHost([{sheet: "Source", name: "Transactions", header: ["ID", "Amount"], rows: [["a", "12"]]}]);
  const writes = [];
  const workbook = existing.workbook;
  workbook.name = "synthetic.xlsx";
  workbook.load = () => {};
  const sourceSheet = workbook.worksheets.items[0];
  const sourceValues = [["a", "12"]];
  const sourceTable = sourceSheet.tables.items[0];
  const originalBody = sourceTable.getDataBodyRange;
  sourceTable.getDataBodyRange = () => {
    const body = originalBody();
    Object.defineProperty(body, "values", {get: () => sourceValues});
    return body;
  };
  workbook.worksheets.add = (name) => {
    if (collision || workbook.worksheets.items.some((sheet) => sheet.name === name)) throw new Error("Target collision");
    const cells = new Map(), formats = new Set();
    const sheet = {name, tables: {items: [], load() {}}, getUsedRangeOrNullObject() { return {isNullObject: true, load() {}}; }, getRangeByIndexes(row, column, rowCount, columnCount) {
      let loaded = false;
      return {set numberFormat(value) {
        assert.deepEqual(plain(value), Array.from({length: rowCount}, () => Array(columnCount).fill("@")));
        for (let r = 0; r < rowCount; r++) for (let c = 0; c < columnCount; c++) formats.add(`${row + r}:${column + c}`);
        writes.push({kind: "format", row, column, rowCount, columnCount});
      }, set values(value) {
        for (let r = 0; r < rowCount; r++) for (let c = 0; c < columnCount; c++) {
          assert.ok(formats.has(`${row + r}:${column + c}`), "Text format must precede value assignment");
          cells.set(`${row + r}:${column + c}`, value[r][c]);
        }
        writes.push({kind: "values", row, column, rowCount, columnCount});
      }, get values() {
        const matrix = Array.from({length: rowCount}, (_, r) => Array.from({length: columnCount}, (_, c) => cells.get(`${row + r}:${column + c}`) ?? ""));
        if (loaded && corrupt && row === 0 && rowCount > 21) matrix[25][0] = "CHANGED_AFTER_WRITE";
        return matrix;
      }, load(properties) { loaded = properties.includes("values"); },
      getSpecialCellsOrNullObject(type) {
        assert.equal(type, "Formulas");
        return {isNullObject: !formula, load() {}};
      }};
    }};
    writes.push({kind: "new-sheet", name});
    workbook.worksheets.items.push(sheet);
    return sheet;
  };
  return {workbook, writes, sourceValues};
}

(async () => {
  const localDate = new Date(2026, 8, 1);
  assert.equal(sandbox.__isoDateLocal(localDate), "2026-09-01");
  assert.notEqual(localDate.toISOString().slice(0, 10), "2026-09-01");
  assert.equal(sandbox.__flowCell(localDate), "2026-09-01");
  assert.equal(sandbox.__flowCell(true), "TRUE");
  assert.equal(sandbox.__flowCell(false), "FALSE");
  assert.equal(sandbox.__flowCell(0.1), "0.1");
  assert.equal(sandbox.__flowCell(null), "");
  assert.match(sandbox.__flowNowIso(), /^\d{4}-\d{2}-\d{2}T.*Z$/);

  // QA17: real Office.js dates are numeric doubles, not JavaScript Date objects.
  const nativeValues = [[45292, 45292.5, 45292, "45292", "2024-01-01", 45292, 1.5, 45292]];
  const nativeFormats = [["dd/mm/yyyy", "yyyy-mm-dd hh:mm:ss", "General", "dd/mm/yyyy", "General", '0" days"', "[h]:mm:ss", "[$-409]mmm d, yyyy"]];
  host = makeHost([{sheet: "Native", header: ["Date", "DateTime", "Amount", "TextSerial", "TextISO", "Literal", "Elapsed", "LocaleDate"],
    rows: nativeValues, numberFormats: nativeFormats}]);
  const native = plain(await sandbox.__flowReadOpenWorkbook("compute"));
  assert.deepEqual(native[0].rows, [["2024-01-01", "2024-01-01T12:00:00", "45292", "45292", "2024-01-01", "45292", "1.5", "2024-01-01"]]);
  assert.deepEqual(nativeValues, [[45292, 45292.5, 45292, "45292", "2024-01-01", 45292, 1.5, 45292]], "reader must not mutate native values");
  assert.ok(host.reads.some((read) => read.kind === "formats"));
  assert.ok(host.reads.some((read) => read.kind === "epoch-probe"));
  host = makeHost([{sheet: "Epoch1904", header: ["Date"], rows: [[43830], [0], [0.25]],
    numberFormats: [["yyyy-mm-dd"], ["yyyy-mm-dd"], ["yyyy-mm-dd"]]}], {epochProbe: 0});
  assert.deepEqual(plain(await sandbox.__flowReadOpenWorkbook())[0].rows,
    [["2024-01-01"], ["1904-01-01"], ["1904-01-01T06:00:00"]]);
  host = makeHost([{sheet: "LooseDates", header: ["Date", "Midnight", "Subsecond"], table: false,
    rows: [[45292, 45292, 45292.500001]], numberFormats: [["yyyy-mm-dd;@", "yyyy-mm-dd hh:mm:ss", "yyyy-mm-dd hh:mm:ss.000000"]]}]);
  assert.deepEqual(plain(await sandbox.__flowReadOpenWorkbook())[0].rows,
    [["2024-01-01", "2024-01-01T00:00:00", "2024-01-01T12:00:00.0864"]]);
  host = makeHost([{sheet: "Boundaries", header: ["Date"], rows: [[1], [59], [61], [2958465], [45292 + 1 / 86400]],
    numberFormats: Array.from({length: 5}, () => ["yyyy-mm-dd"])}]);
  assert.deepEqual(plain(await sandbox.__flowReadOpenWorkbook())[0].rows,
    [["1900-01-01"], ["1900-02-28"], ["1900-03-01"], ["9999-12-31"], ["2024-01-01T00:00:01"]]);
  for (const value of [0, -1, 60, 60.5, NaN, Infinity, 2958466]) {
    host = makeHost([{sheet: "InvalidDate", header: ["Date"], rows: [[value]], numberFormats: [["yyyy-mm-dd"]]}]);
    await assert.rejects(() => sandbox.__flowReadOpenWorkbook(), (error) => error.code === "AF_WORKBOOK_DATE_UNSUPPORTED");
  }
  for (const options of [{epochProbe: 123}, {epochError: "#VALUE!"}, {probeUnavailable: true}]) {
    host = makeHost([{sheet: "UnknownEpoch", header: ["Date"], rows: [[45292]], numberFormats: [["yyyy-mm-dd"]]}], options);
    await assert.rejects(() => sandbox.__flowReadOpenWorkbook(), (error) => error.code === "AF_WORKBOOK_DATE_UNSUPPORTED");
    host = makeHost([{sheet: "Numeric", header: ["Amount"], rows: [[45292]]}], options);
    assert.deepEqual(plain(await sandbox.__flowReadOpenWorkbook())[0].rows, [["45292"]]);
  }
  for (const format of ['0\\d', '0"day"', "0_d", "0*d", "[h]:mm:ss", "hh:mm:ss", "0.00E+00", "[<0]0;0"]) {
    host = makeHost([{sheet: "NotCalendar", header: ["Amount"], rows: [[45292]], numberFormats: [[format]]}]);
    assert.deepEqual(plain(await sandbox.__flowReadOpenWorkbook())[0].rows, [["45292"]], `must not infer a date from ${format}`);
  }
  for (const format of ["[>=1]yyyy-mm-dd;0", "[<1]h:mm;yyyy-mm-dd", "yyyy-mm-dd [h]", 'yyyy-mm-dd"unterminated', "yyyyyy-mm-dd", "y".repeat(513), null]) {
    host = makeHost([{sheet: "Ambiguous", header: ["Date"], rows: [[45292]], numberFormats: [[format]]}]);
    await assert.rejects(() => sandbox.__flowReadOpenWorkbook(), (error) => error.code === "AF_WORKBOOK_DATE_UNSUPPORTED");
  }
  host = makeHost([{sheet: "PerSection", header: ["Month", "Time"], rows: [[45292, 45292]],
    numberFormats: [["m;[h]", "[h];yyyy-mm-dd"]]}]);
  assert.deepEqual(plain(await sandbox.__flowReadOpenWorkbook())[0].rows, [["2024-01-01", "45292"]],
    "elapsed tokens in an inactive format section must not change calendar detection");
  host = makeHost([{sheet: "Submicrosecond", header: ["Date"], rows: [[1.0000000001]], numberFormats: [["yyyy-mm-dd hh:mm:ss.000000"]]}]);
  await assert.rejects(() => sandbox.__flowReadOpenWorkbook(), (error) => error.code === "AF_WORKBOOK_DATE_UNSUPPORTED");
  const datedRows = Array.from({length: 37}, (_, index) => [45292 + index]);
  host = makeHost([{sheet: "SampledDates", header: ["Date"], rows: datedRows,
    numberFormats: datedRows.map(() => ["yyyy-mm-dd"])}]);
  const datedFull = plain(await sandbox.__flowReadOpenWorkbook("compute"))[0];
  host.reads.length = 0;
  const datedSample = plain(await sandbox.__flowReadOpenWorkbook("discover"))[0];
  assert.deepEqual(datedSample.rows, datedSample.sampleOrdinals.map((ordinal) => datedFull.rows[ordinal]));
  assert.deepEqual(datedSample.sampleOrdinals, plain(sandbox.__flowSampleOrdinals(datedFull.header, datedFull.rows, datedFull.totalRows)));
  assert.ok(!host.reads.some((read) => read.kind === "full"), "date discovery must retain sampled-only value reads");

  const rows = Array.from({length: 37}, (_, index) => [index, index === 0 ? localDate : null, index % 2 === 0]);
  host = makeHost([{sheet: "Orders", header: ["", " Date ", "Flag"], rows},
    {sheet: "Loose", header: [null, "Value"], rows: [["x", 7]], table: false}]);
  const full = plain(await sandbox.__flowReadOpenWorkbook());
  assert.deepEqual(full[0].header, ["A", "Date", "Flag"]);
  assert.deepEqual(full[0].rows[0], ["0", "2026-09-01", "TRUE"]);
  assert.equal(full[0].totalRows, 37);
  assert.equal(full[0].totalColumns, full[0].header.length);
  assert.equal(full[0].range, "C4:E41");
  assert.deepEqual(full[1].header, ["A", "Value"]);
  assert.deepEqual(full[1].rows, [["x", "7"]]);
  assert.equal(full[1].totalRows, 1);
  assert.ok(host.reads.some((item) => item.kind === "body"));
  assert.ok(host.reads.some((item) => item.kind === "header"));

  const ordinals = plain(sandbox.__flowSampleOrdinals(full[0].header, full[0].rows, 37));
  assert.deepEqual(ordinals, plain(sandbox.__flowSampleOrdinals(full[0].header, full[0].rows, 37)));
  assert.equal(ordinals.length, 20);
  assert.equal(ordinals[0], 0);
  assert.equal(ordinals.at(-1), 36);
  assert.equal(new Set(ordinals).size, 20);
  assert.ok(ordinals.every((value, index) => value >= 0 && value < 37 && (!index || value > ordinals[index - 1])));
  assert.deepEqual(plain(sandbox.__flowSampleOrdinals(["A"], [], 0)), []);
  assert.deepEqual(plain(sandbox.__flowSampleOrdinals(["A"], [[1]], 1)), [0]);
  host.reads.length = 0;
  const sampled = plain(await sandbox.__flowReadOpenWorkbook("discover"));
  assert.deepEqual(sampled[0].sampleOrdinals, ordinals);
  assert.deepEqual(sampled[0].rows, ordinals.map((index) => full[0].rows[index]));
  assert.ok(!host.reads.some((item) => item.kind === "full"), "discover must never load the full body values");

  host = makeHost([{sheet: "Huge", header: ["A", "B", "C", "D", "E"], rows: [], rowCount: 100001},
    {sheet: "Small", header: ["A"], rows: [[1]]}]);
  await assert.rejects(() => sandbox.__flowReadOpenWorkbook(), /giới hạn/);
  assert.ok(!host.reads.some((item) => item.kind === "full"), "bounds must be checked before loading full values");
  const metadata = await sandbox.__flowReadOpenWorkbook("discover", null, true);
  assert.equal(metadata.length, 2, "navigator can inspect metadata before selecting a smaller source");
  const smallKey = JSON.stringify(["Small", "Small", true]);
  const selectedSmall = await sandbox.__flowReadOpenWorkbook("compute", new Set([smallKey]));
  assert.equal(selectedSmall.length, 1);
  assert.equal(selectedSmall[0].name, "Small");

  sandbox.__bindFlowEvents();
  const disabledFlow = readyFlow();
  disabledFlow.v2Capability = false;
  sandbox.__updateFlowButtons();
  const beforeDisabled = calls.length;
  await element("flow-root-button").click();
  await sandbox.__flowBindRoot();
  await sandbox.__flowIngest("compute");
  await sandbox.__flowUnderstand();
  assert.equal(calls.length, beforeDisabled, "feature-gated actions must make zero requests");

  readyFlow();
  element("flow-root-input").value = "C:\\synthetic";
  responseHandler = async (request) => request.url.endsWith("/session")
    ? {stage: "new", rootLabel: "synthetic"}
    : {stage: "ingested", mode: request.payload.requests[0].mode, snapshot: {snapshotId: "snap_1"}, sources: [], tables: [],
      errors: [], warnings: [], csvOptions: [], requiresRename: [], sampleInfo: []};
  await sandbox.__flowBindRoot();
  assert.equal(sandbox.__state.flow.rootLabel, "synthetic");
  assert.equal(calls.at(-1).headers["X-Local-Token"], "token-test");
  element("flow-path-input").value = "first.csv";
  sandbox.__flowAddFile("csv");
  element("flow-path-input").value = "second.csv";
  sandbox.__flowAddFile("csv");
  const checkbox = element("flow-navigator").children[1].children[0];
  checkbox.checked = false;
  await checkbox.emit("change");
  await sandbox.__flowIngest("discover");
  assert.deepEqual(calls.at(-1).payload.requests, [{kind: "csv", path: "first.csv", options: {}, mode: "discover"}]);
  assert.equal(sandbox.__state.flow.busy, false);

  readyFlow();
  host = makeHost([{sheet: "One", header: ["Amount"], rows: [[1], [2]]},
    {sheet: "Two", header: ["Amount"], rows: [[8]]}]);
  await sandbox.__flowAddOpenWorkbook();
  assert.ok(!host.reads.some((item) => item.kind === "full"));
  const second = element("flow-navigator").children[1].children[0];
  second.checked = false;
  await second.emit("change");
  await sandbox.__flowIngest("compute");
  const workbookRequests = calls.at(-1).payload.requests;
  assert.equal(workbookRequests.length, 1);
  assert.equal(workbookRequests[0].payload.name, "One");
  assert.equal(workbookRequests[0].mode, "compute");
  assert.deepEqual(workbookRequests[0].payload.rows, [["1"], ["2"]]);
  assert.deepEqual(workbookRequests[0].payload.sampleOrdinals, [0, 1]);
  assert.ok(!host.reads.some((item) => item.kind === "full" && item.name === "Two"));

  readyFlow();
  host = makeHost([{sheet: "Raw", name: "Orders", header: ["Amount"], rows: [[1]]},
    {sheet: "Orders", header: ["Amount"], rows: [[2]], table: false}]);
  await sandbox.__flowAddOpenWorkbook();
  responseHandler = async () => ({stage: "ingest_blocked", mode: "discover", snapshot: null,
    sources: [{id: "src_table", name: "Orders", origin: "Workbook!Raw!Orders"},
      {id: "src_sheet", name: "Orders", origin: "Workbook!Orders!Orders"}],
    tables: [], errors: [], warnings: [], csvOptions: [], sampleInfo: [],
    requiresRename: [{tableName: "Orders", sources: ["src_table", "src_sheet"]}]});
  await sandbox.__flowIngest("discover");
  assert.equal(sandbox.__state.flow.stage, "ingest_blocked");
  const renameInputs = element("flow-rename-list").children.map((label) => label.children[0]);
  assert.equal(renameInputs.length, 2);
  assert.ok(renameInputs.every((input) => !input.disabled), "every conflicting workbook selection must be recoverable");
  renameInputs[0].value = "OrdersTable";
  await renameInputs[0].emit("change");
  renameInputs[1].value = "OrdersSheet";
  await renameInputs[1].emit("change");
  responseHandler = async () => ({stage: "ingested", mode: "compute", snapshot: {snapshotId: "renamed"},
    sources: [], tables: [], errors: [], warnings: [], csvOptions: [], requiresRename: [], sampleInfo: []});
  await sandbox.__flowIngest("compute");
  assert.deepEqual(calls.at(-1).payload.requests.map((request) => request.payload.name), ["OrdersTable", "OrdersSheet"]);

  readyFlow();
  element("flow-path-input").value = "csv/ambiguous.csv";
  sandbox.__flowAddFile("csv");
  responseHandler = async () => ({stage: "ingest_blocked", mode: "discover", snapshot: null,
    sources: [],
    errors: [{code: "CSV_AMBIGUOUS_DELIMITER", detail: "choose delimiter"}], warnings: [], requiresRename: [], tables: [], sampleInfo: [],
    csvOptions: [{sourceId: "src_csv", origin: "csv/ambiguous.csv", encoding: "utf-8", headerRow: 1, needsClarification: true,
      candidates: [{delimiter: ";"}, {delimiter: ","}]}]});
  await sandbox.__flowIngest("discover");
  const csvGroup = element("flow-csv-options").children[0];
  const delimiter = csvGroup.children[1].children[0];
  delimiter.value = ";";
  await delimiter.emit("change");
  const headerInput = csvGroup.children[3].children[0];
  headerInput.value = "2";
  await headerInput.emit("change");
  responseHandler = async () => ({stage: "ingested", mode: "discover", snapshot: {snapshotId: "csv_fixed"},
    sources: [], tables: [], errors: [], warnings: [], csvOptions: [], requiresRename: [], sampleInfo: []});
  await sandbox.__flowIngest("discover");
  assert.deepEqual(calls.at(-1).payload.requests[0].options, {delimiter: ";", header_row: 2});

  const flow = readyFlow();
  flow.snapshot = {snapshotId: "snap_1"};
  flow.stage = "ingested";
  let complete;
  responseHandler = () => new Promise((resolve) => { complete = resolve; });
  const pending = sandbox.__flowUnderstand();
  assert.equal(flow.busy, true);
  sandbox.__resetFlowView("", {explicit: true});
  complete({stage: "understood", understand: {roles: [], relationships: [], assumptions: []}, questions: [{id: "old"}]});
  await pending;
  assert.equal(sandbox.__state.flow.understand, null, "old async reply must not populate the replacement flow");
  assert.deepEqual(plain(sandbox.__state.flow.questions), []);

  const recovering = readyFlow();
  recovering.snapshot = {snapshotId: "snap_2"};
  recovering.stage = "ingested";
  responseHandler = async () => { throw Object.assign(new Error("synthetic disconnect"), {code: "AF_INGEST_FAILED"}); };
  await sandbox.__flowUnderstand();
  assert.equal(recovering.busy, false);
  assert.equal(element("error-code").textContent, "AF_INGEST_FAILED");
  responseHandler = async () => ({stage: "understood", understand: {roles: [], relationships: [], assumptions: []},
    questions: [{id: "q_1", question: "What is the grain?", whyItMatters: "Avoid duplicates", kind: "single_choice", options: ["Order", "Line"], evidence: [{kind: "stats", value: "2 rows"}]}]});
  await sandbox.__flowUnderstand();
  assert.equal(recovering.stage, "understood");
  const answer = element("flow-questions").children[0].children[0];
  answer.value = "Line";
  await answer.emit("change");
  assert.equal(recovering.answers.q_1, "Line");
  answer.value = "";
  await answer.emit("change");
  assert.equal(Object.prototype.hasOwnProperty.call(recovering.answers, "q_1"), false, "clearing an optional answer removes it");
  assert.match(element("flow-understand-summary").textContent, /0 bảng, 0 quan hệ/);
  assert.equal(element("flow-understand-section").dataset.state, "understood");

  let completeAfterWorkbookSwitch;
  responseHandler = () => new Promise((resolve) => { completeAfterWorkbookSwitch = resolve; });
  const changedWorkbook = sandbox.__flowUnderstand();
  sandbox.__state.workbook = {name: "another-synthetic.xlsx", url: ""};
  completeAfterWorkbookSwitch({stage: "understood", understand: {roles: [], relationships: []}, questions: []});
  await changedWorkbook;
  assert.equal(sandbox.__state.flow.snapshot, null);
  assert.equal(sandbox.__state.flow.understand, null);
  assert.equal(element("error-code").textContent, "AF_SPEC_STALE");

  const planned = readyFlow();
  planned.snapshot = {snapshotId: "snap_plan"};
  planned.understand = {roles: [], relationships: []};
  planned.stage = "understood";
  planned.answers = {q_2: "Keep lines", q_1: "Amount is the measure"};
  element("flow-disclosure").checked = false;
  sandbox.__updateFlowButtons();
  assert.equal(element("flow-plan-button").disabled, true);
  const beforeDisclosure = calls.length;
  await sandbox.__flowPlanDraft();
  assert.equal(calls.length, beforeDisclosure, "disclosure must gate the actual Codex request");
  assert.equal(element("error-code").textContent, "AF_DISCLOSURE_REQUIRED");
  element("flow-disclosure").checked = true;
  await element("flow-disclosure").emit("change");
  assert.equal(element("flow-plan-button").disabled, false);
  const cards = {stage: "planning", planningHash: "sha256:" + "c".repeat(64), summary: "Two plans awaiting computation", questions: ["Confirm measure"],
    assumptions: [{statement: "Synthetic assumption", risk: "low"}], branches: ["A", "B"].map((id) => ({
      id, label: id === "A" ? "All lines" : "<img src=x>", rationale: "Engine will compute values later",
      controlTotal: null, planHash: "sha256:" + id.repeat(64),
      steps: [{id: "step_" + id, operationType: "source.workbookTable", label: "Read named source"}]}))};
  responseHandler = async (request) => {
    assert.ok(request.url.endsWith("/plan-draft"));
    assert.deepEqual(request.payload, {prompt: "Summarize synthetic values", acknowledged: true,
      answers: [{questionId: "q_1", answer: "Amount is the measure"}, {questionId: "q_2", answer: "Keep lines"}]});
    return cards;
  };
  await element("flow-plan-button").click();
  assert.equal(planned.stage, "planning");
  assert.equal(element("flow-branches-section").classList.contains("hidden"), false);
  assert.equal(element("flow-plan-summary").textContent, cards.summary);
  const branches = element("flow-branches").children;
  assert.equal(branches.length, 2);
  assert.equal(branches[1].children[0].textContent, "B · <img src=x>");
  for (const card of branches) {
    assert.equal(card.children[2].textContent, "chưa tính số");
    assert.equal(card.children[3].children.length, 1);
    assert.equal(card.children[4].textContent, "Chọn nhánh");
    assert.equal(card.children[4].disabled, true);
    assert.ok(!card.children.some((child) => child.tag === "table"), "skeleton contains no computed result table");
  }
  planned.pendingRequests = [{id: "source_plan", request: {kind: "csv", path: "fixture.csv", options: {}}}];
  planned.selectedTableIds.add("source_plan");
  responseHandler = async (request) => {
    assert.equal(request.payload.expectedPlanningHash, cards.planningHash);
    return {stage: "planning", mode: "compute", snapshot: {snapshotId: "snap_full_plan"},
      understand: {roles: [], relationships: []}, branches: cards.branches, planningHash: cards.planningHash};
  };
  await sandbox.__flowIngest("compute");
  assert.equal(planned.planningHash, cards.planningHash);
  assert.ok(calls.at(-1).url.endsWith("/ingest"), "full ingestion does not automatically execute plans");
  assert.equal(element("flow-branches-button").disabled, false);
  const computedBranches = {stage: "branched", planningHash: cards.planningHash,
    snapshotHash: "sha256:" + "d".repeat(64), allBlocked: false,
    engine: {executor: "typed_local", version: "1.0", parityChecked: "none"},
    delta: {applicable: true, a: "12.30", b: "3.10", value: "9.20", computedBy: "typed_local"},
    branches: cards.branches.map((branch, index) => ({...branch,
      columns: [{name: "Total", type: "number"}], rows: [[index ? "3.10" : "12.30"]],
      totalRows: 1, truncated: false, counts: {before: {rows: 50, cols: 2}, after: {rows: 1, cols: 1}},
      elapsedMs: index ? 7 : 11, cached: false, selectable: !index,
      error: index ? {code: "AF_FANOUT_RISK", detail: "Join exceeds declared bound"} : null,
      reconciliation: {passed: !index, controlTotalApplicable: true, controlTotalReason: null}}))};
  responseHandler = async (request) => {
    assert.ok(request.url.endsWith("/branches"));
    assert.deepEqual(request.payload, {expectedPlanningHash: cards.planningHash});
    assert.equal(planned.mode, "compute");
    return plain(computedBranches);
  };
  await element("flow-branches-button").click();
  assert.equal(planned.stage, "branched");
  assert.match(element("flow-branch-engine").textContent, /chưa đối chiếu với Power Query/);
  assert.match(element("flow-branch-delta").textContent, /A 12.30 − B 3.10 = 9.20/);
  const computedCards = element("flow-branches").children;
  assert.equal(computedCards[0].children[4].type, "radio");
  assert.equal(computedCards[0].children[4].disabled, false);
  assert.equal(computedCards[1].children[4].disabled, true);
  assert.match(computedCards[1].children[5].textContent, /AF_FANOUT_RISK/);
  assert.equal(computedCards[0].children[5].getAttribute("role"), "status");
  assert.equal(element("flow-branch-A-preview").children[0].children[1].children[0].children[0].textContent, "12.30");
  assert.deepEqual(element("flow-branch-A-counts").children[0].children[1].children.map((row) => row.children.map((cell) => cell.textContent)),
    [["Trước", "50", "2"], ["Sau", "1", "1"]]);
  assert.match(computedCards[0].children.at(-1).textContent, /11 ms/);
  computedCards[0].children[4].checked = true;
  await computedCards[0].children[4].emit("change");
  assert.equal(planned.chosenBranch, "A");
  assert.equal(element("flow-freeze-button").disabled, false, "a selected verified compute branch can now be frozen");

  // QA-17/48: review exact parameters after execute; total equality cannot hide warnings.
  planned.branches[0].normalizedSteps = [{stepId: "review-filter", variableName: "Filtered", inputs: ["source"],
    operation: {type: "table.filterRows", parameters: {predicate: {kind: "compare", operator: "gt",
      left: {kind: "columnRef", column: "Amount"}, right: {kind: "literal", valueType: "number", value: 137}}}}}];
  planned.branches[0].finalOutputContract = {columns: [{name: "Amount", type: "number"}]};
  planned.branches[0].warnings = [{code: "AF_EXECUTOR_DATE_NULL", path: "review-filter.Date", message: "Giá trị ngày không hợp lệ được chuyển thành null."}];
  planned.branches[0].warningCount = 1;
  sandbox.__renderFlowBranches();
  const reviewedCard = element("flow-branches").children[0];
  assert.match(renderedText(reviewedCard), /"value":\s*137/);
  assert.match(renderedText(reviewedCard), /"column":\s*"Amount"/);
  assert.match(renderedText(reviewedCard), /AF_EXECUTOR_DATE_NULL/);
  assert.match(reviewedCard.children[5].textContent, /Đối soát tổng đạt.*cảnh báo/);
  assert.match(renderedText(reviewedCard), /nhóm cảnh báo/);
  assert.equal(reviewedCard.children[4].disabled, false, "visible warning does not bypass or invent hard blockers");
  planned.branches[0].warnings = []; planned.branches[0].warningCount = 0;

  // Missing R2 is explicitly unverified, rather than a successful reconciliation.
  const unverified = planned.branches[0];
  unverified.reconciliation = {passed: false, controlTotalApplicable: false,
    controlTotalReason: "Source basis is unavailable", acknowledgementRequired: true, hardChecksPassed: true};
  unverified.rows = Array.from({length: 205}, (_, index) => [String(index)]);
  unverified.totalRows = 205;
  unverified.truncated = true;
  unverified.cached = true;
  sandbox.__renderFlowBranches();
  assert.match(element("flow-branches").children[0].children[5].textContent, /Chưa có đối soát tổng kiểm soát.*xác nhận tường minh/);
  assert.equal(element("flow-branches").children[0].children[4].disabled, false);
  sandbox.__updateFlowButtons();
  assert.equal(element("flow-freeze-button").disabled, true, "missing control requires a separate explicit acknowledgement");
  element("flow-control-ack").checked = true;
  await element("flow-control-ack").emit("change");
  assert.equal(element("flow-freeze-button").disabled, false);
  assert.equal(element("flow-branch-A-preview").children[0].children[1].children.length, 200);
  assert.match(element("flow-branches").children[0].children.at(-1).textContent, /dùng cache/);
  assert.match(element("flow-branches").children[0].children.at(-1).textContent, /200\/205 dòng/);
  planned.allBlocked = true;
  planned.branches.forEach((branch) => { branch.selectable = false; });
  sandbox.__renderFlowBranches();
  assert.match(element("flow-branch-status").textContent, /Cả hai nhánh bị chặn.*Quay lại/);
  assert.ok(element("flow-branches").children.every((card) => card.children[4].disabled));
  element("prompt").value = "A changed business goal";
  await element("prompt").emit("input");
  assert.equal(planned.branches.length, 0, "editing the goal invalidates old plan cards");
  assert.equal(element("flow-disclosure").checked, false);
  assert.equal(element("flow-plan-button").disabled, true);
  assert.equal(planned.planningHash, null);
  responseHandler = async (request) => {
    assert.equal(Object.prototype.hasOwnProperty.call(request.payload, "expectedPlanningHash"), false);
    return {stage: "ingested", mode: "compute", snapshot: {snapshotId: "snap_after_edit"}, understand: null,
      branches: [], planningHash: null};
  };
  await sandbox.__flowIngest("compute");
  assert.equal(planned.branches.length, 0, "compute after goal edit cannot restore the previous plan");

  const pendingComputeFlow = readyFlow();
  pendingComputeFlow.stage = "planning";
  pendingComputeFlow.snapshot = {snapshotId: "snap_before_compute"};
  pendingComputeFlow.understand = {roles: [], relationships: []};
  pendingComputeFlow.branches = cards.branches;
  pendingComputeFlow.planningHash = cards.planningHash;
  pendingComputeFlow.pendingRequests = [{id: "compute_source", request: {kind: "csv", path: "fixture.csv", options: {}}}];
  pendingComputeFlow.selectedTableIds.add("compute_source");
  let resolveCompute;
  responseHandler = () => new Promise((resolve) => { resolveCompute = resolve; });
  const pendingCompute = sandbox.__flowIngest("compute");
  element("prompt").value = "Changed while full ingestion was pending";
  await element("prompt").emit("input");
  resolveCompute({stage: "planning", mode: "compute", snapshot: {snapshotId: "late_compute"},
    understand: {roles: [], relationships: []}, branches: cards.branches, planningHash: cards.planningHash});
  await pendingCompute;
  assert.equal(element("error-code").textContent, "AF_SPEC_STALE");
  assert.equal(sandbox.__state.flow.branches.length, 0, "late compute cannot resurrect a goal invalidated during the HTTP call");
  assert.equal(sandbox.__state.flow.planningHash, null);

  const sampleOnly = readyFlow();
  sampleOnly.mode = "discover";
  sampleOnly.stage = "planning";
  sampleOnly.planningHash = cards.planningHash;
  const beforeSampleExecute = calls.length;
  await sandbox.__flowExecuteBranches();
  assert.equal(calls.length, beforeSampleExecute);
  assert.equal(element("error-code").textContent, "AF_SAMPLE_ONLY");

  const staleBranches = readyFlow();
  Object.assign(staleBranches, {mode: "compute", stage: "planning", planningHash: cards.planningHash,
    snapshot: {snapshotId: "snapshot_branch_race"}, understand: {roles: [], relationships: []}, branches: cards.branches});
  let resolveBranches;
  responseHandler = () => new Promise((resolve) => { resolveBranches = resolve; });
  const pendingBranches = sandbox.__flowExecuteBranches();
  assert.equal(staleBranches.stage, "branching");
  assert.match(element("flow-branch-status").textContent, /Đang tính A\/B/);
  const beforeDoubleBranches = calls.length;
  await sandbox.__flowExecuteBranches();
  assert.equal(calls.length, beforeDoubleBranches, "branch calculations cannot double submit");
  element("prompt").value = "New goal while calculations were pending";
  await element("prompt").emit("input");
  resolveBranches(plain(computedBranches));
  await pendingBranches;
  assert.equal(element("error-code").textContent, "AF_SPEC_STALE");
  assert.equal(sandbox.__state.flow.branches.length, 0, "late numeric previews cannot restore invalid plans");

  const resetBranches = readyFlow();
  Object.assign(resetBranches, {mode: "compute", stage: "planning", planningHash: cards.planningHash,
    snapshot: {snapshotId: "snapshot_branch_reset"}, understand: {roles: [], relationships: []}, branches: cards.branches});
  let resolveResetBranches;
  responseHandler = () => new Promise((resolve) => { resolveResetBranches = resolve; });
  const pendingResetBranches = sandbox.__flowExecuteBranches();
  sandbox.__resetFlowView("", {explicit: true});
  resolveResetBranches(plain(computedBranches));
  await pendingResetBranches;
  assert.equal(sandbox.__state.flow.branches.length, 0, "late branch reply cannot populate a reset flow");

  const stalePlan = readyFlow();
  stalePlan.snapshot = {snapshotId: "snap_stale_plan"};
  stalePlan.understand = {roles: [], relationships: []};
  stalePlan.stage = "understood";
  element("flow-disclosure").checked = true;
  let resolvePlan;
  responseHandler = () => new Promise((resolve) => { resolvePlan = resolve; });
  const pendingPlan = sandbox.__flowPlanDraft();
  assert.equal(stalePlan.busy, true);
  const inFlightCount = calls.length;
  await sandbox.__flowPlanDraft();
  assert.equal(calls.length, inFlightCount, "double submit cannot create a second Codex call");
  element("prompt").value = "Changed while Codex was running";
  resolvePlan(cards);
  await pendingPlan;
  assert.equal(element("error-code").textContent, "AF_SPEC_STALE");
  assert.equal(sandbox.__state.flow.branches.length, 0);

  const resetPlan = readyFlow();
  resetPlan.snapshot = {snapshotId: "snap_reset_plan"};
  resetPlan.understand = {roles: [], relationships: []};
  resetPlan.stage = "understood";
  element("flow-disclosure").checked = true;
  let resolveResetPlan;
  responseHandler = () => new Promise((resolve) => { resolveResetPlan = resolve; });
  const pendingResetPlan = sandbox.__flowPlanDraft();
  sandbox.__resetFlowView("", {explicit: true});
  resolveResetPlan(cards);
  await pendingResetPlan;
  assert.equal(sandbox.__state.flow.branches.length, 0, "late plan reply cannot populate a reset flow");

  const restoredFlow = readyFlow();
  element("prompt").value = "";
  const restoredState = {stage: "planning", snapshot: {snapshotId: "snap_restored"},
    understand: {roles: [], relationships: []}, branches: cards.branches, planningHash: cards.planningHash,
    draftInputs: {prompt: "Restored goal", answers: [{questionId: "q_policy", answer: "Confirmed"}]}};
  responseHandler = async () => plain(restoredState);
  await sandbox.__flowLoadState();
  assert.equal(element("prompt").value, "Restored goal");
  assert.equal(restoredFlow.answers.q_policy, "Confirmed");
  assert.equal(restoredFlow.planningHash, cards.planningHash);
  assert.equal(restoredFlow.branches.length, 2);
  element("prompt").value = "Unsubmitted new goal";
  await element("prompt").emit("input");
  await sandbox.__flowLoadState();
  assert.equal(element("prompt").value, "Unsubmitted new goal", "state reload cannot overwrite local unsent edits");
  assert.equal(restoredFlow.planningHash, null);
  assert.equal(restoredFlow.branches.length, 0, "state reload cannot pair old plans with a new local goal");

  // E: the actual UI journey freezes the displayed revision, approves after a
  // fresh full source read, writes one new sheet, and verifies every row.
  let supported = true;
  const office = {context: {document: {url: ""}, requirements: {isSetSupported: () => supported}}};
  sandbox.Office = sandbox.window.Office = office;
  sandbox.__setFlowExport(async () => "SYNTHETIC_PACKAGE");
  const resultColumns = [{name: "=Literal header", type: "text"}, {name: "Decimal", type: "number"}];
  const resultRows = Array.from({length: 30}, (_, index) => [index === 0 ? "=SUM(1,1)" : "line " + index, "9007199254740993.123"]);
  const resultDigest = await sandbox.__flowDigest({columns: resultColumns, rows: resultRows});
  const frozenSpec = {branchId: "A", fingerprint: "sha256:" + "e".repeat(64), previewHash: "sha256:" + "f".repeat(64),
    resultDigest, target: {sheet: "Assistant_A_owned"}, labels: [], steps: [{operation: {type: "table.aggregateRows"}}]};
  const receiptBinding = {handoffId: "handoff_synthetic", specFingerprint: frozenSpec.fingerprint,
    previewHash: frozenSpec.previewHash, resultDigest, sheet: frozenSpec.target.sheet, marker: "LOCAL_DATA_COPILOT|synthetic",
    rowCount: resultRows.length, columnCount: resultColumns.length};
  const handoffResult = {stage: "handoff", result: {columns: resultColumns, rows: resultRows, totalRows: 30, truncated: false},
    resultDigest, marker: receiptBinding.marker, labels: [], receiptBinding, apply: {target: frozenSpec.target, approval: {consumed: true}}};
  function readyE(options = {}) {
    const flow = readyFlow();
    host = writeHost(options);
    Object.assign(flow, {mode: "compute", stage: "branched", chosenBranch: "A", planningHash: cards.planningHash,
      snapshot: {snapshotId: "snap_frozen"}, understand: {roles: [], relationships: []},
      branches: computedBranches.branches.map((branch) => ({...plain(branch), previewHash: frozenSpec.previewHash, resultDigest})),
      workbookSourceSelections: [{sheet: "Source", name: "Transactions", origin: "Workbook!Source!Transactions", table: true}]});
    sandbox.__updateFlowButtons();
    return flow;
  }
  const eFlow = readyE();
  responseHandler = async (request) => {
    assert.ok(request.url.endsWith("/freeze"));
    assert.equal(request.payload.expectedPlanningHash, cards.planningHash);
    assert.equal(request.payload.expectedPreviewHash, frozenSpec.previewHash);
    assert.equal(request.payload.expectedResultDigest, resultDigest);
    assert.equal(request.payload.workbookIdentity.documentHash, await sandbox.__flowDigest(""));
    return {stage: "frozen", spec: plain(frozenSpec), chosenBranch: "A"};
  };
  await element("flow-freeze-button").click();
  assert.equal(eFlow.stage, "frozen");
  assert.equal(element("flow-spec-section").classList.contains("hidden"), false);
  assert.match(element("flow-spec-summary").textContent, /Assistant_A_owned/);
  assert.equal(element("flow-approve-button").disabled, true);
  element("flow-approve-check").checked = true;
  await element("flow-approve-check").emit("change");
  assert.equal(element("flow-approve-button").disabled, false);
  responseHandler = async (request) => {
    assert.ok(request.url.endsWith("/approvals"));
    assert.equal(request.payload.expectedSpecFingerprint, frozenSpec.fingerprint);
    assert.equal(request.payload.expectedPreviewHash, frozenSpec.previewHash);
    assert.deepEqual(request.payload.workbookSources[0].payload.rows, [["a", "12"]]);
    return {stage: "approved", spec: plain(frozenSpec), approval: {consumed: false, approvalId: "display-only"}};
  };
  await element("flow-approve-button").click();
  assert.equal(eFlow.stage, "approved");
  assert.equal(host.writes.length, 0, "approval never writes worksheets");
  let verifiedReceipts = 0;
  responseHandler = async (request) => {
    assert.ok(request.url.endsWith("/apply"));
    if (!request.payload.receipt) {
      assert.equal(request.payload.expectedSpecFingerprint, frozenSpec.fingerprint);
      assert.equal(request.payload.workbookBase64, "SYNTHETIC_PACKAGE");
      assert.deepEqual(request.payload.workbookSources[0].payload.rows, [["a", "12"]]);
      return plain(handoffResult);
    }
    assert.deepEqual(request.payload.receipt, {...receiptBinding, verified: true});
    verifiedReceipts++;
    assert.notEqual(eFlow.stage, "applied", "handoff alone cannot report an applied result");
    return {stage: "applied", apply: {workbookSaved: false}};
  };
  await element("flow-apply-button").click();
  assert.equal(eFlow.stage, "applied", element("error-message").textContent + " / " + element("error-detail").textContent);
  assert.equal(verifiedReceipts, 1);
  assert.equal(eFlow.approvalConsumed, true);
  assert.equal(eFlow.handoffStatus, "readback-verified");
  assert.equal(host.writes.filter((item) => item.kind === "new-sheet").length, 1);
  assert.equal(host.workbook.worksheets.items[0].name, "Source");
  assert.deepEqual(host.sourceValues, [["a", "12"]], "source table remains byte-equivalent in the fake Office host");
  assert.match(element("flow-apply-status").textContent, /Đã ghi.*toàn bộ.*chưa lưu.*văn bản/);
  assert.equal(element("flow-apply-button").disabled, true);

  function approvedE(options = {}) {
    const flow = readyE(options);
    Object.assign(flow, {stage: "approved", spec: plain(frozenSpec), approval: {consumed: false}});
    element("flow-approve-check").checked = true;
    element("flow-approve-check").checked = true;
    sandbox.__updateFlowButtons();
    return flow;
  }
  for (const failure of ["tail-corruption", "formula", "source-during-handoff", "receipt-expired", "network-lost", "collision"]) {
    const partial = approvedE({corrupt: failure === "tail-corruption", formula: failure === "formula", collision: failure === "collision"});
    let failedReceipt = false, sentVerified = false;
    responseHandler = async (request) => {
      if (!request.payload.receipt) {
        if (failure === "network-lost") throw new Error("Synthetic response lost after possible consume");
        if (failure === "source-during-handoff") host.sourceValues[0][1] = "999";
        return plain(handoffResult);
      }
      if (request.payload.receipt.verified) {
        sentVerified = true;
        assert.equal(failure, "receipt-expired");
        return {__httpStatus: 401, error: {code: "TOKEN_EXPIRED", detail: "Synthetic expired receipt token"}};
      }
      failedReceipt = true;
      return {__httpStatus: 500, error: {code: "AF_WRITE_PARTIAL", detail: "Read-back rejected", approvalConsumed: true, retryable: false}};
    };
    await sandbox.__flowApply();
    assert.equal(sandbox.__state.flow, partial, failure + ": consumed state must survive token expiry");
    assert.equal(partial.stage, "partial", failure);
    assert.equal(partial.approvalConsumed, true, failure);
    assert.equal(partial.handoffStatus, "partial-unknown", failure);
    assert.doesNotMatch(element("flow-apply-status").textContent, /Đã ghi sheet mới/);
    assert.match(element("flow-apply-status").textContent, /chưa biết.*không tự thử lại/);
    assert.equal(element("flow-apply-button").disabled, true);
    if (failure === "source-during-handoff" || failure === "network-lost" || failure === "collision") {
      assert.equal(host.writes.filter((item) => item.kind === "values").length, 0, failure);
    }
    assert.equal(sentVerified, failure === "receipt-expired");
    assert.equal(failedReceipt, failure !== "network-lost");
    const priorCalls = calls.length;
    await sandbox.__flowApply();
    assert.equal(calls.length, priorCalls, "consumed partial cannot automatically retry");
  }
  const unsupported = approvedE();
  supported = false;
  const beforeUnsupported = calls.length;
  await sandbox.__flowApply();
  assert.equal(calls.length, beforeUnsupported, "unsupported formula-check API must block before handoff");
  assert.equal(host.writes.length, 0);
  assert.equal(unsupported.approvalConsumed, false);
  supported = true;
  const preconsumeFailure = approvedE();
  responseHandler = async () => ({__httpStatus: 500, error: {code: "AF_WRITE_PARTIAL", detail: "Target exists", approvalConsumed: false, retryable: true}});
  await sandbox.__flowApply();
  assert.equal(preconsumeFailure.approvalConsumed, false);
  assert.equal(preconsumeFailure.stage, "approved");
  assert.equal(host.writes.length, 0);

  // A proven pre-consume stale rejection is distinct from a lost handoff response.
  const staleBeforeConsume = approvedE();
  responseHandler = async () => ({__httpStatus: 409, error: {code: "AF_SPEC_STALE", detail: "Source changed", approvalConsumed: false}});
  await sandbox.__flowApply();
  assert.equal(staleBeforeConsume.approvalConsumed, false);
  assert.equal(host.writes.length, 0);
  assert.doesNotMatch(element("flow-apply-status").textContent, /có thể.*một phần|partial\/unknown/);

  // The fingerprint-bound Spec exposes predicates before approval, not only operation names.
  const oldReviewSpec = sandbox.__state.flow.spec;
  for (const threshold of [0, 100]) {
    sandbox.__state.flow.spec = {...plain(frozenSpec), steps: [{stepId: "filter", inputs: ["source"],
      operation: {type: "table.filterRows", parameters: {predicate: {kind: "compare", operator: "gt",
        left: {kind: "columnRef", column: "Amount"}, right: {kind: "literal", valueType: "number", value: threshold}}}}}]};
    sandbox.__renderFlowFreeze();
    assert.match(renderedText(element("flow-spec-steps")), new RegExp('"value":\\s*' + threshold + '(?:[\\s,}])'));
    assert.match(renderedText(element("flow-spec-steps")), /"inputs"/);
  }
  sandbox.__state.flow.spec = oldReviewSpec;

  const restoredHandoff = readyFlow();
  element("prompt").value = "";
  responseHandler = async () => ({...plain(restoredState), stage: "handoff", spec: plain(frozenSpec), chosenBranch: "A",
    approval: {consumed: true}, approvalConsumed: true, handoffStatus: "partial-unknown"});
  await sandbox.__flowLoadState();
  assert.equal(restoredHandoff.chosenBranch, "A");
  assert.equal(restoredHandoff.approvalConsumed, true);
  assert.equal(element("flow-apply-button").disabled, true);
  assert.match(element("flow-apply-status").textContent, /partial\/unknown/);

  // F: full Record stays in the local session, fMetadata has its own hash/CAS.
  let xmlNode = null, xmlReads = 0;
  const expectedXmlHashes = [];
  sandbox.AssistantRecordXml = {
    async readAssistantRecord(expectedWorkbook) {
      assert.deepEqual(plain(expectedWorkbook), {name: sandbox.__state.workbook.name, url: sandbox.__state.workbook.url || ""});
      xmlReads++; return xmlNode ? plain(xmlNode) : null;
    },
    async verifyAssistantRecordHash(value) {
      return value.hash === await sandbox.__flowDigest(Object.fromEntries(Object.entries(value).filter(([key]) => key !== "hash")));
    },
    async writeAssistantRecord(value, expectedHash, expectedWorkbook) {
      assert.deepEqual(plain(expectedWorkbook), {name: "synthetic.xlsx", url: ""});
      expectedXmlHashes.push(expectedHash);
      if ((xmlNode?.hash ?? null) !== expectedHash) throw Object.assign(new Error("Synthetic CAS conflict"), {code: "PQPC_HISTORY_CONFLICT"});
      xmlNode = plain(value);
      return {written: true, hash: value.hash};
    },
  };
  const fullRecord = {schemaVersion: "2.0", id: "rec_" + "1".repeat(24), createdAt: "2026-10-31T03:00:00Z",
    snapshot: {snapshotHash: "sha256:" + "2".repeat(64)}, brief: {prompt: "Synthetic"}, decisions: [], assumptions: [],
    steps: [], reconciliations: [{engine: {executor: "typed_local", parityChecked: "none", knownDifferences: ["decimal-money"]}}],
    delta: {rowsIn: 3, rowsOut: 1, duplicatesBefore: 0, duplicatesAfter: 0, changedColumns: ["Amount→Total"]},
    labels: ["unverified"], stale: false, variantOf: null, variantReason: null};
  fullRecord.hashBasis = ["id", "createdAt", "snapshot", "brief", "decisions", "assumptions", "steps", "reconciliations", "delta", "labels", "stale", "variantOf", "variantReason"];
  fullRecord.hash = await sandbox.__flowDigest(Object.fromEntries(fullRecord.hashBasis.map((key) => [key, fullRecord[key]])));
  const fSpec = {...plain(frozenSpec), snapshotHash: fullRecord.snapshot.snapshotHash,
    workbookIdentity: {name: "synthetic.xlsx", documentHash: await sandbox.__flowDigest("")}};
  const fMetadata = {schemaVersion: "1.0", id: fullRecord.id, recordHash: fullRecord.hash,
    snapshot: fullRecord.snapshot.snapshotHash, spec: fSpec.fingerprint, branch: "A", createdAt: fullRecord.createdAt, labels: fullRecord.labels};
  fMetadata.hash = await sandbox.__flowDigest(fMetadata);
  const recordResponse = {stage: "recorded", recordId: fullRecord.id, recordHash: fullRecord.hash, node: fMetadata,
    record: fullRecord, staleCheck: {stale: null, freshness: "unknown", verifiedAtApply: true}, workbookSaved: false};
  const fFlow = readyFlow();
  host = writeHost();
  Object.assign(fFlow, {stage: "applied", approvalConsumed: true, handoffStatus: "readback-verified", spec: fSpec});
  sandbox.__state.workbookRecord = sandbox.__createWorkbookRecordState("\0synthetic.xlsx");
  await sandbox.__flowReadRecord();
  assert.equal(sandbox.__state.workbookRecord.loaded, true);
  assert.equal(sandbox.__state.workbookRecord.persistedNodeHash, null);
  responseHandler = async (request) => {
    assert.ok(request.url.endsWith("/record"));
    assert.deepEqual(request.payload, {});
    return plain(recordResponse);
  };
  await sandbox.__flowCreateRecord();
  assert.equal(fFlow.stage, "recorded");
  assert.equal(sandbox.__state.workbookRecord.record.hash, fullRecord.hash);
  assert.equal(element("flow-record-save").disabled, false);
  assert.match(element("flow-record-delta").textContent, /3 → 1/);
  assert.match(element("flow-record-stale").textContent, /unknown/);
  await sandbox.__flowPersistRecord();
  assert.deepEqual(expectedXmlHashes, [null]);
  assert.equal(xmlNode.recordHash, fullRecord.hash);
  assert.equal(sandbox.__state.workbookRecord.persistedNodeHash, fMetadata.hash);
  assert.match(element("flow-record-persist").textContent, /đọc lại.*chưa lưu/);
  assert.match(element("flow-workbook-saved").textContent, /Chưa/);
  assert.equal(host.writes.length, 0, "fMetadata persistence does not write source cells or Save");

  // A concurrent pane changes the part. Save must keep the original CAS pin.
  const oldHash = fMetadata.hash;
  xmlNode = {...plain(fMetadata), labels: ["assumed"]};
  delete xmlNode.hash;
  xmlNode.hash = await sandbox.__flowDigest(xmlNode);
  const beforeConflictReads = xmlReads;
  await sandbox.__flowPersistRecord();
  assert.equal(xmlReads, beforeConflictReads, "Save never reads/adopts latest fMetadata before CAS");
  assert.equal(expectedXmlHashes.at(-1), oldHash);
  assert.equal(sandbox.__state.workbookRecord.persistedNodeHash, oldHash);
  assert.equal(sandbox.__state.workbookRecord.reloadRequired, true);
  assert.equal(element("flow-record-save").disabled, true);
  await sandbox.__flowReadRecord();
  assert.equal(sandbox.__state.workbookRecord.persistedNodeHash, xmlNode.hash);
  assert.match(element("flow-record-persist").textContent, /Metadata hiện có khác.*Bấm Lưu sẽ thay/);
  assert.match(element("flow-record-persist").textContent, new RegExp(xmlNode.hash));

  // Reset/ingest do not discard the independent workbook fMetadata/CAS state.
  const preservedRecordState = sandbox.__state.workbookRecord;
  responseHandler = async () => ({stage: "new"});
  await sandbox.__flowReset();
  assert.equal(sandbox.__state.workbookRecord, preservedRecordState);
  assert.equal(sandbox.__state.workbookRecord.persistedNodeHash, xmlNode.hash);
  assert.equal(element("flow-record-save").disabled, true, "Reset discards write authority, not fMetadata");
  assert.equal(element("flow-record-download").disabled, false);

  // Reopen restores fMetadata only; a server-restored compute snapshot is old.
  sandbox.__state.workbookRecord = sandbox.__createWorkbookRecordState("\0synthetic.xlsx");
  sandbox.__state.flow.v2Capability = false;
  await sandbox.__flowReadRecord();
  assert.equal(sandbox.__state.workbookRecord.record, null);
  assert.equal(sandbox.__state.workbookRecord.persistedNodeHash, xmlNode.hash);
  assert.match(element("flow-record-delta").textContent, /Chỉ có metadata/);
  assert.match(element("flow-record-stale").textContent, /unknown/);
  sandbox.__state.flow.v2Capability = true;
  Object.assign(sandbox.__state.flow, {mode: "compute", snapshot: {snapshotHash: fMetadata.snapshot}, freshSnapshotHash: fMetadata.snapshot});
  responseHandler = async () => ({stage: "ingested", mode: "compute", snapshot: {snapshotHash: fMetadata.snapshot}});
  await sandbox.__flowLoadState();
  assert.equal(sandbox.__state.flow.freshSnapshotHash, null);
  assert.match(element("flow-record-stale").textContent, /unknown/, "state restore is not a fresh source read");
  sandbox.__state.flow.freshSnapshotHash = "sha256:" + "9".repeat(64);
  sandbox.__state.flow.snapshot = {snapshotHash: sandbox.__state.flow.freshSnapshotHash};
  sandbox.__renderFlowRecord();
  assert.match(element("flow-record-stale").textContent, /STALE.*Nguồn đã đổi/);
  assert.equal(xmlNode.hash, sandbox.__state.workbookRecord.persistedNodeHash, "stale display never rewrites historical fMetadata");

  // Switching workbook disables all pending fMetadata writes until its own read.
  sandbox.__state.workbook = {name: "other.xlsx", url: "", activeSheet: "Other", tables: [], sheets: []};
  sandbox.__renderWorkbook();
  assert.equal(sandbox.__state.workbookRecord.loaded, false);
  assert.equal(sandbox.__state.workbookRecord.node, null);
  assert.equal(element("flow-record-save").disabled, true);
  // F-JS-11: re-read only the bound workbook selection before understand.
  const freshFlow = readyFlow();
  host = writeHost();
  const sourceBasis = {header: ["ID", "Amount"], rows: [["a", "12"]], mode: "compute", totalRows: 1, sampleOrdinals: [0]};
  Object.assign(freshFlow, {stage: "ingested", mode: "compute", workbookSourceSelections: [{sheet: "Source", name: "Transactions", origin: "Workbook!Source!Transactions", table: true}],
    snapshot: {tables: [{name: "Transactions", contentHash: await sandbox.__flowDigest(sourceBasis)}]}});
  responseHandler = async (request) => {
    assert.ok(host.writes.length === 0);
    assert.ok(host.workbook.worksheets.items[0].tables.items[0]);
    assert.ok(request.url.endsWith("/understand"));
    return {stage: "understood", understand: {roles: [], relationships: []}, questions: []};
  };
  const freshBefore = calls.length;
  await sandbox.__flowUnderstand();
  assert.equal(calls.length, freshBefore + 1);
  assert.match(element("flow-understand-summary").textContent, /1 bảng/);
  freshFlow.branches = [{id: "A"}]; freshFlow.planningHash = "old";
  host.sourceValues[0][1] = "999";
  await sandbox.__flowUnderstand();
  assert.equal(calls.length, freshBefore + 1, "changed bound content must never reach understand");
  assert.equal(freshFlow.snapshot, null); assert.equal(freshFlow.planningHash, null);
  assert.deepEqual(plain(freshFlow.branches), []);
  assert.equal(element("error-code").textContent, "AF_SPEC_STALE");

  const readFailure = readyFlow();
  Object.assign(readFailure, {stage: "partial", mode: "compute", approvalConsumed: true, handoffStatus: "partial-unknown", applyMessage: "Quyền ghi đã dùng; không tự thử lại.",
    spec: plain(frozenSpec), approval: {consumed: true}, branches: [{id: "A"}], planningHash: "old", snapshot: {tables: []},
    workbookSourceSelections: [{sheet: "Source", name: "Transactions", origin: "Workbook!Source!Transactions", table: true}]});
  host = {workbook: {worksheets: {load() { throw new Error("Synthetic Office read failed"); }}}};
  const failureBefore = calls.length;
  await sandbox.__flowUnderstand();
  assert.equal(calls.length, failureBefore);
  assert.equal(readFailure.snapshot, null); assert.equal(readFailure.understand, null);
  assert.deepEqual(plain(readFailure.branches), []); assert.equal(readFailure.approvalConsumed, true);
  assert.equal(readFailure.stage, "partial"); assert.match(element("flow-apply-status").textContent, /không tự thử lại/);
  assert.equal(element("error-code").textContent, "OFFICE_READ_FAILED");
  const fileOnly = readyFlow(); Object.assign(fileOnly, {stage: "ingested", snapshot: {tables: []}});
  await sandbox.__flowUnderstand();
  assert.equal(calls.length, failureBefore + 1, "file-only understand must not read Office");

  // Discover verifies exactly its bound sample plus dimensions, not unsampled cells.
  const discoverFresh = readyFlow(); host = writeHost();
  const discoverBasis = {...sourceBasis, mode: "discover"};
  Object.assign(discoverFresh, {stage: "ingested", mode: "discover", workbookSourceSelections: [{sheet: "Source", name: "Transactions", origin: "Workbook!Source!Transactions", table: true}],
    snapshot: {tables: [{name: "Transactions", sampleOrdinals: [0], contentHash: await sandbox.__flowDigest(discoverBasis)}]}});
  await sandbox.__flowUnderstand();
  assert.equal(discoverFresh.stage, "understood");

  // Automatic refresh retains the consumed-write warning, with no retry authority.
  const refreshConsumed = readyFlow();
  Object.assign(refreshConsumed, {stage: "partial", spec: plain(frozenSpec), approvalConsumed: true, handoffStatus: "partial-unknown", applyMessage: "Consumed; do not retry"});
  sandbox.__setReadWorkbook(async () => ({name: "synthetic.xlsx", url: "", activeSheet: "Source", tables: [], sheets: []}));
  Object.assign(sandbox.__state.workbook, {activeSheet: "Source", tables: [], sheets: []});
  await sandbox.__refreshWorkbook();
  assert.equal(sandbox.__state.flow.approvalConsumed, true);
  assert.equal(sandbox.__state.flow.applyMessage, "Consumed; do not retry");
  assert.match(element("flow-apply-status").textContent, /Consumed; do not retry/);
  assert.equal(sandbox.__state.flow.snapshot, null);
  assert.equal(element("flow-apply-button").disabled, true);

  // Retained write outcomes always identify their bound workbook after a switch.
  for (const outcome of ["partial", "applied"]) {
    Object.assign(sandbox.__state.flow, {stage: outcome, approvalConsumed: true,
      handoffStatus: outcome === "applied" ? "readback-verified" : "partial-unknown",
      applyMessage: outcome === "applied" ? "Đã ghi và đọc lại." : "Consumed; do not retry",
      spec: {...plain(frozenSpec), workbookIdentity: {name: "synthetic.xlsx"}}});
    sandbox.__setReadWorkbook(async () => ({name: "other.xlsx", url: "", activeSheet: "Source", tables: [], sheets: []}));
    await sandbox.__refreshWorkbook();
    assert.equal(sandbox.__state.workbook.name, "other.xlsx");
    assert.match(element("flow-apply-status").textContent, /Lần ghi vào workbook «synthetic.xlsx»/);
    assert.doesNotMatch(element("flow-apply-status").textContent, /«other.xlsx»/);
    assert.equal(sandbox.__state.flow.stage, outcome);
    assert.equal(sandbox.__state.flow.approvalConsumed, true);
    assert.equal(element("flow-apply-button").disabled, true);
  }

  // F-JS-12: shortcut invokes only the enabled flow action, never composition/repeats.
  sandbox.__bindFlowPromptShortcut();
  let shortcutClicks = 0, prevented = 0;
  const shortcutButton = element("flow-analyze-button"), oldClick = shortcutButton.click;
  shortcutButton.click = async () => { shortcutClicks++; };
  const keyEvent = {key: "Enter", ctrlKey: true, preventDefault() { prevented++; }};
  shortcutButton.disabled = true; await element("prompt").emit("keydown", keyEvent);
  shortcutButton.disabled = false;
  for (const extra of [{isComposing: true}, {repeat: true}, {altKey: true}, {metaKey: true}, {shiftKey: true}]) await element("prompt").emit("keydown", {...keyEvent, ...extra});
  assert.equal(shortcutClicks, 0);
  await element("prompt").emit("keydown", keyEvent);
  assert.equal(shortcutClicks, 1); assert.equal(prevented, 1); shortcutButton.click = oldClick;

  // F-JS-13: the replaced advice surface cannot return, and navigation stays two tabs.
  const html = fs.readFileSync(path.join(__dirname, "../../pbip_assistant/excel_addin/taskpane.html"), "utf8");
  for (const id of ["plan-section", "plan-title", "plan-status", "plan-summary", "analysis-notes", "warning-list", "code-section", "code-list", "operation-list", "preview-section", "preview-title", "preview-label", "before-table", "approval-section", "approval-title", "approval-check", "result-section", "result-title", "runtime-badge", "copy-path", "excel-version", "reconcile-status", "runtime-table", "apply-button", "apply-progress", "analyze-button", "codex-status", "formula-list-separator"]) {
    assert.ok(!html.includes(`id="${id}"`), `${id} must not exist`);
    assert.ok(!source.includes(`byId("${id}")`), `${id} must not have stale handlers`);
  }
  for (const name of ["analyze", "applyPlan", "renderPlan", "renderCodeBlocks", "renderCodeCard", "renderOperations", "renderRuntime", "updateApplyState", "invalidatePlan"]) assert.ok(!new RegExp(`function ${name}\\(`).test(source));
  assert.equal((html.match(/id="tab-(?:assistant|pq)-button"/g) || []).length, 2);
  assert.equal((html.match(/<nav class="tab-bar"[\s\S]*?<\/nav>/)[0].match(/<button /g) || []).length, 2);
  const cardIds = ["flow-workbook-section", "flow-source-section", "flow-prompt-section", "flow-understand-section", "flow-branches-section", "flow-spec-section", "flow-apply-section", "flow-result-section"];
  for (const id of cardIds) {
    assert.match(html, new RegExp(`<section id="${id}"[^>]*data-state=`));
    assert.equal(element(id).dataset.state, sandbox.__state.flow.stage);
    const chip = element(id + "-status");
    assert.ok(chip.children.length >= 2, "status has an icon and text");
    assert.match(chip.className,
      ["flow-workbook-section", "flow-source-section"].includes(id) ? /sr-only/ : /badge-/);
  }

  // F-JS-14: restored approval remains unusable until explicit checkbox retick.
  const unchecked = approvedE(); element("flow-approve-check").checked = false;
  sandbox.__updateFlowButtons();
  const uncheckedBefore = calls.length;
  await sandbox.__flowApply();
  assert.equal(calls.length, uncheckedBefore); assert.equal(host.writes.length, 0);
  assert.equal(element("flow-apply-button").disabled, true);
  assert.equal(element("flow-approve-check").disabled, false, "restored approved state allows explicit retick");
  element("flow-approve-check").checked = true; await element("flow-approve-check").emit("change");
  assert.equal(element("flow-apply-button").disabled, false);
  assert.equal(unchecked.approvalConsumed, false);
  // Prepared usedRange includes outside-Table rows and retains exact scope on compute.
  const reviewed={sources:[{sourceId:'s',sheetId:'native-clean',headers:['ID','Date'],rows:[['table',1],['outside',2]],
    formulaCells:[],numberFormats:[['General','yyyy-mm-dd'],['General','yyyy-mm-dd']],dateSystem:'1904',rowOffset:4,columnOffset:2}],sourceLabels:{s:'Clean'},observedHash:'reviewed'};
  let live=plain(reviewed), handoffCalls=[];
  const handoff=()=>({...plain(reviewed),validate:async()=>{
    if(JSON.stringify(live)!==JSON.stringify(reviewed))throw Object.assign(new Error('review changed'),{code:'DP_SOURCE_STALE'});
    return {...plain(live),validate:handoff().validate};
  }});
  function handoffReady(){const flow=readyFlow();flow.busy=false;flow.snapshot={old:true};flow.spec={old:true};flow.approval={old:true};return flow;}
  responseHandler=async request=>{
    handoffCalls.push(request);
    if(request.url.endsWith('/session'))return {rootLabel:'Workbook',stage:'new'};
    if(request.url.endsWith('/ingest'))return {rootLabel:'Workbook',stage:'ingested',snapshot:{tables:[]}};
    return {};
  };
  const preparedFlow=handoffReady();
  await sandbox.__preparationBusinessHandoff(handoff());
  const ingested=handoffCalls.find(request=>request.url.endsWith('/ingest'));
  assert.deepEqual(plain(ingested.payload.requests[0].payload.rows),[['table','1904-01-02'],['outside','1904-01-03']]);
  assert.equal(ingested.payload.requests[0].payload.table,false);
  assert.equal(ingested.payload.requests[0].payload.range,'C4:D6');
  const freshPrepared=await sandbox.__flowFreshWorkbookSources(preparedFlow);
  assert.deepEqual(plain(freshPrepared[0].payload.rows),[['table','1904-01-02'],['outside','1904-01-03']]);
  await sandbox.__flowIngest('compute');
  assert.deepEqual(plain(handoffCalls.at(-1).payload.requests[0].payload.rows),[['table','1904-01-02'],['outside','1904-01-03']]);
  // Edits or same-name native sheet replacement during either HTTP await invalidate all old authority.
  for(const boundary of ['session','ingest'])for(const change of ['rows','sheetId']){
    live=plain(reviewed);handoffCalls=[];const failed=handoffReady();
    responseHandler=async request=>{
      handoffCalls.push(request);
      if(request.url.endsWith('/'+boundary)){
        if(change==='rows')live.sources[0].rows[1][0]='unreviewed';else live.sources[0].sheetId='replacement';
      }
      return request.url.endsWith('/session')?{rootLabel:'Workbook'}:{stage:'ingested',snapshot:{bad:true}};
    };
    await assert.rejects(()=>sandbox.__preparationBusinessHandoff(handoff()),error=>error.code==='DP_SOURCE_STALE');
    assert.equal(failed.snapshot,null);assert.equal(failed.spec,null);assert.equal(failed.approval,null);
    if(boundary==='session')assert(!handoffCalls.some(request=>request.url.endsWith('/ingest')),'changed source never reaches ingest');
  }
  live=plain(reviewed);const stalePrepared=handoffReady();
  responseHandler=async()=>({stage:'ingested',snapshot:{tables:[]}});
  await sandbox.__preparationBusinessHandoff(handoff());live.sources[0].rows.push(['later',3]);
  await assert.rejects(()=>sandbox.__flowFreshWorkbookSources(stalePrepared),error=>error.code==='DP_SOURCE_STALE');
  // A change while compute ingest awaits cannot publish the returned snapshot.
  live=plain(reviewed);const computeRace=handoffReady();
  responseHandler=async()=>({rootLabel:'Workbook',stage:'ingested',snapshot:{tables:[]}});
  await sandbox.__preparationBusinessHandoff(handoff());
  responseHandler=async()=>{live.sources[0].rows[0][0]='during-compute';return {stage:'ingested',snapshot:{stale:true}};};
  await sandbox.__flowIngest('compute');
  assert.equal(computeRace.snapshot,null,'compute response rejected when exact review changed during await');
  let detached=0;
  sandbox.__state.preparationDetach=()=>{detached++;return Promise.resolve();};
  const beforeDetach=calls.length;
  sandbox.__closeCoordinatorSession();
  assert.equal(detached,1,'preparation pane close retains logical recovery through detach');
  assert.equal(calls.length,beforeDetach,'pane detach cannot also destroy the session journal');
  sandbox.__state.preparationDetach=()=>null;
  sandbox.__closeCoordinatorSession();
  assert.equal(calls.at(-1).url,'/api/session/close','pane without preparation still retires legacy authority');
  console.log("taskpane assistant flow tests passed");
})().catch((error) => { console.error(error); process.exitCode = 1; });
