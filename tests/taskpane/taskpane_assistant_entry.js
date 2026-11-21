"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
let api;
try { api = require(path.join(__dirname, "../../pbip_assistant/excel_addin/assistant_entry.js")); }
catch (_) { assert.fail("Single assistant entry is unavailable"); }
class Node {
  constructor() { this.hidden = false; this.disabled = false; this.textContent = ""; this.listeners = {}; this.attrs = {}; this.children = []; }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  setAttribute(name, value) { this.attrs[name] = value; }
  replaceChildren(...children) { this.children = children; }
  append(...children) { this.children.push(...children); }
  async click() { if (!this.disabled) await this.listeners.click?.(); }
}
(async () => {
  const nodes = new Map();
  const document = {getElementById: id => { if (!nodes.has(id)) nodes.set(id, new Node()); return nodes.get(id); }, createElement: () => new Node()};
  const get = document.getElementById;
  const calls = [];
  let selection = {cancelled: true}, hasData = false, imported = false, scanned = 0;
  const progress = [];
  const sourceState = {sourceHash: "hash", sources: [{sheetId: "sheet"}], answers: {q1: {choice: "DMY"}}};
  const entry = api.mount({document,
    chooseFolder: async () => { calls.push("picker"); return selection; },
    inventory: async root => { calls.push(root); return {files: [{fileId: "one", fileName: "one.csv", kind: "csv"}, {fileId: "bad", fileName: "bad.csv", kind: "csv"}], sheets: [{fileId: "one", sourceSheetId: "csv", proposedName: "one"}], errors: [{fileId: "bad", code: "AMBIGUOUS_CSV"}]}; },
    selectWorkbook: async () => { calls.push("workbook"); return hasData; },
    showCleaning: () => calls.push("cleaning"),
    importFiles: async request => { assert.deepEqual(request.fileIds, ["one"]); assert.equal(request.mappings.length, 1); request.onProgress({message: "Imported 1/1"}); progress.push(get("assistant-source-message").textContent); imported = true; return {status: "verified"}; },
    scanWorkbook: async request => { scanned++; request.onProgress({message: "Scanning all sheets"}); return sourceState; },
    showProblem: () => calls.push("problem"), invalidateBusiness: () => calls.push("invalidated")});
  entry.updateWorkbook({name: "Book1", hasData: false});
  assert.equal(get("assistant-workbook-summary").textContent, "Book1 · Chưa có dữ liệu");
  assert.equal(get("assistant-source-choice").hidden, false);
  assert.equal(get("preparation-wizard").hidden, true);
  assert.equal(get("flow-source-legacy").hidden, true);
  assert(get("assistant-step-clean").disabled);
  assert(get("assistant-step-problem").disabled);
  await get("assistant-choose-folder").click();
  assert.deepEqual(calls, ["picker"], "cancel cannot submit an empty root");
  selection = {cancelled: false, path: "chosen-root", name: "My data"};
  await get("assistant-choose-folder").click();
  assert.deepEqual(calls, ["picker", "picker", "chosen-root"]);
  assert(get("assistant-step-clean").disabled, "inventory is not a completed import");
  assert.equal(get("preparation-wizard").hidden, true);
  const rowNodes = get("assistant-folder-result").children.flatMap(row => row.children || []);
  assert(rowNodes.some(row => row.disabled && row.type === "checkbox"), "ambiguous file is disabled");
  await get("assistant-select-all").click();
  await get("assistant-import-selected").click();
  assert(imported); assert.equal(scanned, 1); assert.deepEqual(progress, ["Imported 1/1"]);
  assert(get("assistant-step-problem").disabled, "scan is not clean approval");
  entry.cleaningComplete({status: "unverified"});
  assert(get("assistant-step-problem").disabled);
  entry.cleaningComplete({status: "verified"});
  assert.equal(get("assistant-step-problem").disabled, false);
  await get("assistant-step-problem").click();
  assert(calls.includes("problem"));
  const pickersBeforeAppend=calls.filter(value=>value==="picker").length;
  await get("assistant-add-source").click();
  assert.equal(calls.filter(value=>value==="picker").length,pickersBeforeAppend+1,'add source opens folder browser directly');
  assert.equal(get("assistant-source-choice").hidden, false);
  assert.equal(get("assistant-step-problem").disabled, false, "navigation preserves prior approval until actual source changes");
  assert.equal(entry.state().preparation.answers.q1.choice, "DMY");
  hasData = true;
  entry.updateWorkbook({name: "Orders", hasData: true});
  await get("assistant-choose-workbook").click();
  assert.equal(get("assistant-source-choice").hidden, true);
  assert.equal(get("preparation-wizard").hidden, false);
  assert(calls.includes("cleaning"));
  await get("assistant-step-source").click();
  assert.equal(get("assistant-source-choice").hidden, false);
  assert.equal(get("preparation-wizard").hidden, true);
  const failureNodes = new Map();
  const failureDocument = {getElementById: id => { if (!failureNodes.has(id)) failureNodes.set(id, new Node()); return failureNodes.get(id); }, createElement: () => new Node()};
  let finishImport, scansAfterFailure = 0, failureWriteEnabled = true;
  const failureEntry = api.mount({document: failureDocument,
    canImport: () => failureWriteEnabled,
    chooseFolder: async () => ({path: "synthetic", name: "Synthetic"}),
    inventory: async () => ({files: [{fileId: "x", fileName: "x.xlsx", kind: "xlsx"}], sheets: [{fileId: "x", sourceSheetId: "a", proposedName: "A"}, {fileId: "x", sourceSheetId: "b", proposedName: "B"}], errors: []}),
    importFiles: request => { assert.equal(request.mappings.length, 2, "XLSX selected as complete group"); return new Promise(resolve => { finishImport = resolve; }); },
    scanWorkbook: async () => { scansAfterFailure++; return sourceState; }, showCleaning: () => {}});
  await failureDocument.getElementById("assistant-choose-folder").click();
  await failureDocument.getElementById("assistant-select-all").click();
  const importing = failureDocument.getElementById("assistant-import-selected").click();
  assert(failureDocument.getElementById("assistant-step-source").disabled, "navigation is disabled during import");
  assert(failureDocument.getElementById("assistant-choose-folder").disabled);
  failureWriteEnabled = false;
  finishImport({status: "partial_unknown"}); await importing;
  assert.equal(scansAfterFailure, 0, "partial import cannot trigger scan or business");
  assert(failureEntry.state().blocked);
  assert(failureDocument.getElementById("assistant-import-selected").disabled, "partial mutation cannot be replayed");
  assert(failureDocument.getElementById("assistant-source-message").textContent.includes("phục hồi"));
  assert.equal(failureDocument.getElementById("assistant-import-message").textContent,
    failureDocument.getElementById("assistant-source-message").textContent,
    "import errors must also be visible beside the import action after a long file list");
  const dateNodes = new Map();
  const dateDocument = {getElementById: id => { if (!dateNodes.has(id)) dateNodes.set(id, new Node()); return dateNodes.get(id); }, createElement: () => new Node()};
  let dateRecovery = false;
  api.mount({document: dateDocument, chooseFolder: async () => ({path: "synthetic", name: "Synthetic"}),
    inventory: async () => ({files: [{fileId: "x", fileName: "x.csv"}], sheets: [{fileId: "x", sourceSheetId: "csv"}], errors: []}),
    importFiles: async () => ({status: "verified"}),
    scanWorkbook: async () => { throw new Error("Confirm date system 1900 or 1904"); },
    showCleaning: options => { dateRecovery = options.scanRequired; }});
  await dateDocument.getElementById("assistant-choose-folder").click();
  await dateDocument.getElementById("assistant-select-all").click();
  await dateDocument.getElementById("assistant-import-selected").click();
  assert(dateRecovery, "verified import opens scan/date recovery without importing again");
  assert.equal(dateDocument.getElementById("preparation-wizard").hidden, false);
  assert(dateDocument.getElementById("assistant-step-problem").disabled);
  // A delayed failed handoff cannot reveal problem UI or retain old business authority.
  const delayedNodes = new Map();
  const delayedDocument = {getElementById:id=>{if(!delayedNodes.has(id))delayedNodes.set(id,new Node());return delayedNodes.get(id);},createElement:()=>new Node()};
  let rejectHandoff, authority=true, controllerState=null;
  const cleaningCalls=[];
  const delayed=api.mount({document:delayedDocument,selectWorkbook:async()=>true,scanWorkbook:async()=>sourceState,showCleaning:options=>{cleaningCalls.push(options);if(options?.state)controllerState=options.state;},
    invalidateBusiness:()=>{authority=false;},showProblem:()=>new Promise((_,reject)=>{rejectHandoff=reject;})});
  await delayedDocument.getElementById('assistant-choose-workbook').click();
  controllerState={...sourceState,answerRevision:2,answers:{q1:{choice:'MDY'}},preview:{reviewHash:'new-preview'}};
  delayed.cleaningComplete({status:'noop_verified'}); authority=true;
  const opening=delayedDocument.getElementById('assistant-step-problem').click();
  assert.equal(authority,false,'old snapshot/approval invalidated before async handoff');
  assert.equal(delayed.state().step,'clean','problem remains hidden while handoff pending');
  rejectHandoff(new Error('source changed')); await opening;
  assert.equal(delayed.state().step,'clean'); assert.equal(delayed.state().canProblem,false);
  assert.equal(cleaningCalls.at(-1)?.state,undefined,'failed handoff reopens current cleaning controller without a stale scan state');
  assert.equal(controllerState.answerRevision,2,'current controller answer revision retained');
  assert.equal(controllerState.answers.q1.choice,'MDY','answers changed after scan survive failed handoff');
  assert.equal(controllerState.preview.reviewHash,'new-preview','current preview retained');
  const blockedNodes=new Map();
  const blockedDocument={getElementById:id=>{if(!blockedNodes.has(id))blockedNodes.set(id,new Node());return blockedNodes.get(id);},createElement:()=>new Node()};
  let importAttempts=0;
  api.mount({document:blockedDocument,chooseFolder:async()=>({path:'synthetic'}),inventory:async()=>({files:[{fileId:'f',fileName:'data.csv'}],sheets:[{fileId:'f'}]}),
    canImport:()=>false,importBlocker:()=>"Native preservation qualification is pending",importFiles:async()=>{importAttempts++;}});
  await blockedDocument.getElementById('assistant-choose-folder').click();
  await blockedDocument.getElementById('assistant-select-all').click();
  assert(blockedDocument.getElementById('assistant-import-selected').disabled,'unqualified native import visibly disabled before click');
  assert(blockedDocument.getElementById('assistant-source-message').textContent.includes('qualification'));
  await blockedDocument.getElementById('assistant-import-selected').click();assert.equal(importAttempts,0);
  const resetNodes=new Map(),resetDocument={getElementById:id=>{if(!resetNodes.has(id))resetNodes.set(id,new Node());return resetNodes.get(id);},createElement:()=>new Node()};
  let restarted=0;
  api.mount({document:resetDocument,chooseFolder:async()=>({path:'chosen'}),inventory:async()=>{throw Object.assign(new Error('expired'),{code:'DP_POINT_EXPIRED'});},
    restartSession:async()=>{restarted++;}});
  assert(resetDocument.getElementById('assistant-new-session').hidden);
  await resetDocument.getElementById('assistant-choose-folder').click();
  assert.equal(resetDocument.getElementById('assistant-new-session').hidden,false);
  await resetDocument.getElementById('assistant-new-session').click();
  assert.equal(restarted,1);assert(resetDocument.getElementById('assistant-new-session').hidden);
  const directNodes=new Map(),directDocument={getElementById:id=>{if(!directNodes.has(id))directNodes.set(id,new Node());return directNodes.get(id);},createElement:()=>new Node()};
  let directRestarts=0;
  const directEntry=api.mount({document:directDocument,chooseFolder:async()=>null,inventory:async()=>null,
    canRestartAfterPartial:true,restartSession:async()=>{directRestarts++;}});
  directEntry.cleaningComplete({status:'partial_unknown'});
  assert.equal(directDocument.getElementById('assistant-new-session').hidden,false,'uncertain cleanup exposes explicit re-read recovery');
  assert.equal(directDocument.getElementById('assistant-new-session').disabled,false);
  await directDocument.getElementById('assistant-new-session').click();
  assert.equal(directRestarts,1);
  assert.equal(directEntry.state().blocked,false);
  directEntry.cleaningComplete({status:'failed',code:'DP_SOURCE_STALE'});
  assert.equal(directDocument.getElementById('assistant-new-session').hidden,false,'stale cleanup can establish a fresh reviewed attachment');
  const html = fs.readFileSync(path.join(__dirname, "../../pbip_assistant/excel_addin/taskpane.html"), "utf8");
  assert(html.includes('id="flow-source-legacy" hidden'));
  assert(html.includes("Bạn muốn lấy dữ liệu từ đâu?"));
  console.log("Assistant single entry guards passed");
})().catch(error => { console.error(error); process.exitCode = 1; });
