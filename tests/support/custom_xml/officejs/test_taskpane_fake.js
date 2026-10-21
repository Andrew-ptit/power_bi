"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const {performance} = require("node:perf_hooks");
const codec = require("./problem_chain_codec.js");

const elements = new Map();
function element(id) {
  if (!elements.has(id)) elements.set(id, {
    id, textContent: "", dataset: {}, disabled: false, listeners: {}, scrollTop: 0, scrollHeight: 0,
    addEventListener(name, callback) { this.listeners[name] = callback; },
  });
  return elements.get(id);
}
[
  "log", "status", "part-count", "history-hash", "payload-size", "capability", "refresh",
  "add-small", "read-one", "set-unicode", "set-large", "add-duplicate", "delete-one", "delete-all",
].forEach(element);

const parts = [];
let nextId = 1;
function makePart(xml) {
  const part = {
    id: `part-${nextId++}`,
    xml,
    getXml() { return {value: this.xml}; },
    setXml(value) { this.xml = value; },
    delete() { const index = parts.indexOf(this); if (index >= 0) parts.splice(index, 1); },
  };
  parts.push(part);
  return part;
}

const sentinel = {address: "Fake!A1", values: [["SOURCE_SENTINEL"]], formulas: [["SOURCE_SENTINEL"]], numberFormat: [["General"]], load() {}};
const context = {
  workbook: {
    worksheets: {getActiveWorksheet() { return {name: "Fake", load() {}, getRange() { return sentinel; }}; }},
    customXmlParts: {
      getByNamespace(namespace) {
        return {items: parts.filter((part) => part.xml.includes(namespace)), load() {}};
      },
      add(xml) { return makePart(xml); },
    },
  },
  async sync() {},
};

let readyCallback;
const sandbox = {
  window: {ProblemChainCodec: codec, location: {search: ""}, crypto: {randomUUID() { return "00000000-0000-4000-8000-000000000000"; }}},
  document: {
    getElementById: element,
    querySelectorAll() { return ["add-small", "read-one", "set-unicode", "set-large", "add-duplicate", "delete-one", "delete-all"].map(element); },
  },
  Office: {
    HostType: {Excel: "Excel"},
    context: {requirements: {isSetSupported(name, version) { return name === "ExcelApi" && version === "1.5"; }}},
    onReady(callback) { readyCallback = callback; },
  },
  Excel: {async run(callback) { return callback(context); }},
  performance,
  URLSearchParams,
  fetch: async () => ({ok: true, status: 204}),
  console,
  setTimeout,
  clearTimeout,
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync("taskpane.js", "utf8"), sandbox, {filename: "taskpane.js"});

(async () => {
  await readyCallback({host: "Excel"});
  assert.equal(element("capability").textContent, "ExcelApi 1.5: supported");
  assert.equal(element("part-count").textContent, "0");

  await vm.runInContext("runMeasured('fake-add', addSmall)", sandbox);
  assert.equal(parts.length, 1);
  assert.equal(element("part-count").textContent, "1");
  assert.equal(sentinel.values[0][0], "SOURCE_SENTINEL");

  await vm.runInContext("runMeasured('fake-get', readOne)", sandbox);
  await vm.runInContext("runMeasured('fake-set', setUnicode)", sandbox);
  const parsed = await codec.parseXml(parts[0].xml);
  assert.equal(parsed.document.revisions[0].name, "Đơn hàng Hà Nội – 測試 ✓");

  await vm.runInContext("runMeasured('fake-duplicate', addDuplicate)", sandbox);
  assert.equal(parts.length, 2);
  assert.match(element("status").textContent, /PQPC_DUPLICATE_XML_PART/);

  await vm.runInContext("runMeasured('fake-cleanup', deleteAll)", sandbox);
  assert.equal(parts.length, 0);
  assert.equal(sentinel.formulas[0][0], "SOURCE_SENTINEL");
  assert.match(element("log").textContent, /"elapsedMs"/);
  assert.match(element("log").textContent, /"syncs"/);
  console.log("Office.js taskpane fake-host operations passed");
})().catch((error) => { console.error(error); process.exitCode = 1; });
