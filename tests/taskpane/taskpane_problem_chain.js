"use strict";

const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const {TextDecoder, TextEncoder} = require("node:util");

const source = fs.readFileSync(path.join(__dirname, "../../pbip_assistant/excel_addin/taskpane.js"), "utf8");

function makeElement(id = "") {
  const listeners = new Map();
  const children = [];
  const classes = new Set();
  const attributes = new Map();
  const el = {
    id, tagName: "DIV", textContent: "", value: "", disabled: false, checked: false,
    children, options: [], dataset: {}, style: {}, parentElement: null,
    classList: {
      toggle(name, enabled) {
        const has = classes.has(name);
        const shouldAdd = enabled !== undefined ? enabled : !has;
        if (shouldAdd) classes.add(name); else classes.delete(name);
      },
      add(...names) { for (const n of names) if (n) classes.add(n); },
      remove(...names) { for (const n of names) classes.delete(n); },
      contains(name) { return classes.has(name); },
    },
    addEventListener(name, callback) { listeners.set(name, callback); },
    click(event = {}) {
      let stopped = false;
      const evt = {
        defaultPrevented: false,
        target: el,
        preventDefault() { this.defaultPrevented = true; },
        stopPropagation() { stopped = true; },
        ...event,
      };
      const res = listeners.get("click")?.(evt);
      return res;
    },
    dispatch(name, event = {}) { return listeners.get(name)?.({target: el, ...event}); },
    append(...items) {
      for (const item of items) {
        if (item) {
          if (item.parentElement && item.parentElement !== el) {
            const oldIndex = item.parentElement.children.indexOf(item);
            if (oldIndex >= 0) item.parentElement.children.splice(oldIndex, 1);
          }
          children.push(item);
          item.parentElement = el;
        }
      }
    },
    appendChild(item) {
      if (item) {
        if (item.parentElement && item.parentElement !== el) {
          const oldIndex = item.parentElement.children.indexOf(item);
          if (oldIndex >= 0) item.parentElement.children.splice(oldIndex, 1);
        }
        children.push(item);
        item.parentElement = el;
      }
      return item;
    },
    insertBefore(item, refChild) {
      if (!item) return item;
      if (item.parentElement && item.parentElement !== el) {
        const oldIndex = item.parentElement.children.indexOf(item);
        if (oldIndex >= 0) item.parentElement.children.splice(oldIndex, 1);
      }
      const idx = refChild ? children.indexOf(refChild) : -1;
      if (idx >= 0) {
        children.splice(idx, 0, item);
      } else {
        children.push(item);
      }
      item.parentElement = el;
      return item;
    },
    replaceChildren(...items) {
      for (const child of children) {
        if (child.parentElement === el) child.parentElement = null;
      }
      children.splice(0, children.length);
      for (const item of items) {
        if (item) {
          children.push(item);
          item.parentElement = el;
        }
      }
    },
    setAttribute(key, val) {
      attributes.set(key, String(val));
      if (key === "class") {
        classes.clear();
        for (const cls of String(val).trim().split(/\s+/)) {
          if (cls) classes.add(cls);
        }
      }
    },
    getAttribute(key) { return attributes.get(key) || null; },
    removeAttribute(key) { attributes.delete(key); },
    focus() {},
    remove() {
      if (el.parentElement) {
        const idx = el.parentElement.children.indexOf(el);
        if (idx >= 0) el.parentElement.children.splice(idx, 1);
        el.parentElement = null;
      }
    },
    querySelector(selector) {
      return el.querySelectorAll(selector)[0] || null;
    },
    querySelectorAll(selector) {
      const results = [];
      const cleanSelector = selector.replace(":scope > ", "").trim();
      function matches(node) {
        if (!node) return false;
        if (cleanSelector.startsWith("#")) return node.id === cleanSelector.slice(1);
        if (cleanSelector.startsWith(".")) {
          const className = cleanSelector.slice(1);
          return node.classList?.contains(className) || node.className?.split(/\s+/).includes(className);
        }
        if (cleanSelector.startsWith("[data-") && cleanSelector.includes("='")) {
          const m = cleanSelector.match(/\[([a-zA-Z0-9_-]+)='([^']*)'\]/);
          if (m) {
            const prop = m[1].replace("data-", "").replace(/-([a-z])/g, (_, g) => g.toUpperCase());
            return node.dataset?.[prop] === m[2] || attributes.get(m[1]) === m[2];
          }
        }
        if (cleanSelector.startsWith("[data-") && cleanSelector.includes("=\"")) {
          const m = cleanSelector.match(/\[([a-zA-Z0-9_-]+)="([^"]*)"\]/);
          if (m) {
            const prop = m[1].replace("data-", "").replace(/-([a-z])/g, (_, g) => g.toUpperCase());
            return node.dataset?.[prop] === m[2] || attributes.get(m[1]) === m[2];
          }
        }
        if (cleanSelector.startsWith("[") && cleanSelector.endsWith("]")) {
          const attr = cleanSelector.slice(1, -1);
          const prop = attr.replace(/^data-/, "").replace(/-([a-z])/g, (_, g) => g.toUpperCase());
          return attributes.has(attr) || node.dataset?.[attr] !== undefined || node.dataset?.[prop] !== undefined;
        }
        if (["button", "li", "ul", "ol", "span", "div", "section", "article", "svg", "p"].includes(cleanSelector.toLowerCase())) {
          return node.tagName?.toLowerCase() === cleanSelector.toLowerCase();
        }
        return false;
      }
      function walk(parent) {
        for (const child of parent.children || []) {
          if (matches(child)) results.push(child);
          walk(child);
        }
      }
      walk(el);
      return results;
    },
    closest(selector) {
      let cur = el;
      const cleanSelector = selector.trim();
      while (cur) {
        if (cleanSelector.startsWith(".") && (cur.classList?.contains(cleanSelector.slice(1)) || cur.className?.split(/\s+/).includes(cleanSelector.slice(1)))) return cur;
        if (cleanSelector.startsWith("#") && cur.id === cleanSelector.slice(1)) return cur;
        if (cur.tagName && cur.tagName.toLowerCase() === cleanSelector.toLowerCase()) return cur;
        cur = cur.parentElement;
      }
      return null;
    },
  };
  Object.defineProperty(el, "className", {
    get() { return [...classes].join(" "); },
    set(val) {
      classes.clear();
      if (val) {
        for (const cls of String(val).trim().split(/\s+/)) {
          if (cls) classes.add(cls);
        }
      }
    },
    configurable: true,
    enumerable: true,
  });
  return el;
}

const elements = new Map();
function element(id) {
  if (!elements.has(id)) elements.set(id, makeElement(id));
  return elements.get(id);
}

let api15 = true;
let excelRuns = 0;
let saveCalls = 0;
let cellWrites = 0;
let syncs = 0;
let nextPart = 1;
let parts = [];

function makePart(xml) {
  const part = {
    id: `part-${nextPart++}`, xml,
    getXml() { return {value: this.xml}; },
    setXml(value) { this.xml = value; },
    delete() { parts = parts.filter((candidate) => candidate !== this); },
  };
  parts.push(part);
  return part;
}

const context = {
  workbook: {
    customXmlParts: {
      getByNamespace(namespace) {
        return {items: parts.filter((part) => part.xml.includes(namespace)), load() {}};
      },
      add(xml) { return makePart(xml); },
    },
    save() { saveCalls += 1; },
  },
  async sync() { syncs += 1; },
};

const sandbox = {
  document: {
    getElementById: element,
    addEventListener() {},
    createElement(tag) { const el = makeElement(tag); el.tagName = tag; return el; },
    createElementNS(ns, tag) { const el = makeElement(tag); el.tagName = tag; return el; },
  },
  window: {
    Office: {context: {requirements: {isSetSupported(name, version) { return name === "ExcelApi" && (version === "1.4" || (version === "1.5" && api15)); }}}},
    addEventListener() {},
  },
  Office: {
    context: {requirements: {isSetSupported(name, version) { return name === "ExcelApi" && (version === "1.4" || (version === "1.5" && api15)); }}},
  },
  Excel: {async run(callback) { excelRuns += 1; return callback(context); }},
  TextEncoder, TextDecoder, Uint8Array, URLSearchParams,
  btoa(value) { return Buffer.from(value, "binary").toString("base64"); },
  atob(value) { return Buffer.from(value, "base64").toString("binary"); },
  console, setTimeout, clearTimeout,
};

