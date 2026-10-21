"use strict";

const codec = window.ProblemChainCodec;
const state = {supported: false, busy: false, lastHistoryHash: "", lastCanonicalBytes: 0, officeInfo: null};
const byId = (id) => document.getElementById(id);
const AUTORUN_STEPS = [
  "inspect-zero", "add-small", "get-parse", "set-unicode", "set-near-2mib",
  "add-duplicate", "detect-duplicate", "cleanup",
];

function roundMs(value) {
  return Math.round(value * 10) / 10;
}

function logEvent(event, fields = {}) {
  const entry = {at: new Date().toISOString(), event, ...fields};
  byId("log").textContent += `${JSON.stringify(entry)}\n`;
  byId("log").scrollTop = byId("log").scrollHeight;
}

function setStatus(message, kind = "info") {
  byId("status").textContent = message;
  byId("status").dataset.kind = kind;
}

function setBusy(value) {
  state.busy = value;
  document.querySelectorAll("button[data-action]").forEach((button) => { button.disabled = value || !state.supported; });
}

function snapshotRange(range, sheetName) {
  return JSON.stringify({sheetName, address: range.address, values: range.values, formulas: range.formulas, numberFormat: range.numberFormat});
}

async function measuredSync(context, label, syncs) {
  const started = performance.now();
  await context.sync();
  syncs.push({label, elapsedMs: roundMs(performance.now() - started)});
}

async function loadParts(context, syncs, prefix = "parts") {
  const collection = context.workbook.customXmlParts.getByNamespace(codec.NAMESPACE);
  collection.load("items/id");
  await measuredSync(context, `${prefix}.load`, syncs);
  return collection.items;
}

async function readPartXml(context, part, syncs, prefix = "part") {
  const result = part.getXml();
  await measuredSync(context, `${prefix}.getXml`, syncs);
  return result.value;
}

function publicResult(value) {
  const result = {};
  for (const key of ["partCount", "canonicalBytes", "deleted", "expectedBlockCode"]) {
    if (Object.prototype.hasOwnProperty.call(value || {}, key)) result[key] = value[key];
  }
  return result;
}

async function executeMeasured(label, operation) {
  const syncs = [];
  const started = performance.now();
  try {
    const value = await Excel.run(async (context) => {
      const sheet = context.workbook.worksheets.getActiveWorksheet();
      const sentinel = sheet.getRange("A1");
      sheet.load("name");
      sentinel.load(["address", "values", "formulas", "numberFormat"]);
      await measuredSync(context, "sentinel.before", syncs);
      const before = snapshotRange(sentinel, sheet.name);
      const operationValue = await operation(context, syncs);
      sentinel.load(["address", "values", "formulas", "numberFormat"]);
      await measuredSync(context, "sentinel.after", syncs);
      const after = snapshotRange(sentinel, sheet.name);
      if (before !== after) throw Object.assign(new Error("Active sheet A1 changed during Custom XML operation."), {code: "SOURCE_SENTINEL_CHANGED"});
      return operationValue;
    });
    return {
      label,
      status: "Pass",
      elapsedMs: roundMs(performance.now() - started),
      sentinelUnchanged: true,
      syncs,
      ...publicResult(value),
      // Kept for the local manual UI only. postEvidence() strips this field.
      historyHash: value && value.historyHash ? value.historyHash : undefined,
    };
  } catch (error) {
    return {
      label,
      status: "Fail",
      elapsedMs: roundMs(performance.now() - started),
      sentinelUnchanged: false,
      syncs,
      code: error.code || "SPIKE_FAILED",
    };
  }
}

async function runMeasured(label, operation) {
  if (state.busy) return;
  setBusy(true);
  try {
    const result = await executeMeasured(label, operation);
    logEvent(label, result);
    if (result.status === "Pass") setStatus(`${label}: Pass (${result.elapsedMs} ms). A1 unchanged.`, "pass");
    else setStatus(`${label}: Fail (${result.code}).`, "fail");
    await refreshSummary();
  } finally {
    setBusy(false);
  }
}

