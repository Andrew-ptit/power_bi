"use strict";

const fs = require("node:fs");
const https = require("node:https");
const os = require("node:os");
const path = require("node:path");
const {performance} = require("node:perf_hooks");

const root = __dirname;
const defaultPort = Number(process.env.PQPC_SPIKE_PORT || 3100);
const certRoot = path.join(os.homedir(), ".office-addin-dev-certs");
const certPath = process.env.PQPC_SPIKE_CERT || path.join(certRoot, "localhost.crt");
const keyPath = process.env.PQPC_SPIKE_KEY || path.join(certRoot, "localhost.key");
const types = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml"};
const iconPng = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=", "base64");
const EVIDENCE_MAX_BYTES = 32 * 1024;
const DOCUMENT_MAX_BYTES = 2 * 1024 * 1024;
const AUTORUN_STEPS = ["inspect-zero", "add-small", "get-parse", "set-unicode", "set-near-2mib", "add-duplicate", "detect-duplicate", "cleanup"];
const TOP_KEYS = new Set(["schemaVersion", "runId", "capturedAt", "startedAt", "host", "platform", "excelApi", "status", "sentinelUnchanged", "finalPartCount", "noSaveCalled", "steps"]);
const STEP_KEYS = new Set(["label", "status", "elapsedMs", "sentinelUnchanged", "syncs", "partCount", "canonicalBytes", "deleted", "expectedBlockCode", "code"]);
const SYNC_KEYS = new Set(["label", "elapsedMs"]);

function exactKeys(value, allowed, label) {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error(`${label} must be an object.`);
  const keys = Object.keys(value);
  const unknown = keys.filter((key) => !allowed.has(key));
  if (unknown.length) throw new Error(`${label} contains unknown fields.`);
}

function finiteDuration(value, label) {
  if (!Number.isFinite(value) || value < 0 || value > 600000) throw new Error(`${label} must be a finite duration.`);
}

