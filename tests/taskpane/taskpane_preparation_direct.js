"use strict";
const assert = require("node:assert/strict");
const crypto = require("node:crypto").webcrypto;
const bridgeApi = require("../../pbip_assistant/excel_addin/preparation_bridge.js");

(async () => {
  const calls = [], messages = [];
  let state = null, consume, failAfterWrite = false, loseBeginResponse = false, rejectBegin = false;
  const before = {version: 1, fingerprint: "before", sheets: [{sheetId: "old", name: "Existing",
    rowOffset: 0, columnOffset: 0, values: [], formulas: [], formulaCells: [], numberFormats: []}]};
  const after = {...before, fingerprint: "after", sheets: [...before.sheets, {...before.sheets[0], sheetId: "new", name: "Imported"}]};
  const bridge = bridgeApi.create({backupEnabled: false,
    environment: {crypto, ReqwisePreparationSession: {create() { throw Error("recovery session must not be created"); }}},
    runtime: {describeWorkbook: async () => ({workbookName: "Book"}), createMutationRuntime(environment) {
      assert.equal(environment.preparationBackupEnabled, false);
      consume = environment.consumeWritePermit;
      return {captureAffectedScope: async () => before, async importReviewedSources(attempt, packages, progress) {
        assert.equal(attempt.expectedFingerprint, "after");
        assert.equal(packages.length, 1);
        await consume({attemptId: "attempt", writePermit: "permit", currentFingerprint: "before", operation: "import"});
        progress({processed: 1, total: 1});
        if (failAfterWrite) throw Error("readback failed");
        return {phase: "verified", after, createdSheetIds: ["new"]};
      }};
    }}, getState: () => state, setState: value => { state = value; },
    async post(action, body) {
      calls.push(action);
      assert(!/preservation|image-|undo|redo/.test(action), "active journey must not create backup/evidence uploads");
      if (action === "attach") {
        assert.equal(body.claim.marker, null);
        assert(!("preservationFingerprint" in body.claim));
        return {preparationId: "direct", writeEnabled: true, backupEnabled: false};
      }
      if (action === "review-import") return {reviewHash: "review"};
      if (action === "packages") return {reviewHash: "review", packages: [], importReport: {totals: {files: 0, sheets: 0, skipped: 0, decisions: 0}, files: []}};
      if (action === "approve") return {grantId: "grant"};
      if (action === "direct-begin") {
        if (loseBeginResponse) throw Object.assign(new TypeError("begin response lost"), typeof loseBeginResponse === "string" ? {code: loseBeginResponse} : {});
        if (rejectBegin) throw Object.assign(new Error("source changed"), {code: "DP_SOURCE_STALE"});
        assert.equal(body.beforeImage.fingerprint, "before");
        return {attemptId: "attempt", writePermit: "permit", operation: "import", kind: "import",
          beforeFingerprint: "before", expectedFingerprint: "after", packages: [{}]};
      }
      if (action === "direct-write-ready") return {attemptId: "attempt", writePermit: "permit", currentFingerprint: "before", operation: "import"};
      if (action === "direct-complete") {
        assert.equal(body.receipt.imageId, null);
        if (body.receipt.phase === "partial_unknown") {
          assert.equal(body.afterImage, null);
          return {...state, status: "partial_unknown", writeEnabled: false};
        }
        assert.equal(body.afterImage.fingerprint, "after");
        return {...state, status: "verified", importedSheetIds: ["new"]};
      }
      throw Error("unexpected action " + action);
    }});
  await bridge.attach();
  const request = {inventory: {inventoryHash: "inventory"}, fileIds: ["file"],
    mappings: [{fileId: "file", sourceSheetId: "csv", proposedName: "Imported"}], onProgress: message => messages.push(message)};
  assert.equal((await bridge.importFiles(request)).status, "verified");
  assert(messages.some(message => message.includes("Đang đọc lại")), "final file reports verification before completion");
  assert.equal(calls.filter(action => action === "direct-write-ready").length, 1);
  failAfterWrite = true;
  await assert.rejects(() => bridge.importFiles(request), error => error.code === "DP_PARTIAL_UNKNOWN");
  assert.equal(state.status, "partial_unknown");
  await bridge.restart();
  assert.equal(state.backupEnabled, false);
  assert.equal(state.writeEnabled, true, "explicit restart establishes a new reviewed attachment");
  failAfterWrite = false; loseBeginResponse = true;
  const readyCount = calls.filter(action => action === "direct-write-ready").length;
  await assert.rejects(() => bridge.importFiles(request), error => error.code === "DP_PARTIAL_UNKNOWN");
  assert.equal(calls.filter(action => action === "direct-write-ready").length, readyCount, "lost begin response never starts native writes");
  await bridge.restart();
  for (const code of ["COORDINATOR_RESPONSE_INVALID", "COORDINATOR_TIMEOUT"]) {
    loseBeginResponse = code;
    await assert.rejects(() => bridge.importFiles(request), error => error.code === "DP_PARTIAL_UNKNOWN");
    await bridge.restart();
  }
  loseBeginResponse = false; rejectBegin = true;
  await assert.rejects(() => bridge.importFiles(request), error => error.code === "DP_SOURCE_STALE", "deterministic rejection retains its original error");
  console.log("Preparation direct no-backup handshake passed");
})().catch(error => { console.error(error); process.exitCode = 1; });
