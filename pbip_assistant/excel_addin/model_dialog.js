/* Expanded 1:3 model dialog (feature 004). Pure view: receives modelView/
 * answers/questions via messageChild, replies via messageParent. No network
 * calls, no workbook API, no credentials, no data in the URL. */
(function (root) {
  "use strict";
  const CLOSED_KEYS = {model: ["modelView", "answers", "questions"], stale: [], ready: [], close: []};

  function mount({document, office, diagram}) {
    if (!document || !office) throw new Error("Hộp thoại cần document và Office.");
    const get = id => document.getElementById(id);
    const element = (tag, text) => { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; return node; };
    let modelView = null;
    let answers = {};
    let questionsById = new Map();
    let stale = false;
    let selectedRelationship = null;
    let selectedTable = null;

    function send(message) {
      if (typeof office.context?.ui?.messageParent !== "function") return;
      office.context.ui.messageParent(JSON.stringify(message));
    }

    function optionButtons(questionId, options) {
      const group = element("div");
      group.className = "understand-options";
      for (const option of options || []) {
        const button = element("button", option);
        button.type = "button";
        button.className = "button button-ghost";
        button.disabled = stale;
        if (answers[questionId] === option) button.disabled = true;
        button.addEventListener("click", () => {
          if (stale || !modelView) return;
          send({type: "answer", questionId, answer: option, modelViewHash: modelView.modelViewHash});
        });
        group.appendChild(button);
      }
      return group;
    }

    function questionLabel(questionId) {
      const label = element("span");
      label.className = answers[questionId] ? "badge badge-ready" : "badge badge-wait";
      label.textContent = answers[questionId] ? `Đã trả lời: ${answers[questionId]}` : "cần xác nhận";
      return label;
    }

    function renderLists() {
      const tables = get("model-dialog-tables");
      const relationships = get("model-dialog-relationships");
      tables.replaceChildren();
      relationships.replaceChildren();
      if (!modelView) return;
      for (const table of modelView.tables || []) {
        const button = element("button", `${table.name} · ${table.rowCount} dòng`);
        button.type = "button";
        button.className = "model-dialog-entry" + (selectedTable === table.tableId ? " diagram-selected" : "");
        button.addEventListener("click", () => {
          selectedTable = table.tableId;
          renderLists();
          highlightWires();
        });
        tables.appendChild(button);
      }
      for (const link of modelView.relationships || []) {
        const row = element("div");
        row.className = "model-dialog-entry" + (selectedRelationship === link.id ? " diagram-selected" : "");
        const button = element("button", `${link.fromTable}.${link.fromColumns.join("+")} → ${link.toTable}.${link.toColumns.join("+")}`);
        button.type = "button";
        button.addEventListener("click", () => {
          selectedRelationship = link.id;
          renderLists();
          highlightWires();
        });
        row.appendChild(button);
        const question = link.questionId ? questionsById.get(link.questionId) : null;
        if (question) {
          row.appendChild(questionLabel(question.id));
          row.appendChild(optionButtons(question.id, question.options));
        }
        relationships.appendChild(row);
      }
    }

    function highlightWires() {
      const host = get("model-dialog-diagram-host");
      for (const group of Array.from(host.querySelectorAll?.("[data-relationship-id]") || [])) {
        group.classList?.remove?.("diagram-selected");
        if (selectedRelationship === group.getAttribute("data-relationship-id")) {
          group.classList?.add?.("diagram-selected");
        }
      }
      for (const group of Array.from(host.querySelectorAll?.("[data-table-id]") || [])) {
        group.classList?.remove?.("diagram-selected");
        if (selectedTable === group.getAttribute("data-table-id")) {
          group.classList?.add?.("diagram-selected");
        }
      }
    }

    function renderDiagram() {
      const host = get("model-dialog-diagram-host");
      host.replaceChildren();
      if (!modelView || !diagram) return;
      try {
        const layout = diagram.layout(modelView, {mode: "full", width: Math.max(420, host.clientWidth || 600)});
        diagram.render(host, layout, {
          onSelectWire: relationshipId => { selectedRelationship = relationshipId; renderLists(); highlightWires(); },
          onSelectTable: tableId => { selectedTable = tableId; renderLists(); highlightWires(); },
        });
        highlightWires();
      } catch (error) {
        host.appendChild(element("p", `Chưa vẽ được sơ đồ: ${error.message}`));
      }
    }

    function applyModel(message) {
      if (stale || !message.modelView) return;
      modelView = message.modelView;
      answers = message.answers || {};
      questionsById = new Map((message.questions || []).map(question => [question.id, question]));
      get("model-dialog-status").textContent = modelView.measuredOn === "sample" ? "đo trên mẫu" : "";
      selectedRelationship = null;
      selectedTable = null;
      renderLists();
      renderDiagram();
    }

    function applyStale() {
      stale = true;
      get("model-dialog-status").textContent = "Nguồn hoặc kết quả hiểu đã đổi; hết hiệu lực — không nhận trả lời.";
      renderLists();
    }

    function handleMessage(raw) {
      let message;
      try { message = JSON.parse(raw); } catch { return; }
      if (!message || typeof message !== "object" || typeof message.type !== "string") return;
      const allowed = CLOSED_KEYS[message.type];
      if (!allowed) return;
      if (Object.keys(message).some(key => key !== "type" && !allowed.includes(key))) return;
      if (message.type === "model") applyModel(message);
      else if (message.type === "stale") applyStale();
    }

    office.context.ui.addEventHandler("dialogMessageReceived", event => handleMessage(event?.message));
    get("model-dialog-collapse").addEventListener("click", () => send({type: "close"}));
    send({type: "ready"});
    return {handleMessage, state: () => ({stale, modelView: modelView ? modelView.modelViewHash : null,
      selectedRelationship, selectedTable}), render: renderLists};
  }

  const api = {mount};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.ReqwiseModelDialog = api;
})(typeof window !== "undefined" ? window : globalThis);