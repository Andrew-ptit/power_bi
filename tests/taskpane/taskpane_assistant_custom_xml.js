"use strict";
const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "../../pbip_assistant/excel_addin/assistant_custom_xml.js"), "utf8");
const NS = "urn:local-data-copilot:assistant-record:v1";
const OTHER = "urn:local-data-copilot:pq-problem-chain:v1";
const GOLDEN = "sha256:f813cd07ff6e1ff65a8f4e4ac051fc525ce5a092b9c32edfd806068e34684cd3";
const json = (value) => JSON.parse(JSON.stringify(value));
const canonical = (value) => JSON.stringify(Object.fromEntries(Object.keys(value).sort().map((key) => [key, value[key]])));
function node(overrides = {}) {
  const result = {schemaVersion: "1.0", id: "rec_" + "a".repeat(24), hash: "", recordHash: "sha256:" + "1".repeat(64),
    snapshot: "sha256:" + "2".repeat(64), spec: "sha256:" + "3".repeat(64), branch: "A",
    createdAt: "2026-10-31T03:00:00Z", labels: ["assumed", "unverified"], ...overrides};
  const basis = {...result};
  delete basis.hash;
  result.hash = "sha256:" + crypto.createHash("sha256").update(canonical(basis), "utf8").digest("hex");
  return result;
}
function harness() {
  const state = {parts: [], next: 1, writes: 0, saves: 0, runs: 0, syncs: 0, api: true, hook: null, xmlDeclaration: "", workbookName: "Synthetic.xlsx", documentUrl: ""};
  function part(xml) {
    const item = {id: "p" + state.next++, xml,
      getXml() { return {value: state.xmlDeclaration + this.xml}; },
      setXml(value) { state.writes++; this.xml = value; },
      delete() { state.writes++; state.parts = state.parts.filter((entry) => entry !== this); }};
    state.parts.push(item);
    return item;
  }
  const context = {workbook: {get name() { return state.workbookName; }, load() {}, customXmlParts: {
    getByNamespace(namespace) { return {items: state.parts.filter((item) => item.xml.includes(namespace)), load() {}}; },
    add(xml) { state.writes++; return part(xml); },
  }, save() { state.saves++; throw new Error("Save is forbidden"); }},
  async sync() { state.syncs++; if (state.hook) await state.hook(state.syncs); }};
  const sandbox = {crypto: crypto.webcrypto, TextEncoder, TextDecoder, Uint8Array,
    btoa: (value) => Buffer.from(value, "binary").toString("base64"), atob: (value) => Buffer.from(value, "base64").toString("binary"),
    Office: {context: {document: {get url() { return state.documentUrl; }}, requirements: {isSetSupported: (name, version) => state.api && name === "ExcelApi" && version === "1.5"}}},
    Excel: {async run(callback) { state.runs++; return callback(context); }}};
  vm.createContext(sandbox);
  vm.runInContext(source, sandbox);
  return {api: sandbox.AssistantRecordXml, state, sandbox, part};
}
const rejects = (operation, code) => assert.rejects(operation, (error) => error.code === code);
async function main() {
  let checks = 0;
  const h = harness();
  assert.equal(node().hash, GOLDEN);
  assert.equal(h.api.ASSISTANT_RECORD_NAMESPACE, NS);
  assert.notEqual(NS, OTHER);
  assert.equal(await h.api.readAssistantRecord(), null);
  assert.equal(await h.api.verifyAssistantRecordHash(node()), true);
  assert.equal(await h.api.verifyAssistantRecordHash({...node(), branch: "B"}), false);
  checks++;

  // Handwritten independent SHA oracle, full metadata roundtrip and opaque
  // full-Record reference: the helper verifies metadata, not a missing Record.
  const other = h.part(`<other xmlns="${OTHER}" />`);
  assert.deepEqual(json(await h.api.writeAssistantRecord(node(), null)), {written: true, hash: GOLDEN});
  assert.deepEqual(json(await h.api.readAssistantRecord()), node());
  const written = h.state.parts.find((item) => item !== other);
  assert(!written.xml.includes("C:\\"));
  const payload = written.xml.match(/<ldc:payload encoding="base64">([^<]+)</)[1];
  const decoded = JSON.parse(Buffer.from(payload, "base64").toString("utf8"));
  assert.deepEqual(Object.keys(decoded).sort(), ["schemaVersion", "id", "hash", "recordHash", "snapshot", "spec", "branch", "createdAt", "labels"].sort());
  assert.equal(decoded.recordHash, "sha256:" + "1".repeat(64));
  assert.equal(h.state.saves, 0);
  checks++;

  // Native Office XML declarations describe the originating package bytes;
  // getXml has already decoded them into JS strings. Namespace stays exact.
  for (const declaration of ['<?xml version="1.0" encoding="utf-8"?>',
    '<?xml version="1.0" encoding="UTF-16" standalone="yes"?>\r\n',
    '<?xml version="1.0" encoding="uTf-16" standalone="no"?>']) {
    h.state.xmlDeclaration = declaration;
    await h.api.writeAssistantRecord(node(), GOLDEN);
    assert.deepEqual(json(await h.api.readAssistantRecord()), node());
  }
  for (const declaration of ['<?xml version="1.0" encoding="UTF-7"?>',
    '<?xml version="1.0" private="C:\\secret"?>', '<?xml version="1.1"?>']) {
    h.state.xmlDeclaration = declaration;
    await rejects(() => h.api.readAssistantRecord(), "AF_RECORD_INVALID");
  }
  h.state.xmlDeclaration = "";
  checks++;

  const second = node({branch: "B"});
  await rejects(() => h.api.writeAssistantRecord(second, null), "PQPC_HISTORY_CONFLICT");
  await h.api.writeAssistantRecord(second, GOLDEN);
  await rejects(() => h.api.writeAssistantRecord(node(), GOLDEN), "PQPC_HISTORY_CONFLICT");
  await rejects(() => h.api.writeAssistantRecord(node()), "AF_RECORD_INVALID");
  assert.deepEqual(json(await h.api.readAssistantRecord()), second);
  checks++;

  // Caller data, hidden fields, raw matrices and every path style fail closed
  // before touching Custom XML. The size limit rejects rather than truncates.
  const runsBefore = h.state.runs;
  for (const bad of [node({source: "C:\\private\\book.xlsx"}), node({labels: [["cell"]]}),
    node({labels: ["/private/book.xlsx"]}), node({labels: ["\\\\server\\share"]}),
    node({createdAt: "2026-02-30T00:00:00Z"}), node({labels: ["assumed", "assumed"]}),
    node({raw: "x".repeat(40000)}), {...node(), hash: "sha256:" + "0".repeat(64)}]) {
    await rejects(() => h.api.writeAssistantRecord(bad, second.hash), "AF_RECORD_INVALID");
  }
  const hidden = node();
  Object.defineProperty(hidden, "privatePath", {value: "C:\\secret"});
  await rejects(() => h.api.writeAssistantRecord(hidden, second.hash), "AF_RECORD_INVALID");
  assert.equal(h.state.runs, runsBefore);
  assert.deepEqual(json(await h.api.readAssistantRecord()), second);
  checks++;

  // Hash tampering, noncanonical JSON, malformed wrappers, oversized XML and
  // namespace duplicates are detected without deleting or repairing the part.
  const originalXml = written.xml;
  const replacePayload = (text) => originalXml.replace(/(<ldc:payload encoding="base64">)[^<]+/, "$1" + Buffer.from(text, "utf8").toString("base64"));
  for (const badXml of [replacePayload(canonical({...second, branch: "A"})), replacePayload(JSON.stringify(second)),
    originalXml.replace("<ldc:payload", '<extra/><ldc:payload'), '<!DOCTYPE x [<!ENTITY e SYSTEM "file:///private">]>' + originalXml,
    originalXml + " ".repeat(32768), originalXml.replace("assistant-record:v1", "assistant-record:V1")]) {
    written.xml = badXml;
    // A differently cased namespace does not belong to this namespace at all.
    if (badXml.includes("assistant-record:V1")) assert.equal(await h.api.readAssistantRecord(), null);
    else await rejects(() => h.api.readAssistantRecord(), "AF_RECORD_INVALID");
  }
  written.xml = originalXml;
  const duplicate = h.part(originalXml);
  const beforeDuplicate = h.state.writes;
  await rejects(() => h.api.readAssistantRecord(), "PQPC_DUPLICATE_XML_PART");
  await rejects(() => h.api.writeAssistantRecord(node(), second.hash), "PQPC_DUPLICATE_XML_PART");
  await rejects(() => h.api.clearAssistantRecord(), "PQPC_DUPLICATE_XML_PART");
  assert.equal(h.state.writes, beforeDuplicate);
  h.state.parts = h.state.parts.filter((item) => item !== duplicate);
  checks++;

  // A race after initial verification is observed by the final recheck.
  h.state.syncs = 0;
  h.state.hook = async (count) => { if (count === 3) written.xml = replacePayload(canonical(node())); };
  const beforeRace = h.state.writes;
  await rejects(() => h.api.writeAssistantRecord(node(), second.hash), "PQPC_HISTORY_CONFLICT");
  assert.equal(h.state.writes, beforeRace);
  h.state.hook = null;
  written.xml = originalXml;
  checks++;

  // Mutation/sync or read-back failures may already have written. They must
  // carry a partial/unknown result and may never invite an automatic retry.
  h.state.syncs = 0;
  h.state.hook = async (count) => { if (count === 5) written.xml = "corrupt"; };
  await assert.rejects(() => h.api.writeAssistantRecord(node(), second.hash), (error) =>
    error.code === "AF_WRITE_PARTIAL" && error.written === true && error.retryable === false);
  h.state.hook = null;
  written.xml = originalXml;
  checks++;

  assert.deepEqual(json(await h.api.clearAssistantRecord()), {cleared: true});
  assert.equal(await h.api.readAssistantRecord(), null);
  assert.deepEqual(h.state.parts, [other]);
  assert.deepEqual(json(await h.api.clearAssistantRecord()), {cleared: true});
  assert.equal(h.state.saves, 0);
  checks++;

  // Same-pane concurrent writers cannot both consume an empty-base CAS.
  const concurrent = harness();
  const outcomes = await Promise.allSettled([concurrent.api.writeAssistantRecord(node(), null), concurrent.api.writeAssistantRecord(second, null)]);
  assert.equal(outcomes.filter((outcome) => outcome.status === "fulfilled").length, 1);
  assert.equal(outcomes.find((outcome) => outcome.status === "rejected").reason.code, "PQPC_HISTORY_CONFLICT");
  assert.equal(concurrent.state.parts.length, 1);
  checks++;

  // The caller's precheck cannot bind a future Excel.run. Guard identity inside
  // that context, including switches while XML hashing/read requests yield.
  const expectedWorkbook = {name: "Synthetic.xlsx", url: ""};
  const beforeContext = harness();
  beforeContext.state.workbookName = "Other.xlsx";
  await rejects(() => beforeContext.api.writeAssistantRecord(node(), null, expectedWorkbook), "AF_SPEC_STALE");
  assert.equal(beforeContext.state.writes, 0);
  await rejects(() => beforeContext.api.readAssistantRecord(expectedWorkbook), "AF_SPEC_STALE");
  assert.equal(beforeContext.state.writes, 0);
  checks++;

  for (const point of [3, 5]) {
    const switching = harness();
    await switching.api.writeAssistantRecord(node(), null);
    switching.state.syncs = 0;
    switching.state.hook = async (count) => { if (count === point) switching.state.workbookName = "Other.xlsx"; };
    const writes = switching.state.writes;
    await rejects(() => switching.api.writeAssistantRecord(second, GOLDEN, expectedWorkbook), "AF_SPEC_STALE");
    assert.equal(switching.state.writes, writes, "switch during async read/hash cannot mutate either workbook");
    switching.state.hook = null;
    switching.state.workbookName = "Synthetic.xlsx";
    assert.equal((await switching.api.readAssistantRecord(expectedWorkbook)).hash, GOLDEN);
  }
  checks++;

  const urlSwitch = harness();
  await urlSwitch.api.writeAssistantRecord(node(), null, expectedWorkbook);
  urlSwitch.state.syncs = 0;
  urlSwitch.state.hook = async (count) => { if (count === 5) urlSwitch.state.documentUrl = "https://example.invalid/other.xlsx"; };
  const writesBeforeUrlSwitch = urlSwitch.state.writes;
  await rejects(() => urlSwitch.api.writeAssistantRecord(second, GOLDEN, expectedWorkbook), "AF_SPEC_STALE");
  assert.equal(urlSwitch.state.writes, writesBeforeUrlSwitch);
  assert.equal(urlSwitch.state.saves, 0);
  await rejects(() => urlSwitch.api.writeAssistantRecord(node(), GOLDEN, {...expectedWorkbook, extra: true}), "AF_RECORD_INVALID");
  checks++;

  const unsupported = harness();
  unsupported.state.api = false;
  await rejects(() => unsupported.api.readAssistantRecord(), "PQPC_EXCEL_API_UNSUPPORTED");
  assert.equal(unsupported.state.runs, 0);
  unsupported.state.api = true;
  unsupported.sandbox.crypto = undefined;
  await rejects(() => unsupported.api.verifyAssistantRecordHash(node()), "AF_CRYPTO_UNAVAILABLE");
  await rejects(() => unsupported.api.writeAssistantRecord(node(), null), "AF_CRYPTO_UNAVAILABLE");
  assert.equal(unsupported.state.writes, 0);
  checks++;
  console.log(`Assistant Record Custom XML: ${checks} cases passed`);
}
main().catch((error) => { console.error(error); process.exitCode = 1; });
