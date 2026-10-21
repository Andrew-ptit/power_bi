"use strict";

(function exposeCodec(root, factory) {
  const codec = factory();
  if (typeof module === "object" && module.exports) module.exports = codec;
  root.ProblemChainCodec = codec;
})(typeof globalThis === "undefined" ? this : globalThis, function createCodec() {
  const NAMESPACE = "urn:local-data-copilot:pq-problem-chain:v1";
  const SCHEMA_VERSION = "1.0";
  const MAX_BYTES = 2 * 1024 * 1024;

  function canonicalJson(value) {
    const seen = new Set();
    function normalize(item) {
      if (item === null || typeof item === "string" || typeof item === "boolean") return item;
      if (typeof item === "number") {
        if (!Number.isFinite(item)) throw new Error("Non-finite JSON numbers are forbidden.");
        return item;
      }
      if (Array.isArray(item)) return item.map(normalize);
      if (typeof item !== "object") throw new Error("Value is not JSON data.");
      if (seen.has(item)) throw new Error("Cyclic JSON data is forbidden.");
      seen.add(item);
      const result = {};
      Object.keys(item).sort().forEach((key) => {
        if (typeof item[key] === "undefined") throw new Error("Undefined JSON values are forbidden.");
        result[key] = normalize(item[key]);
      });
      seen.delete(item);
      return result;
    }
    return JSON.stringify(normalize(value));
  }

  function utf8Bytes(text) {
    return new TextEncoder().encode(text);
  }

  function bytesToBase64(bytes) {
    if (typeof Buffer !== "undefined") return Buffer.from(bytes).toString("base64");
    let binary = "";
    const chunk = 0x8000;
    for (let index = 0; index < bytes.length; index += chunk) {
      binary += String.fromCharCode(...bytes.subarray(index, index + chunk));
    }
    return btoa(binary);
  }

  function base64ToBytes(value) {
    if (!/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(value)) {
      throw new Error("Payload is not canonical Base64.");
    }
    if (typeof Buffer !== "undefined") return new Uint8Array(Buffer.from(value, "base64"));
    const binary = atob(value);
    return Uint8Array.from(binary, (character) => character.charCodeAt(0));
  }

  async function sha256Bytes(bytes) {
    if (typeof module === "object" && module.exports) {
      return "sha256:" + require("node:crypto").createHash("sha256").update(bytes).digest("hex");
    }
    const digest = await crypto.subtle.digest("SHA-256", bytes);
    return "sha256:" + Array.from(new Uint8Array(digest), (item) => item.toString(16).padStart(2, "0")).join("");
  }

  async function hashJson(value) {
    return sha256Bytes(utf8Bytes(canonicalJson(value)));
  }

  function escapeAttribute(value) {
    return value.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");
  }

  async function buildXml(document) {
    const canonical = canonicalJson(document);
    const bytes = utf8Bytes(canonical);
    if (bytes.length > MAX_BYTES) throw Object.assign(new Error("Canonical JSON exceeds 2 MiB."), {code: "PQPC_HISTORY_LIMIT"});
    const historyHash = await sha256Bytes(bytes);
    const payload = bytesToBase64(bytes);
    const xml = `<ldc:problemChain xmlns:ldc="${NAMESPACE}" schemaVersion="${SCHEMA_VERSION}" historyHash="${escapeAttribute(historyHash)}"><ldc:payload encoding="base64">${payload}</ldc:payload></ldc:problemChain>`;
    return {
      xml,
      historyHash,
      canonicalBytes: bytes.length,
      xmlBytes: utf8Bytes(xml).length,
    };
  }

  function parseEnvelope(xml) {
    if (/<!\s*(?:DOCTYPE|ENTITY)\b/i.test(xml)) throw new Error("DTD and entities are forbidden.");
    if (typeof DOMParser === "undefined") {
      const root = xml.match(/^<ldc:problemChain xmlns:ldc="([^"]+)" schemaVersion="([^"]+)" historyHash="([^"]+)"><ldc:payload encoding="base64">([^<]+)<\/ldc:payload><\/ldc:problemChain>$/);
      if (!root) throw new Error("Custom XML wrapper is invalid.");
      return {namespace: root[1], schemaVersion: root[2], historyHash: root[3], payload: root[4]};
    }
    const parsed = new DOMParser().parseFromString(xml, "application/xml");
    if (parsed.getElementsByTagName("parsererror").length) throw new Error("Custom XML is not well formed.");
    const root = parsed.documentElement;
    if (root.namespaceURI !== NAMESPACE || root.localName !== "problemChain") throw new Error("Unexpected root or namespace.");
    const children = Array.from(root.children);
    if (children.length !== 1 || children[0].namespaceURI !== NAMESPACE || children[0].localName !== "payload") {
      throw new Error("Exactly one payload element is required.");
    }
    if (children[0].getAttribute("encoding") !== "base64") throw new Error("Payload encoding must be base64.");
    return {
      namespace: root.namespaceURI,
      schemaVersion: root.getAttribute("schemaVersion"),
      historyHash: root.getAttribute("historyHash"),
      payload: children[0].textContent || "",
    };
  }

  async function parseXml(xml) {
    const envelope = parseEnvelope(xml);
    if (envelope.namespace !== NAMESPACE || envelope.schemaVersion !== SCHEMA_VERSION) throw new Error("Unsupported Problem Chain envelope.");
    const bytes = base64ToBytes(envelope.payload);
    if (bytes.length > MAX_BYTES) throw Object.assign(new Error("Canonical JSON exceeds 2 MiB."), {code: "PQPC_HISTORY_LIMIT"});
    let document;
    try {
      document = JSON.parse(new TextDecoder("utf-8", {fatal: true}).decode(bytes));
    } catch (error) {
      throw new Error(`Payload is not UTF-8 JSON: ${error.message}`);
    }
    const canonical = canonicalJson(document);
    if (bytesToBase64(utf8Bytes(canonical)) !== envelope.payload) throw new Error("Payload JSON is not canonical.");
    const actualHash = await sha256Bytes(utf8Bytes(canonical));
    if (actualHash !== envelope.historyHash) throw Object.assign(new Error("historyHash does not match payload."), {code: "PQPC_HASH_MISMATCH"});
    return {document, historyHash: actualHash, canonicalBytes: bytes.length};
  }

  async function makeRepresentativeDocument() {
    const sources = [{kind: "excelTable", objectName: "tblSales", columns: [
      {ordinal: 0, name: "OrderID", type: "text"},
      {ordinal: 1, name: "Qty", type: "integer"},
    ]}];
    const sourceSchemaFingerprint = await hashJson({typeInferencePolicy: "pq-infer-v1", sources});
    const revision = {
      revisionId: "rev_0123456789abcdef01234567",
      parentRevisionId: null,
      originKind: "problem",
      createdAt: "2026-10-13T00:00:00+07:00",
      problemPrompt: "Chuẩn hóa dữ liệu bán hàng – tiếng Việt ✓",
      changeReason: "Wave 0 Office.js transport spike",
      name: "Bản thử Unicode",
      note: "Không chứa dòng mẫu mặc định.",
      annotationUpdatedAt: null,
      sourceSchemaFingerprint,
      snapshotId: "snap_officejs_spike",
      summary: "Kiểm tra round-trip Custom XML.",
      questions: [], assumptions: [], warnings: [], sources, steps: [],
      finalOutputStepId: "stp_source_sales", changeSet: [], validationAtCreation: {}, runtimeSummary: null,
      reviewHash: "",
    };
    revision.reviewHash = await hashJson({
      problemPrompt: revision.problemPrompt,
      sourceSchemaFingerprint: revision.sourceSchemaFingerprint,
      summary: revision.summary,
      questions: revision.questions,
      assumptions: revision.assumptions,
      warnings: revision.warnings,
      sources: revision.sources,
      steps: revision.steps,
      finalOutputStepId: revision.finalOutputStepId,
    });
    return {
      schemaVersion: SCHEMA_VERSION,
      chainId: "chain_officejs_spike",
      planId: "plan_officejs_spike",
      storageVersion: 1,
      headRevisionId: revision.revisionId,
      samplePersistence: {enabled: false, warningAcceptedAt: null, maxRows: 20, maxColumns: 200},
      sampleStore: {},
      revisions: [revision],
    };
  }

  async function makeNearLimitDocument(targetBytes = MAX_BYTES - 4096) {
    if (targetBytes <= 0 || targetBytes > MAX_BYTES) throw new Error("Target must be within the 2 MiB limit.");
    const document = await makeRepresentativeDocument();
    // Transport padding belongs to historical validation metadata. Keeping the
    // sample policy disabled proves that a near-limit payload does not need to
    // smuggle worksheet values into the workbook.
    document.revisions[0].validationAtCreation = {transportPadding: ""};
    let current = utf8Bytes(canonicalJson(document)).length;
    document.revisions[0].validationAtCreation.transportPadding = "x".repeat(Math.max(0, targetBytes - current));
    current = utf8Bytes(canonicalJson(document)).length;
    if (current < targetBytes) document.revisions[0].validationAtCreation.transportPadding += "x".repeat(targetBytes - current);
    while (utf8Bytes(canonicalJson(document)).length > targetBytes) {
      document.revisions[0].validationAtCreation.transportPadding = document.revisions[0].validationAtCreation.transportPadding.slice(0, -1);
    }
    document.storageVersion += 1;
    return document;
  }

  return {
    NAMESPACE, SCHEMA_VERSION, MAX_BYTES, canonicalJson, utf8Bytes, hashJson,
    buildXml, parseXml, makeRepresentativeDocument, makeNearLimitDocument,
  };
});
