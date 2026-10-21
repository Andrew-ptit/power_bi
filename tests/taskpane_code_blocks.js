"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../pbip_assistant/excel_addin/taskpane.js"), "utf8");
const html = fs.readFileSync(path.join(__dirname, "../pbip_assistant/excel_addin/taskpane.html"), "utf8");
const elements = new Map();
let selectedText = "";
function makeElement(tagName) {
  return {
    tagName, children: [], attributes: {}, className: "", textContent: "", value: "",
    checked: false, disabled: false, dataset: {}, handlers: {},
    classList: {toggle() {}},
    append(...children) { this.children.push(...children); },
    appendChild(child) { this.children.push(child); },
    replaceChildren() { this.children = []; },
    setAttribute(name, value) { this.attributes[name] = value; },
    addEventListener(name, handler) { this.handlers[name] = handler; },
    select() { selectedText = this.value; },
    remove() {},
    style: {},
  };
}
function byId(id) {
  if (!elements.has(id)) elements.set(id, makeElement("div"));
  return elements.get(id);
}
function descendants(element, tagName) {
  return element.children.flatMap((child) => [
    ...(child.tagName === tagName ? [child] : []),
    ...descendants(child, tagName),
  ]);
}
const copied = [];
const sandbox = {
  document: {
    getElementById: byId, createElement: makeElement, addEventListener() {},
    body: makeElement("body"), execCommand: () => { copied.push(selectedText); return true; },
  },
  navigator: {clipboard: {writeText: async (value) => { copied.push(value); }}},
};
vm.runInNewContext(source + "\nglobalThis.__renderPlan = renderPlan;", sandbox);

const formula = '=TEXTBEFORE(B2;"-")';
const mCode = 'let Source = Excel.CurrentWorkbook(){[Name="PQ_Input"]}[Content] in Source';
sandbox.__renderPlan({
  status: "analysis_only", canApply: false, summary: "Xóa dòng rỗng và trùng.",
  questions: [], assumptions: ["Mã đơn hàng là text."], warnings: ["Cần kiểm tra tên cột."],
  operations: [{id: "op1", target: "Raw_Orders[D]", formula, reason: "Lấy prefix."}],
  codeBlocks: [{language: "m", label: "M làm sạch", code: mCode}],
  hardBlockers: [],
  preview: {
    label: "Simulated preview", beforeColumns: ["Order"], beforeRows: [["A1"]],
    afterColumns: ["Order"], afterRows: [["FABRICATED"]],
  },
});
assert.equal(byId("plan-summary").textContent, "Xóa dòng rỗng và trùng.");
assert.equal(descendants(byId("warning-list"), "li")[0].textContent, "Cần kiểm tra tên cột.");
assert.equal(descendants(byId("analysis-notes"), "li")[0].textContent, "Giả định: Mã đơn hàng là text.");
assert.equal(descendants(byId("operation-list"), "code")[0].textContent, formula);
assert.equal(descendants(byId("code-list"), "code")[0].textContent, mCode);
assert.equal(descendants(byId("operation-list"), "input")[0].disabled, true);
assert.equal(descendants(byId("before-table"), "td")[0].textContent, "A1");
assert.equal(descendants(byId("after-table"), "td").length, 0, "simulated after-values must never render");
assert.match(byId("preview-label").textContent, /chưa có kết quả sau được kiểm chứng/i);
assert.doesNotMatch(html, /id="after-table"|Kết quả dự kiến|preview mô phỏng/);

(async () => {
  const buttons = [
    ...descendants(byId("operation-list"), "button"),
    ...descendants(byId("code-list"), "button"),
  ];
  assert.equal(buttons.length, 2);
  await buttons[0].handlers.click();
  await buttons[1].handlers.click();
  assert.deepEqual(copied, [formula, mCode]);
  assert.equal(buttons[1].textContent, "Đã sao chép");
  sandbox.navigator.clipboard = null;
  await buttons[1].handlers.click();
  assert.equal(copied[2], mCode, "fallback must copy only M, not surrounding prose");
  console.log("taskpane code blocks test passed");
})().catch((error) => { console.error(error); process.exitCode = 1; });