function validateEvidence(value) {
  exactKeys(value, TOP_KEYS, "evidence");
  for (const key of TOP_KEYS) if (!(key in value)) throw new Error(`evidence.${key} is required.`);
  if (value.schemaVersion !== "1.0" || value.host !== "Excel" || value.excelApi !== "1.5") throw new Error("Unsupported evidence identity.");
  if (!/^[A-Za-z0-9-]{10,80}$/.test(value.runId)) throw new Error("Invalid runId.");
  if (typeof value.platform !== "string" || !/^[A-Za-z0-9 ._-]{1,40}$/.test(value.platform)) throw new Error("Invalid platform.");
  if (!Number.isFinite(Date.parse(value.capturedAt)) || !Number.isFinite(Date.parse(value.startedAt))) throw new Error("Invalid evidence timestamp.");
  if (!new Set(["Pass", "Fail"]).has(value.status)) throw new Error("Invalid evidence status.");
  if (typeof value.sentinelUnchanged !== "boolean" || typeof value.noSaveCalled !== "boolean" || value.noSaveCalled !== true) throw new Error("Invalid safety flags.");
  if (!Number.isInteger(value.finalPartCount) || value.finalPartCount < 0 || value.finalPartCount > 2) throw new Error("Invalid finalPartCount.");
  if (!Array.isArray(value.steps) || value.steps.length < 2 || value.steps.length > AUTORUN_STEPS.length) throw new Error("Invalid steps length.");

  const expectedLabels = AUTORUN_STEPS.slice(0, value.steps.length - 1).concat("cleanup");
  value.steps.forEach((step, index) => {
    exactKeys(step, STEP_KEYS, `steps[${index}]`);
    for (const key of ["label", "status", "elapsedMs", "sentinelUnchanged", "syncs"]) {
      if (!(key in step)) throw new Error(`steps[${index}].${key} is required.`);
    }
    if (step.label !== expectedLabels[index]) throw new Error("Autorun step order mismatch.");
    if (!new Set(["Pass", "Fail"]).has(step.status) || typeof step.sentinelUnchanged !== "boolean") throw new Error("Invalid step status.");
    finiteDuration(step.elapsedMs, `steps[${index}].elapsedMs`);
    if (!Array.isArray(step.syncs) || step.syncs.length < 2 || step.syncs.length > 16) throw new Error("Invalid sync measurements.");
    step.syncs.forEach((sync, syncIndex) => {
      exactKeys(sync, SYNC_KEYS, `steps[${index}].syncs[${syncIndex}]`);
      if (typeof sync.label !== "string" || !/^[A-Za-z0-9.-]{1,64}$/.test(sync.label)) throw new Error("Invalid sync label.");
      finiteDuration(sync.elapsedMs, "sync.elapsedMs");
    });
    for (const key of ["partCount", "canonicalBytes", "deleted"]) {
      if (key in step && (!Number.isInteger(step[key]) || step[key] < 0 || step[key] > (key === "canonicalBytes" ? 2 * 1024 * 1024 : 2))) throw new Error(`Invalid ${key}.`);
    }
    if ("expectedBlockCode" in step && step.expectedBlockCode !== "PQPC_DUPLICATE_XML_PART") throw new Error("Invalid expectedBlockCode.");
    if ("code" in step && (typeof step.code !== "string" || !/^[A-Z0-9_]{3,80}$/.test(step.code))) throw new Error("Invalid failure code.");
  });
  if (value.status === "Pass") {
    if (value.steps.length !== AUTORUN_STEPS.length || !value.sentinelUnchanged || value.finalPartCount !== 0 || value.steps.some((step) => step.status !== "Pass" || !step.sentinelUnchanged)) {
      throw new Error("Pass evidence does not satisfy all safety gates.");
    }
    const expectedPartCounts = [0, 1, 1, 1, 1, 2, 2, 0];
    if (value.steps.some((step, index) => step.partCount !== expectedPartCounts[index])) throw new Error("Pass evidence has invalid part counts.");
    const nearLimit = value.steps[4];
    if (!Number.isInteger(nearLimit.canonicalBytes) || nearLimit.canonicalBytes < DOCUMENT_MAX_BYTES - 4098 || nearLimit.canonicalBytes > DOCUMENT_MAX_BYTES) {
      throw new Error("Pass evidence did not exercise the near-limit payload.");
    }
    for (const index of [5, 6]) {
      if (value.steps[index].expectedBlockCode !== "PQPC_DUPLICATE_XML_PART") throw new Error("Pass evidence did not prove duplicate blocking.");
    }
    if (value.steps[7].deleted !== 2) throw new Error("Pass evidence did not clean exactly the two autorun-created parts.");
  }
  return JSON.parse(JSON.stringify(value));
}

function isLocalRequest(request) {
  return new Set(["127.0.0.1", "::1", "::ffff:127.0.0.1"]).has(request.socket && request.socket.remoteAddress);
}

function sendJson(response, status, value) {
  const body = Buffer.from(JSON.stringify(value), "utf8");
  response.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Content-Length": body.length,
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
  });
  response.end(body);
}

