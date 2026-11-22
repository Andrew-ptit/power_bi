"use strict";

// T404: understand-step view tests: overview counts, key sentences, in-place
// answers, per_sheet mode, HTML-safe rendering and a11y/CSS constraints.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const understand = require("../../pbip_assistant/excel_addin/assistant_understand.js");

const HTML = fs.readFileSync(path.join(__dirname, "../../pbip_assistant/excel_addin/taskpane.html"), "utf8");
const CSS = fs.readFileSync(path.join(__dirname, "../../pbip_assistant/excel_addin/taskpane.css"), "utf8");
const FIXTURES = path.join(__dirname, "../fixtures/assistant/model_view");
const star = JSON.parse(fs.readFileSync(path.join(FIXTURES, "star_model_valid.json"), "utf8"));
const perSheet = JSON.parse(fs.readFileSync(path.join(FIXTURES, "per_sheet_valid.json"), "utf8"));

class Node {
  constructor() { this.hidden = false; this.disabled = false; this.textContent = ""; this.className = ""; this.listeners = {}; this.attrs = {}; this.children = []; }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  setAttribute(name, value) { this.attrs[name] = value; }
  replaceChildren(...children) { this.children = children; }
  appendChild(child) { this.children.push(child); }
  async click() { if (!this.disabled) await this.listeners.click?.(); }
  async change(value) { this.value = value; await this.listeners.change?.(); }
}

function textOf(node) {
  return [node.textContent, ...node.children.map(textOf)].filter(Boolean).join(" ");
}

function makeDocument() {
  const nodes = new Map();
  const document = {
    getElementById: id => { if (!nodes.has(id)) nodes.set(id, new Node()); return nodes.get(id); },
    createElement: () => new Node(),
  };
  return {document, get: document.getElementById};
}

function mount(overrides = {}) {
  const {document, get} = makeDocument();
  const answers = {};
  const calls = {answers: [], continues: 0};
  const ui = understand.mount({
    document,
    getState: () => ({modelView: star, questions: [], answers, message: ""}),
    setAnswer: (questionId, option) => { calls.answers.push([questionId, option]); answers[questionId] = option; ui.render(); },
    onContinue: () => { calls.continues++; },
    diagram: {layout: () => ({width: 320, height: 100, nodes: [], wires: []}), render: () => {}},
    ...overrides,
  });
  return {ui, get, calls};
}

