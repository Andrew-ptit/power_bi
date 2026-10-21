"use strict";

const assert = require("node:assert/strict");
const codec = require("./problem_chain_codec.js");

(async () => {
  assert.equal(codec.canonicalJson({z: 1, a: {b: "✓", a: 2}}), '{"a":{"a":2,"b":"✓"},"z":1}');
  const document = await codec.makeRepresentativeDocument();
  assert.equal(document.samplePersistence.enabled, false);
  assert.deepEqual(document.sampleStore, {});
  assert.equal(codec.canonicalJson(document).includes("CELL_SAMPLE_SENTINEL"), false);

  const built = await codec.buildXml(document);
  const parsed = await codec.parseXml(built.xml);
  assert.deepEqual(parsed.document, document);
  assert.equal(parsed.historyHash, built.historyHash);
  assert.match(parsed.document.revisions[0].problemPrompt, /tiếng Việt/);

  const reordered = JSON.parse(JSON.stringify(document));
  const rebuilt = await codec.buildXml(reordered);
  assert.equal(rebuilt.historyHash, built.historyHash);

  await assert.rejects(codec.parseXml(built.xml.replace(/sha256:[0-9a-f]{64}/, "sha256:" + "0".repeat(64))), /historyHash/);
  await assert.rejects(codec.parseXml(`<!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]>${built.xml}`), /DTD/);
  await assert.rejects(codec.parseXml(built.xml.replace(/>eyJ/, ">***eyJ")), /Base64|wrapper/);

  const target = codec.MAX_BYTES - 4096;
  const large = await codec.makeNearLimitDocument(target);
  const largeBuilt = await codec.buildXml(large);
  assert.ok(largeBuilt.canonicalBytes >= target - 2 && largeBuilt.canonicalBytes <= target + 64, `${largeBuilt.canonicalBytes} not near ${target}`);
  assert.deepEqual((await codec.parseXml(largeBuilt.xml)).document, large);

  const tooLarge = JSON.parse(JSON.stringify(large));
  tooLarge.revisions[0].validationAtCreation.transportPadding += "x".repeat(8192);
  await assert.rejects(codec.buildXml(tooLarge), (error) => error.code === "PQPC_HISTORY_LIMIT");
  console.log(JSON.stringify({status: "passed", smallCanonicalBytes: built.canonicalBytes, nearLimitCanonicalBytes: largeBuilt.canonicalBytes, nearLimitXmlBytes: largeBuilt.xmlBytes}));
})().catch((error) => { console.error(error); process.exitCode = 1; });
