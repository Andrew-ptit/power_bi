"use strict";
const assert = require("node:assert/strict");
const path = require("node:path");
const fs = require("node:fs");
let api;
try { api = require(path.join(__dirname, "../../pbip_assistant/excel_addin/preparation_controller.js")); }
catch (_) { assert.fail("Preparation wizard is unavailable"); }
(async () => {
  const html = fs.readFileSync(path.join(__dirname, "../../pbip_assistant/excel_addin/taskpane.html"), "utf8");
  assert(html.includes("Chuẩn bị dữ liệu · quét và xem trước"), "wizard Vietnamese labels are preserved in UTF-8");
  const calls = [];
  const initial = {preparationId: "prep", claimVersion: 1, sourceHash: "hash", sourceRevision: 2,
    answerRevision: 3, answers: {}, questions: [{questionId: "q1", group: "formats", choices: ["DMY", "keep_text"]}],
    findings: [], sources: [{sourceId: "source", sheetId: "sheet", fingerprint: "hash"}], preview: null, writeEnabled: false};
  const wizard = new api.Wizard(async (action, body) => {
    calls.push({action, body});
    if (action === "answer") return {...initial, answerRevision: 4, answers: {q1: body.answer}};
    if (action === "preview") return {...wizard.state, preview: {changeCount: 1, examples: []}};
    return initial;
  });
  wizard.accept(initial);
  wizard.go(1);
  await assert.rejects(wizard.preview(), /trả lời/);
  await wizard.answer("q1", "DMY");
  assert.equal(calls[0].body.expectedAnswerRevision, 3);
  await wizard.preview();
  assert.equal(calls[1].body.answerRevision, 4);
  assert.equal(wizard.step, 3);
  wizard.go(1);
  assert.equal(wizard.state.answers.q1.choice, "DMY");
  await wizard.answer("q1", "keep_text");
  assert.equal(wizard.state.preview, null);
  assert(calls.every(c => !["apply", "approve", "undo", "redo"].includes(c.action)));
  let resolve;
  const pending = new api.Wizard(() => new Promise(r => { resolve = r; }));
  pending.accept(initial);
  const request = pending.answer("q1", "DMY");
  pending.accept({...initial, sourceRevision: 9, answers: {}, preview: null});
  resolve({...initial, answerRevision: 4, answers: {q1: {choice: "DMY"}}});
  await request;
  assert.equal(pending.state.sourceRevision, 9, "old response cannot replace current source");
  // Exercise the mounted UI with untrusted header text and real navigation.
  class Element {
    constructor(tag) { this.tag = tag; this.children = []; this.listeners = {}; this.attributes = {}; this.textContent = ""; this.disabled = false; }
    append(...children) { this.children.push(...children); }
    replaceChildren(...children) { this.children = children; }
    setAttribute(key, value) { this.attributes[key] = value; }
    addEventListener(event, callback) { this.listeners[event] = callback; }
    set innerHTML(_) { throw new Error("User data must use textContent"); }
    async click() { if (!this.disabled) await this.listeners.click?.(); await new Promise(r => setImmediate(r)); }
  }
  const ids = {};
  for (const id of ["preparation-wizard", "preparation-message", "preparation-panel", "preparation-date-system",
                    "preparation-scan", "preparation-inventory", "flow-root-input", "flow-path-input"]) ids[id] = new Element("div");
  ids["preparation-date-system"].value = "1900";
  ids["flow-root-input"].value = "synthetic-root";
  ids["flow-path-input"].value = ".";
  const rendered = () => {
    const all = [];
    function visit(element) { all.push(element); element.children.forEach(visit); }
    visit(ids["preparation-panel"]); return all;
  };
  const namedButton = text => rendered().find(el => el.tag === "button" && el.textContent === text);
  const mountedCalls = [];
  let mountedState = {...initial, questions: [{...initial.questions[0], label: "<img src=x onerror=alert(1)>"}],
    findings: [{sourceId: "source", sheetId: "sheet", column: 1, columnLabel: "Delivery date", kind: "missing", count: 1,
      examples: [{row: 5, address: "D12", value: null}]}]};
  const mounted = api.mount({document: {getElementById: id => ids[id], createElement: tag => new Element(tag)},
    environment: {crypto: require("node:crypto").webcrypto},
    runtime: {describeWorkbook: async () => ({workbookName: "Synthetic", sheetId: "sheet"}),
      readSelection: async () => ({workbookName: "Synthetic", snapshot: {sheetId: "sheet"}})},
    post: async (action, body) => {
      mountedCalls.push(action);
      if (action === "inventory") return {...mountedState, inventory: {files: [], sheets: [], errors: []}};
      if (action === "answer") mountedState = {...mountedState, answerRevision: 4, answers: {q1: body.answer}, preview: null};
      if (action === "preview") mountedState = {...mountedState, preview: {changeCount: 1, examples: [{address: "D7", before: "03/04/2026", after: 46115}]}};
      return mountedState;
    }});
  await ids["preparation-inventory"].click();
  assert.deepEqual(mountedCalls, ["attach", "inventory"], "empty workbook inventory does not read a cell region");
  await ids["preparation-scan"].click();
  assert(rendered().some(el => el.textContent.includes("<img src=x onerror=alert(1)>")));
  await namedButton("Ngày / tháng / năm").click();
  await namedButton("3 · Ngoại lệ").click();
  assert(rendered().some(el => el.textContent.includes("Delivery date")), "finding identifies the affected column");
  assert(rendered().some(el => el.textContent.includes("D12")), "finding locates the affected cell");
  await namedButton("Tạo bản xem trước").click();
  assert.equal(mounted.wizard.step, 3);
  assert(rendered().some(el => el.textContent.includes("D7:")));
  assert(namedButton("Áp dụng").disabled);
  await namedButton("← Quay lại").click();
  assert.equal(mounted.wizard.state.answers.q1.choice, "DMY");
  let applied = null, dirty = 0;
  const writable = api.mount({document: {getElementById: id => ids[id], createElement: tag => new Element(tag)},
    environment: {}, runtime: {}, deferOpen: true,
    post: async () => mountedState,
    scanWorkbook: async request => { assert.equal(request.append, true); request.onProgress({message: "Sheet 2/2"}); return {...mountedState, writeEnabled: true}; },
    applyCleanup: async request => { assert.equal(request.state.preview.changeCount, 1); return {status: "verified"}; },
    onApplied: receipt => { applied = receipt; }, onDirty: () => { dirty++; }});
  await writable.scanWorkbook();
  assert.equal(writable.wizard.step, 1);
  writable.show({fresh: true});
  assert.equal(writable.wizard.state.answers.q1.choice, "DMY", "returning to cleaning retains prior answers");
  writable.wizard.go(3); writable.show();
  assert.equal(namedButton("Áp dụng").disabled, false);
  await namedButton("Áp dụng").click();
  assert.equal(applied.status, "verified");
  assert(dirty > 0);
  const restoreCalls = [];
  let approvals = 0, restoredDirty = 0;
  const ready = {...mountedState, writeEnabled: true, journal: {status: "ready", undoCount: 1, redoCount: 0}};
  const journalUI = api.mount({document: {getElementById: id => ids[id], createElement: tag => new Element(tag)},
    environment: {}, runtime: {}, deferOpen: true, post: async () => ready,
    scanWorkbook: async () => ({state: ready, sourceLabels: {source: "Orders"}, warnings: [{sheetName: "Empty", code: "EMPTY_SHEET"}], dateSystem: "1904"}),
    applyCleanup: async ({state}) => { assert.equal(state.preview.changeCount, 0); return {status: "noop_verified"}; },
    undo: async () => { restoreCalls.push("undo"); return {status: "verified", state: {...ready, preview: null, journal: {status: "ready", undoCount: 0, redoCount: 1}}}; },
    redo: async () => { restoreCalls.push("redo"); return {status: "verified", state: ready}; },
    onApplied: () => { approvals++; }, onDirty: () => { restoredDirty++; }});
  await journalUI.scanWorkbook();
  assert.equal(ids["preparation-date-system"].value, "1904");
  assert(rendered().some(el => el.textContent.includes("Empty") && el.textContent.includes("EMPTY_SHEET")), "skipped sheets remain explicit");
  journalUI.wizard.go(2); journalUI.show();
  assert(rendered().some(el => el.textContent.includes("Orders") && el.textContent.includes("Delivery date")));
  journalUI.wizard.go(3); journalUI.acceptState(ready);
  assert.equal(journalUI.wizard.step, 3, "state synchronization keeps review open");
  const beforeRestoreDirty = restoredDirty;
  assert.equal(namedButton("↶ Khôi phục").disabled, false);
  assert.equal(namedButton("↷ Làm lại").disabled, true);
  await namedButton("↶ Khôi phục").click();
  assert.equal(journalUI.wizard.state.preview, null);
  assert.equal(restoredDirty, beforeRestoreDirty + 1);
  assert.equal(approvals, 0, "restore never grants business approval");
  await namedButton("↷ Làm lại").click();
  assert.deepEqual(restoreCalls, ["undo", "redo"]);
  await namedButton("← Quay lại").click();
  assert.deepEqual(restoreCalls, ["undo", "redo"], "Back navigation does not restore");
  journalUI.wizard.go(3);
  journalUI.acceptState({...ready, writeEnabled: false, preview: {changeCount: 0, examples: []}});
  assert.equal(namedButton("Dùng dữ liệu này").disabled, false, "zero-change review requires no write capability");
  await namedButton("Dùng dữ liệu này").click();
  assert.equal(approvals, 1);
  assert.equal(namedButton("↶ Khôi phục").disabled, true, "restore still requires write capability");
  let failedRestoreApprovals = 0;
  const failedRestore = api.mount({document: {getElementById: id => ids[id], createElement: tag => new Element(tag)},
    environment: {}, runtime: {}, post: async () => ready,
    undo: async () => ({status: "partial_unknown"}), onApplied: () => { failedRestoreApprovals++; }});
  failedRestore.acceptState(ready);
  await namedButton("↶ Khôi phục").click();
  assert.equal(failedRestoreApprovals, 0, "failed restore also never calls cleanup approval callback");
  assert(namedButton("↶ Khôi phục").disabled, "unknown restore cannot be replayed");
  const directUI = api.mount({document: {getElementById: id => ids[id], createElement: tag => new Element(tag)},
    environment: {}, runtime: {}, post: async () => ready,
    applyCleanup: async () => { throw Object.assign(new Error("Read-back interrupted"), {code: "DP_PARTIAL_UNKNOWN"}); }});
  const directState = {...ready, backupEnabled: false, preparationId: "direct-original", preview: {changeCount: 1, examples: []}};
  directUI.acceptState(directState);
  assert.equal(namedButton("↶ Khôi phục"), undefined, "no-backup mode removes recovery controls");
  assert.equal(namedButton("↷ Làm lại"), undefined, "no-backup mode removes redo controls");
  directUI.wizard.go(3); directUI.show();
  await namedButton("Áp dụng").click();
  assert(ids["preparation-scan"].disabled, "unknown write blocks the current cleaning session");
  directUI.acceptState(directState);
  assert(ids["preparation-scan"].disabled, "ordinary refresh cannot clear unknown write");
  directUI.acceptState({...directState, preparationId: "direct-fresh", preview: null});
  assert.equal(ids["preparation-scan"].disabled, false, "explicit fresh session can scan again");
  assert.equal(ids["preparation-date-system"].disabled, false);
  console.log("Preparation wizard revision and navigation guards passed");
})().catch(error => { console.error(error); process.exitCode = 1; });
