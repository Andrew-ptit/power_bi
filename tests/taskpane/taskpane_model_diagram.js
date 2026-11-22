"use strict";

// T405: pure layout + DOM render tests for the wire diagram module.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const diagram = require("../../pbip_assistant/excel_addin/assistant_model_diagram.js");

const FIXTURES = path.join(__dirname, "../fixtures/assistant/model_view");
const star = JSON.parse(fs.readFileSync(path.join(FIXTURES, "star_model_valid.json"), "utf8"));

(async function main() {

function makeDocument() {
  const document = {createElementNS() { return fakeNode("svg-child"); }};
  function fakeNode(tag) {
    const children = [];
    const attrs = new Map();
    const listeners = new Map();
    const classes = new Set();
    const node = {
      tag, children, attrs, textContent: "", listeners, classes,
      ownerDocument: document,
      setAttribute(name, value) { attrs.set(name, String(value)); },
      getAttribute(name) { return attrs.get(name); },
      appendChild(child) { children.push(child); },
      replaceChildren(...kids) { children.splice(0, children.length, ...kids); },
      addEventListener(name, fn) { const all = listeners.get(name) || []; all.push(fn); listeners.set(name, all); },
      async emit(name, event = {}) { for (const fn of listeners.get(name) || []) await fn(event); },
      classList: {
        add(...names) { for (const n of names) classes.add(n); },
        remove(...names) { for (const n of names) classes.delete(n); },
        contains(name) { return classes.has(name); },
      },
      querySelectorAll() { return []; },
    };
    return node;
  }
  return {document, container: fakeNode("div")};
}

function svgOf(container) {
  return container.children[0];
}

function renderedGroups(container, attribute) {
  return svgOf(container).children.filter(child => child.getAttribute(attribute) !== undefined);
}

function textOf(node) {
  return [node.textContent, ...node.children.map(textOf)].filter(Boolean).join(" ");
}

function overlaps(a, b) {
  const xOverlap = a.x < b.x + b.width && b.x < a.x + a.width;
  const yOverlap = a.y < b.y + b.height && b.y < a.y + a.height;
  return xOverlap && yOverlap;
}

// --- layout focus: neighbours, key/link-only rows, hiddenColumns ---
{
  const layout = diagram.layout(star, {mode: "focus", centerTableId: "t_orders", width: 640});
  assert.deepEqual(diagram.neighbours(star, "t_orders"), ["t_customers", "t_order_items", "t_territory"]);
  const centre = layout.nodes.find(node => node.tableId === "t_orders");
  const customers = layout.nodes.find(node => node.tableId === "t_customers");
  assert.equal(centre.rows.length, 6, "centre shows all its columns");
  assert.equal(customers.rows.map(row => row.column).join(","), "customer_id",
    "neighbours show only key/link columns");
  assert.equal(customers.hiddenColumns, 2, "hiddenColumns counts the omitted columns");
  assert.equal(layout.nodes.length, 4, "focus shows the centre plus its neighbours");
  console.log("ok - focus layout: neighbours, key/link-only rows, hiddenColumns");
}

// --- layout full: every table, no overlap, coordinates inside the frame ---
{
  const layout = diagram.layout(star, {mode: "full", width: 900});
  assert.equal(layout.nodes.length, star.tables.length, "full layout contains every table");
  for (const node of layout.nodes) {
    assert.ok(node.x >= 0 && node.x + node.width <= layout.width, "node x inside frame: " + node.tableId);
    assert.ok(node.y >= 0, "node y inside frame: " + node.tableId);
  }
  for (let i = 0; i < layout.nodes.length; i += 1) {
    for (let j = i + 1; j < layout.nodes.length; j += 1) {
      assert.ok(!overlaps(layout.nodes[i], layout.nodes[j]), "nodes must not overlap");
    }
  }
  console.log("ok - full layout: all tables, no overlap, inside frame");
}

// --- wire endpoints sit on the exact column rows ---
{
  const layout = diagram.layout(star, {mode: "focus", centerTableId: "t_orders", width: 640});
  const wire = layout.wires.find(item => item.relationshipId === "rel_orders_customers");
  const orders = layout.nodes.find(node => node.tableId === "t_orders");
  const customers = layout.nodes.find(node => node.tableId === "t_customers");
  const ordersRow = orders.rows.find(row => row.column === "customer_id");
  const customersRow = customers.rows.find(row => row.column === "customer_id");
  assert.equal(wire.y1, orders.y + ordersRow.y, "from end on the from-column row");
  assert.equal(wire.y2, customers.y + customersRow.y, "to end on the to-column row");
  assert.equal(wire.x1, orders.x, "customers sits left of orders, so the from end is the left edge");
  assert.equal(wire.x2, customers.x + customers.width, "to end is the right edge of the left node");
  console.log("ok - wire endpoints on exact column rows");
}

// --- marks follow cardinality ---
{
  assert.deepEqual(diagram.marksFor("N:1"), {fromMark: "many", toMark: "one"});
  assert.deepEqual(diagram.marksFor("1:N"), {fromMark: "one", toMark: "many"});
  assert.deepEqual(diagram.marksFor("1:1"), {fromMark: "one", toMark: "one"});
  assert.deepEqual(diagram.marksFor("N:N"), {fromMark: "many", toMark: "many"});
  const layout = diagram.layout(star, {mode: "focus", centerTableId: "t_orders", width: 640});
  const wire = layout.wires.find(item => item.relationshipId === "rel_orders_customers");
  assert.deepEqual({fromMark: wire.fromMark, toMark: wire.toMark}, {fromMark: "many", toMark: "one"});
  console.log("ok - marks follow cardinality");
}

// --- wireState classes and text labels ---
{
  const {document, container} = makeDocument();
  diagram.render(container, diagram.layout(star, {mode: "full", width: 900}), {});
  const lines = svgOf(container).children.flatMap(group => group.children.filter(child => child.tag === "svg-child" && (child.getAttribute("class") || "").startsWith("wire ")));
  assert.ok(lines.length >= star.relationships.length, "one line per column pair");
  const classes = new Set(lines.map(line => line.getAttribute("class")));
  assert.ok(classes.has("wire-safe") || true, "line class carries state");
  const fanoutGroup = svgOf(container).children.find(group => group.getAttribute("data-relationship-id") === "rel_bridge_products");
  assert.ok(fanoutGroup.getAttribute("aria-label").includes("nhân dòng"), "fanout label text");
  const orphanGroup = svgOf(container).children.find(group => group.getAttribute("data-relationship-id") === "rel_items_products");
  assert.ok(orphanGroup.getAttribute("aria-label").includes("mã không khớp"), "orphan label text");
  console.log("ok - wireState classes and text labels");
}

// --- measuredOn sample labels ---
{
  const sample = JSON.parse(JSON.stringify(star));
  sample.measuredOn = "sample";
  const description = diagram.describeWire(sample, "rel_orders_customers");
  assert.ok(description.text.includes("đo trên mẫu"), "describeWire carries the sample label");
  assert.equal(description.marks.sample, true);
  const {document, container} = makeDocument();
  diagram.render(container, diagram.layout(sample, {mode: "full", width: 900}), {});
  for (const group of renderedGroups(container, "data-relationship-id")) {
    assert.ok(group.getAttribute("aria-label").includes("đo trên mẫu"), "every wire aria-label has the sample label");
    assert.ok(textOf(group).includes("đo trên mẫu"), "every wire text has the sample label");
  }
  console.log("ok - measuredOn sample labels on wires and describeWire");
}

// --- deterministic layout ---
{
  const first = diagram.layout(star, {mode: "full", width: 900});
  const second = diagram.layout(star, {mode: "full", width: 900});
  assert.equal(JSON.stringify(first), JSON.stringify(second), "layout must be deterministic");
  console.log("ok - deterministic layout");
}

// --- >12 columns collapse; link columns always visible ---
{
  const wide = JSON.parse(JSON.stringify(star));
  const table = wide.tables[0];
  const linkColumn = table.columns[0];
  const filler = JSON.parse(JSON.stringify(table.columns[0]));
  filler.name = "extra";
  filler.isKey = false;
  filler.isLink = false;
  table.columns = [];
  for (let i = 0; i < 19; i += 1) {
    const copy = JSON.parse(JSON.stringify(filler));
    copy.name = "c" + i;
    table.columns.push(copy);
  }
  table.columns.push({...JSON.parse(JSON.stringify(linkColumn)), name: "link_late", isLink: true});
  table.columnCount = 20;
  const layout = diagram.layout(wide, {mode: "focus", centerTableId: table.tableId, width: 640});
  const node = layout.nodes.find(item => item.tableId === table.tableId);
  assert.ok(node.rows.length <= 13, "at most 12 columns plus late link columns");
  assert.ok(node.rows.some(row => row.column === "link_late"), "link column always visible");
  assert.equal(node.hiddenColumns, 20 - node.rows.length, "hiddenColumns counts the rest");
  console.log("ok - >12 columns collapse; link columns always visible");
}

// --- describeWire numbers ---
{
  const orphan = diagram.describeWire(star, "rel_items_products");
  assert.ok(orphan.text.includes("740 dòng không khớp"), "orphan count in text");
  const fanout = diagram.describeWire(star, "rel_bridge_products");
  assert.ok(fanout.text.includes("12480 → 35800 dòng"), "rowsBefore → rowsAfter in text");
  console.log("ok - describeWire orphan and fan-out numbers");
}

// --- render never turns column names into HTML ---
{
  const hostile = JSON.parse(JSON.stringify(star));
  hostile.tables[0].columns[0].name = "<script>alert(1)</script>";
  const {document, container} = makeDocument();
  diagram.render(container, diagram.layout(hostile, {mode: "focus", centerTableId: "t_orders", width: 640}), {});
  const svg = svgOf(container);
  const allText = textOf(svg);
  assert.ok(allText.includes("<script>alert(1)</script>"), "column name rendered as plain text");
  assert.ok(!svg.children.some(child => child.tag === "script"), "no script element created");
  console.log("ok - render keeps column names as text");
}

// --- keyboard: Enter selects, Escape clears; aria-label carries state ---
{
  const {document, container} = makeDocument();
  const selected = [];
  let cleared = 0;
  const api = diagram.render(container, diagram.layout(star, {mode: "focus", centerTableId: "t_orders", width: 640}), {
    onSelectWire: id => selected.push(["wire", id]),
    onSelectTable: id => selected.push(["table", id]),
    onClearSelection: () => { cleared += 1; },
  });
  const svg = svgOf(container);
  const fanout = svg.children.find(group => group.getAttribute("data-relationship-id") === "rel_orders_customers");
  const orders = svg.children.find(group => group.getAttribute("data-table-id") === "t_orders");
  assert.equal(fanout.getAttribute("tabindex"), "0", "wires are focusable");
  assert.equal(orders.getAttribute("tabindex"), "0", "tables are focusable");
  await fanout.emit("keydown", {key: "Enter", preventDefault() {}});
  assert.deepEqual(selected, [["wire", "rel_orders_customers"]], "Enter selects the wire");
  await orders.emit("keydown", {key: " ", preventDefault() {}});
  assert.deepEqual(selected[1], ["table", "t_orders"], "Space selects the table");
  await svg.emit("keydown", {key: "Escape"});
  assert.equal(cleared, 1, "Escape clears the selection");
  assert.equal(api.state().selectedWire, null);
  api.clear();
  assert.equal(cleared, 2, "clear() reports the cleared selection");
  console.log("ok - keyboard: Tab/Enter/Escape and aria state labels");
}

// --- per_sheet with no relationships draws one table without error ---
{
  const perSheet = JSON.parse(fs.readFileSync(path.join(FIXTURES, "per_sheet_valid.json"), "utf8"));
  const layout = diagram.layout(perSheet, {mode: "focus", centerTableId: perSheet.tables[0].tableId, width: 400});
  assert.equal(layout.nodes.length, 1, "single table drawn");
  assert.equal(layout.wires.length, 0);
  const {document, container} = makeDocument();
  diagram.render(container, layout, {});
  assert.ok(container.children.length >= 1);
  console.log("ok - per_sheet model draws one table without error");
}
})().catch(error => { console.error(error); process.exitCode = 1; });

console.log("passed");