async function refreshSummary() {
  if (!state.supported) return;
  const syncs = [];
  const started = performance.now();
  try {
    const summary = await Excel.run(async (context) => {
      const parts = await loadParts(context, syncs, "inspect");
      const result = {partCount: parts.length, historyHash: "", canonicalBytes: 0};
      if (parts.length === 1) {
        const parsed = await codec.parseXml(await readPartXml(context, parts[0], syncs, "inspect"));
        result.historyHash = parsed.historyHash;
        result.canonicalBytes = parsed.canonicalBytes;
      }
      return result;
    });
    state.lastHistoryHash = summary.historyHash;
    state.lastCanonicalBytes = summary.canonicalBytes;
    byId("part-count").textContent = String(summary.partCount);
    byId("history-hash").textContent = summary.historyHash || "-";
    byId("payload-size").textContent = summary.canonicalBytes ? `${summary.canonicalBytes.toLocaleString()} bytes` : "-";
    if (summary.partCount > 1) setStatus("PQPC_DUPLICATE_XML_PART: multiple matching parts; no part was selected or deleted automatically.", "fail");
    logEvent("inspect", {status: summary.partCount > 1 ? "Blocked" : "Pass", elapsedMs: roundMs(performance.now() - started), syncs, ...summary});
  } catch (error) {
    setStatus("Custom XML inspection failed.", "fail");
    logEvent("inspect", {status: "Fail", code: error.code || "PQPC_DOCUMENT_INVALID"});
  }
}

async function inspectZero(context, syncs) {
  const parts = await loadParts(context, syncs, "zero");
  if (parts.length !== 0) throw Object.assign(new Error("Autorun requires a clean namespace."), {code: "AUTORUN_INITIAL_STATE_NOT_EMPTY"});
  return {partCount: 0};
}

function trackCreatedParts(before, after, createdPartIds) {
  if (!createdPartIds) return;
  const previous = new Set(before.map((part) => part.id));
  after.filter((part) => !previous.has(part.id)).forEach((part) => createdPartIds.add(part.id));
}

async function addSmall(context, syncs, createdPartIds) {
  const parts = await loadParts(context, syncs, "add.before");
  if (parts.length !== 0) throw new Error(`Expected 0 matching parts, found ${parts.length}.`);
  const built = await codec.buildXml(await codec.makeRepresentativeDocument());
  const created = context.workbook.customXmlParts.add(built.xml);
  if (createdPartIds) created.load("id");
  await measuredSync(context, "add.commit", syncs);
  if (createdPartIds) createdPartIds.add(created.id);
  const after = await loadParts(context, syncs, "add.after");
  trackCreatedParts(parts, after, createdPartIds);
  if (after.length !== 1) throw new Error(`Add read-back expected 1 part, found ${after.length}.`);
  const parsed = await codec.parseXml(await readPartXml(context, after[0], syncs, "add.readBack"));
  if (parsed.historyHash !== built.historyHash) throw new Error("Add read-back hash mismatch.");
  return {partCount: after.length, canonicalBytes: built.canonicalBytes, historyHash: built.historyHash};
}

async function readOne(context, syncs) {
  const parts = await loadParts(context, syncs, "read");
  if (parts.length !== 1) throw new Error(`Expected exactly 1 part, found ${parts.length}.`);
  const parsed = await codec.parseXml(await readPartXml(context, parts[0], syncs, "read"));
  return {partCount: 1, canonicalBytes: parsed.canonicalBytes, historyHash: parsed.historyHash};
}

async function setUnicode(context, syncs) {
  const parts = await loadParts(context, syncs, "unicode.before");
  if (parts.length !== 1) throw new Error(`Expected exactly 1 part, found ${parts.length}.`);
  const parsed = await codec.parseXml(await readPartXml(context, parts[0], syncs, "unicode.before"));
  parsed.document.storageVersion += 1;
  parsed.document.revisions[0].name = "\u0110\u01a1n h\u00e0ng H\u00e0 N\u1ed9i \u2013 \u6e2c\u8a66 \u2713";
  parsed.document.revisions[0].note = `Office.js annotation ${new Date().toISOString()}`;
  parsed.document.revisions[0].annotationUpdatedAt = new Date().toISOString();
  const built = await codec.buildXml(parsed.document);
  parts[0].setXml(built.xml);
  await measuredSync(context, "unicode.commit", syncs);
  const readBack = await codec.parseXml(await readPartXml(context, parts[0], syncs, "unicode.readBack"));
  if (readBack.document.revisions[0].name !== parsed.document.revisions[0].name) throw new Error("Unicode set/read-back mismatch.");
  return {partCount: 1, canonicalBytes: readBack.canonicalBytes, historyHash: readBack.historyHash};
}