vm.runInNewContext(source + `
  globalThis.__state = state;
  globalThis.__hydrate = hydrateProblemChain;
  globalThis.__read = readProblemChainXml;
  globalThis.__create = createProblemContinuation;
  globalThis.__openBranch = openProblemBranchEditor;
  globalThis.__closeBranch = closeProblemBranchEditor;
  globalThis.__submitBranch = submitProblemBranchDraft;
  globalThis.__promptInput = handleProblemPromptInput;
  globalThis.__renderChain = renderProblemChain;
  globalThis.__typedPlanFromRevision = typedPlanFromProblemRevision;
  globalThis.__checkout = checkoutProblemRevision;
  globalThis.__deleteProblem = deleteProblemRevision;
  globalThis.__clearHistory = clearProblemChainHistory;
  globalThis.__setConfirmation = (callback) => { requestPQConfirmation = callback; };
  globalThis.__select = selectProblemChainRevision;
  globalThis.__manualEdit = createTypedRevision;
  globalThis.__renderTypedPreview = renderTypedPreview;
  globalThis.__rememberPreview = rememberProblemChainPreview;
  globalThis.__markSourceChanged = markProblemSourceChanged;
  globalThis.__reconcileCache = reconcileProblemChainPreviewCache;
  globalThis.__invalidateSession = invalidateSessionBoundState;
  globalThis.__persist = persistProblemChainCandidate;
  globalThis.__canonical = canonicalProblemChainJson;
  globalThis.__buildXml = buildProblemChainXml;
  globalThis.__parseXml = parseProblemChainXml;
  globalThis.__update = updatePQButtons;
  globalThis.__originalRenderTypedPlan = renderTypedPlan;
  globalThis.__setHistoryExpanded = setProblemChainHistoryExpanded;
  api = async (endpoint, payload) => globalThis.__api(endpoint, payload);
  readWorkbook = async () => globalThis.__workbook;
  renderWorkbook = () => {};
  renderTypedPlan = (plan) => { state.pqTypedPlan = plan; };
  exportWorkbookBase64 = async () => "synthetic-export";
  applyPQValuesToOpenWorkbook = async () => {
    globalThis.__recordWrite();
    return {resultSheetName: "PQ_Typed_Result", rowCount: 1, columnCount: 1};
  };
`, sandbox);
sandbox.__recordWrite = () => { cellWrites += 1; };

const workbook = {
  name: "ProblemChain.xlsx", url: "file:///C:/ProblemChain.xlsx", activeSheet: "Sales",
  activeCell: {rowIndex: 1, columnIndex: 0}, sheets: [],
  tables: [{sheet: "Sales", name: "tblSales", headers: ["OrderID"], rows: [["A-1"]], totalRows: 1, totalColumns: 1}],
};
sandbox.__workbook = workbook;
sandbox.__state.workbook = workbook;
sandbox.__state.officeReady = true;
sandbox.__state.codexAvailable = true;
sandbox.__state.sessionId = "ses-test";
sandbox.__state.problemChainCapability = true;

function hash(documentValue) {
  return "sha256:" + crypto.createHash("sha256").update(sandbox.__canonical(documentValue)).digest("hex");
}

function revision(id, parent, prompt) {
  return {
    revisionId: id, parentRevisionId: parent, originKind: "problem", createdAt: "2026-10-14T12:00:00+07:00",
    problemPrompt: prompt, changeReason: prompt, name: null, note: null, annotationUpdatedAt: null,
    sourceSchemaFingerprint: "sha256:" + "1".repeat(64), snapshotId: `snap_${id}`, summary: prompt,
    questions: [], assumptions: [], warnings: [], sources: [],
    steps: [{stepId: `stp_${id}`, position: 1, variableName: "Source", actionDescription: "Load source", operation: {type: "source.workbookTable", parameters: {sourceId: "src_sales"}}, inputs: [], outputContract: {kind: "table", columns: []}}],
    finalOutputStepId: `stp_${id}`, changeSet: [], validationAtCreation: {planStatus: "reviewReady"}, runtimeSummary: null,
    reviewHash: "sha256:" + "2".repeat(64),
  };
}

function documentWith(revisions, headRevisionId) {
  return {
    schemaVersion: "1.0", chainId: "chain_test", planId: "plan_test", storageVersion: revisions.length,
    headRevisionId, samplePersistence: {enabled: false, warningAcceptedAt: null, maxRows: 20, maxColumns: 200},
    sampleStore: {}, revisions,
  };
}

const calls = [];
let pending = null;
sandbox.__api = async (endpoint, payload) => {
  calls.push({endpoint, payload});
  if (endpoint.endsWith("/load")) {
    assert.equal(payload.workbook, workbook, "load must provide workbook schema so the server can revalidate and activate HEAD");
    return {document: payload.document, historyHash: payload.document ? hash(payload.document) : null};
  }
  if (endpoint.endsWith("/problems")) {
    const prior = payload.document;
    assert.equal(Object.prototype.hasOwnProperty.call(payload, "typedPlan"), false,
      "root and continuation let the server planner own typed-plan creation/changes");
    assert.equal(payload.workbook, workbook);
    if (!prior) {
      assert.equal(payload.source.kind, "table");
      assert.equal(payload.source.sheet, "Sales");
      assert.equal(payload.source.name, "tblSales");
    }
    const revisions = prior ? prior.revisions.slice() : [];
    const id = `rev_${String(revisions.length + 1).padStart(24, "0")}`;
    const parentId = prior ? (payload.baseRevisionId || prior.headRevisionId) : null;
    revisions.push(revision(id, parentId, payload.prompt));
    const documentValue = prior ? {...prior, storageVersion: prior.storageVersion + 1, headRevisionId: id, revisions} : documentWith(revisions, id);
    pending = {mutationId: `mut-${calls.length}`, baseHistoryHash: payload.baseHistoryHash, document: documentValue, historyHash: hash(documentValue), revision: revisions.at(-1), creationMode: payload.creationMode || "continue"};
    if (payload.creationMode === "editProblem") {
      pending.impactReport = {affectedRevisionIds: [payload.editRevisionId], affectedStepIds: ["stp_affected"], affectedColumnIds: ["col_order"], issues: [{code: "PQPC_DESCENDANT_REVIEW_REQUIRED", revisionId: payload.editRevisionId, stepIds: ["stp_affected"], columnIds: ["col_order"], reason: "review"}]};
    }
    return pending;
  }
  if (endpoint.endsWith("/problems/delete")) {
    const descendants = new Set([payload.revisionId]);
    let changed = true;
    while (changed) {
      changed = false;
      for (const item of payload.document.revisions) {
        if (descendants.has(item.parentRevisionId) && !descendants.has(item.revisionId)) {
          descendants.add(item.revisionId);
          changed = true;
        }
      }
    }
    const target = payload.document.revisions.find((item) => item.revisionId === payload.revisionId);
    const revisions = payload.document.revisions.filter((item) => !descendants.has(item.revisionId));
    const headRevisionId = descendants.has(payload.document.headRevisionId)
      ? target.parentRevisionId : payload.document.headRevisionId;
    const documentValue = {...payload.document, storageVersion: payload.document.storageVersion + 1,
      headRevisionId, revisions};
    pending = {mutationId: `mut-${calls.length}`, baseHistoryHash: payload.baseHistoryHash,
      document: documentValue, historyHash: hash(documentValue),
      revision: revisions.find((item) => item.revisionId === headRevisionId),
      deletedRevisionIds: [...descendants]};
    return pending;
  }
  if (endpoint.endsWith("/checkout")) {
    const documentValue = {...payload.document, storageVersion: payload.document.storageVersion + 1, headRevisionId: payload.revisionId};
    pending = {mutationId: `mut-${calls.length}`, baseHistoryHash: payload.baseHistoryHash, document: documentValue, historyHash: hash(documentValue), revision: documentValue.revisions.find((item) => item.revisionId === payload.revisionId)};
    return pending;
  }
  if (endpoint.endsWith("/revisions")) {
    assert.ok(payload.document, "manual edit must include persisted history");
    assert.equal(payload.baseRevisionId, payload.document.headRevisionId);
    assert.equal(payload.baseHistoryHash, hash(payload.document));
    assert.equal(payload.workbook, workbook);
    assert.ok(Array.isArray(payload.changes) && payload.changes.length === 1);
    const prior = payload.document;
    const revisions = prior.revisions.slice();
    const id = `rev_${String(revisions.length + 1).padStart(24, "0")}`;
    const edited = {...structuredClone(revisions.at(-1)), revisionId: id,
      parentRevisionId: prior.headRevisionId, originKind: "manualEdit",
      changeReason: payload.changeReason, changeSet: payload.changes,
      reviewHash: "sha256:" + String(revisions.length + 1).padStart(64, "0")};
    revisions.push(edited);
    const documentValue = {...prior, storageVersion: prior.storageVersion + 1,
      headRevisionId: id, revisions};
    pending = {mutationId: `mut-${calls.length}`, baseHistoryHash: payload.baseHistoryHash,
      document: documentValue, historyHash: hash(documentValue), revision: edited};
    return pending;
  }
  if (endpoint.endsWith("/mutations/commit")) {
    assert.equal(payload.mutationId, pending.mutationId);
    assert.equal(payload.observedHistoryHash, pending.historyHash);
    return {document: pending.document, historyHash: pending.historyHash};
  }
  if (endpoint.endsWith("/cached-results/prepare")) {
    throw Object.assign(new Error("full result was evicted"), {code: "PQPC_RESULT_CACHE_MISS"});
  }
  if (endpoint.endsWith("/previews")) {
    return {previewId: "prv-cache-miss-refresh", revisionId: payload.revisionId,
      sourceRows: 1, resultRows: 1, resultColumns: 1,
      beforeColumns: ["OrderID"], beforeRows: [["A-1"]],
      afterColumns: ["OrderID"], afterRows: [["A-1"]],
      runtimeEvidence: {excelVersion: "16.0"}, runVersion: sandbox.__state.problemChainDataVersion};
  }
  throw new Error(`Unexpected endpoint: ${endpoint}`);
};

