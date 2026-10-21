"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../../pbip_assistant/excel_addin/taskpane.js"), "utf8");
const elements = new Map();
function element(id) {
  if (!elements.has(id)) {
    const listeners = {};
    elements.set(id, {
      listeners,
      value: "Phân tích dữ liệu",
      disabled: false, textContent: "", checked: false,
      clicks: 0,
      classList: {toggle() {}},
      setAttribute() {},
      addEventListener(type, callback) { listeners[type] = callback; },
      click() { this.clicks += 1; },
    });
  }
  return elements.get(id);
}
const sandbox = {document: {getElementById: element, addEventListener() {}}};
vm.runInNewContext(source + "\nglobalThis.__bindEvents = bindEvents;", sandbox);
sandbox.__bindEvents();

const prompt = element("prompt");
const analyze = element("analyze-button");
assert.equal(typeof analyze.listeners.click, "function");

function keydown(overrides) {
  let prevented = false;
  prompt.listeners.keydown({
    key: "Enter", ctrlKey: true, altKey: false, metaKey: false,
    shiftKey: false, isComposing: false, repeat: false,
    preventDefault() { prevented = true; },
    ...overrides,
  });
  return prevented;
}

assert.equal(keydown({}), true);
assert.equal(analyze.clicks, 1);
for (const overrides of [
  {ctrlKey: false}, {key: "a"}, {altKey: true}, {metaKey: true},
  {shiftKey: true}, {isComposing: true}, {repeat: true},
]) {
  assert.equal(keydown(overrides), false);
}
analyze.disabled = true;
assert.equal(keydown({}), false);
assert.equal(analyze.clicks, 1);
console.log("taskpane shortcut test passed");
