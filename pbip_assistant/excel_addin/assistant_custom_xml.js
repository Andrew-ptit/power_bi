/* Assistant Record metadata only. Office.js has no atomic compare-and-set:
 * serialized local writes, a final external-state recheck and read-back detect
 * conflicts, but cannot promise isolation from another pane's concurrent write.
 * Full Decision Records and source cells never belong in this part.
 */
(() => {
  "use strict";
  const ASSISTANT_RECORD_NAMESPACE = "urn:local-data-copilot:assistant-record:v1";
  const LIMIT = 32 * 1024;
  const FIELDS = ["schemaVersion", "id", "hash", "recordHash", "snapshot", "spec", "branch", "createdAt", "labels"].sort();
  const HASH = /^sha256:[0-9a-f]{64}$/;
  const LABELS = new Set(["assumed", "unverified", "out_of_scope", "stale"]);
  let tail = Promise.resolve();

  function fail(code, message, partial = false) {
    const error = new Error(message);
    error.code = code;
    if (partial) { error.written = true; error.retryable = false; }
    return error;
  }
  const invalid = () => fail("AF_RECORD_INVALID", "Assistant Record metadata or XML is invalid.");
  const bytes = (text) => new TextEncoder().encode(text);
  const canonical = (node) => JSON.stringify(Object.fromEntries(Object.keys(node).sort().map((key) => [key, node[key]])));
  function validate(node) {
    if (!node || typeof node !== "object" || Array.isArray(node)
      || Object.getOwnPropertySymbols(node).length
      || JSON.stringify(Object.getOwnPropertyNames(node).sort()) !== JSON.stringify(FIELDS)) throw invalid();
    const descriptors = Object.getOwnPropertyDescriptors(node);
    if (FIELDS.some((key) => !descriptors[key].enumerable || !Object.hasOwn(descriptors[key], "value"))) throw invalid();
    if (node.schemaVersion !== "1.0" || typeof node.id !== "string" || !/^rec_[a-f0-9]{24}$/.test(node.id)
      || !["hash", "recordHash", "snapshot", "spec"].every((key) => typeof node[key] === "string" && HASH.test(node[key]))
      || !["A", "B"].includes(node.branch)
      || typeof node.createdAt !== "string"
      || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,3})?Z$/.test(node.createdAt)
      || !Number.isFinite(Date.parse(node.createdAt))
      || new Date(node.createdAt).toISOString().replace(/\.000Z$/, "Z") !== node.createdAt.replace(/\.(\d{1,3})Z$/, (_, digits) => "." + digits.padEnd(3, "0") + "Z").replace(/\.000Z$/, "Z")
      || !Array.isArray(node.labels) || node.labels.length > LABELS.size
      || node.labels.some((label) => typeof label !== "string" || !LABELS.has(label))
      || new Set(node.labels).size !== node.labels.length) throw invalid();
    // All strings have closed formats; nested arrays, raw cells and paths cannot
    // pass the allowlist. Reject exotic arrays with hidden or extra properties.
    if (Object.getOwnPropertySymbols(node.labels).length
      || Object.getOwnPropertyNames(node.labels).some((key) => key !== "length" && !/^(0|[1-9]\d*)$/.test(key))
      || Object.keys(node.labels).length !== node.labels.length) throw invalid();
    return node;
  }
  async function digest(node) {
    if (!globalThis.crypto?.subtle?.digest) throw fail("AF_CRYPTO_UNAVAILABLE", "WebCrypto SHA-256 is required for Assistant Records.");
    const basis = Object.fromEntries(Object.keys(node).filter((key) => key !== "hash").sort().map((key) => [key, node[key]]));
    const result = await globalThis.crypto.subtle.digest("SHA-256", bytes(canonical(basis)));
    return "sha256:" + Array.from(new Uint8Array(result), (value) => value.toString(16).padStart(2, "0")).join("");
  }
  async function verifyAssistantRecordHash(node) {
    try { validate(node); } catch (_) { return false; }
    return (await digest(node)) === node.hash;
  }
  function encode(text) {
    let binary = "";
    for (const value of bytes(text)) binary += String.fromCharCode(value);
    return btoa(binary);
  }
  function build(node) {
    const xml = `<ldc:assistantRecord xmlns:ldc="${ASSISTANT_RECORD_NAMESPACE}"><ldc:payload encoding="base64">${encode(canonical(node))}</ldc:payload></ldc:assistantRecord>`;
    if (bytes(xml).length > LIMIT) throw invalid();
    return xml;
  }
  async function parse(xml) {
    if (typeof xml !== "string" || bytes(xml).length > LIMIT || /<!|<\?(?!xml\s)/i.test(xml)) throw invalid();
    if (xml.startsWith("<?xml")) {
      const declaration = xml.match(/^<\?xml\s+([^?]*)\?>\s*/);
      // This is already a JavaScript string. Native getXml() may retain the
      // package's UTF-16 declaration without changing the string's code points.
      if (!declaration || !/^version="1\.0"(?:\s+encoding="[Uu][Tt][Ff]-(?:8|16)")?(?:\s+standalone="(?:yes|no)")?\s*$/.test(declaration[1])) throw invalid();
      xml = xml.slice(declaration[0].length);
    }
    // Accept only our closed envelope, with an optional Office XML declaration.
    // There is no general XML expansion, entity resolution or fallback parser.
    const match = xml.match(/^<ldc:assistantRecord xmlns:ldc="urn:local-data-copilot:assistant-record:v1"><ldc:payload encoding="base64">([A-Za-z0-9+/]*={0,2})<\/ldc:payload><\/ldc:assistantRecord>$/);
    if (!match || !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(match[1])) throw invalid();
    let node;
    let decoded;
    try {
      decoded = new TextDecoder("utf-8", {fatal: true}).decode(Uint8Array.from(atob(match[1]), (value) => value.charCodeAt(0)));
      node = JSON.parse(decoded);
      validate(node);
    } catch (_) { throw invalid(); }
    if (canonical(node) !== decoded || !(await verifyAssistantRecordHash(node))) throw invalid();
    return node;
  }
  function supported() {
    if (!globalThis.Office?.context?.requirements?.isSetSupported("ExcelApi", "1.5") || !globalThis.Excel?.run) {
      throw fail("PQPC_EXCEL_API_UNSUPPORTED", "Assistant Records require ExcelApi 1.5.");
    }
  }
  function workbookBinding(expectedWorkbook) {
    if (expectedWorkbook === undefined) return undefined;
    if (!expectedWorkbook || typeof expectedWorkbook !== "object" || Array.isArray(expectedWorkbook)
      || JSON.stringify(Object.keys(expectedWorkbook).sort()) !== JSON.stringify(["name", "url"])
      || typeof expectedWorkbook.name !== "string" || !expectedWorkbook.name
      || typeof expectedWorkbook.url !== "string") throw invalid();
    return {name: expectedWorkbook.name, url: expectedWorkbook.url};
  }
  function assertWorkbook(context, expectedWorkbook) {
    if (expectedWorkbook !== undefined && (context.workbook.name !== expectedWorkbook.name
      || (globalThis.Office?.context?.document?.url || "") !== expectedWorkbook.url)) {
      throw fail("AF_SPEC_STALE", "Workbook changed before Assistant Record access.");
    }
  }
  async function checkWorkbook(context, expectedWorkbook) {
    if (expectedWorkbook === undefined) return;
    context.workbook.load("name");
    await context.sync();
    assertWorkbook(context, expectedWorkbook);
  }
  async function raw(context) {
    const collection = context.workbook.customXmlParts.getByNamespace(ASSISTANT_RECORD_NAMESPACE);
    collection.load("items/id");
    await context.sync();
    if (collection.items.length > 1) throw fail("PQPC_DUPLICATE_XML_PART", "Multiple Assistant Record XML parts exist.");
    if (!collection.items.length) return {part: null, xml: null};
    const part = collection.items[0];
    const result = part.getXml();
    await context.sync();
    return {part, xml: result.value};
  }
  const serial = (operation) => {
    const result = tail.then(operation, operation);
    tail = result.catch(() => {});
    return result;
  };
  async function readAssistantRecord(expectedWorkbook) {
    supported();
    expectedWorkbook = workbookBinding(expectedWorkbook);
    return serial(() => Excel.run(async (context) => {
      await checkWorkbook(context, expectedWorkbook);
      const current = await raw(context);
      const node = current.part ? await parse(current.xml) : null;
      await checkWorkbook(context, expectedWorkbook);
      return node;
    }));
  }
  async function change(node, expectedHash, clear, expectedWorkbook) {
    supported();
    expectedWorkbook = workbookBinding(expectedWorkbook);
    if (!clear) {
      validate(node);
      node = JSON.parse(canonical(node));
      if (!(await verifyAssistantRecordHash(node))) throw invalid();
      if (expectedHash !== null && (typeof expectedHash !== "string" || !HASH.test(expectedHash))) throw invalid();
    }
    const xml = clear ? null : build(node);
    return serial(() => Excel.run(async (context) => {
      await checkWorkbook(context, expectedWorkbook);
      const original = await raw(context);
      const old = original.part ? await parse(original.xml) : null;
      if (!clear && (old?.hash ?? null) !== expectedHash) {
        throw fail("PQPC_HISTORY_CONFLICT", "Assistant Record changed; reload before writing.");
      }
      // Hashing may yield to another pane. Re-read immediately before mutation;
      // compare the already verified bytes so no further async hash precedes it.
      await checkWorkbook(context, expectedWorkbook);
      const fresh = await raw(context);
      assertWorkbook(context, expectedWorkbook);
      if ((fresh.part?.id ?? null) !== (original.part?.id ?? null) || fresh.xml !== original.xml) {
        throw fail("PQPC_HISTORY_CONFLICT", "Assistant Record changed before writing.");
      }
      if (clear && !fresh.part) return {cleared: true};
      try {
        if (clear) fresh.part.delete();
        else if (fresh.part) fresh.part.setXml(xml);
        else context.workbook.customXmlParts.add(xml);
        await context.sync();
        const observed = await raw(context);
        if (clear) {
          if (observed.part) throw invalid();
          return {cleared: true};
        }
        if (!observed.part) throw invalid();
        const restored = await parse(observed.xml);
        if (restored.hash !== node.hash || canonical(restored) !== canonical(node)) throw invalid();
        return {written: true, hash: restored.hash};
      } catch (_) {
        throw fail("AF_WRITE_PARTIAL", "Assistant Record write or read-back is partial/unknown; reload before continuing.", true);
      }
    }));
  }
  const writeAssistantRecord = (node, expectedHash, expectedWorkbook) => change(node, expectedHash, false, expectedWorkbook);
  const clearAssistantRecord = () => change(null, null, true);
  globalThis.AssistantRecordXml = Object.freeze({ASSISTANT_RECORD_NAMESPACE, readAssistantRecord,
    writeAssistantRecord, clearAssistantRecord, verifyAssistantRecordHash});
})();