(async () => {
  // A newer Excel host with an older coordinator must fail closed and keep
  // standalone Typed Steps visible instead of issuing endpoints that 404.
  sandbox.__state.problemChainCapability = false;
  api15 = true;
  const runsBeforeMissingCapability = excelRuns;
  await sandbox.__hydrate();
  assert.equal(excelRuns, runsBeforeMissingCapability);
  assert.equal(element("pq2-standalone-prompt-section").classList.contains("hidden"), false);

  // ExcelApi 1.4 must keep standalone Typed Steps and never touch Custom XML.
  sandbox.__state.problemChainCapability = true;
  api15 = false;
  const runsBeforeUnsupported = excelRuns;
  await sandbox.__hydrate();
  assert.equal(excelRuns, runsBeforeUnsupported, "unsupported host must not call workbook.customXmlParts");
  assert.equal(element("pq2-standalone-prompt-section").classList.contains("hidden"), false);

  // Clean ExcelApi 1.5 workbook hydrates without writing cells or calling Save.
  api15 = true;
  await sandbox.__hydrate();
  assert.equal(sandbox.__state.problemChainHydrated, true);
  assert.equal(parts.length, 0);
  assert.equal(calls.filter((call) => call.endpoint.endsWith("/load")).length, 1);

  // Problem 1 and 2 use read/CAS/write/read-back/commit and preserve revision 1.
  element("pqpc-prompt").value = "Problem one";
  await sandbox.__create();
  assert.equal(parts.length, 1);
  const firstDocument = structuredClone(sandbox.__state.problemChainDocument);
  assert.equal(firstDocument.revisions.length, 1);
  // Continuation uses the persisted base and workbook catalog. It must not be
  // blocked merely because the active sheet is a managed result sheet.
  workbook.activeSheet = "PQ_Result";
  element("pqpc-prompt").value = "Problem two";
  sandbox.__update();
  assert.equal(element("pqpc-create-button").disabled, false,
    "continuation remains available while a result sheet is active");
  await sandbox.__create();
  workbook.activeSheet = "Sales";
  assert.equal(sandbox.__state.problemChainDocument.revisions.length, 2);
  assert.deepEqual(sandbox.__state.problemChainDocument.revisions[0], firstDocument.revisions[0], "old revision must remain immutable");
  const valNode = element("pqpc-timeline").querySelector("[data-validation-status]") || element("pqpc-timeline").querySelector(".node");
  assert.match(valNode?.dataset?.validationStatus || valNode?.textContent || "", /reviewReady/,
    "timeline must expose the revision validation state");
  assert.equal(saveCalls, 0, "task pane must never call workbook.save");
  assert.equal(cellWrites, 0, "Problem Chain persistence must not write cells");

  // Loading is a runtime trust boundary. History returns from workbook, but
  // preview and approval never survive reload/session rehydration.
  sandbox.__state.pqTypedPreview = {previewId: "prv-stale"};
  sandbox.__state.pqTypedApproval = {approvalId: "apr-stale", status: "approved"};
  await sandbox.__hydrate();
  assert.equal(sandbox.__state.pqTypedPreview, null);
  assert.equal(sandbox.__state.pqTypedApproval, null);

  // If commit acknowledges a different document/hash, fail closed. XML is
  // already the source of truth, so the UI must rehydrate instead of guessing
  // or replaying the mutation.
  const normalApiBeforeCommitMismatch = sandbox.__api;
  sandbox.__api = async (endpoint, payload) => {
    if (endpoint.endsWith("/mutations/commit")) {
      return {document: pending.document, historyHash: "sha256:" + "f".repeat(64)};
    }
    return normalApiBeforeCommitMismatch(endpoint, payload);
  };
  const beforeMismatch = sandbox.__state.problemChainDocument;
  const mismatchDocument = {...beforeMismatch, storageVersion: beforeMismatch.storageVersion + 1};
  await assert.rejects(() => sandbox.__persist({
    mutationId: "mut-commit-mismatch", baseHistoryHash: sandbox.__state.problemChainHistoryHash,
    document: mismatchDocument, historyHash: hash(mismatchDocument),
  }), (error) => error.code === "PQPC_HASH_MISMATCH");
  assert.equal(sandbox.__state.problemChainHydrated, false);
  sandbox.__update();
  assert.equal(element("pq2-preview-button").disabled, true,
    "ambiguous XML commit must disable preview until reload");
  assert.equal(element("pq2-approve-button").disabled, true,
    "ambiguous XML commit must disable approval until reload");
  assert.equal(element("pq2-add-step").disabled, true,
    "ambiguous XML commit must disable manual editing until reload");
  sandbox.__api = normalApiBeforeCommitMismatch;
  await sandbox.__hydrate();
  assert.equal(sandbox.__state.problemChainHydrated, true);
  assert.equal(sandbox.__state.problemChainDocument.storageVersion, mismatchDocument.storageVersion,
    "rehydration must follow workbook XML after an ambiguous commit response");

  // Viewing a non-head revision blocks preview and approval; checkout creates a CAS mutation.
  const firstId = firstDocument.headRevisionId;
  sandbox.__select(firstId);
  sandbox.__update();
  assert.equal(element("pq2-preview-button").disabled, true);
  assert.equal(element("pq2-approve-button").disabled, true);
  await sandbox.__checkout(firstId);
  assert.equal(sandbox.__state.problemChainDocument.headRevisionId, firstId);
  assert.equal(sandbox.__state.problemChainViewRevisionId, firstId);
  assert.equal(sandbox.__state.pqTypedPreview.previewId, "prv-cache-miss-refresh",
    "evicted full result must trigger fresh preview, never a truncated write");

  // One-click checkout of an unchanged source restores the complete server
  // result. Marking the global source-changed checkbox invalidates cache and
  // runs a fresh preview, but never writes until the user approves it.
  const normalCheckoutApi = sandbox.__api;
  sandbox.__api = async (endpoint, payload) => {
    if (endpoint.endsWith("/cached-results/prepare")) {
      calls.push({endpoint, payload});
      assert.equal(payload.sourceDataChanged, false);
      assert.equal(payload.baseHistoryHash, sandbox.__state.problemChainHistoryHash);
      if (payload.revisionId === firstId && sandbox.__state.problemChainDataVersion > 0) {
        throw Object.assign(new Error("old source version"), {code: "PQPC_RESULT_CACHE_STALE"});
      }
      return {applyId: "apply-cache", resultWorkbookBase64: "full-values",
        resultWorkbookSheetName: "PQ_Typed_Result", expectedRows: 1, expectedColumns: 1};
    }
    if (endpoint.endsWith("/data-version/increment")) {
      calls.push({endpoint, payload});
      return {status: "versionIncremented", dataVersion: 1};
    }
    if (endpoint.endsWith("/applies/complete")) {
      calls.push({endpoint, payload});
      assert.equal(payload.applyId, "apply-cache");
      return {status: "applied"};
    }
    if (endpoint.endsWith("/previews")) {
      calls.push({endpoint, payload});
      return {previewId: "prv-refresh", revisionId: payload.revisionId,
        sourceRows: 1, resultRows: 1, resultColumns: 1,
        beforeColumns: ["OrderID"], beforeRows: [["A-1"]],
        afterColumns: ["OrderID"], afterRows: [["A-1"]],
        runtimeEvidence: {excelVersion: "16.0"}, runVersion: 1};
    }
    return normalCheckoutApi(endpoint, payload);
  };
  const secondId = firstDocument.revisions[0].revisionId === firstId
    ? sandbox.__state.problemChainDocument.revisions[1].revisionId : firstId;
  const writesBeforeCacheRestore = cellWrites;
  await sandbox.__checkout(secondId);
  assert.equal(sandbox.__state.problemChainDocument.headRevisionId, secondId);
  assert.equal(cellWrites, writesBeforeCacheRestore + 1, "unchanged checkout writes full cached values once");
  assert.equal(element("pq2-result-badge").textContent, "ĐÃ GHI TỪ CACHE");
  element("pqpc-source-changed").checked = true;
  await sandbox.__markSourceChanged();
  assert.equal(sandbox.__state.problemChainDataVersion, 1);
  await sandbox.__checkout(firstId);
  assert.equal(sandbox.__state.problemChainDocument.headRevisionId, firstId);
  assert.equal(cellWrites, writesBeforeCacheRestore + 1, "changed source must not restore old cache");
  assert.equal(sandbox.__state.pqTypedPreview.previewId, "prv-refresh", "changed source reruns preview");
  assert.equal(calls.some((call) => call.endpoint.endsWith("/data-version/increment")), true);
  element("pqpc-source-changed").checked = false;
  sandbox.__api = normalCheckoutApi;

  // An out-of-band history change fails closed before setXml/commit.
  const current = sandbox.__state.problemChainDocument;
  const currentHash = sandbox.__state.problemChainHistoryHash;
  const candidateDocument = {...current, storageVersion: current.storageVersion + 1};
  const staleCandidate = {mutationId: "mut-stale", baseHistoryHash: currentHash, document: candidateDocument, historyHash: hash(candidateDocument)};
  const externalDocument = {...current, storageVersion: current.storageVersion + 10};
  parts[0].xml = sandbox.__buildXml(externalDocument, hash(externalDocument));
  const commitsBefore = calls.filter((call) => call.endpoint.endsWith("/mutations/commit")).length;
  await assert.rejects(() => sandbox.__persist(staleCandidate), (error) => error.code === "PQPC_HISTORY_CONFLICT");
  assert.equal(calls.filter((call) => call.endpoint.endsWith("/mutations/commit")).length, commitsBefore);
  assert.equal(sandbox.__canonical(sandbox.__parseXml(parts[0].xml).document), sandbox.__canonical(externalDocument), "stale candidate must not overwrite workbook history");

  // A changed payload cannot bypass CAS by reusing the expected hash in the
  // XML envelope. The current payload must still equal the loaded document.
  parts[0].xml = sandbox.__buildXml(current, currentHash);
  await sandbox.__hydrate();
  const trusted = sandbox.__state.problemChainDocument;
  const trustedHash = sandbox.__state.problemChainHistoryHash;
  const payloadTamper = {...trusted, storageVersion: trusted.storageVersion + 100};
  parts[0].xml = sandbox.__buildXml(payloadTamper, trustedHash);
  const nextDocument = {...trusted, storageVersion: trusted.storageVersion + 1};
  const payloadProtectedCandidate = {
    mutationId: "mut-payload-protected", baseHistoryHash: trustedHash,
    document: nextDocument, historyHash: hash(nextDocument),
  };
  const commitsBeforePayloadTamper = calls.filter((call) => call.endpoint.endsWith("/mutations/commit")).length;
  await assert.rejects(() => sandbox.__persist(payloadProtectedCandidate), (error) => error.code === "PQPC_HISTORY_CONFLICT");
  assert.equal(calls.filter((call) => call.endpoint.endsWith("/mutations/commit")).length, commitsBeforePayloadTamper);
  assert.equal(sandbox.__canonical(sandbox.__parseXml(parts[0].xml).document), sandbox.__canonical(payloadTamper),
    "payload tamper using a reused envelope hash must not be overwritten");

  // Duplicate namespace parts hard-block hydration without deleting either part.
  makePart(parts[0].xml);
  const countBeforeDuplicate = parts.length;
  await sandbox.__hydrate();
  assert.equal(sandbox.__state.problemChainHydrated, false);
  assert.equal(parts.length, countBeforeDuplicate);
  assert.match(element("pqpc-support").textContent, /PQPC_DUPLICATE_XML_PART/);

  // A failed problem POST is invoked exactly once and never reaches Custom XML write/commit.
  parts = [];
  await sandbox.__hydrate();
  const normalApi = sandbox.__api;
  let expiredPosts = 0;
  sandbox.__api = async (endpoint, payload) => {
    if (endpoint.endsWith("/problems")) {
      expiredPosts += 1;
      throw Object.assign(new Error("expired; a new session may bootstrap, but POST is not replayed"), {code: "TOKEN_EXPIRED"});
    }
    return normalApi(endpoint, payload);
  };
  element("pqpc-prompt").value = "Must not replay";
  await sandbox.__create();
  assert.equal(expiredPosts, 1);
  assert.equal(parts.length, 0);

  // Manual edits create immutable Problem Chain revisions through the same
  // candidate XML CAS/read-back/commit path. No old preview may be reused.
  sandbox.__api = normalApi;
  await sandbox.__hydrate();
  element("pqpc-prompt").value = "Manual edit base";
  await sandbox.__create();
  const manualBase = structuredClone(sandbox.__state.problemChainDocument.revisions[0]);
  const editKinds = [
    {type: "insertStep", afterStepId: manualBase.steps[0].stepId,
      stepDraft: {variableName: "AddedColumn", actionDescription: "Add column",
        operationType: "table.addColumn", inputs: [{kind: "step", ref: manualBase.steps[0].stepId}], parameters: {}}},
    {type: "updateStep", stepId: manualBase.steps[0].stepId, stepDraft: {variableName: "Source", actionDescription: "Updated source"}},
    {type: "moveStep", stepId: manualBase.steps[0].stepId, position: 1},
    {type: "deleteStep", stepId: manualBase.steps[0].stepId},
  ];
  for (const change of editKinds) {
    sandbox.__state.pqTypedPreview = {previewId: "prv-old"};
    sandbox.__state.pqTypedApproval = {approvalId: "apr-old", status: "approved"};
    assert.equal(await sandbox.__manualEdit([change], `Manual ${change.type}`), true);
    assert.equal(sandbox.__state.pqTypedPreview, null);
    assert.equal(sandbox.__state.pqTypedApproval, null);
    assert.equal(sandbox.__state.problemChainDocument.revisions.at(-1).originKind, "manualEdit");
    assert.deepEqual(sandbox.__state.problemChainDocument.revisions[0], manualBase,
      "manual edit must not mutate the root revision");
  }
  assert.equal(sandbox.__state.problemChainDocument.revisions.length, 5);
  const headBeforeRejectedEdit = sandbox.__state.problemChainDocument.headRevisionId;
  const xmlBeforeRejectedEdit = parts[0].xml;
  const manualCallsBeforeView = calls.filter((call) => call.endpoint.endsWith("/revisions")).length;
  sandbox.__select(manualBase.revisionId);
  sandbox.__update();
  assert.equal(element("pq2-add-step").disabled, true,
    "manual editing must be disabled while viewing a non-HEAD revision");
  assert.equal(await sandbox.__manualEdit([{type: "moveStep", stepId: manualBase.steps[0].stepId, position: 1}], "Should block"), false);
  assert.equal(calls.filter((call) => call.endpoint.endsWith("/revisions")).length, manualCallsBeforeView,
    "non-HEAD view must not call edit API");
  assert.equal(parts[0].xml, xmlBeforeRejectedEdit);
  assert.equal(sandbox.__state.problemChainDocument.headRevisionId, headBeforeRejectedEdit);
  sandbox.__select(headBeforeRejectedEdit);
  sandbox.__api = async (endpoint, payload) => {
    if (endpoint.endsWith("/revisions")) throw Object.assign(new Error("validation failed"), {code: "PQV2_DEPENDENCY_INVALID"});
    return normalApi(endpoint, payload);
  };
  assert.equal(await sandbox.__manualEdit([{type: "deleteStep", stepId: manualBase.steps[0].stepId}], "Rejected"), false);
  assert.equal(parts[0].xml, xmlBeforeRejectedEdit, "server rejection cannot write XML");
  assert.equal(sandbox.__state.problemChainDocument.headRevisionId, headBeforeRejectedEdit);
  sandbox.__api = normalApi;

  // Session-only preview FIFO keeps display rows, never runtime authority.
  const cacheRevisions = Array.from({length: 6}, (_, index) => {
    const id = `rev_cache_${index + 1}`;
    return revision(id, index ? `rev_cache_${index}` : null, `Cached problem ${index + 1}`);
  });
  sandbox.__state.problemChainDocument = documentWith(cacheRevisions, cacheRevisions[5].revisionId);
  sandbox.__state.problemChainHydrated = true;
  sandbox.__state.problemChainSupported = true;
  sandbox.__state.pqTypedPreviewCache = [];
  const previewFor = (item, value) => ({
    previewId: `prv_secret_${item.revisionId}`, revisionId: item.revisionId,
    sourceRows: 10, resultRows: 1, resultColumns: 1,
    beforeColumns: ["OrderID"], beforeRows: [["A-1"]],
    afterColumns: ["OrderID"], afterRows: [[value]],
    runtimeEvidence: {excelVersion: "16.0"},
  });
  for (const item of cacheRevisions) {
    sandbox.__state.problemChainDocument.headRevisionId = item.revisionId;
    sandbox.__select(item.revisionId);
    sandbox.__renderTypedPreview(previewFor(item, item.revisionId));
    sandbox.__rememberPreview(previewFor(item, item.revisionId));
  }
  assert.deepEqual(Array.from(sandbox.__state.pqTypedPreviewCache, (entry) => entry.revisionId),
    cacheRevisions.slice(1).map((item) => item.revisionId), "sixth preview must evict the oldest");
  assert.equal(JSON.stringify(sandbox.__state.pqTypedPreviewCache).includes("prv_secret"), false,
    "display cache must not retain preview authority IDs");
  const apiBeforeCacheView = calls.length;
  const excelBeforeCacheView = excelRuns;
  sandbox.__select(cacheRevisions[0].revisionId);
  assert.equal(element("pq2-preview-section").classList.contains("hidden"), true,
    "evicted preview needs a fresh Excel run");
  sandbox.__state.problemChainDocument.headRevisionId = cacheRevisions[1].revisionId;
  sandbox.__select(cacheRevisions[1].revisionId);
  assert.equal(element("pq2-preview-section").classList.contains("hidden"), false);
  assert.equal(element("pq2-result-badge").textContent, "BẢN XEM ĐÃ LƯU");
  assert.equal(sandbox.__state.pqTypedPreview, null, "cached rows are not an approvable preview");
  assert.equal(element("pq2-approve-button").disabled, true);
  assert.equal(calls.length, apiBeforeCacheView, "viewing cache must not call the coordinator");
  assert.equal(excelRuns, excelBeforeCacheView, "viewing cache must not call Excel");
  sandbox.__state.problemChainDocument.headRevisionId = cacheRevisions[2].revisionId;
  sandbox.__select(cacheRevisions[2].revisionId);
  sandbox.__renderTypedPreview(previewFor(cacheRevisions[2], "x".repeat(300)));
  sandbox.__rememberPreview(previewFor(cacheRevisions[2], "x".repeat(300)));
  assert.deepEqual(Array.from(sandbox.__state.pqTypedPreviewCache, (entry) => entry.revisionId),
    [cacheRevisions[1], cacheRevisions[3], cacheRevisions[4], cacheRevisions[5], cacheRevisions[2]].map((item) => item.revisionId),
    "refreshing an existing revision moves its display cache to the FIFO tail");
  assert.equal(sandbox.__state.pqTypedPreviewCache.at(-1).display.afterRows[0][0].length, 256,
    "long cell text must be bounded in session cache");
  assert.equal(JSON.stringify(sandbox.__state.problemChainDocument).includes("prv_secret"), false,
    "cache must not be serialized into workbook history");
  const savedEntry = sandbox.__state.pqTypedPreviewCache.at(-1);
  workbook.name = "SavedAsCopy.xlsx";
  sandbox.__reconcileCache();
  assert.equal(sandbox.__state.pqTypedPreviewCache.length, 0, "Save As workbook identity cannot reuse cached rows");
  workbook.name = "ProblemChain.xlsx";
  sandbox.__state.pqTypedPreviewCache = [savedEntry];
  sandbox.__state.problemChainDocument.chainId = "chain_other_workbook";
  sandbox.__reconcileCache();
  assert.equal(sandbox.__state.pqTypedPreviewCache.length, 0, "another chain cannot inherit preview rows");
  sandbox.__state.pqTypedPreviewCache = [{revisionId: "temporary"}];
  sandbox.__invalidateSession();
  assert.equal(sandbox.__state.pqTypedPreviewCache.length, 0, "session reset clears display cache");

  // Phase 2 tree actions must be explicit and preserve both existing branches.
  const treeRoot = revision("rev_" + "a".repeat(24), null, "Tree root");
  const treeMain = revision("rev_" + "b".repeat(24), treeRoot.revisionId, "Main problem");
  const treeDescendant = revision("rev_" + "c".repeat(24), treeMain.revisionId, "Main descendant");
  const treeDocument = documentWith([treeRoot, treeMain, treeDescendant], treeDescendant.revisionId);
  sandbox.__state.problemChainDocument = treeDocument;
  sandbox.__state.problemChainHistoryHash = hash(treeDocument);
  sandbox.__state.problemChainViewRevisionId = treeDescendant.revisionId;
  sandbox.__state.problemChainHydrated = true;
  sandbox.__state.problemChainSupported = true;
  sandbox.__state.codexAvailable = true;
  sandbox.__state.workbook = workbook;
  parts = [];
  makePart(sandbox.__buildXml(treeDocument, hash(treeDocument)));
  sandbox.__renderChain();
  const questionRevision = {...treeDescendant, questions: ["Which rule handles blank Qty?"]};
  const questionPlan = sandbox.__typedPlanFromRevision(questionRevision);
  assert.equal(questionPlan.planStatus, "needsClarification",
    "unanswered questions must not be presented as review-ready");
  sandbox.__originalRenderTypedPlan(questionPlan);
  assert.match(element("pq2-progress").textContent, /câu hỏi cần làm rõ/);
  assert.match(element("pq2-revision-owner").textContent, /Tiếp nối 1\.2 · HEAD/,
    "Revision header must use the same label as the timeline");
  const copiedParentRevision = {...treeDescendant,
    steps: structuredClone(treeMain.steps), finalOutputStepId: treeMain.finalOutputStepId};
  const copiedParentPlan = sandbox.__typedPlanFromRevision(copiedParentRevision);
  assert.equal(copiedParentPlan.planStatus, "blocked",
    "a legacy branch that copied all parent steps must not appear preview-ready");
  assert.equal(copiedParentPlan.hardBlockers.at(-1).code, "PQPC_NO_PIPELINE_CHANGE");
  sandbox.__state.pqTypedPlan = questionPlan;
  sandbox.__update();
  assert.equal(element("pq2-preview-button").disabled, true,
    "question-bearing HEAD must block Preview before making an HTTP call");
  sandbox.__state.pqTypedPlan = null;
  const treeNodes = element("pqpc-timeline").querySelectorAll(".node");
  assert.deepEqual(treeNodes.map((item) => item.dataset.branchDepth), ["0", "1", "2"]);

  const beforeBranch = structuredClone(treeDocument.revisions);
  sandbox.__state.typedStepDiagnosticsCapability = true;
  const samplerCallsBeforeBranch = calls.filter((call) => call.endpoint.endsWith("/step-diagnostics/samples")).length;
  sandbox.__openBranch("branch", treeRoot.revisionId);
  element("pqpc-branch-prompt").value = "Alternative branch";
  await sandbox.__submitBranch();
  assert.equal(calls.filter((call) => call.endpoint.endsWith("/step-diagnostics/samples")).length,
    samplerCallsBeforeBranch, "branch creation must not export and profile the entire workbook again");
  const branchCall = calls.filter((call) => call.endpoint.endsWith("/problems")).at(-1);
  assert.equal(branchCall.payload.creationMode, "branch");
  assert.equal(branchCall.payload.baseRevisionId, treeRoot.revisionId);
  assert.deepEqual(sandbox.__state.problemChainDocument.revisions.slice(0, beforeBranch.length), beforeBranch,
    "explicit branch must preserve the old branch byte-for-byte");
  assert.equal(sandbox.__state.problemChainDocument.revisions.at(-1).parentRevisionId, treeRoot.revisionId);

  const beforeEdit = structuredClone(sandbox.__state.problemChainDocument.revisions);
  sandbox.__openBranch("editProblem", treeMain.revisionId);
  element("pqpc-branch-prompt").value = "Edited main problem";
  await sandbox.__submitBranch();
  const editCall = calls.filter((call) => call.endpoint.endsWith("/problems")).at(-1);
  assert.equal(editCall.payload.creationMode, "editProblem");
  assert.equal(editCall.payload.baseRevisionId, treeRoot.revisionId);
  assert.equal(editCall.payload.editRevisionId, treeMain.revisionId);
  assert.deepEqual(sandbox.__state.problemChainDocument.revisions.slice(0, beforeEdit.length), beforeEdit,
    "editing an old problem must not replay, mutate or delete its descendants");
  sandbox.__state.typedStepDiagnosticsCapability = false;
  assert.equal(element("pqpc-impact-section").classList.contains("hidden"), false);
  assert.match(element("pqpc-impact-summary").textContent, /revision/);

  // A planner failure must finish the UI operation without losing the draft,
  // changing HEAD, or attempting a Custom XML write.
  const beforeFailedBranchHead = sandbox.__state.problemChainDocument.headRevisionId;
  const beforeFailedBranchXml = parts[0].xml;
  const normalBranchApi = sandbox.__api;
  let failedBranchCalls = 0;
  sandbox.__api = async (endpoint, payload) => {
    if (endpoint.endsWith("/problems")) {
      failedBranchCalls += 1;
      throw Object.assign(new Error("Synthetic planner timeout"), {code: "CODEX_TIMEOUT"});
    }
    return normalBranchApi(endpoint, payload);
  };
  sandbox.__openBranch("branch", treeRoot.revisionId);
  element("pqpc-branch-prompt").value = "Keep this structured request";
  await sandbox.__submitBranch();
  assert.equal(failedBranchCalls, 1, "failed branch must not auto-retry Codex");
  assert.equal(sandbox.__state.problemChainDocument.headRevisionId, beforeFailedBranchHead);
  assert.equal(parts[0].xml, beforeFailedBranchXml);
  assert.equal(element("pqpc-branch-prompt").value, "Keep this structured request");
  assert.match(element("pqpc-branch-status").textContent, /CODEX_TIMEOUT/);
  assert.equal(sandbox.__state.busy, false, "failure must unblock controls");
  sandbox.__api = normalBranchApi;
  sandbox.__closeBranch();

  // Clarification remains inside the current branch draft. No XML/HEAD change
  // is allowed until the user answers and the planner returns a real candidate.
  const beforeClarificationHead = sandbox.__state.problemChainDocument.headRevisionId;
  const beforeClarificationXml = parts[0].xml;
  const beforeClarificationCommits = calls.filter((call) => call.endpoint.endsWith("/mutations/commit")).length;
  const clarificationPrompt = "Use missing OrderMonth column";
  let clarificationPosts = 0;
  sandbox.__api = async (endpoint, payload) => {
    if (endpoint.endsWith("/problems") && payload.prompt.startsWith(clarificationPrompt)) {
      clarificationPosts += 1;
      if (!payload.prompt.includes("Làm rõ yêu cầu:")) {
        return {status: "needsClarification", questions: ["OrderMonth chưa có. Bạn muốn tạo cột hay dùng cột khác?"], assumptions: [], warnings: ["Nguồn mẫu có giới hạn", "Nguồn mẫu có giới hạn"]};
      }
      assert.match(payload.prompt, /Use missing OrderMonth column/);
      assert.match(payload.prompt, /Tạo OrderMonth từ OrderDate, định dạng YYYYMM/);
      if (!payload.prompt.includes("Dùng ngày đầu tháng")) {
        return {status: "needsClarification", questions: ["Khi OrderDate rỗng thì xử lý thế nào?"], assumptions: [], warnings: []};
      }
      assert.match(payload.prompt, /Dùng ngày đầu tháng/);
    }
    return normalBranchApi(endpoint, payload);
  };
  sandbox.__openBranch("branch", treeRoot.revisionId);
  element("pqpc-branch-prompt").value = clarificationPrompt;
  await sandbox.__submitBranch();
  assert.equal(clarificationPosts, 1);
  assert.equal(sandbox.__state.problemChainDocument.headRevisionId, beforeClarificationHead);
  assert.equal(parts[0].xml, beforeClarificationXml);
  assert.equal(calls.filter((call) => call.endpoint.endsWith("/mutations/commit")).length, beforeClarificationCommits);
  assert.equal(element("pqpc-branch-prompt").value, clarificationPrompt);
  assert.equal(element("pqpc-clarification").classList.contains("hidden"), false);
  assert.equal(element("pqpc-clarification-notes").classList.contains("hidden"), false);
  assert.equal(element("pqpc-clarification-notes-list").children.length, 1, "duplicate warnings should collapse");
  assert.equal(element("pqpc-branch-submit").disabled, true, "all clarification answers are required");
  const answer = element("pqpc-clarification-questions").querySelector(".clarification-answer");
  assert.ok(answer);
  answer.value = "Tạo OrderMonth từ OrderDate, định dạng YYYYMM";
  answer.dispatch("input");
  assert.equal(element("pqpc-branch-submit").disabled, false);
  await sandbox.__submitBranch();
  assert.equal(clarificationPosts, 2);
  assert.equal(sandbox.__state.problemChainDocument.headRevisionId, beforeClarificationHead);
  const followUpAnswer = element("pqpc-clarification-questions").querySelector(".clarification-answer");
  followUpAnswer.value = "Dùng ngày đầu tháng";
  followUpAnswer.dispatch("input");
  await sandbox.__submitBranch();
  assert.equal(clarificationPosts, 3);
  assert.equal(sandbox.__state.problemChainDocument.revisions.at(-1).parentRevisionId, treeRoot.revisionId);
  assert.equal(element("pqpc-clarification").classList.contains("hidden"), true);
  assert.equal(sandbox.__state.problemChainClarification, null);
  sandbox.__api = normalBranchApi;

  // Cancelling or editing the original request discards only the draft Q&A.
  sandbox.__api = async (endpoint, payload) => endpoint.endsWith("/problems")
    ? {status: "needsClarification", questions: ["Which column?"], assumptions: [], warnings: []}
    : normalBranchApi(endpoint, payload);
  const beforeCancelXml = parts[0].xml;
  sandbox.__openBranch("branch", treeRoot.revisionId);
  element("pqpc-branch-prompt").value = "Another unclear branch";
  const originalSubmitChildren = [...element("pqpc-branch-submit").children];
  await sandbox.__submitBranch();
  assert.equal(element("pqpc-clarification").classList.contains("hidden"), false);
  element("pqpc-branch-prompt").value = "Rewritten clear branch";
  sandbox.__promptInput();
  assert.equal(element("pqpc-clarification").classList.contains("hidden"), true);
  assert.equal(sandbox.__state.problemChainClarification, null);
  assert.deepEqual(element("pqpc-branch-submit").children, originalSubmitChildren,
    "editing the original request should restore the original submit icon/label");
  sandbox.__closeBranch();
  assert.equal(parts[0].xml, beforeCancelXml);
  sandbox.__api = normalBranchApi;

  sandbox.__api = async (endpoint, payload) => {
    if (endpoint.endsWith("/problems")) {
      element("pqpc-branch-prompt").value = "Changed while planning";
      return {status: "needsClarification", questions: ["Old question?"], assumptions: [], warnings: []};
    }
    return normalBranchApi(endpoint, payload);
  };
  sandbox.__openBranch("branch", treeRoot.revisionId);
  element("pqpc-branch-prompt").value = "Original while planning";
  await sandbox.__submitBranch();
  assert.equal(element("pqpc-clarification").classList.contains("hidden"), true);
  assert.equal(sandbox.__state.problemChainClarification, null);
  assert.match(element("pqpc-branch-status").textContent, /PQPC_CLARIFICATION_STALE/);
  assert.equal(parts[0].xml, beforeCancelXml);
  sandbox.__closeBranch();
  sandbox.__api = normalBranchApi;

  // A still-running older coordinator may return a candidate containing
  // questions; the new pane must not persist that legacy candidate.
  const beforeLegacyQuestionXml = parts[0].xml;
  sandbox.__api = async (endpoint, payload) => {
    const response = await normalBranchApi(endpoint, payload);
    if (endpoint.endsWith("/problems")) response.revision.questions = ["Legacy unresolved question?"];
    return response;
  };
  sandbox.__openBranch("branch", treeRoot.revisionId);
  element("pqpc-branch-prompt").value = "Old coordinator asks a question";
  await sandbox.__submitBranch();
  assert.equal(parts[0].xml, beforeLegacyQuestionXml);
  assert.equal(element("pqpc-clarification").classList.contains("hidden"), false);
  sandbox.__closeBranch();
  sandbox.__api = normalBranchApi;

  // Leaf delete is immediate. Deleting a parent asks once and removes the
  // whole subtree while preserving its sibling branch.
  let confirmations = 0;
  sandbox.__setConfirmation(async () => { confirmations += 1; return true; });
  const deleteRoot = revision("rev_" + "1".repeat(24), null, "Delete root");
  const deleteParent = revision("rev_" + "2".repeat(24), deleteRoot.revisionId, "Delete parent");
  const deleteLeaf = revision("rev_" + "3".repeat(24), deleteParent.revisionId, "Delete leaf");
  const keepSibling = revision("rev_" + "4".repeat(24), deleteRoot.revisionId, "Keep sibling");
  const installDeleteDocument = () => {
    const value = documentWith([deleteRoot, deleteParent, deleteLeaf, keepSibling], deleteLeaf.revisionId);
    sandbox.__state.problemChainDocument = value;
    sandbox.__state.problemChainHistoryHash = hash(value);
    sandbox.__state.problemChainViewRevisionId = deleteLeaf.revisionId;
    parts = [];
    makePart(sandbox.__buildXml(value, hash(value)));
  };
  installDeleteDocument();
  await sandbox.__deleteProblem(deleteLeaf.revisionId);
  assert.equal(confirmations, 0, "a leaf delete must not show confirmation");
  assert.deepEqual(Array.from(sandbox.__state.problemChainDocument.revisions, (item) => item.revisionId),
    [deleteRoot.revisionId, deleteParent.revisionId, keepSibling.revisionId]);

  installDeleteDocument();
  await sandbox.__deleteProblem(deleteParent.revisionId);
  assert.equal(confirmations, 1, "a parent delete must show one confirmation");
  assert.deepEqual(Array.from(sandbox.__state.problemChainDocument.revisions, (item) => item.revisionId),
    [deleteRoot.revisionId, keepSibling.revisionId], "parent delete removes its subtree only");
  assert.equal(sandbox.__state.problemChainDocument.headRevisionId, deleteRoot.revisionId);

  // Root deletion asks confirmation and clears all history/XML
  installDeleteDocument();
  confirmations = 0;
  await sandbox.__deleteProblem(deleteRoot.revisionId);
  assert.equal(confirmations, 1, "root delete must show one confirmation");
  assert.equal(parts.length, 0, "root delete clears customXmlParts");
  assert.equal(sandbox.__state.problemChainDocument, null, "root delete resets problem chain document");
  assert.equal(element("pqpc-clear-history").disabled, true, "clear history button must be disabled when empty");

  // Clear history button verification
  installDeleteDocument();
  sandbox.__renderChain();
  assert.equal(element("pqpc-clear-history").disabled, false, "clear history button enabled when history exists");
  confirmations = 0;
  await sandbox.__clearHistory();
  assert.equal(parts.length, 0, "clear history clears customXmlParts");
  assert.equal(sandbox.__state.problemChainDocument, null, "clear history resets problem chain document");

  // =========================================================================
  // Compact UI Verification: AC-UI-001 through AC-UI-012
  // =========================================================================

  // AC-UI-005: Separate "Xem" button must be completely removed from the timeline
  installDeleteDocument();
  sandbox.__renderChain();
  const allTimelineButtons = element("pqpc-timeline").querySelectorAll("button");
  assert.equal(allTimelineButtons.some((b) => b.textContent.trim() === "Xem"), false,
    "AC-UI-005: separate 'Xem' button must be completely removed from timeline");

  // AC-UI-003: Clicking a non-HEAD revision row directly triggers checkout
  const callsBeforeClick = calls.length;
  const nonHeadRow = element("pqpc-timeline").querySelectorAll(".node-row")
    .find((r) => r.dataset.revisionId !== sandbox.__state.problemChainDocument.headRevisionId);
  assert.ok(nonHeadRow, "a non-HEAD revision node row must exist to test checkout");
  const nonHeadRowBtn = nonHeadRow.querySelector(".node-label");
  assert.ok(nonHeadRowBtn, "node label button must exist");
  const targetRevId = nonHeadRow.dataset.revisionId;
  await nonHeadRowBtn.click();
  const checkoutCall = calls.slice(callsBeforeClick).find((c) => c.endpoint.endsWith("/checkout"));
  assert.ok(checkoutCall, "AC-UI-003: clicking revision row label must invoke checkout API");
  assert.equal(checkoutCall.payload.revisionId, targetRevId, "must checkout the clicked revision");

  // AC-UI-006: Action buttons (branch, edit, delete) stop propagation and do NOT checkout row
  const callsBeforeAction = calls.length;
  const branchActionBtn = element("pqpc-timeline").querySelector(".branch");
  assert.ok(branchActionBtn, "branch action button must exist");
  branchActionBtn.click();
  const checkoutCallsDuringAction = calls.slice(callsBeforeAction).filter((c) => c.endpoint.endsWith("/checkout"));
  assert.equal(checkoutCallsDuringAction.length, 0,
    "AC-UI-006: clicking branch action button must stop propagation and never trigger row checkout");
  assert.equal(element("pqpc-branch-editor").classList.contains("hidden"), false,
    "branch composer must open upon clicking branch button");
  assert.equal(sandbox.__state.problemChainDraftAction.mode, "branch", "branch mode must be active");
  assert.equal(element("pqpc-branch-editor").parentElement, element("pqpc-composer-host"),
    "branch composer must remain in its stable host outside the rerendered timeline");

  // Regression: rerendering the revision tree must not destroy the singleton composer.
  sandbox.__renderChain();
  assert.equal(element("pqpc-branch-editor").parentElement, element("pqpc-composer-host"),
    "timeline rerender must preserve the branch composer");
  sandbox.__openBranch("newRoot");
  assert.equal(element("pqpc-branch-editor").classList.contains("hidden"), false,
    "header new-problem button must open the composer after a timeline rerender");
  assert.equal(sandbox.__state.problemChainDraftAction.mode, "newRoot",
    "header new-problem button must select independent-root mode");
  assert.equal(sandbox.__state.problemChainDraftAction.baseRevisionId, null,
    "new root must not continue from the current HEAD");

  const revisionTwo = sandbox.__state.problemChainDocument.revisions.find((item) => item.parentRevisionId);
  const revisionTwoNode = element("pqpc-timeline").querySelectorAll(".node")
    .find((item) => item.dataset.revisionId === revisionTwo.revisionId);
  assert.ok(revisionTwoNode, "revision 2 must be present in the rendered tree");
  revisionTwoNode.querySelector(".branch").click();
  assert.equal(sandbox.__state.problemChainDraftAction.mode, "branch",
    "revision 2 branch icon must open branch mode");
  assert.equal(sandbox.__state.problemChainDraftAction.baseRevisionId, revisionTwo.revisionId,
    "revision 2 branch must use revision 2 itself as the parent");

  // Multiple independent roots render as separate problem trees with stable labels.
  const archivedRoot = revision("rev_archive000000000000000", null, "Archived root");
  const archivedChain = {...documentWith([archivedRoot], archivedRoot.revisionId),
    chainId: "chain_archive", planId: "plan_archive"};
  sandbox.__state.problemChainDocument.archivedChains = [archivedChain];
  sandbox.__renderChain();
  const rootNodes = element("pqpc-timeline").querySelectorAll(".node")
    .filter((item) => item.dataset.branchDepth === "0");
  assert.equal(rootNodes.length, 2, "two independent chains must render as two root problem cards");
  const rootNames = rootNodes.map((item) => item.querySelector(".node-name")?.textContent || "");
  assert.ok(rootNames.some((name) => name.includes("Vấn đề 1")), "first chain root uses Vấn đề 1 label");
  assert.ok(rootNames.some((name) => name.includes("Vấn đề 2")), "second chain root uses Vấn đề 2 label");

  // AC-UI-004: Accordion sibling collapse - expanding one sibling collapses other siblings at same level
  const rootR = revision("rev_root000000000000000000", null, "Root");
  const sibA = revision("rev_siba000000000000000000", rootR.revisionId, "Sibling A");
  const childA = revision("rev_chda000000000000000000", sibA.revisionId, "Child A");
  const sibB = revision("rev_sibb000000000000000000", rootR.revisionId, "Sibling B");
  const childB = revision("rev_chdb000000000000000000", sibB.revisionId, "Child B");
  const sibDoc = documentWith([rootR, sibA, childA, sibB, childB], childA.revisionId);
  sandbox.__state.problemChainDocument = sibDoc;
  sandbox.__state.problemChainHistoryHash = hash(sibDoc);
  sandbox.__state.expandedRevisionIds.clear();
  sandbox.__renderChain();

  const renderedNodes = element("pqpc-timeline").querySelectorAll(".node");
  const nodeA = renderedNodes.find((n) => n.dataset.revisionId === sibA.revisionId);
  const nodeB = renderedNodes.find((n) => n.dataset.revisionId === sibB.revisionId);
  assert.ok(nodeA && nodeB, "both sibling nodes must be rendered");

  // Path to HEAD (Sibling A) starts auto-expanded, while Sibling B starts collapsed
  assert.equal(nodeA.classList.contains("expanded"), true, "path to HEAD (Sibling A) must be auto-expanded");
  assert.equal(nodeB.classList.contains("collapsed"), true, "Sibling B must start collapsed");
  assert.equal(sandbox.__state.expandedRevisionIds.has(sibA.revisionId), true);

  // Toggle Sibling B open -> Sibling B must expand and Sibling A must collapse
  const toggleB = nodeB.querySelector(".toggle");
  assert.ok(toggleB && !toggleB.disabled, "Sibling B must have active toggle");
  toggleB.click();
  assert.equal(nodeB.classList.contains("expanded"), true, "Sibling B must be expanded");
  assert.equal(nodeA.classList.contains("expanded"), false, "Sibling A must be collapsed when Sibling B opens");
  assert.equal(sandbox.__state.expandedRevisionIds.has(sibB.revisionId), true);
  assert.equal(sandbox.__state.expandedRevisionIds.has(sibA.revisionId), false);

  // AC-UI-010 & AC-UI-011: Step cards accordion (single-open) and compact column representation
  const samplePlan = {
    planId: "plan_test",
    planStatus: "reviewReady",
    summary: "Plan summary test",
    revision: deleteRoot,
    finalOutputStepId: "stp_2",
    questions: ["Clarify input format?"],
    assumptions: ["Assume header in row 1"],
    warnings: ["Large dataset warning"],
    hardBlockers: [],
    steps: [
      {
        stepId: "stp_1", position: 1, variableName: "SourceData",
        actionDescription: "Load and inspect source data",
        operation: {type: "source.workbookTable", parameters: {}},
        inputs: [],
        outputContract: {kind: "table", columns: [{name: "ID", type: "number"}, {name: "Name", type: "text"}, {name: "Amount", type: "currency"}]},
      },
      {
        stepId: "stp_2", position: 2, variableName: "FilteredSales",
        actionDescription: "Filter positive amounts",
        operation: {type: "table.filterRows", parameters: {}},
        inputs: [{ref: "stp_1"}],
        outputContract: {kind: "table", columns: [{name: "ID", type: "number"}, {name: "Amount", type: "currency"}]},
      },
    ],
  };

  sandbox.__originalRenderTypedPlan(samplePlan);
  const stepList = element("pq2-step-list");
  const stepCards = stepList.querySelectorAll(".step");
  assert.equal(stepCards.length, 2, "must render exactly 2 step cards");

  // AC-UI-010: Both cards collapsed initially
  assert.equal(stepCards[0].classList.contains("open"), false, "step 1 must start collapsed");
  assert.equal(stepCards[1].classList.contains("open"), false, "step 2 must start collapsed");

  // AC-UI-011: Collapsed card does NOT contain full columns text (only summary count)
  assert.equal(stepCards[0].querySelector(".step-summary").textContent.includes("3 cột"), true,
    "collapsed card shows column count summary");

  // Click step 1 -> opens step 1
  const mainBtn1 = stepCards[0].querySelector(".step-main");
  assert.ok(mainBtn1, "step 1 main button must exist");
  mainBtn1.click();
  assert.equal(stepCards[0].classList.contains("open"), true, "clicking step 1 opens card 1");
  assert.equal(stepCards[1].classList.contains("open"), false, "step 2 remains collapsed");

  // Structure toggle reveals full column structure
  const structLink = stepCards[0].querySelector(".link-button");
  const structDiv = stepCards[0].querySelector(".step-structure");
  assert.ok(structLink && structDiv, "Xem cấu trúc button and structure container must exist");
  assert.equal(structDiv.hidden, true, "structure is hidden initially");
  structLink.click();
  assert.equal(structDiv.hidden, false, "clicking Xem cấu trúc shows full structure");
  assert.match(structDiv.textContent, /ID.*Name.*Amount/, "structure lists all column names");

  // AC-UI-010: Click step 2 -> opens step 2 and collapses step 1 (single-open accordion)
  const mainBtn2 = stepCards[1].querySelector(".step-main");
  assert.ok(mainBtn2, "step 2 main button must exist");
  mainBtn2.click();
  assert.equal(stepCards[1].classList.contains("open"), true, "clicking step 2 opens card 2");
  assert.equal(stepCards[0].classList.contains("open"), false, "card 1 must automatically collapse when card 2 opens");

  // Overflow menu and run button verification
  const moreBtn = stepCards[1].querySelector(".more");
  const menuPop = stepCards[1].querySelector(".menu-pop");
  assert.ok(moreBtn && menuPop, "overflow menu must exist in step card");
  assert.equal(menuPop.hidden, true, "overflow menu hidden initially");
  moreBtn.click();
  assert.equal(menuPop.hidden, false, "clicking more button opens menu");

  const runBtn = stepCards[1].querySelector(".run-button");
  assert.ok(runBtn, "diagnostic run button must exist");

  // AC-UI-006: Revision metadata/warnings behind info panel with alert indicator
  assert.equal(element("pq2-info-alert").classList.contains("hidden"), false,
    "amber alert dot must be visible when notes/warnings exist");

  // AC-UI-001: All icon-only buttons have accessible Vietnamese labels and titles
  const allIconButtons = [
    ...element("pqpc-timeline").querySelectorAll(".icon-button"),
    ...element("pq2-step-list").querySelectorAll(".icon-button"),
    element("pqpc-history-toggle"),
    element("pqpc-clear-history"),
    element("pqpc-new-problem"),
    element("pq2-revision-info"),
    element("pq2-add-step"),
  ].filter(Boolean);

  for (const btn of allIconButtons) {
    const label = btn.getAttribute("aria-label");
    const title = btn.getAttribute("title") || btn.dataset?.tooltip;
    assert.ok(label && label.trim().length > 0, `icon button must have accessible aria-label: ${btn.className || btn.id}`);
    assert.ok(title && title.trim().length > 0, `icon button must have tooltip/title: ${btn.className || btn.id}`);
  }

  // AC-UI-001 & AC-UI-002: Offline/local SVG policy & No forbidden glyphs/CDN check
  const taskpaneHtml = fs.readFileSync(path.join(__dirname, "../../pbip_assistant/excel_addin/taskpane.html"), "utf8");
  const taskpaneJs = fs.readFileSync(path.join(__dirname, "../../pbip_assistant/excel_addin/taskpane.js"), "utf8");

  // Ensure no external icon CDN references
  assert.equal(/cdn\.(jsdelivr|cloudflare|unpkg)\.com.*(?:lucide|fontawesome|icons)/i.test(taskpaneHtml), false,
    "no external icon CDN in taskpane.html");
  assert.equal(/https?:\/\/[^\s"']+lucide/i.test(taskpaneJs), false,
    "no remote Lucide CDN in taskpane.js");

  // Ensure no wireframe icon glyph spans in taskpane.html
  assert.equal(taskpaneHtml.includes('class="glyph"'), false,
    "taskpane.html must not use wireframe character glyph spans");
  assert.equal(taskpaneHtml.includes("class='glyph'"), false,
    "taskpane.html must not use wireframe character glyph spans");
  assert.equal(taskpaneHtml.includes('id="pqpc-composer-host"'), true,
    "problem composer must have a stable host outside the dynamic timeline");
  assert.equal(taskpaneJs.includes("targetNode.insertBefore(composer"), false,
    "problem composer must never be moved into a revision node that renderProblemChain replaces");
  assert.match(taskpaneJs, /openProblemBranchEditor\(state\.problemChainDocument \? "newRoot" : "new"\)/,
    "header new-problem button must create an independent root when history exists");

  assert.ok(syncs > 0, "test must cross actual Office.js sync boundaries");
  console.log(`taskpane Problem Chain tests passed · ${calls.length} API calls · ${syncs} syncs`);
})().catch((error) => { console.error(error); process.exitCode = 1; });
