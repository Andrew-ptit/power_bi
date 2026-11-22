"use strict";

// T406: expanded 1:3 dialog — capability gate, protocol, sync, answers, stale, limits.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const understand = require("../../pbip_assistant/excel_addin/assistant_understand.js");
const dialog = require("../../pbip_assistant/excel_addin/model_dialog.js");

const FIXTURES = path.join(__dirname, "../fixtures/assistant/model_view");
const star = JSON.parse(fs.readFileSync(path.join(FIXTURES, "star_model_valid.json"), "utf8"));

class Node {
  constructor() {
    this.hidden = false; this.disabled = false; this.textContent = ""; this.className = ""; this.listeners = {}; this.attrs = {}; this.children = []; this.classes = new Set();
    this.classList = {
      add: (...names) => names.forEach(name => this.classes.add(name)),
      remove: (...names) => names.forEach(name => this.classes.delete(name)),
      contains: name => this.classes.has(name),
    };
  }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  setAttribute(name, value) { this.attrs[name] = value; }
  getAttribute(name) { return this.attrs[name]; }
  replaceChildren(...children) { this.children = children; }
  appendChild(child) { this.children.push(child); }
  async click() { if (!this.disabled) await this.listeners.click?.(); }
  querySelectorAll(selector) {
    const match = selector.match(/\[data-([a-z-]+)(?:="([^"]+)")?\]/);
    if (!match) return [];
    const value = match[2];
    return this.children.filter(child => {
      const actual = child.getAttribute("data-" + match[1]);
      return value === undefined ? actual !== undefined : actual === value;
    });
  }
}

function makeDocument() {
  const nodes = new Map();
  const document = {
    getElementById: id => { if (!nodes.has(id)) nodes.set(id, new Node()); return nodes.get(id); },
    createElement: () => new Node(),
  };
  return {document, get: document.getElementById};
}

function textOf(node) {
  return [node.textContent, ...node.children.map(textOf)].filter(Boolean).join(" ");
}

function fakeDiagram() {
  return {
    layout: () => ({width: 600, height: 200, nodes: [], wires: []}),
    render: (container, layout, handlers) => {
      for (const wire of [{id: "rel_orders_customers"}, {id: "rel_bridge_products"}]) {
        const group = new Node();
        group.setAttribute("data-relationship-id", wire.id);
        group.addEventListener("click", () => handlers?.onSelectWire?.(wire.id));
        container.appendChild(group);
      }
      const group = new Node();
      group.setAttribute("data-table-id", "t_orders");
      group.addEventListener("click", () => handlers?.onSelectTable?.("t_orders"));
      container.appendChild(group);
    },
  };
}

(async () => {
  // 1. DialogApi 1.2 unsupported → the button stays hidden, no displayDialogAsync.
  {
    const {document, get} = makeDocument();
    let displayed = 0;
    const office = {context: {requirements: {isSetSupported: () => false},
      ui: {displayDialogAsync: () => { displayed++; }}}};
    understand.mount({document, getState: () => ({modelView: star, questions: [], answers: {}}),
      setAnswer: () => {}, onContinue: () => {}, diagram: fakeDiagram(), office});
    assert.equal(get("assistant-understand-expand").hidden, true, "button hidden without DialogApi 1.2");
    await get("assistant-understand-expand").click();
    assert.equal(displayed, 0, "no displayDialogAsync call without support");
    console.log("ok - unsupported DialogApi hides the button and never opens");
  }

  // 2. Open: same-origin URL without query; model is sent only after ready.
  {
    const {document, get} = makeDocument();
    const calls = {display: [], sent: []};
    const dialogHandlers = {};
    const fakeDialog = {
      messageChild: raw => calls.sent.push(JSON.parse(raw)),
      addEventListener: (name, fn) => { dialogHandlers[name] = fn; },
    };
    const office = {context: {
      requirements: {isSetSupported: (set, version) => set === "DialogApi" && version === "1.2"},
      ui: {displayDialogAsync: (url, options, callback) => { calls.display.push(url); callback({value: fakeDialog}); }},
    }};
    understand.mount({document, getState: () => ({modelView: star, questions: [], answers: {}}),
      setAnswer: () => {}, onContinue: () => {}, diagram: fakeDiagram(), office});
    assert.equal(get("assistant-understand-expand").hidden, false, "button visible with DialogApi 1.2");
    await get("assistant-understand-expand").click();
    assert.equal(calls.display.length, 1);
    assert.equal(calls.display[0], "/model_dialog.html", "same-origin dialog URL");
    assert.ok(!calls.display[0].includes("?"), "no query data in the URL");
    assert.equal(calls.sent.length, 0, "nothing sent before ready");
    dialogHandlers.dialogMessageReceived({message: JSON.stringify({type: "ready"})});
    assert.equal(calls.sent.at(-1).type, "model", "model is sent after ready");
    assert.equal(calls.sent.at(-1).modelView.modelViewHash, star.modelViewHash);
    assert.ok(!JSON.stringify(calls.sent.at(-1)).includes("token"), "no token in messages");
    console.log("ok - open URL, ready-first protocol, model payload");
  }

  // 3. Selecting a relationship in the left list marks the wire, and vice versa.
  {
    const {document, get} = makeDocument();
    const sent = [];
    const office = {context: {ui: {messageParent: raw => sent.push(JSON.parse(raw)),
      addEventHandler: () => {}}}};
    const ui = dialog.mount({document, office, diagram: fakeDiagram()});
    assert.equal(sent[0].type, "ready", "dialog announces ready on load");
    ui.handleMessage(JSON.stringify({type: "model", modelView: star, answers: {}, questions: []}));
    const entries = get("model-dialog-relationships").children;
    assert.ok(entries.length >= 7, "relationship list rendered");
    await entries[0].children[0].click(); // first entry's button
    const host = get("model-dialog-diagram-host");
    const marked = host.children.find(child => child.classList.contains("diagram-selected"));
    assert.equal(marked.getAttribute("data-relationship-id"), "rel_orders_customers",
      "left selection marks the matching wire");
    // And reverse: selecting the wire highlights the left entry.
    const wire = host.children.find(child => child.getAttribute("data-relationship-id") === "rel_bridge_products");
    await wire.click();
    const freshEntries = get("model-dialog-relationships").children;
    const markedEntry = freshEntries.find(entry => entry.className.includes("diagram-selected"));

    assert.ok(textOf(markedEntry).includes("t_bridge.product_id → t_products.product_id"),
      "wire selection marks the left entry");
    console.log("ok - left/right selection sync");
  }

  // 4. Valid answers reach setAnswer; bad hash/option/unknown messages are dropped.
  {
    const {document, get} = makeDocument();
    const calls = {answers: [], sent: []};
    const dialogHandlers = {};
    const fakeDialog = {
      messageChild: raw => calls.sent.push(JSON.parse(raw)),
      addEventListener: (name, fn) => { dialogHandlers[name] = fn; },
    };
    const questions = [{id: "q_rel_fanout", topic: "relationship", question: "?", whyItMatters: "w",
      kind: "single_choice", options: ["Xác nhận", "Không nối", "Cần làm rõ"], evidence: []}];
    const office = {context: {
      requirements: {isSetSupported: () => true},
      ui: {displayDialogAsync: (url, options, callback) => callback({value: fakeDialog})},
    }};
    understand.mount({document, getState: () => ({modelView: star, questions, answers: {}}),
      setAnswer: (id, option) => calls.answers.push([id, option]), onContinue: () => {},
      diagram: fakeDiagram(), office});
    await get("assistant-understand-expand").click();
    dialogHandlers.dialogMessageReceived({message: JSON.stringify({type: "ready"})});
    const good = {type: "answer", questionId: "q_rel_fanout", answer: "Không nối", modelViewHash: star.modelViewHash};
    dialogHandlers.dialogMessageReceived({message: JSON.stringify(good)});
    assert.deepEqual(calls.answers.at(-1), ["q_rel_fanout", "Không nối"], "valid answer is applied");
    const before = calls.answers.length;
    dialogHandlers.dialogMessageReceived({message: JSON.stringify({...good, modelViewHash: "sha256:" + "0".repeat(64)})});
    dialogHandlers.dialogMessageReceived({message: JSON.stringify({...good, answer: "Không tồn tại"})});
    dialogHandlers.dialogMessageReceived({message: JSON.stringify({type: "bogus", anything: 1})});
    dialogHandlers.dialogMessageReceived("not json");
    assert.equal(calls.answers.length, before, "bad hash/option/unknown messages are dropped");
    assert.equal(calls.sent.at(-1).type, "model", "an applied answer refreshes the dialog model");
    console.log("ok - answer validation on the task-pane side");
  }

  // 5. stale locks every answer button inside the dialog.
  {
    const {document, get} = makeDocument();
    const office = {context: {ui: {messageParent: () => {}, addEventHandler: () => {}}}};
    const questions = [{id: "q_rel_fanout", topic: "relationship", question: "?", whyItMatters: "w",
      kind: "single_choice", options: ["Xác nhận"], evidence: []}];
    const ui = dialog.mount({document, office, diagram: fakeDiagram()});
    ui.handleMessage(JSON.stringify({type: "model", modelView: star, answers: {}, questions}));
    const entries = get("model-dialog-relationships").children;
    const buttons = entries.find(entry => textOf(entry).includes("t_bridge.product_id → t_products.product_id"))
      .children.filter(child => child.className === "understand-options")[0].children;
    assert.equal(buttons[0].disabled, false);
    ui.handleMessage(JSON.stringify({type: "stale"}));
    assert.equal(ui.state().stale, true);
    const lockedEntries = get("model-dialog-relationships").children;
    const lockedButtons = lockedEntries.find(entry => textOf(entry).includes("t_bridge.product_id → t_products.product_id"))
      .children.filter(child => child.className === "understand-options")[0].children;
    assert.equal(lockedButtons[0].disabled, true, "stale locks answer buttons");
    assert.match(get("model-dialog-status").textContent, /hết hiệu lực/);
    console.log("ok - stale locks dialog answers");
  }

  // 6. Oversized payloads are not sent; the task pane shows a notice.
  {
    const {document, get} = makeDocument();
    const calls = {sent: []};
    const dialogHandlers = {};
    const fakeDialog = {
      messageChild: raw => calls.sent.push(JSON.parse(raw)),
      addEventListener: (name, fn) => { dialogHandlers[name] = fn; },
    };
    const office = {context: {
      requirements: {isSetSupported: () => true},
      ui: {displayDialogAsync: (url, options, callback) => callback({value: fakeDialog})},
    }};
    const hugeQuestions = Array.from({length: 7000}, (_, index) => ({
      id: "q_huge_" + index, topic: "relationship", question: "?".repeat(120), whyItMatters: "w",
      kind: "single_choice", options: ["Xác nhận"], evidence: [],
    }));
    understand.mount({document, getState: () => ({modelView: star, questions: hugeQuestions, answers: {}}),
      setAnswer: () => {}, onContinue: () => {}, diagram: fakeDiagram(), office});
    await get("assistant-understand-expand").click();
    dialogHandlers.dialogMessageReceived({message: JSON.stringify({type: "ready"})});
    assert.equal(calls.sent.length, 0, "oversized model payload is never sent");
    assert.match(get("assistant-understand-message").textContent, /vượt giới hạn message hộp thoại/);
    console.log("ok - oversized payload blocked with a notice");
  }

  // 7. model_dialog.js contains no fetch/XMLHttpRequest/Excel.run.
  {
    const source = fs.readFileSync(path.join(__dirname, "../../pbip_assistant/excel_addin/model_dialog.js"), "utf8");
    for (const forbidden of ["fetch(", "XMLHttpRequest", "Excel.run", "token"]) {
      assert.ok(!source.includes(forbidden), "model_dialog.js must not contain " + forbidden);
    }
    console.log("ok - dialog source stays a pure view");
  }

  // 8. Closing removes the handler; reopening works again.
  {
    const {document, get} = makeDocument();
    const calls = {sent: []};
    const dialogHandlers = {};
    const fakeDialog = {
      messageChild: raw => calls.sent.push(JSON.parse(raw)),
      addEventListener: (name, fn) => { dialogHandlers[name] = fn; },
    };
    let displayCount = 0;
    const office = {context: {
      requirements: {isSetSupported: () => true},
      ui: {displayDialogAsync: (url, options, callback) => { displayCount++; callback({value: fakeDialog}); }},
    }};
    const ui = understand.mount({document, getState: () => ({modelView: star, questions: [], answers: {}}),
      setAnswer: () => {}, onContinue: () => {}, diagram: fakeDiagram(), office});
    await get("assistant-understand-expand").click();
    assert.equal(ui.dialogs(), 1);
    dialogHandlers.dialogMessageReceived({message: JSON.stringify({type: "close"})});
    assert.equal(ui.dialogs(), 0, "close removes the dialog");
    await get("assistant-understand-expand").click();
    assert.equal(displayCount, 2, "reopening works after close");
    assert.equal(ui.dialogs(), 1);
    console.log("ok - close removes handlers; reopen works");
  }

  console.log("passed");
})().catch(error => { console.error(error); process.exit(1); });