(async () => {
  // 1. Overview counts match the modelView.
  {
    const questions = [
      {id: "q_rel_orphan", topic: "relationship", question: "?", whyItMatters: "w", kind: "single_choice", options: ["Xác nhận"], evidence: []},
      {id: "q_rel_fanout", topic: "relationship", question: "?", whyItMatters: "w", kind: "single_choice", options: ["Xác nhận"], evidence: []},
      {id: "q_grain_inventory", topic: "grain", question: "?", whyItMatters: "w", kind: "single_choice", options: ["Đúng, là ảnh chụp"], evidence: []},
    ];
    const {get} = mount({getState: () => ({modelView: star, questions, answers: {}, message: ""})});
    const overview = get("assistant-understand-overview").textContent;
    assert.match(overview, /8 bảng/, "table count");
    assert.match(overview, /3 giao dịch/, "fact count");
    assert.match(overview, /7 quan hệ/, "relationship count");
    assert.match(overview, /3 mục cần xác nhận/, "needsConfirm count");
    assert.match(overview, /2 cảnh báo/, "warning count");
    assert.match(get("assistant-understand-status").textContent, /Còn 3 mục cần xác nhận/);
  }

  // 2. Key sentence follows the key column; missing keys say so.
  {
    const noKey = JSON.parse(JSON.stringify(star));
    noKey.tables[0].keys = [];
    const {ui, get} = mount({getState: () => ({modelView: noKey, questions: [], answers: {}, message: ""})});
    const tables = get("assistant-understand-tables").children;
    assert.match(textOf(tables[0]), /Chưa tìm thấy khóa duy nhất/);
    assert.match(textOf(tables[1]), /Mỗi dòng ứng với một order_item_id/);
    assert.equal(ui.keySentence(star.tables[0]), "Mỗi dòng ứng với một order_id");
  }

  // 3. Answering a fan-out relationship calls setAnswer with questionId + option.
  {
    const questions = [
      {id: "q_rel_fanout", topic: "relationship", question: "Xác nhận nối?", whyItMatters: "w",
       kind: "single_choice", options: ["Xác nhận", "Không nối", "Cần làm rõ"], evidence: []},
      {id: "q_rel_orphan", topic: "relationship", question: "Xác nhận nối?", whyItMatters: "w",
       kind: "single_choice", options: ["Xác nhận", "Không nối", "Cần làm rõ"], evidence: []},
    ];
    const {get, calls} = mount({getState: () => ({modelView: star, questions, answers: {}, message: ""})});
    const items = get("assistant-understand-relationships").children;
    assert.ok(items.length >= 7, "every relationship is listed");
    const withQuestion = items.find(item => textOf(item).includes("nhân dòng"));
    assert.ok(withQuestion, "fan-out row exists");
    const buttons = withQuestion.children.filter(child => child.className === "understand-options")[0].children;
    await buttons[0].click();
    assert.deepEqual(calls.answers.at(-1), ["q_rel_fanout", "Xác nhận"], "setAnswer gets questionId and option string");
  }

  // 4. Answered questions show their state and stay editable.
  {
    const questions = [
      {id: "q_rel_orphan", topic: "relationship", question: "Xác nhận nối?", whyItMatters: "w",
       kind: "single_choice", options: ["Xác nhận", "Không nối", "Cần làm rõ"], evidence: []},
    ];
    const {get, calls} = mount({
      getState: () => ({modelView: star, questions, answers: {q_rel_orphan: "Không nối"}, message: ""}),
      setAnswer: (questionId, option) => { calls.answers.push([questionId, option]); },
    });
    const relItems = get("assistant-understand-relationships").children;
    const item = relItems.find(child => textOf(child).includes("mã không khớp"));
    assert.match(textOf(item), /Đã trả lời: Không nối/, "answered state is visible");
    // The answer button for the same option is disabled, others remain clickable.
    const buttons = item.children.filter(child => child.className === "understand-options")[0].children;
    assert.ok(buttons.find(button => button.textContent === "Không nối").disabled, "chosen option is disabled");
    await buttons.find(button => button.textContent === "Xác nhận").click();
    assert.deepEqual(calls.answers.at(-1), ["q_rel_orphan", "Xác nhận"], "the answer can be changed");
  }

  // 5. per_sheet shows the explanation and still enables Tiếp tục.
  {
    const {get} = mount({getState: () => ({modelView: perSheet, questions: [], answers: {}, message: ""})});
    assert.match(get("assistant-understand-message").textContent, /Chưa đủ bằng chứng để dựng mô hình quan hệ/);
    assert.equal(get("assistant-understand-continue").disabled, false);
  }

  // 6. Sample measurement shows the fixed warning.
  {
    const sample = JSON.parse(JSON.stringify(star));
    sample.measuredOn = "sample";
    const {get} = mount({getState: () => ({modelView: sample, questions: [], answers: {}, message: ""})});
    assert.match(get("assistant-understand-message").textContent, /đo trên mẫu và có thể thiếu hoặc sai/);
  }

  // 7. Sheet/column names containing HTML are rendered as text.
  {
    const hostile = JSON.parse(JSON.stringify(star));
    hostile.tables[0].name = "<script>alert(1)</script>";
    const {get} = mount({getState: () => ({modelView: hostile, questions: [], answers: {}, message: ""})});
    const tables = get("assistant-understand-tables").children;
    assert.ok(textOf(tables[0]).includes("<script>alert(1)</script>"), "name rendered as plain text");
    assert.ok(!tables[0].children.some(child => child.tagName === "SCRIPT"), "no script element");
  }

  // 8. Tiếp tục fires onContinue.
  {
    const {get, calls} = mount();
    await get("assistant-understand-continue").click();
    assert.equal(calls.continues, 1);
  }

  // 9. Diagram toggle switches between list and diagram and keeps the list default.
  {
    let rendered = 0;
    const {ui, get} = mount({diagram: {
      layout: () => ({width: 320, height: 100, nodes: [], wires: []}),
      render: (container, layout) => { rendered++; container.append(layout); },
    }});
    assert.equal(get("assistant-understand-relationships").hidden, false);
    assert.equal(get("assistant-understand-diagram").hidden, true);
    await get("assistant-rel-diagram-button").click();
    assert.equal(get("assistant-understand-relationships").hidden, true);
    assert.equal(get("assistant-understand-diagram").hidden, false);
    assert.equal(rendered, 1, "focus diagram rendered once");
    assert.equal(get("assistant-rel-diagram-button").attrs["aria-pressed"], "true");
    await get("assistant-rel-list-button").click();
    assert.equal(get("assistant-understand-relationships").hidden, false);
  }

  // 10. a11y: aria-current steps, aria-live status, 32px buttons, no fixed width > 360px.
  {
    assert(HTML.includes('id="assistant-step-understand"'), "understand step button exists");
    assert.match(HTML, /id="assistant-understand-status"[^>]*role="status"[^>]*aria-live="polite"/, "aria-live status");
    assert.match(HTML, /id="assistant-understand-message"[^>]*role="status"[^>]*aria-live="polite"/, "aria-live message");
    assert.match(CSS, /\.button\s*\{[^}]*min-height:\s*32px/s, "buttons are at least 32px tall");
    for (const line of CSS.split("\n")) {
      if (line.trimStart().startsWith("@media")) continue;
      const match = line.match(/width:\s*(\d+)px/);
      if (match) assert.ok(Number(match[1]) <= 360, "no fixed width above 360px: " + line.trim());
    }
    for (const id of ["assistant-step-source", "assistant-step-understand", "assistant-step-problem"]) {
      assert(HTML.includes(`id="${id}"`), id + " exists");
    }
  }

  console.log("assistant understand view: 10 cases passed");
})().catch(error => { console.error(error); process.exit(1); });