/* Wire diagram for the understand step: pure layout + DOM render (feature 004).
 * The layout is a pure function of (modelView, mode, centerTableId, width);
 * render uses only DOM APIs and textContent — never innerHTML with user data.
 * No Office, no fetch, no task-pane globals. */
(function (root) {
  "use strict";
  const NODE_WIDTH = 200;
  const NODE_TITLE_HEIGHT = 28;
  const ROW_HEIGHT = 18;
  const GAP_X = 48;
  const GAP_Y = 20;
  const MAX_ROWS_VISIBLE = 12;
  const SAMPLE_LABEL = "đo trên mẫu";
  const WIRE_LABELS = {safe: "an toàn", fanout: "nhân dòng", orphan: "mã không khớp"};
  const SVG_NS = "http://www.w3.org/2000/svg";

  function tableById(modelView, tableId) {
    return (modelView.tables || []).find(table => table.tableId === tableId) || null;
  }

  function neighbours(modelView, tableId) {
    const ids = new Set();
    for (const link of modelView.relationships || []) {
      if (link.fromTable === tableId) ids.add(link.toTable);
      if (link.toTable === tableId) ids.add(link.fromTable);
    }
    ids.delete(tableId);
    return Array.from(ids).sort();
  }

  function visibleRows(table, keyOnly) {
    const columns = table.columns || [];
    const chosen = [];
    const rest = [];
    for (const column of columns) {
      if (keyOnly ? (column.isKey || column.isLink) : column.isLink) chosen.push(column);
      else rest.push(column);
    }
    if (!keyOnly) {
      for (const column of rest) {
        if (chosen.length >= MAX_ROWS_VISIBLE) break;
        chosen.push(column);
      }
    }
    const order = new Map(columns.map((column, index) => [column.name, index]));
    chosen.sort((a, b) => order.get(a.name) - order.get(b.name));
    return {rows: chosen, hiddenColumns: table.columnCount - chosen.length};
  }

  function nodeBox(table, x, y) {
    const visible = visibleRows(table, false);
    const rows = visible.rows.map((column, index) => ({
      column: column.name,
      y: NODE_TITLE_HEIGHT + index * ROW_HEIGHT + ROW_HEIGHT / 2,
      isKey: !!column.isKey,
      isLink: !!column.isLink,
    }));
    return {tableId: table.tableId, x, y, width: NODE_WIDTH, height: NODE_TITLE_HEIGHT + rows.length * ROW_HEIGHT,
            rows, hiddenColumns: visible.hiddenColumns};
  }

  function sides(fromX, toX) {
    if (toX > fromX) return {fromSide: "right", toSide: "left"};
    if (toX < fromX) return {fromSide: "left", toSide: "right"};
    return {fromSide: "right", toSide: "right"};
  }

  function wireEnds(node, column, side) {
    const row = (node.rows || []).find(item => item.column === column);
    const y = node.y + (row ? row.y : NODE_TITLE_HEIGHT);
    return {x: side === "right" ? node.x + node.width : node.x, y};
  }

  function layoutWires(modelView, nodesByTable) {
    const wires = [];
    for (const link of modelView.relationships || []) {
      const fromNode = nodesByTable[link.fromTable];
      const toNode = nodesByTable[link.toTable];
      if (!fromNode || !toNode) continue;
      const pair = sides(fromNode.x, toNode.x);
      link.fromColumns.forEach((fromColumn, index) => {
        const toColumn = link.toColumns[index];
        const from = wireEnds(fromNode, fromColumn, pair.fromSide);
        const to = wireEnds(toNode, toColumn, pair.toSide);
        const marks = marksFor(link.cardinality);
        wires.push({relationshipId: link.id, wireState: link.wireState || "safe",
                    fromTableId: link.fromTable, fromColumn, toTableId: link.toTable, toColumn,
                    x1: from.x, y1: from.y, x2: to.x, y2: to.y,
                    fromSide: pair.fromSide, toSide: pair.toSide,
                    fromMark: marks.fromMark, toMark: marks.toMark});
      });
    }
    return wires;
  }

  function marksFor(cardinality) {
    const parts = String(cardinality || "").split(":");
    return {fromMark: parts[0] === "1" ? "one" : "many",
            toMark: parts[1] === "1" ? "one" : "many"};
  }

  function stackColumn(tables, x) {
    let y = 0;
    return tables.map(table => {
      const node = nodeBox(table, x, y);
      y = node.y + node.height + GAP_Y;
      return node;
    });
  }

  function layoutFocus(modelView, centerTableId, width) {
    const center = tableById(modelView, centerTableId);
    const nodes = [];
    if (!center) return {width, height: 0, nodes, wires: []};
    const ids = neighbours(modelView, centerTableId);
    const leftIds = ids.filter((id, index) => index % 2 === 0);
    const rightIds = ids.filter((id, index) => index % 2 === 1);
    const centre = nodeBox(center, Math.max(0, Math.round((width - NODE_WIDTH) / 2)), 0);
    nodes.push(centre);
    const leftColumn = stackColumn(leftIds.map(id => tableById(modelView, id)).filter(Boolean), 0);
    const rightColumn = stackColumn(rightIds.map(id => tableById(modelView, id)).filter(Boolean),
                                    Math.max(0, width - NODE_WIDTH));
    for (const table of leftIds.map(id => tableById(modelView, id)).filter(Boolean)) {
      // neighbour nodes show only key/link columns
      const node = leftColumn.find(item => item.tableId === table.tableId);
      nodes.push({...node, rows: visibleRows(table, true).rows.map((column, index) => ({
        column: column.name, y: NODE_TITLE_HEIGHT + index * ROW_HEIGHT + ROW_HEIGHT / 2,
        isKey: !!column.isKey, isLink: !!column.isLink})),
        hiddenColumns: visibleRows(table, true).hiddenColumns});
    }
    for (const table of rightIds.map(id => tableById(modelView, id)).filter(Boolean)) {
      const node = rightColumn.find(item => item.tableId === table.tableId);
      nodes.push({...node, rows: visibleRows(table, true).rows.map((column, index) => ({
        column: column.name, y: NODE_TITLE_HEIGHT + index * ROW_HEIGHT + ROW_HEIGHT / 2,
        isKey: !!column.isKey, isLink: !!column.isLink})),
        hiddenColumns: visibleRows(table, true).hiddenColumns});
    }
    nodes.sort((a, b) => a.tableId.localeCompare(b.tableId));
    const byTable = Object.fromEntries(nodes.map(node => [node.tableId, node]));
    const wires = layoutWires(modelView, byTable);
    const height = Math.max(0, ...nodes.map(node => node.y + node.height));
    return {width, height, measuredOn: modelView.measuredOn || "full", nodes, wires};
  }

  function layoutFull(modelView, width) {
    const columns = {left: [], middle: [], right: []};
    for (const table of (modelView.tables || []).slice().sort((a, b) => a.tableId.localeCompare(b.tableId))) {
      if (table.structural === "dim" || table.structural === "lookup") columns.left.push(table);
      else if (table.structural === "fact") columns.middle.push(table);
      else columns.right.push(table);
    }
    const middleX = Math.max(0, Math.round((width - NODE_WIDTH) / 2));
    const nodes = [
      ...stackColumn(columns.left, 0),
      ...stackColumn(columns.middle, middleX),
      ...stackColumn(columns.right, Math.max(0, width - NODE_WIDTH)),
    ];
    const byTable = Object.fromEntries(nodes.map(node => [node.tableId, node]));
    const wires = layoutWires(modelView, byTable);
    const height = Math.max(0, ...nodes.map(node => node.y + node.height));
    return {width, height, measuredOn: modelView.measuredOn || "full", nodes, wires};
  }

  function layout(modelView, options) {
    if (!modelView || !options) throw new Error("Sơ đồ cần modelView và tùy chọn bố cục.");
    const mode = options.mode === "full" ? "full" : "focus";
    const width = Number.isFinite(options.width) && options.width > 0 ? options.width : 600;
    if (mode === "full") return layoutFull(modelView, width);
    return layoutFocus(modelView, options.centerTableId || (modelView.tables || [])[0]?.tableId, width);
  }

  function describeWire(modelView, relationshipId) {
    const link = (modelView.relationships || []).find(rel => rel.id === relationshipId);
    if (!link) return {text: "", marks: {}};
    const fromTable = tableById(modelView, link.fromTable);
    const toTable = tableById(modelView, link.toTable);
    const text = `${fromTable ? fromTable.name : link.fromTable}.${link.fromColumns.join("+")}` +
      ` → ${toTable ? toTable.name : link.toTable}.${link.toColumns.join("+")}`;
    const marks = {fanout: link.wireState === "fanout", orphan: link.wireState === "orphan" || link.orphan > 0,
                   sample: modelView.measuredOn === "sample"};
    let sentence = text;
    if (link.orphan > 0) sentence += ` · ${link.orphan} dòng không khớp`;
    if (link.rowsBefore !== null && link.rowsBefore !== undefined && link.rowsAfter !== null && link.rowsAfter !== undefined) {
      sentence += ` · ${link.rowsBefore} → ${link.rowsAfter} dòng`;
    }
    if (marks.sample) sentence += ` · ${SAMPLE_LABEL}`;
    return {text: sentence, marks};
  }

  function render(container, diagram, handlers) {
    if (!container || !diagram) throw new Error("Sơ đồ cần container và bố cục.");
    const onSelectWire = handlers && typeof handlers.onSelectWire === "function" ? handlers.onSelectWire : () => {};
    const onSelectTable = handlers && typeof handlers.onSelectTable === "function" ? handlers.onSelectTable : () => {};
    const document = container.ownerDocument || (typeof document !== "undefined" ? document : null);
    if (!document || typeof document.createElementNS !== "function") {
      throw new Error("Sơ đồ cần một document hỗ trợ createElementNS.");
    }
    container.replaceChildren();
    const svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("width", String(diagram.width));
    svg.setAttribute("height", String(diagram.height));
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", "Sơ đồ quan hệ giữa các bảng dữ liệu");
    const state = {selectedWire: null, selectedTable: null};
    const clear = () => {
      state.selectedWire = null;
      state.selectedTable = null;
      for (const element of container.querySelectorAll?.(".diagram-selected") || []) {
        element.classList?.remove?.("diagram-selected");
      }
      if (typeof handlers.onClearSelection === "function") handlers.onClearSelection();
    };
    svg.addEventListener("keydown", event => {
      if (event.key === "Escape") clear();
    });

    for (const node of diagram.nodes || []) {
      const group = document.createElementNS(SVG_NS, "g");
      group.setAttribute("data-table-id", node.tableId);
      group.setAttribute("tabindex", "0");
      group.setAttribute("role", "button");
      group.setAttribute("aria-label", `Bảng ${node.tableId}`);
      const rect = document.createElementNS(SVG_NS, "rect");
      rect.setAttribute("x", String(node.x));
      rect.setAttribute("y", String(node.y));
      rect.setAttribute("width", String(node.width));
      rect.setAttribute("height", String(node.height));
      const title = document.createElementNS(SVG_NS, "text");
      title.textContent = node.tableId;
      title.setAttribute("x", String(node.x + 8));
      title.setAttribute("y", String(node.y + 18));
      group.appendChild(rect);
      group.appendChild(title);
      for (const row of node.rows || []) {
        const text = document.createElementNS(SVG_NS, "text");
        text.textContent = row.column;
        text.setAttribute("x", String(node.x + 8));
        text.setAttribute("y", String(node.y + row.y));
        group.appendChild(text);
      }
      if (node.hiddenColumns > 0) {
        const text = document.createElementNS(SVG_NS, "text");
        text.textContent = `+ ${node.hiddenColumns} cột khác`;
        text.setAttribute("x", String(node.x + 8));
        text.setAttribute("y", String(node.y + node.height - 6));
        group.appendChild(text);
      }
      group.addEventListener("click", () => {
        state.selectedTable = node.tableId;
        onSelectTable(node.tableId);
      });
      group.addEventListener("keydown", event => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          state.selectedTable = node.tableId;
          onSelectTable(node.tableId);
        }
      });
      svg.appendChild(group);
    }

    for (const wire of diagram.wires || []) {
      const group = document.createElementNS(SVG_NS, "g");
      group.setAttribute("data-relationship-id", wire.relationshipId);
      group.setAttribute("tabindex", "0");
      group.setAttribute("role", "button");
      const label = WIRE_LABELS[wire.wireState] || wire.wireState;
      const sample = diagram.measuredOn === "sample";
      group.setAttribute("aria-label", `Dây ${wire.fromColumn} sang ${wire.toColumn} · ${label}` +
        (sample ? ` · ${SAMPLE_LABEL}` : ""));
      const line = document.createElementNS(SVG_NS, "line");
      line.setAttribute("x1", String(wire.x1));
      line.setAttribute("y1", String(wire.y1));
      line.setAttribute("x2", String(wire.x2));
      line.setAttribute("y2", String(wire.y2));
      line.setAttribute("class", `wire wire-${wire.wireState}`);
      const text = document.createElementNS(SVG_NS, "text");
      text.textContent = label + (sample ? ` · ${SAMPLE_LABEL}` : "");
      text.setAttribute("x", String(Math.round((wire.x1 + wire.x2) / 2)));
      text.setAttribute("y", String(Math.round((wire.y1 + wire.y2) / 2) - 4));
      group.appendChild(line);
      group.appendChild(text);
      group.addEventListener("click", () => {
        state.selectedWire = wire.relationshipId;
        onSelectWire(wire.relationshipId);
      });
      group.addEventListener("keydown", event => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          state.selectedWire = wire.relationshipId;
          onSelectWire(wire.relationshipId);
        }
      });
      svg.appendChild(group);
    }
    container.appendChild(svg);
    return {clear, state: () => ({selectedWire: state.selectedWire, selectedTable: state.selectedTable})};
  }

  const api = {layout, render, neighbours, describeWire, marksFor};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.ReqwiseAssistantModelDiagram = api;
})(typeof window !== "undefined" ? window : globalThis);