function createRequestHandler({allowedOrigin, evidenceStore = {latest: null}, autorunEnabled = false}) {
  return (request, response) => {
    const started = performance.now();
    const requestUrl = new URL(request.url, allowedOrigin);
    const pathname = requestUrl.pathname;
    response.on("finish", () => console.log(JSON.stringify({method: request.method, path: pathname, status: response.statusCode, elapsedMs: Math.round((performance.now() - started) * 10) / 10})));

    if (!isLocalRequest(request)) {
      sendJson(response, 403, {code: "LOCAL_ONLY"});
      return;
    }
    if (pathname === "/evidence.json" && request.method === "GET") {
      const origin = request.headers.origin;
      if (origin && origin !== allowedOrigin) {
        sendJson(response, 403, {code: "ORIGIN_REJECTED"});
        return;
      }
      sendJson(response, 200, {evidence: evidenceStore.latest});
      return;
    }
    if (pathname === "/evidence" && request.method === "POST") {
      if (request.headers.origin !== allowedOrigin) {
        sendJson(response, 403, {code: "ORIGIN_REJECTED"});
        return;
      }
      if (!String(request.headers["content-type"] || "").toLowerCase().startsWith("application/json")) {
        sendJson(response, 415, {code: "CONTENT_TYPE_REQUIRED"});
        return;
      }
      const contentLength = Number(request.headers["content-length"] || 0);
      if (!Number.isFinite(contentLength) || contentLength > EVIDENCE_MAX_BYTES) {
        sendJson(response, 413, {code: "EVIDENCE_TOO_LARGE"});
        request.resume();
        return;
      }
      const chunks = [];
      let size = 0;
      let rejected = false;
      request.on("data", (chunk) => {
        if (rejected) return;
        size += chunk.length;
        if (size > EVIDENCE_MAX_BYTES) {
          rejected = true;
          chunks.length = 0;
        } else chunks.push(chunk);
      });
      request.on("end", () => {
        if (rejected) {
          sendJson(response, 413, {code: "EVIDENCE_TOO_LARGE"});
          return;
        }
        try {
          evidenceStore.latest = validateEvidence(JSON.parse(Buffer.concat(chunks).toString("utf8")));
          response.writeHead(204, {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"});
          response.end();
        } catch (_error) {
          sendJson(response, 400, {code: "EVIDENCE_INVALID"});
        }
      });
      return;
    }

    if (pathname === "/icon.png" && (request.method === "GET" || request.method === "HEAD")) {
      response.writeHead(200, {"Content-Type": "image/png", "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"});
      response.end(request.method === "HEAD" ? undefined : iconPng);
      return;
    }
    if (autorunEnabled && pathname === "/taskpane.html" && request.method === "GET" && requestUrl.searchParams.get("autorun") !== "1") {
      response.writeHead(302, {Location: "/taskpane.html?autorun=1", "Cache-Control": "no-store"});
      response.end();
      return;
    }
    const relative = pathname === "/" ? "taskpane.html" : decodeURIComponent(pathname).replace(/^\/+/, "");
    const target = path.resolve(root, relative);
    if ((request.method !== "GET" && request.method !== "HEAD") || !target.startsWith(root + path.sep) || !fs.existsSync(target) || !fs.statSync(target).isFile()) {
      response.writeHead(404, {"Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store"});
      response.end("Not found");
      return;
    }
    response.writeHead(200, {
      "Content-Type": types[path.extname(target)] || "application/octet-stream",
      "Cache-Control": "no-store",
      "Content-Security-Policy": "default-src 'self' https://appsforoffice.microsoft.com; script-src 'self' https://appsforoffice.microsoft.com; style-src 'self'; connect-src 'self'; img-src 'self' data:",
      "X-Content-Type-Options": "nosniff",
    });
    if (request.method === "HEAD") response.end(); else fs.createReadStream(target).pipe(response);
  };
}

function startServer(port = defaultPort) {
  if (!fs.existsSync(certPath) || !fs.existsSync(keyPath)) {
    console.error("Missing trusted localhost certificate. Run: npx --yes office-addin-dev-certs install");
    process.exitCode = 2;
    return null;
  }
  const allowedOrigin = `https://localhost:${port}`;
  const evidenceStore = {latest: null};
  const server = https.createServer(
    {cert: fs.readFileSync(certPath), key: fs.readFileSync(keyPath)},
    createRequestHandler({allowedOrigin, evidenceStore, autorunEnabled: process.env.PQPC_SPIKE_AUTORUN === "1"}),
  );
  server.listen(port, "127.0.0.1", () => console.log(`Problem Chain Office.js spike: ${allowedOrigin}/taskpane.html`));
  return server;
}

if (require.main === module) startServer();

module.exports = {AUTORUN_STEPS, DOCUMENT_MAX_BYTES, EVIDENCE_MAX_BYTES, createRequestHandler, startServer, validateEvidence};
