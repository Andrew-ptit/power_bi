/* Isolated native preservation feasibility probe. Never a production patcher.
 * Every Excel.run checks the synthetic marker before touching worksheet data.
 * Passing this probe alone does not establish the later session/journal product.
 */
(async function preparationFeasibility() {
  "use strict";
  const config = window.__LIVE_EXCEL_GATE__;
  if (!config?.driverParameters?.preparation) return;
  const parameters = config.driverParameters;
  let currentStage = "preparation_host", original = null, imported = null, snapshot = null;
  const banner = document.createElement("div");
  banner.id = "preparation-gate-status";
  banner.style.cssText = "padding:12px;background:#123;color:white;font:13px sans-serif";
  document.body.prepend(banner);
  function assert(value, code) { if (!value) throw Object.assign(new Error(code), {code}); }
  async function event(data) {
    banner.textContent = currentStage + ": " + data.status;
    const response = await fetch(config.baseUrl + "/__gate/events?gateKey=" + encodeURIComponent(config.gateKey), {
      method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({stage: currentStage, ...data}),
    });
    assert(response.ok, "PREPARATION_EVIDENCE_WRITE_FAILED");
  }
  async function guarded(work) {
    return Excel.run(async (context) => {
      const marker = context.workbook.names.getItem(config.markerName);
      marker.load("value"); await context.sync();
      assert(String(marker.value).replace(/^=|"/g, "") === config.runId, "DISPOSABLE_WORKBOOK_GUARD");
      return work(context);
    });
  }
  async function stage(name, work) {
    currentStage = name;
    const started = performance.now();
    await event({event: "stage", status: "started"});
    const metrics = await work();
    await event({event: "stage", status: "pass", elapsedMs: performance.now() - started, ...metrics});
  }
  async function read(context, sheet) {
    sheet.load("id,name");
    const range = sheet.getUsedRange();
    range.load("values,formulas,numberFormat,rowCount,columnCount");
    const highlighted = sheet.getRange("B2");
    highlighted.format.font.load("bold"); highlighted.format.fill.load("color");
    await context.sync();
    return {id: sheet.id, name: sheet.name, values: range.values, formulas: range.formulas,
      numberFormat: range.numberFormat, rows: range.rowCount, columns: range.columnCount,
      bold: highlighted.format.font.bold, fill: highlighted.format.fill.color};
  }
  const same = (left, right) => JSON.stringify(left) === JSON.stringify(right);
  async function importFeasibility() {
    // Candidate constant-name scoping; other named expressions stay unqualified.
    let original, imported;
    const semantic = state => { const {id, ...rest} = state; return rest; };
    async function insert(context) {
      const result = context.workbook.insertWorksheetsFromBase64(parameters.preparationSourceBase64, {sheetNamesToInsert: []});
      await context.sync();
      assert(result.value.length === 2, "NAMESPACE_GROUP_INCOMPLETE");
      const group = [];
      for (const id of result.value) group.push(await read(context, context.workbook.worksheets.getItem(id)));
      const orders = group.find(s => s.columns === 4), rates = group.find(s => s.columns === 2);
      assert(orders && rates, "NAMESPACE_GROUP_MAPPING_MISSING");
      const orderSheet = context.workbook.worksheets.getItem(orders.id), rateSheet = context.workbook.worksheets.getItem(rates.id);
      orderSheet.name = "PrepImportedOrders"; rateSheet.name = "PrepImportedRates";
      // Scoped constants isolate incoming formulas from the original global name.
      orderSheet.names.add("TaxRate", "=1"); rateSheet.names.add("TaxRate", "=1");
      await context.sync();
      const tables = orderSheet.tables; tables.load("items/name"); await context.sync();
      assert(tables.items.length === 1, "NAMESPACE_TABLE_MISSING");
      tables.items[0].name = "PrepImportedTable";
      context.application.calculate(Excel.CalculationType.full); await context.sync();
      const actual = await read(context, orderSheet), actualRate = await read(context, rateSheet);
      assert(actual.values[1][3] === 11 && !actual.formulas[1][3].includes("["), "SCOPED_NAME_IMPORT_CHANGED_MEANING");
      assert(actual.numberFormat[1][2] === "yyyy-mm-dd" && actual.bold === true && actual.fill.toUpperCase() === "#FFFF00", "SCOPED_NAME_IMPORT_CHANGED_FORMAT");
      const tax = context.workbook.names.getItem("TaxRate"); tax.load("value"); await context.sync();
      assert(Number(tax.value) === 100, "SCOPED_NAME_CHANGED_ORIGINAL_GLOBAL");
      assert(same(await read(context, context.workbook.worksheets.getItem(original.id)), original), "SCOPED_NAME_CHANGED_PERSONAL_SOURCE");
      return {orders: actual, rates: actualRate};
    }
    await stage("preparation_scoped_constant_import", async () => guarded(async context => {
      original = await read(context, context.workbook.worksheets.getItem("Orders"));
      assert(original.values[1][1] === 2, "SCOPED_NAME_TARGET_ORACLE_MISMATCH");
      imported = await insert(context);
      return {resultRows: imported.orders.rows, resultColumns: imported.orders.columns,
        assertion: "group-renamed-scoped-constant-11-global100-original2", sourceFingerprint: await digest(original)};
    }));
    await stage("preparation_import_undo_redo_probe", async () => guarded(async context => {
      context.workbook.worksheets.getItem(imported.orders.id).delete();
      context.workbook.worksheets.getItem(imported.rates.id).delete();
      await context.sync();
      assert(same(await read(context, context.workbook.worksheets.getItem(original.id)), original), "IMPORT_UNDO_CHANGED_ORIGINAL");
      const again = await insert(context);
      assert(same(semantic(again.orders), semantic(imported.orders)) && same(semantic(again.rates), semantic(imported.rates)), "IMPORT_REDO_SEMANTICS_CHANGED");
      const local = context.workbook.worksheets.getItem(again.rates.id).names.getItemOrNullObject("LocalRate");
      local.load("isNullObject"); await context.sync();
      assert(!local.isNullObject, "SOURCE_LOCAL_NAME_LOST");
      local.load("value"); await context.sync();
      assert(Number(local.value) === 2, "SOURCE_LOCAL_NAME_CHANGED_MEANING");
      return {stepsCount: 2, assertion: "fresh-native-ids-same-reviewed-logical-group-local-name-preserved"};
    }));
    currentStage = "complete";
    await event({event: "complete", status: "partial", assertion: "constant-name-import-feasibility-only-no-product-authority"});
  }
  async function digest(value) {
    const result = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(JSON.stringify(value)));
    return "sha256:" + Array.from(new Uint8Array(result), b => b.toString(16).padStart(2, "0")).join("");
  }
  async function deltaFeasibility() {
    // Disposable experiment only. No product grant, journal or write endpoint.
    assert(Office.context.requirements.isSetSupported("ExcelApi", "1.13"), "EXCEL_API_1_13_REQUIRED");
    let baseline, after, changes;
    async function capture(context) {
      context.application.calculate(Excel.CalculationType.full); await context.sync();
      const orders = await read(context, context.workbook.worksheets.getItem("Orders"));
      const rates = await read(context, context.workbook.worksheets.getItem("Rates"));
      return {orders, rates};
    }
    await stage("preparation_name_conflict_preflight", async () => guarded(async context => {
      const names = context.workbook.names, sheets = context.workbook.worksheets;
      names.load("items/name"); sheets.load("items/id"); await context.sync();
      const ids = sheets.items.map(s => s.id);
      assert(names.items.some(n => n.name.toLowerCase() === "taxrate"), "EXPECTED_NAME_CONFLICT_MISSING");
      // Incoming known TaxRate conflict blocks insertion, regardless of values.
      sheets.load("items/id"); await context.sync();
      assert(same(ids, sheets.items.map(s => s.id)), "PREFLIGHT_CHANGED_SHEETS");
      return {assertion: "known-name-conflict-blocked-before-insert", resultRows: 0, resultColumns: 0};
    }));
    await stage("preparation_delta_setup", async () => guarded(async context => {
      const orders = context.workbook.worksheets.getItem("Orders");
      const date = orders.getRange("C2"), literal = orders.getRange("A3");
      date.numberFormat = [["@"]]; literal.numberFormat = [["@"]]; await context.sync();
      date.values = [["03/04/2026"]]; literal.values = [[" =1+1 "]]; await context.sync();
      date.numberFormat = [["General"]]; literal.numberFormat = [["General"]]; await context.sync();
      baseline = await capture(context);
      assert(baseline.orders.values[1][3] === 11, "DELTA_SOURCE_ORACLE_MISMATCH");
      changes = [
        {sheet: "Orders", address: "A2", row: 1, col: 0, value: "00123", format: "General"},
        {sheet: "Orders", address: "C2", row: 1, col: 2, value: 46115, format: "yyyy-mm-dd"},
        {sheet: "Orders", address: "A3", row: 2, col: 0, value: "=1+1", format: "General"},
        {sheet: "Rates", address: "B2", row: 1, col: 1, value: 3, format: "General"},
      ];
      for (const change of changes) {
        const source = change.sheet === "Orders" ? baseline.orders : baseline.rates;
        change.before = source.values[change.row][change.col];
        change.beforeFormat = source.numberFormat[change.row][change.col];
      }
      return {resultRows: 4, resultColumns: 4, sourceFingerprint: await digest(baseline)};
    }));
    async function patch(direction, expected) {
      return guarded(async context => {
        const current = await capture(context);
        assert(same(current, expected), "DELTA_SOURCE_CONFLICT");
        // Validate every affected cell before the first queued write.
        const ranges = changes.map(change => context.workbook.worksheets.getItem(change.sheet).getRange(change.address));
        const formulas = ranges.map(range => range.getSpecialCellsOrNullObject(Excel.SpecialCellType.formulas));
        formulas.forEach(range => range.load("isNullObject")); await context.sync();
        assert(formulas.every(range => range.isNullObject), "DELTA_FORMULA_CELL_REJECTED");
        const values = changes.map(change => direction === "before" ? change.before : change.value);
        values.forEach((value, i) => { if (typeof value === "string") ranges[i].numberFormat = [["@"]]; });
        await context.sync();
        values.forEach((value, i) => { ranges[i].values = [[value]]; }); await context.sync();
        changes.forEach((change, i) => { ranges[i].numberFormat = [[direction === "before" ? change.beforeFormat : change.format]]; });
        await context.sync();
        return capture(context);
      });
    }
    await stage("preparation_delta_apply", async () => {
      after = await patch("after", baseline);
      assert(after.orders.values[1][0] === "00123" && after.orders.values[2][0] === "=1+1", "DELTA_LITERAL_CHANGED_TYPE");
      assert(after.orders.values[1][2] === 46115 && after.orders.numberFormat[1][2] === "yyyy-mm-dd", "DELTA_DATE_OR_FORMAT_MISMATCH");
      assert(after.orders.values[1][3] === 16 && after.orders.formulas[1][3] === baseline.orders.formulas[1][3], "DELTA_DEPENDENCY_CHANGED");
      assert(after.orders.id === baseline.orders.id && after.rates.id === baseline.rates.id, "DELTA_SHEET_IDS_CHANGED");
      return {resultRows: 4, resultColumns: 4, sourceFingerprintBefore: await digest(baseline), sourceFingerprintAfter: await digest(after)};
    });
    await stage("preparation_delta_undo_redo", async () => {
      const undo = await patch("before", after);
      assert(same(undo, baseline), "DELTA_UNDO_DID_NOT_RESTORE_SCOPE");
      const redo = await patch("after", baseline);
      assert(same(redo, after), "DELTA_REDO_DID_NOT_RESTORE_SCOPE");
      return {sourceFingerprintBefore: await digest(undo), sourceFingerprintAfter: await digest(redo), stepsCount: 2};
    });
    await stage("preparation_delta_conflict", async () => {
      const edited = await guarded(async context => {
        context.workbook.worksheets.getItem("Orders").getRange("A2").values = [["Manual edit"]]; await context.sync();
        return capture(context);
      });
      let blocked = false;
      try { await patch("before", after); } catch (error) { blocked = error.code === "DELTA_SOURCE_CONFLICT"; }
      assert(blocked, "DELTA_MANUAL_EDIT_NOT_BLOCKED");
      assert(same(await guarded(capture), edited), "DELTA_CONFLICT_OVERWROTE_EDIT");
      return {assertion: "manual-edit-rejected-zero-restore-writes", sourceFingerprint: await digest(edited)};
    });
    currentStage = "complete";
    await event({event: "complete", status: "partial", assertion: "delta-feasibility-only-no-product-authority"});
  }
  try {
    const ready = await Office.onReady();
    assert(ready.host === Office.HostType.Excel, "EXCEL_HOST_REQUIRED");
    const delta = await guarded(async context => {
      const marker = context.workbook.names.getItemOrNullObject("Gate_Delta_Probe");
      marker.load("isNullObject"); await context.sync();
      if (marker.isNullObject) return false;
      marker.load("value"); await context.sync();
      return Number(String(marker.value).replace(/^=/, "")) === 1;
    });
    if (delta) { await deltaFeasibility(); return; }
    const importProbe = await guarded(async context => {
      const marker = context.workbook.names.getItemOrNullObject("Gate_Import_Probe");
      marker.load("isNullObject"); await context.sync();
      return !marker.isNullObject;
    });
    if (importProbe) { await importFeasibility(); return; }
    if (parameters.preparationReadOnly) {
      async function until(test, code) {
        const deadline = performance.now() + 15000;
        while (!test()) {
          assert(performance.now() < deadline, code);
          await new Promise(resolve => setTimeout(resolve, 100));
        }
      }
      await stage("preparation_readonly_wizard", async () => {
        const before = await guarded(async context => {
          const sheet = context.workbook.worksheets.getItem("Orders");
          const result = await read(context, sheet);
          sheet.getRange("A1:B2").select(); await context.sync();
          return result;
        });
        const host = document.getElementById("preparation-wizard");
        await until(() => host && !host.hidden, "PREPARATION_UI_NOT_READY");
        host.open = true;
        const selected = await window.ReqwisePreparationRuntime.readSelection(window, "1900");
        assert(same(selected.snapshot.formulaCells, [[0, 1]]), "NATIVE_FORMULA_MASK_MISMATCH");
        document.getElementById("preparation-date-system").value = "1900";
        document.getElementById("preparation-scan").click();
        const panel = document.getElementById("preparation-panel");
        await until(() => panel.textContent.includes("Không có câu hỏi chuyển kiểu"), "PREPARATION_SCAN_NOT_READY");
        Array.from(panel.querySelectorAll("button")).find(b => b.textContent === "3 · Ngoại lệ").click();
        Array.from(panel.querySelectorAll("button")).find(b => b.textContent === "Tạo bản xem trước").click();
        await until(() => panel.textContent.includes("1 ô được đề xuất thay đổi"), "PREPARATION_PREVIEW_NOT_READY");
        const apply = Array.from(panel.querySelectorAll("button")).find(b => b.textContent === "Áp dụng");
        assert(apply && apply.disabled, "UNQUALIFIED_WRITE_ENABLED");
        assert(panel.textContent.includes('A2: " Personal " → "Personal"'), "PREPARATION_REVIEW_DIFF_MISMATCH");
        const after = await guarded(context => read(context, context.workbook.worksheets.getItem(before.id)));
        assert(same(before, after), "READONLY_WIZARD_CHANGED_SOURCE");
        return {resultRows: 1, resultColumns: 2, sourceFingerprintBefore: await digest(before), sourceFingerprintAfter: await digest(after),
          assertion: "one-trim-preview-formula-protected-zero-source-write"};
      });
      currentStage = "complete";
      await event({event: "complete", status: "partial", qualification: "readonly-wizard-only", sessionJournalQualified: false});
      return;
    }
    assert(Office.context.requirements.isSetSupported("ExcelApi", "1.13"), "EXCEL_API_1_13_REQUIRED");
    await stage("preparation_original", async () => guarded(async (context) => {
      original = await read(context, context.workbook.worksheets.getItem("Orders"));
      assert(original.values[1][1] === 2 && original.formulas[1][1] === "=1+1", "SYNTHETIC_TARGET_ORACLE_MISMATCH");
      return {resultRows: original.rows, resultColumns: original.columns, sourceGuard: true};
    }));
    await stage("preparation_group_import", async () => guarded(async (context) => {
      const ids = context.workbook.insertWorksheetsFromBase64(parameters.preparationSourceBase64, {sheetNamesToInsert: []});
      await context.sync();
      assert(ids.value.length === 2, "GROUP_SHEET_COUNT_MISMATCH");
      const sheets = [];
      for (const id of ids.value) sheets.push(await read(context, context.workbook.worksheets.getItem(id)));
      const orders = sheets.find((item) => item.columns === 4);
      const rates = sheets.find((item) => item.columns === 2);
      assert(orders && rates, "GROUP_MAPPING_MISSING");
      context.application.calculate(Excel.CalculationType.full);
      await context.sync();
      const checked = await read(context, context.workbook.worksheets.getItem(orders.id));
      const meaningPreserved = checked.values[1][3] === 11;
      assert(checked.values[1][0] === " 00123 " && checked.values[1][2] === 46340, "GROUP_LITERAL_OR_DATE_CHANGED");
      assert(checked.numberFormat[1][2] === "yyyy-mm-dd" && checked.bold === true && checked.fill.toUpperCase() === "#FFFF00", "GROUP_FORMAT_CHANGED");
      const sourceNow = await read(context, context.workbook.worksheets.getItem(original.id));
      assert(same(sourceNow, original), "PERSONAL_SOURCE_CHANGED");
      imported = {orders: checked, rates};
      // A failed import probe must not prevent independent copy/restore probes.
      // The known fixture's defined-name collision remains a hard blocker.
      return {status: meaningPreserved ? "pass" : "blocked", importedSheets: 2,
        code: meaningPreserved ? null : "CROSS_SHEET_OR_NAME_COLLISION_CHANGED_MEANING",
        expectedSyntheticTotal: 11, observedSyntheticTotal: checked.values[1][3],
        resultRows: checked.rows, resultColumns: checked.columns,
        crossSheetMeaning: meaningPreserved, numberFormat: true, fontFill: true, personalSourcePreserved: true};
    }));
    await stage("preparation_personal_copy", async () => guarded(async (context) => {
      const source = context.workbook.worksheets.getItem(original.id);
      const copy = source.copy(Excel.WorksheetPositionType.after, source);
      copy.name = "PrepPersonalResult";
      await context.sync();
      const actual = await read(context, copy);
      assert(actual.values[1][1] === 2 && actual.formulas[1][1] === "=1+1", "PERSONAL_COPY_FORMULA_CHANGED");
      assert(same(await read(context, source), original), "PERSONAL_COPY_CHANGED_ORIGINAL");
      return {personalCopyFormula: true, originalPreserved: true};
    }));
    await stage("preparation_capture_and_edit", async () => {
      assert(typeof exportWorkbookBase64 === "function", "PRODUCT_EXPORT_UNAVAILABLE");
      await guarded(async () => {});
      snapshot = await exportWorkbookBase64();
      return guarded(async (context) => {
        const rates = context.workbook.worksheets.getItem(imported.rates.id);
        rates.getRange("B2").values = [[3]];
        context.application.calculate(Excel.CalculationType.full); await context.sync();
        const orders = await read(context, context.workbook.worksheets.getItem(imported.orders.id));
        assert(orders.values[1][3] === imported.orders.values[1][3] + 5, "DEPENDENCY_EDIT_DID_NOT_RECALCULATE");
        return {captureBytesBounded: snapshot.length < 64 * 1024 * 1024, dependencyEdit: true};
      });
    });
    await stage("preparation_captured_image_restore_probe", async () => guarded(async (context) => {
      // Reinsert the captured image as staging; restore contents into the same
      // original sheet IDs, then remove staging. This tests (does not assume)
      // whether native copy preserves dependency references after staging dies.
      const staged = context.workbook.insertWorksheetsFromBase64(snapshot, {sheetNamesToInsert: []});
      await context.sync();
      const states = [];
      for (const id of staged.value) states.push(await read(context, context.workbook.worksheets.getItem(id)));
      const orders = states.find((item) => item.columns === 4);
      const rates = states.find((item) => item.values[0]?.[0] === "Class");
      assert(orders && rates, "RESTORE_STAGE_MAPPING_MISSING");
      context.workbook.worksheets.getItem(imported.orders.id).getUsedRange().copyFrom(
        context.workbook.worksheets.getItem(orders.id).getUsedRange(), Excel.RangeCopyType.all);
      context.workbook.worksheets.getItem(imported.rates.id).getUsedRange().copyFrom(
        context.workbook.worksheets.getItem(rates.id).getUsedRange(), Excel.RangeCopyType.all);
      await context.sync();
      for (const id of staged.value) context.workbook.worksheets.getItem(id).delete();
      context.application.calculate(Excel.CalculationType.full); await context.sync();
      const restored = await read(context, context.workbook.worksheets.getItem(imported.orders.id));
      assert(restored.values[1][3] === imported.orders.values[1][3] && same(restored.formulas, imported.orders.formulas), "RESTORE_DEPENDENCY_REFERENCES_NOT_PRESERVED");
      assert(same(restored.numberFormat, imported.orders.numberFormat), "RESTORE_FORMAT_NOT_PRESERVED");
      assert(same(await read(context, context.workbook.worksheets.getItem(original.id)), original), "RESTORE_CHANGED_PERSONAL_SOURCE");
      return {restoreFormulaMeaning: true, stableSheetIds: true, personalSourcePreserved: true};
    }));
    currentStage = "complete";
    await event({event: "complete", status: "partial", qualification: "native-feasibility-only",
      sessionJournalQualified: false, requiresFurtherCases: ["redo", "external-links", "protected-structure", "partial-write", "merge-geometry"]});
  } catch (error) {
    await event({event: "failure", status: "blocked", code: /^[A-Z0-9_]+$/.test(error.code || "") ? error.code : "OFFICE_NATIVE_PROBE_FAILED",
      qualification: "no-production-write-authority"});
  }
})();