async function setNearLimit(context, syncs) {
  const parts = await loadParts(context, syncs, "large.before");
  if (parts.length !== 1) throw new Error(`Expected exactly 1 part, found ${parts.length}.`);
  const document = await codec.makeNearLimitDocument();
  const built = await codec.buildXml(document);
  parts[0].setXml(built.xml);
  await measuredSync(context, "large.commit", syncs);
  const parsed = await codec.parseXml(await readPartXml(context, parts[0], syncs, "large.readBack"));
  if (parsed.historyHash !== built.historyHash) throw new Error("Near-limit set/read-back hash mismatch.");
  return {partCount: 1, canonicalBytes: parsed.canonicalBytes, historyHash: parsed.historyHash};
}

async function addDuplicate(context, syncs, createdPartIds) {
  const parts = await loadParts(context, syncs, "duplicate.before");
  if (parts.length !== 1) throw new Error(`Duplicate test requires exactly 1 part, found ${parts.length}.`);
  const xml = await readPartXml(context, parts[0], syncs, "duplicate.source");
  const created = context.workbook.customXmlParts.add(xml);
  if (createdPartIds) created.load("id");
  await measuredSync(context, "duplicate.commit", syncs);
  if (createdPartIds) createdPartIds.add(created.id);
  const after = await loadParts(context, syncs, "duplicate.after");
  trackCreatedParts(parts, after, createdPartIds);
  if (after.length !== 2) throw new Error(`Duplicate test expected 2 parts, found ${after.length}.`);
  return {partCount: 2, expectedBlockCode: "PQPC_DUPLICATE_XML_PART"};
}

async function detectDuplicate(context, syncs) {
  const parts = await loadParts(context, syncs, "duplicate.detect");
  if (parts.length !== 2) throw new Error(`Duplicate detection expected 2 parts, found ${parts.length}.`);
  return {partCount: 2, expectedBlockCode: "PQPC_DUPLICATE_XML_PART"};
}

async function deleteOne(context, syncs) {
  const parts = await loadParts(context, syncs, "delete.before");
  if (parts.length !== 1) throw new Error(`Delete-one requires exactly 1 part, found ${parts.length}.`);
  parts[0].delete();
  await measuredSync(context, "delete.commit", syncs);
  const after = await loadParts(context, syncs, "delete.after");
  if (after.length !== 0) throw new Error(`Delete read-back expected 0 parts, found ${after.length}.`);
  return {partCount: 0};
}

async function deleteAll(context, syncs) {
  const parts = await loadParts(context, syncs, "cleanup.before");
  parts.forEach((part) => part.delete());
  await measuredSync(context, "cleanup.commit", syncs);
  const after = await loadParts(context, syncs, "cleanup.after");
  if (after.length !== 0) throw new Error(`Cleanup expected 0 parts, found ${after.length}.`);
  return {deleted: parts.length, partCount: 0};
}

async function deleteCreated(context, syncs, createdPartIds) {
  const parts = await loadParts(context, syncs, "cleanup.before");
  const owned = parts.filter((part) => createdPartIds.has(part.id));
  owned.forEach((part) => part.delete());
  await measuredSync(context, "cleanup.commit", syncs);
  const after = await loadParts(context, syncs, "cleanup.after");
  if (after.some((part) => createdPartIds.has(part.id))) throw new Error("Cleanup left an autorun-created part behind.");
  return {deleted: owned.length, partCount: after.length};
}

function redactedStep(result) {
  const value = {
    label: result.label,
    status: result.status,
    elapsedMs: result.elapsedMs,
    sentinelUnchanged: result.sentinelUnchanged,
    syncs: result.syncs.map((item) => ({label: item.label, elapsedMs: item.elapsedMs})),
  };
  for (const key of ["partCount", "canonicalBytes", "deleted", "expectedBlockCode", "code"]) {
    if (result[key] !== undefined) value[key] = result[key];
  }
  return value;
}

function newRunId() {
  if (window.crypto && typeof window.crypto.randomUUID === "function") return window.crypto.randomUUID();
  return `fallback-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 14)}`;
}

