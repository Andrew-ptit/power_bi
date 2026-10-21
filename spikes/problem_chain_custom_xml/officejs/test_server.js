"use strict";

const assert = require("node:assert/strict");
const http = require("node:http");
const {AUTORUN_STEPS, EVIDENCE_MAX_BYTES, createRequestHandler, validateEvidence} = require("./server.js");

function evidence() {
  return {
    schemaVersion: "1.0",
    runId: "22222222-2222-4222-8222-222222222222",
    capturedAt: "2026-10-13T10:00:01+07:00",
    startedAt: "2026-10-13T10:00:00+07:00",
    host: "Excel",
    platform: "PC",
    excelApi: "1.5",
    status: "Pass",
    sentinelUnchanged: true,
    finalPartCount: 0,
    noSaveCalled: true,
    steps: AUTORUN_STEPS.map((label) => ({
      label,
      status: "Pass",
      elapsedMs: 1.2,
      sentinelUnchanged: true,
      syncs: [
        {label: "sentinel.before", elapsedMs: 0.1},
        {label: "sentinel.after", elapsedMs: 0.1},
      ],
      partCount: label === "add-duplicate" || label === "detect-duplicate" ? 2 : (label === "cleanup" || label === "inspect-zero" ? 0 : 1),
      ...(label === "set-near-2mib" ? {canonicalBytes: 2093056} : {}),
      ...(label === "add-duplicate" || label === "detect-duplicate" ? {expectedBlockCode: "PQPC_DUPLICATE_XML_PART"} : {}),
      ...(label === "cleanup" ? {deleted: 2} : {}),
    })),
  };
}

function request(port, {method = "GET", path = "/evidence.json", origin, body, contentLength} = {}) {
  return new Promise((resolve, reject) => {
    const payload = body === undefined ? null : Buffer.from(body, "utf8");
    const headers = {};
    if (origin !== undefined) headers.Origin = origin;
    if (payload) {
      headers["Content-Type"] = "application/json";
      headers["Content-Length"] = contentLength === undefined ? payload.length : contentLength;
    }
    const req = http.request({hostname: "127.0.0.1", port, method, path, headers}, (res) => {
      const chunks = [];
      res.on("data", (chunk) => chunks.push(chunk));
      res.on("end", () => resolve({status: res.statusCode, body: Buffer.concat(chunks).toString("utf8")}));
    });
    req.on("error", reject);
    if (payload) req.write(payload);
    req.end();
  });
}

(async () => {
  const allowedOrigin = "https://localhost:3100";
  assert.deepEqual(validateEvidence(evidence()), evidence());
  assert.throws(() => validateEvidence({...evidence(), xml: "<secret/>"}), /unknown fields/);
  assert.throws(() => validateEvidence({...evidence(), status: "Pass", finalPartCount: 1}), /safety gates/);
  const weakNearLimit = evidence();
  weakNearLimit.steps[4].canonicalBytes = 1024;
  assert.throws(() => validateEvidence(weakNearLimit), /near-limit/);
  const weakCleanup = evidence();
  weakCleanup.steps[7].deleted = 1;
  assert.throws(() => validateEvidence(weakCleanup), /exactly the two/);
  const withRawCell = evidence();
  withRawCell.steps[0].values = [["SECRET"]];
  assert.throws(() => validateEvidence(withRawCell), /unknown fields/);

  const store = {latest: null};
  const server = http.createServer(createRequestHandler({allowedOrigin, evidenceStore: store, autorunEnabled: true}));
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const port = server.address().port;
  try {
    const empty = await request(port);
    assert.equal(empty.status, 200);
    assert.deepEqual(JSON.parse(empty.body), {evidence: null});

    const autorunRedirect = await request(port, {path: "/taskpane.html"});
    assert.equal(autorunRedirect.status, 302);

    const rejected = await request(port, {method: "POST", path: "/evidence", origin: "https://evil.example", body: JSON.stringify(evidence())});
    assert.equal(rejected.status, 403);
    assert.equal(store.latest, null);

    const tooLargeBody = JSON.stringify({padding: "x".repeat(EVIDENCE_MAX_BYTES)});
    const tooLarge = await request(port, {method: "POST", path: "/evidence", origin: allowedOrigin, body: tooLargeBody});
    assert.equal(tooLarge.status, 413);
    assert.equal(store.latest, null);

    const invalid = await request(port, {method: "POST", path: "/evidence", origin: allowedOrigin, body: JSON.stringify({...evidence(), payload: "secret"})});
    assert.equal(invalid.status, 400);
    assert.equal(store.latest, null);

    const accepted = await request(port, {method: "POST", path: "/evidence", origin: allowedOrigin, body: JSON.stringify(evidence())});
    assert.equal(accepted.status, 204);
    const readBack = await request(port, {origin: allowedOrigin});
    assert.equal(readBack.status, 200);
    assert.deepEqual(JSON.parse(readBack.body), {evidence: evidence()});
    assert.doesNotMatch(readBack.body, /SECRET/i);
    const forbiddenKeys = new Set(["xml", "payload", "values", "formulas", "numberFormat", "historyHash"]);
    const walk = (value) => {
      if (!value || typeof value !== "object") return;
      for (const [key, child] of Object.entries(value)) {
        assert.equal(forbiddenKeys.has(key), false, `evidence leaked forbidden key ${key}`);
        walk(child);
      }
    };
    walk(JSON.parse(readBack.body));
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
  console.log("Office.js evidence server contract passed");
})().catch((error) => { console.error(error); process.exitCode = 1; });
