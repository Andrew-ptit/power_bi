"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const {performance} = require("node:perf_hooks");
const codec = require("./problem_chain_codec.js");

(async () => {
  const original = await codec.buildXml(await codec.makeRepresentativeDocument());
  const elements = new Map();
  const element = (id) => {
    if (!elements.has(id)) elements.set(id, {
      id, textContent: "", dataset: {}, disabled: false, listeners: {}, scrollTop: 0, scrollHeight: 0,
      addEventListener(name, callback) { this.listeners[name] = callback; },
    });
    return elements.get(id);
  };
  ["log", "status", "part-count", "history-hash", "payload-size", "capability", "refresh",
    "add-small", "read-one", "set-unicode", "set-large", "add-duplicate", "delete-one", "delete-all"].forEach(element);

  const parts = [{
    id: "pre-existing-part",
    xml: original.xml,
    getXml() { return {value: this.xml}; },
    setXml(value) { this.xml = value; },
    delete() { throw new Error("autorun attempted to delete pre-existing history"); },
  }];
  const sentinel = {address: "Fake!A1", values: [["SOURCE_SENTINEL"]], formulas: [["=1+1"]], numberFormat: [["General"]], load() {}};
  const context = {
    workbook: {
      worksheets: {getActiveWorksheet() { return {name: "Fake", load() {}, getRange() { return sentinel; }}; }},
      customXmlParts: {
        getByNamespace(namespace) { return {items: parts.filter((part) => part.xml.includes(namespace)), load() {}}; },
        add() { throw new Error("autorun must stop before creating parts"); },
      },
    },
    async sync() {},
  };
  let readyCallback;
  let posted;
  const sandbox = {
    window: {ProblemChainCodec: codec, location: {search: "?autorun=1"}, crypto: {randomUUID() { return "33333333-3333-4333-8333-333333333333"; }}},
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
    fetch: async (_url, options) => { posted = JSON.parse(options.body); return {ok: true, status: 204}; },
    URLSearchParams, performance, console, setTimeout, clearTimeout,
  };
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync("taskpane.js", "utf8"), sandbox, {filename: "taskpane.js"});
  await readyCallback({host: "Excel", platform: "PC"});

  assert.equal(parts.length, 1);
  assert.equal(parts[0].id, "pre-existing-part");
  assert.equal(parts[0].xml, original.xml);
  assert.equal(posted.status, "Fail");
  assert.deepEqual(posted.steps.map((step) => step.label), ["inspect-zero", "cleanup"]);
  assert.equal(posted.steps[0].code, "AUTORUN_INITIAL_STATE_NOT_EMPTY");
  assert.equal(posted.steps[1].status, "Pass");
  assert.equal(posted.steps[1].deleted, 0);
  assert.equal(posted.finalPartCount, 1);
  console.log("Office.js autorun preserves pre-existing Problem Chain history");
})().catch((error) => { console.error(error); process.exitCode = 1; });
