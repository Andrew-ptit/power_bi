"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const root = __dirname;
const js = fs.readFileSync(path.join(root, "taskpane.js"), "utf8");
const html = fs.readFileSync(path.join(root, "taskpane.html"), "utf8");
const manifest = fs.readFileSync(path.join(root, "manifest.xml"), "utf8");

assert.match(js, /isSetSupported\("ExcelApi", "1\.5"\)/);
assert.match(js, /customXmlParts\.getByNamespace/);
assert.match(js, /customXmlParts\.add/);
assert.match(js, /\.getXml\(\)/);
assert.match(js, /\.setXml\(/);
assert.match(js, /\.delete\(\)/);
assert.doesNotMatch(js, /workbook\.save|\.save\(\)/i);
assert.match(js, /SOURCE_SENTINEL_CHANGED/);
assert.match(js, /performance\.now/);
assert.match(js, /URLSearchParams\(window\.location\.search\).*autorun/s);
assert.match(js, /measuredSync/);
assert.match(js, /fetch\("\/evidence"/);
assert.match(js, /historyHash: value && value\.historyHash/);
assert.match(js, /function redactedStep/);
assert.match(html, /không tự Save/i);
assert.match(html, /Save As/);
assert.match(manifest, /DefaultMinVersion="1\.1"/);
assert.match(manifest, /https:\/\/localhost:3100\/taskpane\.html/);
assert.match(manifest, /https:\/\/localhost:3100\/icon\.png/);
assert.doesNotMatch(manifest, /localhost:3000/);
console.log("Office.js spike static contract passed");
