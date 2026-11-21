/* Developer-only real Office.js/DOM audit, loaded by an isolated gate server.
 * Never use an existing user workbook. Every write requires Gate_Run_Id.
 * Deterministic plan-only AI is not evidence of a live Codex call.
 */
(async function assistantV2LiveGate() {
  "use strict";
  const config = window.__LIVE_EXCEL_GATE__;
  if (!config || config.driverParameters?.assistantV2 !== true) return;
  const parameters = config.driverParameters;
  const storageKey = "ldc-assistant-v2-gate:" + config.runId;
  const rawFetch = window.fetch.bind(window);
  const requests = [];
  let currentStage = "v2_bootstrap", loseNextReceiptResponse = false;
  const banner = document.createElement("div");
  banner.id = "live-v2-gate-status";
  banner.style.cssText = "position:sticky;top:0;z-index:99999;padding:12px;background:#123;color:white;font:13px sans-serif;overflow-wrap:anywhere";
  document.body.prepend(banner);
  const gateUrl = (route) => `${config.baseUrl}/__gate/${route}?gateKey=${encodeURIComponent(config.gateKey)}`;
  const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  function assert(value, code) { if (!value) throw Object.assign(new Error(code), {code}); }
  function canonical(value) {
    if (value === null || typeof value !== "object") return JSON.stringify(value);
    if (Array.isArray(value)) return "[" + value.map(canonical).join(",") + "]";
    return "{" + Object.keys(value).sort().map((key) => JSON.stringify(key) + ":" + canonical(value[key])).join(",") + "}";
  }
  async function digest(value) {
    const bytes = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(canonical(value)));
    return "sha256:" + Array.from(new Uint8Array(bytes), (byte) => byte.toString(16).padStart(2, "0")).join("");
  }
  async function event(metrics) {
    banner.textContent = `${config.runId}: ${currentStage} / ${metrics.status || metrics.event}`;
    const response = await rawFetch(gateUrl("events"), {method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({stage: currentStage, ...metrics})});
    assert(response.ok, "V2_EVIDENCE_WRITE_FAILED");
  }
  async function stage(name, work) {
    currentStage = name;
    const start = performance.now();
    await event({event: "stage", status: "started"});
    const metrics = await work();
    await event({event: "stage", status: "pass", elapsedMs: performance.now() - start, ...(metrics || {})});
  }
  window.fetch = async (...args) => {
    const start = performance.now();
    const response = await rawFetch(...args);
    const path = new URL(typeof args[0] === "string" ? args[0] : args[0].url, location.href).pathname;
    if (path.startsWith("/api/")) {
      let payload = {}, submitted = {};
      try { payload = await response.clone().json(); } catch (_) { /* Report protocol failure through product handler. */ }
      try { submitted = JSON.parse(args[1]?.body || "{}"); } catch (_) { /* Never persist request data. */ }
      const request = {path, statusCode: response.status, code: payload.error?.code || null,
        approvalConsumed: payload.error?.approvalConsumed, receipt: !!submitted.receipt};
      requests.push(request);
      await event({event: "http", path, statusCode: response.status, code: request.code, elapsedMs: performance.now() - start});
      if (loseNextReceiptResponse && path === "/api/assistant/apply" && submitted.receipt?.verified === true) {
        loseNextReceiptResponse = false;
        assert(response.ok && payload.stage === "applied", "V2_FAULT_NOT_AFTER_REAL_RECEIPT");
        await event({event: "faultInjection", status: "injected", code: "V2_RECEIPT_RESPONSE_LOST"});
        throw new TypeError("Synthetic receipt response loss after actual server completion");
      }
    }
    return response;
  };
  async function wait(predicate, code, timeout = 120000) {
    const start = performance.now();
    while (!predicate()) {
      if (performance.now() - start > timeout) throw Object.assign(new Error(code), {code});
      await delay(100);
    }
  }
  function click(id) {
    const node = document.getElementById(id);
    assert(node && !node.disabled && node.getClientRects().length > 0, "V2_CONTROL_UNAVAILABLE_" + id);
    node.click();
  }
  function input(id, value) {
    const node = document.getElementById(id);
    assert(node && !node.disabled, "V2_INPUT_UNAVAILABLE_" + id);
    node.value = value; node.dispatchEvent(new Event("input", {bubbles: true}));
  }
  function check(id, value) {
    const node = document.getElementById(id);
    assert(node && !node.disabled, "V2_CHECK_UNAVAILABLE_" + id);
    node.checked = value; node.dispatchEvent(new Event("change", {bubbles: true}));
  }
  async function perform(id, predicate, code) {
    click(id);
    await wait(() => !state.flow.busy && !state.workbookRecord.busy && predicate(), code);
  }
  async function guarded(context) {
    const marker = context.workbook.names.getItem(config.markerName);
    marker.load("value"); await context.sync();
    assert(String(marker.value).replace(/^=|"/g, "") === config.runId, "DISPOSABLE_WORKBOOK_GUARD");
  }
  async function sheetNames() {
    return Excel.run(async (context) => {
      await guarded(context);
      const sheets = context.workbook.worksheets; sheets.load("items/name"); await context.sync();
      return sheets.items.map((sheet) => sheet.name).sort();
    });
  }
  async function sourceSnapshot(names) {
    return Excel.run(async (context) => {
      await guarded(context);
      const entries = names.map((name) => {
        const sheet = context.workbook.worksheets.getItem(name);
        const range = sheet.getUsedRangeOrNullObject(); range.load("isNullObject");
        sheet.tables.load("items/name"); return {name, sheet, range};
      });
      await context.sync();
      for (const entry of entries) {
        if (!entry.range.isNullObject) entry.range.load("address,rowCount,columnCount,values,formulas,numberFormat");
        entry.tables = entry.sheet.tables.items.map((table) => { const range = table.getRange(); range.load("address,rowCount,columnCount"); return {name: table.name, range}; });
      }
      await context.sync();
      return entries.map((entry) => ({name: entry.name, empty: entry.range.isNullObject,
        ...(entry.range.isNullObject ? {} : {address: entry.range.address, rows: entry.range.rowCount, columns: entry.range.columnCount,
          values: entry.range.values, formulas: entry.range.formulas, formats: entry.range.numberFormat}),
        tables: entry.tables.map((table) => ({name: table.name, address: table.range.address, rows: table.range.rowCount, columns: table.range.columnCount}))}));
    });
  }
  async function fingerprint(names) { return digest(await sourceSnapshot(names)); }
  async function mutateAmount(amount) {
    return Excel.run(async (context) => { await guarded(context); context.workbook.worksheets.getItem("V2AuditInput").getRange("B2").values = [[amount]]; await context.sync(); });
  }
  async function refresh() {
    click("tab-assistant-button"); click("refresh-button");
    await wait(() => !state.busy && state.workbook && state.workbookRecord.loaded && !state.workbookRecord.busy, "V2_REFRESH_FAILED");
  }
  async function bindOnlyAuditSource() {
    input("flow-root-input", parameters.sourceRoot);
    await perform("flow-root-button", () => !!state.flow.rootLabel && state.flow.stage === "new", "V2_ROOT_BIND_FAILED");
    await perform("flow-add-workbook", () => state.flow.workbookSelections.some((selection) => selection.name === "V2AuditInput" && selection.table), "V2_SOURCE_NAVIGATION_FAILED");
    // Use the real navigator checkboxes, including change handlers that revoke
    // prior authority. No source selection or product state is assigned here.
    for (const selection of [...state.flow.workbookSelections]) {
      const key = selection.key;
      const labels = [...document.querySelectorAll("#flow-navigator label")];
      const index = state.flow.workbookSelections.findIndex((item) => item.key === key);
      const checkbox = labels[index]?.querySelector("input[type=checkbox]");
      assert(checkbox && !checkbox.disabled, "V2_NAVIGATOR_CONTROL_MISSING");
      const desired = selection.name === "V2AuditInput" && selection.table;
      if (checkbox.checked !== desired) { checkbox.checked = desired; checkbox.dispatchEvent(new Event("change", {bubbles: true})); }
    }
    assert(state.flow.selectedTableIds.size === 1, "V2_SELECTED_EXTRA_SOURCE");
  }
  async function draftAndCompute() {
    await bindOnlyAuditSource();
    await perform("flow-ingest-sample", () => state.flow.mode === "discover" && !!state.flow.snapshot, "V2_DISCOVER_FAILED");
    assert(state.flow.snapshot.tables.length === 1 && state.flow.sampleInfo[0].rowCount === 3, "V2_DISCOVER_BOUND_OR_SOURCE_WRONG");
    input("prompt", "Compare the sum of Amount for all rows and for positive rows. Keep Date and Literal as source evidence only.");
    await perform("flow-analyze-button", () => state.flow.stage === "understood" && !!state.flow.understand, "V2_UNDERSTAND_FAILED");
    const samples = await flowReadOpenWorkbook("discover", new Set(state.flow.workbookSelections.filter((selection) => selection.name === "V2AuditInput").map((selection) => selection.key)));
    assert(canonical(samples[0].rows.map((row) => row[2])) === canonical(["2024-01-01", "2024-01-02", "2024-01-01T12:00:00"]), "V2_NATIVE_DATE_SAMPLE_ORACLE");
    assert(samples[0].rows[0][3] === "=1+1", "V2_SOURCE_LITERAL_NOT_TEXT");
    check("flow-disclosure", true);
    await perform("flow-plan-button", () => state.flow.stage === "planning" && state.flow.branches.length === 2, "V2_PLAN_FAILED");
    assert(state.flow.branches.every((branch) => branch.normalizedSteps?.length >= 3 && branch.finalOutputContract?.columns?.length === 1), "V2_DRAFT_PARAMETERS_NOT_PROJECTED");
    await perform("flow-ingest-full", () => state.flow.mode === "compute" && state.flow.stage === "planning", "V2_COMPUTE_INGEST_LOST_PLAN");
    await perform("flow-branches-button", () => state.flow.stage === "branched", "V2_BRANCH_EXECUTION_FAILED");
    const [a, b] = state.flow.branches;
    assert(a.id === "A" && b.id === "B" && canonical(a.rows) === canonical([["12"]]) && canonical(b.rows) === canonical([["15"]]), "V2_AB_NUMERIC_ORACLE_FAILED");
    assert(a.totalRows === 1 && b.totalRows === 1 && a.columns.length === 1 && b.columns.length === 1 && state.flow.delta?.value === "-3", "V2_AB_SHAPE_OR_DELTA_FAILED");
    assert(a.reconciliation.passed && b.reconciliation.passed && a.selectable && b.selectable, "V2_INDEPENDENT_RECONCILE_FAILED");
    assert(a.engine.parityChecked === "none" && b.engine.parityChecked === "none", "V2_FALSE_RUNTIME_PARITY_AUTHORITY");
    assert(a.warningCount === 0 && b.warningCount === 0 && a.warnings.length === 0 && b.warnings.length === 0, "V2_VALID_INPUT_WARNING_ORACLE_FAILED");
    const text = document.getElementById("flow-branches").textContent;
    assert(text.includes('"parameters"') && text.includes('"inputs"') && text.includes('"aggregations"'), "V2_EXECUTED_ALGORITHM_NOT_REVIEWABLE");
  }
  async function freezeAndApprove() {
    const radio = document.querySelector('#flow-branch-A input[type="radio"]');
    assert(radio && !radio.disabled, "V2_CHOOSE_BRANCH_MISSING");
    radio.checked = true; radio.dispatchEvent(new Event("change", {bubbles: true}));
    await perform("flow-freeze-button", () => state.flow.stage === "frozen" && !!state.flow.spec, "V2_FREEZE_FAILED");
    assert(!document.getElementById("flow-approve-check").checked && document.getElementById("flow-approve-button").disabled, "V2_APPROVAL_GRANTED_WITHOUT_CHECKBOX");
    assert(document.getElementById("flow-spec-steps").textContent.includes('"parameters"'), "V2_FROZEN_ALGORITHM_HIDDEN");
    check("flow-approve-check", true);
    await perform("flow-approve-button", () => state.flow.stage === "approved" && !!state.flow.approval, "V2_APPROVE_FAILED");
  }
  async function auditResult(spec, expectedRows = [["Total"], ["12"]]) {
    return Excel.run(async (context) => {
      await guarded(context);
      const sheet = context.workbook.worksheets.getItem(spec.target.sheet);
      const result = sheet.getRange("A1:A2"), marker = sheet.getRange("A4");
      result.load("values,numberFormat"); marker.load("values");
      const formulas = sheet.getUsedRange().getSpecialCellsOrNullObject("Formulas"); formulas.load("isNullObject");
      await context.sync();
      assert(canonical(result.values) === canonical(expectedRows), "V2_ACTUAL_SHEET_VALUE_ORACLE_FAILED");
      assert(result.numberFormat.every((row) => row[0] === "@"), "V2_DECIMAL_TEXT_FORMAT_MISSING");
      const expected = "LOCAL_DATA_COPILOT|" + spec.target.sheet + "|" + spec.fingerprint + "|" + spec.resultDigest;
      assert(marker.values[0][0] === expected, "V2_ACTUAL_MARKER_MISMATCH");
      assert(formulas.isNullObject, "V2_RESULT_FORMULA_INJECTION");
      return {resultRows: 1, resultColumns: 1};
    });
  }
  async function rawRecordXml() {
    return Excel.run(async (context) => {
      await guarded(context);
      const parts = context.workbook.customXmlParts.getByNamespace(AssistantRecordXml.ASSISTANT_RECORD_NAMESPACE);
      parts.load("items/id"); await context.sync(); assert(parts.items.length === 1, "V2_RECORD_PART_COUNT");
      const xml = parts.items[0].getXml(); await context.sync(); return xml.value;
    });
  }
  async function directPost(path, body) {
    const response = await rawFetch(path, {method: "POST", headers: {"Content-Type": "application/json", "X-Local-Token": state.token}, body: JSON.stringify(body)});
    const payload = await response.json();
    await event({event: "http", path, statusCode: response.status, code: payload.error?.code || null});
    return {response, payload};
  }
  async function assertConsumedReplay(spec) {
    const before = await sheetNames();
    const {response, payload} = await directPost("/api/assistant/apply", {workbookBase64: "", appliedAt: new Date().toISOString(), workbookIdentity: spec.workbookIdentity,
      workbookSources: [], expectedSpecFingerprint: spec.fingerprint, expectedPreviewHash: spec.previewHash, expectedResultDigest: spec.resultDigest});
    assert(!response.ok && payload.error?.code === "AF_WRITE_PARTIAL" && payload.error.approvalConsumed === true && payload.error.retryable === false, "V2_CONSUMED_REPLAY_ACCEPTED");
    assert(canonical(await sheetNames()) === canonical(before), "V2_REPLAY_CREATED_ANOTHER_SHEET");
  }
  async function reloadPhase(saved) {
    await stage("v2_actual_pane_reload_metadata_only", async () => {
      assert(state.flow.stage === "new" && !state.flow.spec && !state.flow.approval && !state.flow.snapshot && !state.flow.approvalConsumed, "V2_RELOAD_RESTORED_RUNTIME_AUTHORITY");
      assert(!state.workbookRecord.record && !state.workbookRecord.node && state.workbookRecord.persistedNodeHash === saved.nodeHash, "V2_RELOAD_NOT_METADATA_ONLY");
      assert(document.getElementById("flow-record-stale").textContent.includes("unknown"), "V2_RELOAD_FRESHNESS_FALSE_GREEN");
      assert(document.getElementById("flow-apply-button").disabled && document.getElementById("flow-record-save").disabled && document.getElementById("flow-record-download").disabled, "V2_RELOAD_GRANTED_WRITE_OR_FULL_RECORD");
      assert(await fingerprint(saved.sourceNames) === saved.sourceFingerprint, "V2_RELOAD_CHANGED_SOURCE");
      assert(await digest(await AssistantRecordXml.readAssistantRecord()) === saved.nodeDigest, "V2_RELOAD_XML_CHANGED");
      return {historyHash: saved.nodeHash, reviewHash: saved.recordHash, sourceFingerprint: saved.sourceFingerprint};
    });
    sessionStorage.removeItem(storageKey);
    currentStage = "complete";
    await event({event: "complete", status: "pass", resultRows: 1, resultColumns: 1, sourceFingerprint: saved.sourceFingerprint,
      assertion: "V2_REAL_OFFICE_SUCCESS_PRECONSUME_RECOVERY_CONSUMED_REPLAY_XML_CAS_LOST_RECEIPT_AND_PANE_RELOAD"});
  }
  try {
    await wait(() => typeof state !== "undefined" && state.officeReady && state.workbook && !state.busy
      && state.problemChainHydrated && state.flow?.v2Capability && state.workbookRecord.loaded && !state.flow.busy && !state.workbookRecord.busy, "V2_OFFICE_BOOTSTRAP_FAILED");
    await Excel.run(guarded);
    const savedText = sessionStorage.getItem(storageKey);
    if (savedText) { await reloadPhase(JSON.parse(savedText)); return; }
    let originalNames, originalFingerprint, sourceNames, sourceFingerprint, successfulSpec, persistedNode, recordHash;
    await stage("v2_guard_fixture_and_create_native_source", async () => {
      originalNames = await sheetNames(); originalFingerprint = await fingerprint(originalNames);
      assert(!originalNames.includes("V2AuditInput"), "V2_FIXTURE_ALREADY_USED");
      assert(!(await AssistantRecordXml.readAssistantRecord()), "V2_FIXTURE_RECORD_NOT_EMPTY");
      const epoch = parameters.dateSystem === 1904 ? 1904 : 1900;
      await Excel.run(async (context) => {
        await guarded(context);
        const probe = context.workbook.functions.date(1904, 1, 1); probe.load("value,error"); await context.sync();
        assert(!probe.error && probe.value === (epoch === 1904 ? 0 : 1462), "V2_NATIVE_WORKBOOK_EPOCH_PROBE_FAILED");
        const sheet = context.workbook.worksheets.add("V2AuditInput"), serial = epoch === 1904 ? 43830 : 45292;
        sheet.getRange("D1:D4").numberFormat = [["@"], ["@"], ["@"], ["@"]];
        sheet.getRange("A1:D4").values = [["ID", "Amount", "Date", "Literal"], ["A", 10, serial, "=1+1"],
          ["B", -3, serial + 1, "V2_PRIVATE_SOURCE_SENTINEL"], ["C", 5, serial + 0.5, "@literal"]];
        sheet.getRange("C2:C3").numberFormat = [["yyyy-mm-dd"], ["yyyy-mm-dd"]];
        sheet.getRange("C4").numberFormat = [["yyyy-mm-dd hh:mm:ss"]];
        const table = sheet.tables.add("A1:D4", true); table.name = "V2AuditInput";
        sheet.activate(); sheet.getRange("A1").select(); await context.sync();
        const literal = sheet.getRange("D2"); const formulas = literal.getSpecialCellsOrNullObject("Formulas"); formulas.load("isNullObject"); await context.sync();
        assert(formulas.isNullObject, "V2_FIXTURE_LITERAL_BECAME_FORMULA");
      });
      assert(await fingerprint(originalNames) === originalFingerprint, "V2_SETUP_CHANGED_EXISTING_SOURCES");
      sourceNames = [...originalNames, "V2AuditInput"].sort(); sourceFingerprint = await fingerprint(sourceNames);
      await refresh();
      return {sourceFingerprint, assertion: epoch === 1904 ? "V2_EPOCH_1904_PROBE_MATCH" : "V2_EPOCH_1900_PROBE_MATCH"};
    });
    await stage("v2_discover_plan_compute_review", async () => { await draftAndCompute(); return {resultRows: 1, resultColumns: 1, sourceFingerprint}; });
    await stage("v2_preconsume_source_stale_no_write", async () => {
      await freezeAndApprove(); const spec = state.flow.spec, beforeSheets = await sheetNames();
      await mutateAmount(11); const changed = await fingerprint(sourceNames); const start = requests.length;
      await perform("flow-apply-button", () => requests.slice(start).some((request) => request.path === "/api/assistant/apply" && request.code === "AF_SPEC_STALE"), "V2_STALE_APPLY_NOT_REJECTED");
      const failure = requests.slice(start).find((request) => request.path === "/api/assistant/apply" && request.code === "AF_SPEC_STALE");
      assert(failure.approvalConsumed === false && !state.flow.approvalConsumed && state.flow.stage !== "partial", "V2_PRECONSUME_FALSE_PARTIAL");
      assert(document.getElementById("error-code").textContent === "AF_SPEC_STALE", "V2_PRECONSUME_WRONG_UI_ERROR");
      assert(canonical(await sheetNames()) === canonical(beforeSheets) && !(await sheetNames()).includes(spec.target.sheet), "V2_STALE_APPLY_WROTE_SHEET");
      assert(await fingerprint(sourceNames) === changed && await fingerprint(originalNames) === originalFingerprint, "V2_STALE_REJECTION_CHANGED_SOURCE");
      await mutateAmount(10); assert(await fingerprint(sourceNames) === sourceFingerprint, "V2_SOURCE_RESTORE_FAILED");
      return {code: "AF_SPEC_STALE", sourceWriteStarted: false, sourceFingerprint};
    });
    await stage("v2_explicit_recovery_real_write_and_receipt", async () => {
      await draftAndCompute(); await freezeAndApprove(); successfulSpec = JSON.parse(JSON.stringify(state.flow.spec));
      const beforeSheets = await sheetNames();
      await perform("flow-apply-button", () => state.flow.stage === "applied" && state.flow.handoffStatus === "readback-verified", "V2_REAL_APPLY_FAILED");
      const added = (await sheetNames()).filter((name) => !beforeSheets.includes(name));
      assert(canonical(added) === canonical([successfulSpec.target.sheet]) && state.flow.approvalConsumed, "V2_APPLY_DESTINATION_OR_CONSUMPTION_WRONG");
      const metrics = await auditResult(successfulSpec);
      assert(await fingerprint(sourceNames) === sourceFingerprint, "V2_APPLY_CHANGED_SOURCES");
      assert(document.getElementById("flow-apply-button").disabled && document.getElementById("flow-apply-status").textContent.includes("chưa lưu"), "V2_APPLY_REPEAT_OR_SAVE_CLAIM");
      await assertConsumedReplay(successfulSpec);
      return {...metrics, sourceFingerprint, reviewHash: successfulSpec.fingerprint};
    });
    await stage("v2_record_real_xml_hash_and_cas_recovery", async () => {
      await perform("flow-record-build", () => state.flow.stage === "recorded" && !!state.workbookRecord.record, "V2_RECORD_BUILD_FAILED");
      const record = state.workbookRecord.record; persistedNode = JSON.parse(JSON.stringify(state.workbookRecord.node)); recordHash = record.hash;
      assert(await digest(Object.fromEntries(record.hashBasis.map((key) => [key, record[key]]))) === recordHash, "V2_FULL_RECORD_INDEPENDENT_HASH_FAILED");
      const metadataBasis = Object.fromEntries(Object.entries(persistedNode).filter(([key]) => key !== "hash"));
      assert(await digest(metadataBasis) === persistedNode.hash && persistedNode.recordHash === recordHash && persistedNode.hash !== recordHash, "V2_METADATA_DISTINCT_HASH_FAILED");
      assert(!canonical(record).includes("V2_PRIVATE_SOURCE_SENTINEL") && !canonical(record).includes("sampleRows"), "V2_FULL_RECORD_LEAKED_SOURCE");
      await perform("flow-record-save", () => state.workbookRecord.persistedNodeHash === persistedNode.hash && !state.workbookRecord.reloadRequired, "V2_XML_PERSIST_FAILED");
      const originalXml = await rawRecordXml();
      assert(!originalXml.includes("V2_PRIVATE_SOURCE_SENTINEL") && !originalXml.includes("C:\\"), "V2_XML_RAW_SOURCE_OR_PATH_LEAK");
      assert(canonical(await AssistantRecordXml.readAssistantRecord()) === canonical(persistedNode), "V2_XML_INDEPENDENT_READ_MISMATCH");
      const other = {...persistedNode, labels: persistedNode.labels.includes("assumed") ? ["unverified"] : ["assumed"]};
      other.hash = await digest(Object.fromEntries(Object.entries(other).filter(([key]) => key !== "hash")));
      await Excel.run(guarded);
      await AssistantRecordXml.writeAssistantRecord(other, persistedNode.hash, {name: state.workbook.name, url: state.workbook.url || ""});
      await perform("flow-record-save", () => state.workbookRecord.reloadRequired, "V2_CAS_CONFLICT_NOT_REPORTED");
      assert(document.getElementById("error-code").textContent === "PQPC_HISTORY_CONFLICT" && (await AssistantRecordXml.readAssistantRecord()).hash === other.hash, "V2_CAS_OVERWROTE_OTHER_ACTOR");
      await perform("flow-record-reload", () => !state.workbookRecord.reloadRequired && state.workbookRecord.persistedNodeHash === other.hash, "V2_CAS_EXPLICIT_RELOAD_FAILED");
      await perform("flow-record-save", () => state.workbookRecord.persistedNodeHash === persistedNode.hash && !state.workbookRecord.reloadRequired, "V2_CAS_REVIEWED_REPLACEMENT_FAILED");
      assert(await rawRecordXml() === originalXml && record.hash === recordHash, "V2_CAS_RECOVERY_CHANGED_HISTORY");
      assert(await fingerprint(sourceNames) === sourceFingerprint, "V2_XML_PERSIST_CHANGED_CELLS");
      return {historyHash: persistedNode.hash, reviewHash: recordHash, sourceFingerprint};
    });
    await stage("v2_real_write_lost_receipt_response_unknown_no_retry", async () => {
      await draftAndCompute(); await freezeAndApprove(); const spec = JSON.parse(JSON.stringify(state.flow.spec));
      assert(spec.target.sheet !== successfulSpec.target.sheet, "V2_SECOND_ATTEMPT_DESTINATION_COLLISION");
      loseNextReceiptResponse = true;
      await perform("flow-apply-button", () => state.flow.stage === "partial" && state.flow.approvalConsumed, "V2_LOST_RECEIPT_NOT_UNKNOWN");
      assert(!loseNextReceiptResponse && state.flow.handoffStatus === "partial-unknown", "V2_RECEIPT_FAULT_NOT_REACHED");
      await auditResult(spec); await auditResult(successfulSpec);
      assert(document.getElementById("flow-apply-button").disabled && document.getElementById("flow-record-build").disabled, "V2_UNKNOWN_GRANTED_RETRY_OR_RECORD");
      await assertConsumedReplay(spec);
      assert((await AssistantRecordXml.readAssistantRecord()).hash === persistedNode.hash && await fingerprint(sourceNames) === sourceFingerprint, "V2_UNKNOWN_CHANGED_PRIOR_HISTORY_OR_SOURCE");
      return {code: "V2_RECEIPT_RESPONSE_LOST", resultRows: 1, resultColumns: 1, sourceFingerprint};
    });
    await stage("v2_prepare_actual_pane_reload", async () => {
      await perform("flow-reset-button", () => state.flow.stage === "new" && !state.flow.spec && !state.flow.approvalConsumed, "V2_EXPLICIT_RESET_FAILED");
      sessionStorage.setItem(storageKey, JSON.stringify({nodeHash: persistedNode.hash, nodeDigest: await digest(persistedNode), recordHash,
        sourceNames, sourceFingerprint}));
      return {historyHash: persistedNode.hash, sourceFingerprint};
    });
    location.reload();
  } catch (error) {
    const code = error.code || (typeof error.name === "string" ? "V2_" + error.name.toUpperCase().replace(/[^A-Z0-9_]/g, "") : "V2_DRIVER_FAILED");
    try { await event({event: "failure", status: "fail", code, errorVisible: !document.getElementById("error-panel")?.classList.contains("hidden")}); }
    catch (_) { banner.textContent = `${config.runId}: ${currentStage} / ${code} / evidence unavailable`; }
  }
})();
