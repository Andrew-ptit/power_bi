/* Developer-only autorun: real DOM handlers, Office.js and Excel runtime.
 * Loaded only by tools/live_excel_gate.py into a disposable marked workbook.
 */
(async function liveExcelGate() {
  "use strict";
  const config = window.__LIVE_EXCEL_GATE__;
  if (!config) return;
  const rawFetch = window.fetch.bind(window);
  const requests = [];
  let currentStage = "initialization";
  const banner = document.createElement("div");
  banner.id = "live-gate-status";
  banner.style.cssText = "position:sticky;top:0;z-index:99999;padding:12px;background:#123;color:white;font:14px sans-serif;overflow-wrap:anywhere;max-width:100%;box-sizing:border-box";
  document.body.prepend(banner);
  const gateUrl = (route) => `${config.baseUrl}/__gate/${route}?gateKey=${encodeURIComponent(config.gateKey)}`;
  async function event(metrics) {
    banner.textContent = `${config.runId}: ${currentStage} / ${metrics.status || metrics.event}`;
    await rawFetch(gateUrl("events"), {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({stage:currentStage,...metrics})});
  }
  window.fetch = async (...args) => {
    const started = performance.now();
    const response = await rawFetch(...args);
    const path = new URL(typeof args[0] === "string" ? args[0] : args[0].url, location.href).pathname;
    if (path.startsWith("/api/")) {
      let body = {};
      try { body = await response.clone().json(); } catch {}
      const record = {path,status:response.status,elapsedMs:performance.now()-started,code:body.error?.code || body.code || null};
      requests.push(record);
      await event({event:"http",...record});
    }
    return response;
  };
  const delay = (ms) => new Promise(resolve => setTimeout(resolve,ms));
  function assert(condition, code) { if (!condition) { const error = new Error(code); error.code=code; throw error; } }
  async function wait(predicate, code, timeout=120000) {
    const start = performance.now();
    while (!predicate()) { if (performance.now()-start>timeout) throw Object.assign(new Error(code),{code}); await delay(100); }
  }
  function click(id) {
    const target = document.getElementById(id);
    assert(target && !target.disabled && target.getClientRects().length > 0,"CONTROL_UNAVAILABLE_"+id);
    target.click();
  }
  function input(id,value) { const target=document.getElementById(id); target.value=value; target.dispatchEvent(new Event("input",{bubbles:true})); }
  async function snapshot() { return (await (await rawFetch(gateUrl("control"),{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({action:"snapshot"})})).json()).state; }
  async function stage(name,work) {
    currentStage=name; const start=performance.now(); await event({event:"stage",status:"started"});
    const metrics=await work(); await event({event:"stage",status:"pass",elapsedMs:performance.now()-start,...metrics});
  }
  async function digest(value) { const bytes=await crypto.subtle.digest("SHA-256",new TextEncoder().encode(JSON.stringify(value))); return "sha256:"+Array.from(new Uint8Array(bytes),x=>x.toString(16).padStart(2,"0")).join(""); }
  async function sourceData() {
    return Excel.run(async ctx=>{
      const sales=ctx.workbook.worksheets.getItem("Sales");
      const dim=ctx.workbook.worksheets.getItem("Dim_Commission");
      const range=sales.getRange("A1:I7"), sentinel=sales.getRange("L1"), other=dim.getUsedRange();
      const table=ctx.workbook.tables.getItem("SalesTable").getRange();
      range.load("values");sentinel.load("values");other.load("values");table.load("address,rowCount,columnCount");
      await ctx.sync();
      return {values:range.values,sentinel:sentinel.values,other:other.values,address:table.address,rows:table.rowCount,columns:table.columnCount};
    });
  }
  async function sourceFingerprint() { return digest(await sourceData()); }
  async function resultData(name=state.pqResultSheetName) {
    if (!name) return null;
    return Excel.run(async ctx=>{ const range=ctx.workbook.worksheets.getItem(name).getUsedRange();range.load("values,rowCount,columnCount");await ctx.sync();return {values:range.values,rows:range.rowCount-1,columns:range.columnCount}; });
  }
  const revisions=()=>problemChainDocuments().flatMap(chain=>chain.revisions || []);
  const head=()=>state.problemChainDocument?.headRevisionId;
  function assertTypedValues(result,child=false) {
    const headers=result.values[0],id=headers.indexOf("SaleID"),profit=headers.indexOf("Profit");
    const expectedIds=child?["S-005","S-003"]:["S-005","S-003","S-002","S-006"];
    const expectedProfit=child?[2800,2100]:[2800,2100,1400,1300];
    assert(id>=0 && profit>=0 && JSON.stringify(result.values.slice(1).map(row=>row[id]))===JSON.stringify(expectedIds)
      && JSON.stringify(result.values.slice(1).map(row=>row[profit]))===JSON.stringify(expectedProfit),"RESULT_VALUE_ORACLE_FAILED");
  }
  async function readVisible() {
    let rendered=false;
    const observer=new MutationObserver(()=>{rendered=true;});
    observer.observe(document.getElementById("pqpc-status"),{childList:true,subtree:true});
    try {
      click("tab-assistant-button");click("refresh-button");
      await wait(()=>rendered && !state.busy && state.problemChainHydrated
        && (!head() || state.pqTypedPlan?.revision?.revisionId===head()),"REFRESH_HYDRATE_FAILED");
      click("tab-pq-button");
    } finally {observer.disconnect();}
  }
  async function activate(sheet) { await Excel.run(async ctx=>{ctx.workbook.worksheets.getItem(sheet).activate();ctx.workbook.worksheets.getItem(sheet).getRange("A1").select();await ctx.sync();});await readVisible(); }
  async function previewTyped() { const previous=state.pqTypedPreview?.previewId;click("pq2-preview-button");await wait(()=>!state.busy && state.pqTypedPreview?.previewId && state.pqTypedPreview.previewId!==previous,"TYPED_PREVIEW_FAILED"); }
  async function confirmTyped() { click("pq2-approve-button");await wait(()=>!state.busy && document.getElementById("pq2-result-badge").textContent.includes("ĐÃ XÁC NHẬN"),"TYPED_CONFIRM_FAILED"); }
  async function checkout(id) {
    assert(head()!==id,"CHECKOUT_ALREADY_HEAD");
    const target=document.querySelector(`li.node[data-revision-id="${id}"] .node-label`);
    assert(target && target.getClientRects().length,"CHECKOUT_CONTROL_UNAVAILABLE");target.click();
    await wait(()=>!state.busy && head()===id,"CHECKOUT_FAILED");
  }
  async function saveExport(name) { const response=await rawFetch(gateUrl("artifact"),{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({name,workbookBase64:await exportWorkbookBase64()})});assert(response.ok,"ARTIFACT_EXPORT_FAILED"); }
  async function advancedPreview(code,{cancel=false}={}) {
    input("pq-code",code); const previous=state.pqPreview?.previewId;
    click("pq-preview-button");
    await wait(()=>!document.getElementById("pq-confirm-overlay").classList.contains("hidden") || state.busy,"ADVANCED_CONFIRM_NOT_SHOWN");
    if (!document.getElementById("pq-confirm-overlay").classList.contains("hidden")) {
      click(cancel ? "pq-confirm-cancel":"pq-confirm-continue");
      if(cancel) { await delay(200);return; }
    }
    await wait(()=>!state.busy && state.pqPreview && state.pqPreview.previewId!==previous,"ADVANCED_PREVIEW_FAILED");
  }
  async function advancedApply() {
    click("pq-apply-source-button");await wait(()=>!document.getElementById("pq-confirm-overlay").classList.contains("hidden"),"APPLY_CONFIRM_NOT_SHOWN");
    click("pq-confirm-continue");await wait(()=>!state.busy && (!state.pqPreview || state.pqPreview.applied===true),"ADVANCED_APPLY_TIMEOUT");
  }
  try {
    await wait(()=>typeof state!=="undefined" && state.officeReady && state.problemChainHydrated && !state.busy,"OFFICE_BOOTSTRAP_FAILED");
    await Excel.run(async ctx=>{const marker=ctx.workbook.names.getItem(config.markerName);marker.load("value");await ctx.sync();assert(String(marker.value).replace(/^=|"/g,"")===config.runId,"DISPOSABLE_WORKBOOK_GUARD");});
    assert(revisions().length===0,"FIXTURE_HISTORY_NOT_EMPTY");
    // All fixture setup precedes the first cache fingerprint. Never touches an unmarked workbook.
    await Excel.run(async ctx=>{ctx.workbook.worksheets.getItem("Sales").getRange("L1").values=[["KEEP_OUTSIDE"]];const sheet=ctx.workbook.worksheets.add("GateUsedRange");sheet.getRange("A1:B5").values=[["Key","Value"],[1,10],[2,20],[3,30],[4,40]];ctx.workbook.worksheets.getItem("Sales").activate();await ctx.sync();});
    await readVisible();click("pq2-mode-button");
    if (!state.problemChainHistoryExpanded) click("pqpc-history-toggle");
    const initialSourceData=await sourceData();
    const initialSource=await digest(initialSourceData);
    let root,child,rootImmutable;
    await stage("typed_root_commit_preview_confirm",async()=>{
      click("pqpc-new-problem");input("pqpc-branch-prompt","Gate root: filter SalesTable Gross Revenue above 1000, add Profit, sort descending.");click("pqpc-branch-submit");
      await wait(()=>!state.busy && revisions().length===1 && state.pqTypedPlan?.planStatus==="reviewReady","ROOT_COMMIT_FAILED");
      root=head();rootImmutable=JSON.stringify(revisions()[0]);
      await saveExport("before-result");
      const before=await snapshot();await previewTyped();const staged=await snapshot();
      assert(!state.pqResultSheetName && staged.cachedResultsCount===before.cachedResultsCount,"STAGING_WROTE_RESULT_OR_CACHE");
      await confirmTyped();const result=await resultData();const after=await snapshot();
      assert(result.rows===4 && result.columns===10 && after.cachedResultsCount===1,"ROOT_RESULT_OR_CACHE_WRONG");
      assertTypedValues(result);
      assert(await sourceFingerprint()===initialSource,"ROOT_CHANGED_SOURCE");
      await saveExport("after-result");
      return {headRevisionId:root,revisionCount:revisions().length,resultRows:result.rows,resultColumns:result.columns,sourceFingerprint:initialSource,...after};
    });
    await stage("typed_child_commit_preview_confirm",async()=>{
      const branch=document.querySelector(`li.node[data-revision-id="${root}"] .node-actions button.branch`);assert(branch,"BRANCH_CONTROL_MISSING");branch.click();
      input("pqpc-branch-prompt","Gate child: keep Gross Revenue above 2000.");click("pqpc-branch-submit");
      await wait(()=>!state.busy && revisions().length===2 && head()!==root,"CHILD_COMMIT_FAILED");child=head();
      assert(JSON.stringify(revisions().find(rev=>rev.revisionId===root))===rootImmutable,"ROOT_REVISION_MUTATED");
      await previewTyped();await confirmTyped();const result=await resultData();
      assert(result.rows===2 && result.columns===10,"CHILD_RESULT_WRONG");
      assertTypedValues(result,true);
      assert(await sourceFingerprint()===initialSource,"CHILD_CHANGED_SOURCE");
      return {headRevisionId:child,revisionCount:2,resultRows:result.rows,resultColumns:result.columns,...await snapshot()};
    });
    await stage("cache_checkout_hit",async()=>{
      const before=await snapshot();await checkout(root);
      const after=await snapshot();const badge=document.getElementById("pq2-result-badge").textContent;
      const result=await resultData();
      assert(after.runtimeCalls===before.runtimeCalls && badge==="ĐÃ GHI TỪ CACHE","CACHE_FALSE_STALE");
      assert(result.rows===4 && result.columns===10,"CACHED_ROOT_RESULT_WRONG");
      assertTypedValues(result);
      assert(await sourceFingerprint()===initialSource,"CACHE_CHANGED_SOURCE");
      return {headRevisionId:head(),resultRows:result.rows,resultColumns:result.columns,runtimeCallsBefore:before.runtimeCalls,runtimeCallsAfter:after.runtimeCalls,...after};
    });
    await stage("cache_stale_fallback_cancel_recovery",async()=>{
      await checkout(child);const oldResult=await digest(await resultData());const before=await snapshot();let old;
      await Excel.run(async ctx=>{const r=ctx.workbook.worksheets.getItem("Sales").getRange("E2");r.load("values");await ctx.sync();old=r.values[0][0];r.values=[[Number(old)+1]];await ctx.sync();});
      const requestStart=requests.length;await checkout(root);await wait(()=>!state.busy && state.pqTypedPreview,"STALE_FALLBACK_PREVIEW_FAILED");
      const after=await snapshot();assert(requests.slice(requestStart).some(r=>r.code==="PQPC_RESULT_CACHE_STALE"),"STALE_CACHE_NOT_REJECTED");
      assert(after.runtimeCalls===before.runtimeCalls+1,"STALE_FALLBACK_RUNTIME_COUNT");
      assert(await digest(await resultData())===oldResult,"STALE_FALLBACK_WROTE_RESULT");
      click("pq2-cancel-preview-button");await wait(()=>!state.busy && !state.pqTypedPreview,"STAGING_CANCEL_FAILED");
      assert((await snapshot()).cachedResultsCount===before.cachedResultsCount && await digest(await resultData())===oldResult,"CANCEL_CHANGED_RESULT_CACHE");
      await Excel.run(async ctx=>{ctx.workbook.worksheets.getItem("Sales").getRange("E2").values=[[old]];await ctx.sync();});
      await previewTyped();await confirmTyped();assert(await sourceFingerprint()===initialSource,"STALE_RECOVERY_CHANGED_SOURCE");
      return {...await snapshot(),sourceFingerprint:initialSource};
    });
    await stage("session_expiry_explicit_recovery",async()=>{
      const oldSession=state.sessionId,oldHead=head(),oldHash=state.problemChainHistoryHash,oldResult=await digest(await resultData());
      await rawFetch(gateUrl("control"),{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({action:"expireSession"})});
      const start=requests.length;click("pq2-preview-button");
      await wait(()=>!state.busy && state.sessionId!==oldSession && !state.problemChainHydrated,"EXPIRED_SESSION_NOT_RESET");
      const attempted=requests.slice(start).filter(r=>r.path==="/api/pq/v2/previews");
      assert(attempted.length===1 && attempted[0].status===401 && attempted[0].code==="TOKEN_EXPIRED","EXPIRED_REQUEST_REPLAY_OR_CODE");
      assert(!state.pqTypedPreview && !state.pqTypedApproval && await digest(await resultData())===oldResult,"EXPIRY_REUSED_APPROVAL_OR_WROTE");
      await readVisible();assert(head()===oldHead && state.problemChainHistoryHash===oldHash && revisions().length===2,"EXPIRY_HISTORY_CHANGED");
      assert((await snapshot()).cachedResultsCount===0,"EXPIRY_RETAINED_SERVER_CACHE");
      await previewTyped();await confirmTyped();assert(await sourceFingerprint()===initialSource,"EXPIRY_RECOVERY_CHANGED_SOURCE");
      return {headRevisionId:head(),historyHash:state.problemChainHistoryHash,...await snapshot()};
    });
    await stage("completion_failure_explicit_recovery",async()=>{
      const before=await snapshot(),oldHead=head(),oldHash=state.problemChainHistoryHash;
      await previewTyped();
      const armed=await rawFetch(gateUrl("control"),{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({action:"failNextCompletion"})});
      assert(armed.ok,"FAULT_INJECTION_NOT_ARMED");
      const start=requests.length;click("pq2-approve-button");
      await wait(()=>!state.busy && !state.pqTypedPreview && !state.pqTypedApproval
        && !document.getElementById("error-panel").classList.contains("hidden"),"COMPLETION_FAILURE_NOT_REVOKED");
      const completes=requests.slice(start).filter(r=>r.path==="/api/pq/v2/applies/complete");
      assert(completes.length===1 && completes[0].code==="GATE_COMPLETION_UNAVAILABLE","COMPLETION_REQUEST_REPLAY_OR_CODE");
      assert(document.getElementById("pq2-progress").textContent.includes("read-back chưa hoàn tất"),"COMPLETION_FAILURE_UNKNOWN_STATE_MISSING");
      assert((await snapshot()).cachedResultsCount===before.cachedResultsCount && head()===oldHead && state.problemChainHistoryHash===oldHash,"COMPLETION_FAILURE_PROMOTED_OR_CHANGED_HISTORY");
      assert(await sourceFingerprint()===initialSource,"COMPLETION_FAILURE_CHANGED_SOURCE");
      assertTypedValues(await resultData());
      await previewTyped();await confirmTyped();assertTypedValues(await resultData());
      return {headRevisionId:head(),historyHash:state.problemChainHistoryHash,sourceFingerprint:initialSource,faultInjected:true,...await snapshot()};
    });
    if (config.driverParameters?.includeAdvancedM !== true) {
      currentStage="complete";
      await event({event:"complete",status:"pass",advancedMDeferred:true,revisionCount:revisions().length,...await snapshot()});
      return;
    }
    await activate("Sales");click("pq-advanced-mode-button");
    const expandCode='let Source=Excel.CurrentWorkbook(){[Name="SalesTable"]}[Content], A=Table.AddColumn(Source,"GateA",each 1), B=Table.AddColumn(A,"GateB",each 2), C=Table.AddColumn(B,"GateC",each 3) in C';
    await stage("advanced_trusted_cancel",async()=>{const before=await snapshot();await advancedPreview(expandCode,{cancel:true});const after=await snapshot();assert(after.runtimeCalls===before.runtimeCalls && await sourceFingerprint()===initialSource,"TRUST_CANCEL_EXECUTED");return after;});
    await stage("table_expansion_collision",async()=>{
      await advancedPreview(expandCode);assert(state.pqPreview.resultColumns===12 && state.pqPreview.resultRows===6,"TABLE_EXPAND_PREVIEW_SHAPE");
      assert(await sourceFingerprint()===initialSource,"TABLE_PREVIEW_CHANGED_SOURCE");
      await advancedApply();assert(!state.pqPreview && !document.getElementById("error-panel").classList.contains("hidden"),"TABLE_COLLISION_NOT_BLOCKED");
      assert(await sourceFingerprint()===initialSource,"TABLE_COLLISION_CHANGED_SOURCE");
      return {resultRows:6,resultColumns:12,sourceFingerprint:initialSource,sourceWriteStarted:false};
    });
    await activate("Sales");click("pq-advanced-mode-button");
    const shrinkCode='let Source=Excel.CurrentWorkbook(){[Name="SalesTable"]}[Content], Result=Table.FirstN(Source,3) in Result';
    await stage("table_stale_apply_recovery",async()=>{
      await advancedPreview(shrinkCode);let old;await Excel.run(async ctx=>{const r=ctx.workbook.worksheets.getItem("Sales").getRange("E2");r.load("values");await ctx.sync();old=r.values[0][0];r.values=[[Number(old)+1]];await ctx.sync();});
      const changed=await sourceFingerprint();await advancedApply();assert(!state.pqPreview && await sourceFingerprint()===changed,"STALE_TABLE_APPLY_WROTE");
      await Excel.run(async ctx=>{ctx.workbook.worksheets.getItem("Sales").getRange("E2").values=[[old]];await ctx.sync();});
      assert(await sourceFingerprint()===initialSource,"TABLE_STALE_TEST_RESTORE_FAILED");return {sourceFingerprint:initialSource,sourceWriteStarted:false};
    });
    await activate("Sales");click("pq-advanced-mode-button");
    await stage("table_shrink_apply_tail_readback",async()=>{
      await advancedPreview(shrinkCode);await advancedApply();assert(state.pqPreview?.applied===true,"TABLE_SHRINK_APPLY_FAILED");
      const data=await sourceData();assert(data.rows===4 && data.columns===9,"TABLE_NOT_RESIZED");
      assert(JSON.stringify(data.values.slice(0,4))===JSON.stringify(initialSourceData.values.slice(0,4)),"TABLE_SHRINK_VALUE_ORACLE");
      assert(JSON.stringify(data.other)===JSON.stringify(initialSourceData.other),"TABLE_APPLY_CHANGED_OTHER_SOURCE");
      assert(data.values.slice(4).every(row=>row.every(value=>value==="")),"TABLE_OLD_TAIL_NOT_CLEARED");
      assert(data.sentinel[0][0]==="KEEP_OUTSIDE","TABLE_ADJACENT_SENTINEL_CHANGED");
      return {resultRows:3,resultColumns:9,sourceFingerprintAfter:await digest(data)};
    });
    await activate("GateUsedRange");click("pq-advanced-mode-button");
    await stage("usedrange_shrink_apply_tail_readback",async()=>{
      await advancedPreview('let Source=Excel.CurrentWorkbook(){[Name="PQ_Input"]}[Content], Result=Table.FirstN(Source,2) in Result');
      await advancedApply();assert(state.pqPreview?.applied===true,"USEDRANGE_APPLY_FAILED");
      await Excel.run(async ctx=>{const range=ctx.workbook.worksheets.getItem("GateUsedRange").getRange("A1:B5");range.load("values");await ctx.sync();assert(range.values.slice(3).every(row=>row.every(value=>value==="")),"USEDRANGE_TAIL_NOT_CLEARED");assert(JSON.stringify(range.values.slice(0,3))===JSON.stringify([["Key","Value"],[1,10],[2,20]]),"USEDRANGE_VALUE_ORACLE");});
      return {resultRows:2,resultColumns:2};
    });
    currentStage="complete";await event({event:"complete",status:"pass",revisionCount:revisions().length,...await snapshot()});
  } catch(error) {
    await event({event:"failure",status:"fail",code:error.code || "UNEXPECTED_DRIVER_ERROR",assertion:String(error.message),errorVisible:!document.getElementById("error-panel").classList.contains("hidden"),busy:state.busy,...await snapshot().catch(()=>({}))});
    banner.style.background="#941a1a";
  }
})();
