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
    load() {},
    getXml() { return {value: this.xml}; },
    setXml(value) { this.xml = value; },
    delete() { const index = parts.indexOf(this); if (index >= 0) parts.splice(index, 1); },
  };
  parts.push(part);
  return part;
}

const sentinel = {address: "Fake!A1", values: [["SOURCE_SENTINEL"]], formulas: [["=1+1"]], numberFormat: [["General"]], load() {}};
let syncCount = 0;
const context = {
  workbook: {
    worksheets: {getActiveWorksheet() { return {name: "Fake", load() {}, getRange() { return sentinel; }}; }},
    customXmlParts: {
      getByNamespace(namespace) { return {items: parts.filter((part) => part.xml.includes(namespace)), load() {}}; },
      add(xml) { return makePart(xml); },
    },
  },
  async sync() { syncCount += 1; },
};

let readyCallback;
let posted;
const sandbox = {
  window: {
    ProblemChainCodec: codec,
    location: {search: "?autorun=1"},
    crypto: {randomUUID() { return "11111111-1111-4111-8111-111111111111"; }},
  },
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
  fetch: async (url, options) => {
    posted = {url, options, evidence: JSON.parse(options.body)};
    return {ok: true, status: 204};
  },
  URLSearchParams,
  performance,
  console,
  setTimeout,
  clearTimeout,
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync("taskpane.js", "utf8"), sandbox, {filename: "taskpane.js"});

(async () => {
  await readyCallback({host: "Excel", platform: "PC"});
  assert.equal(parts.length, 0, "autorun must clean both deliberate duplicate parts");
  assert.equal(element("part-count").textContent, "0");
  assert.ok(posted, "autorun must POST evidence");
  assert.equal(posted.url, "/evidence");
  assert.equal(posted.options.method, "POST");
  assert.equal(posted.options.credentials, "same-origin");

  const evidence = posted.evidence;
  assert.equal(evidence.status, "Pass");
  assert.equal(evidence.sentinelUnchanged, true);
  assert.equal(evidence.finalPartCount, 0);
  assert.equal(evidence.noSaveCalled, true);
  assert.deepEqual(evidence.steps.map((step) => step.label), [
    "inspect-zero", "add-small", "get-parse", "set-unicode", "set-near-2mib",
    "add-duplicate", "detect-duplicate", "cleanup",
  ]);
  assert.ok(evidence.steps.every((step) => step.status === "Pass" && step.sentinelUnchanged));
  assert.ok(evidence.steps.every((step) => step.syncs.length >= 2));
  assert.ok(evidence.steps.flatMap((step) => step.syncs).every((sync) => Number.isFinite(sync.elapsedMs)));
  assert.ok(evidence.steps.find((step) => step.label === "set-near-2mib").canonicalBytes >= codec.MAX_BYTES - 4098);
  assert.equal(evidence.steps.find((step) => step.label === "detect-duplicate").expectedBlockCode, "PQPC_DUPLICATE_XML_PART");

  const body = posted.options.body;
  assert.doesNotMatch(body, /historyHash|<ldc:|payload|SOURCE_SENTINEL|values|formulas|numberFormat/i);
  assert.equal(sentinel.values[0][0], "SOURCE_SENTINEL");
  assert.equal(sentinel.formulas[0][0], "=1+1");
  assert.ok(syncCount > 20, "autorun must exercise actual sync boundaries in the fake host");
  console.log(JSON.stringify({status: "passed", steps: evidence.steps.length, contextSyncs: syncCount, evidenceBytes: Buffer.byteLength(body)}));
})().catch((error) => { console.error(error); process.exitCode = 1; });