async function postEvidence(evidence) {
  const response = await fetch("/evidence", {
    method: "POST",
    credentials: "same-origin",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(evidence),
  });
  if (!response.ok) throw Object.assign(new Error(`Evidence endpoint returned ${response.status}.`), {code: "EVIDENCE_POST_FAILED"});
}

async function runAutorun() {
  if (state.busy || !state.supported) return;
  setBusy(true);
  const startedAt = new Date().toISOString();
  const steps = [];
  const createdPartIds = new Set();
  const sequence = [
    ["inspect-zero", inspectZero],
    ["add-small", (context, syncs) => addSmall(context, syncs, createdPartIds)],
    ["get-parse", readOne],
    ["set-unicode", setUnicode],
    ["set-near-2mib", setNearLimit],
    ["add-duplicate", (context, syncs) => addDuplicate(context, syncs, createdPartIds)],
    ["detect-duplicate", detectDuplicate],
  ];
  try {
    for (const [label, operation] of sequence) {
      const result = await executeMeasured(label, operation);
      steps.push(redactedStep(result));
      logEvent(label, result);
      if (result.status !== "Pass") break;
    }
  } finally {
    const cleanup = await executeMeasured("cleanup", (context, syncs) => deleteCreated(context, syncs, createdPartIds));
    steps.push(redactedStep(cleanup));
    logEvent("cleanup", cleanup);
  }

  const sentinelUnchanged = steps.every((step) => step.sentinelUnchanged === true);
  const expectedOrder = AUTORUN_STEPS.slice(0, steps.length - 1).concat("cleanup");
  const orderMatches = steps.every((step, index) => step.label === expectedOrder[index]);
  const passed = steps.length === AUTORUN_STEPS.length && orderMatches && sentinelUnchanged && steps.every((step) => step.status === "Pass") && steps.at(-1).partCount === 0;
  const evidence = {
    schemaVersion: "1.0",
    runId: newRunId(),
    capturedAt: new Date().toISOString(),
    startedAt,
    host: "Excel",
    platform: String((state.officeInfo && state.officeInfo.platform) || "unknown"),
    excelApi: "1.5",
    status: passed ? "Pass" : "Fail",
    sentinelUnchanged,
    finalPartCount: steps.at(-1).partCount,
    noSaveCalled: true,
    steps,
  };
  try {
    await postEvidence(evidence);
    setStatus(`Autorun ${evidence.status}; redacted evidence posted. Final parts: ${evidence.finalPartCount}.`, passed ? "pass" : "fail");
    logEvent("evidence-post", {status: "Pass", runId: evidence.runId, bytes: JSON.stringify(evidence).length});
  } catch (error) {
    setStatus(`Autorun ${evidence.status}, but evidence POST failed (${error.code || "EVIDENCE_POST_FAILED"}).`, "fail");
    logEvent("evidence-post", {status: "Fail", code: error.code || "EVIDENCE_POST_FAILED"});
  } finally {
    setBusy(false);
    await refreshSummary();
  }
}

function bind(id, label, operation) {
  byId(id).addEventListener("click", () => runMeasured(label, operation));
}

Office.onReady(async (info) => {
  state.officeInfo = info;
  if (info.host !== Office.HostType.Excel) {
    setStatus("This spike supports Excel only.", "fail");
    return;
  }
  state.supported = Office.context.requirements.isSetSupported("ExcelApi", "1.5");
  byId("capability").textContent = state.supported ? "ExcelApi 1.5: supported" : "ExcelApi 1.5: unsupported";
  setBusy(false);
  if (!state.supported) {
    setStatus("PQPC_EXCEL_API_UNSUPPORTED: workbook.customXmlParts was not called.", "fail");
    return;
  }
  setStatus("Ready. The spike never calls Save and reads A1 only as a source sentinel.", "pass");
  bind("add-small", "add-small", addSmall);
  bind("read-one", "get-parse", readOne);
  bind("set-unicode", "set-unicode", setUnicode);
  bind("set-large", "set-near-2mib", setNearLimit);
  bind("add-duplicate", "add-duplicate", addDuplicate);
  bind("delete-one", "delete-one", deleteOne);
  bind("delete-all", "delete-all", deleteAll);
  byId("refresh").addEventListener("click", refreshSummary);
  if (new URLSearchParams(window.location.search).get("autorun") === "1") await runAutorun();
  else await refreshSummary();
});
