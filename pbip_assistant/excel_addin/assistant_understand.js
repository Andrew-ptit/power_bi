/* Understand-data step view (feature 004): overview, tables, relationships
 * (list | focus diagram), warnings and in-place answers. Pure view: reads
 * getState(), writes through setAnswer(); no fetch, no Office, no token. */
(function (root) {
  "use strict";
  const STRUCTURAL_LABELS = {
    fact: "Bảng giao dịch",
    dim: "Danh mục",
    lookup: "Bảng tra cứu",
    bridge: "Bảng nối",
    unclassified: "Chưa phân loại",
  };
  const GRAIN_LABELS = {event: "sự kiện", snapshot: "ảnh chụp theo ngày", unknown: "chưa rõ"};
  const NEEDS_CONFIRM = "cần xác nhận";
  const SAMPLE_WARNING = "Khóa và quan hệ được đo trên mẫu và có thể thiếu hoặc sai.";
  const NO_KEY = "Chưa tìm thấy khóa duy nhất";
  const PER_SHEET_NOTE = "Chưa đủ bằng chứng để dựng mô hình quan hệ giữa các bảng; xem từng sheet. Không phải lỗi — bạn vẫn có thể sang Đề bài.";

  function mount({document, getState, setAnswer, onContinue, diagram}) {
    if (!document || typeof getState !== "function" || typeof setAnswer !== "function") {
      throw new Error("Bước Hiểu cần document, getState và setAnswer.");
    }
    const get = id => document.getElementById(id);
    const element = (tag, text) => { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; return node; };
    let view = "list";
    let centerTableId = null;

    function keySentence(table) {
      const key = (table.keys || [])[0];
      return key && key.length ? `Mỗi dòng ứng với một ${key.join(" + ")}` : NO_KEY;
    }

    function answered(answers, questionId) {
      return !!questionId && !!answers[questionId] && String(answers[questionId]).trim();
    }

    function optionButtons(questionId, options, answers, onClick) {
      const group = element("div");
      group.className = "understand-options";
      for (const option of options || []) {
        const button = element("button", option);
        button.type = "button";
        button.className = "button button-ghost";
        button.addEventListener("click", () => onClick(questionId, option));
        if (answers[questionId] === option) button.disabled = true;
        group.appendChild(button);
      }
      return group;
    }

    function questionLabel(questionId, answers) {
      const label = element("span");
      label.className = answered(answers, questionId) ? "badge badge-ready" : "badge badge-wait";
      label.textContent = answered(answers, questionId) ? `Đã trả lời: ${answers[questionId]}` : NEEDS_CONFIRM;
      return label;
    }

    function questionById(questions) {
      return new Map((questions || []).map(question => [question.id, question]));
    }

    function renderOverview(modelView, questions, answers) {
      const counts = modelView.counts || {};
      const overview = get("assistant-understand-overview");
      overview.replaceChildren();
      overview.textContent = `${counts.tables || 0} bảng (${counts.fact || 0} giao dịch · ${counts.dim || 0} danh mục`
        + ` · ${counts.lookup || 0} tra cứu · ${counts.bridge || 0} nối · ${counts.unclassified || 0} chưa phân loại)`
        + ` · ${counts.relationships || 0} quan hệ · ${counts.needsConfirm || 0} mục cần xác nhận · ${counts.warnings || 0} cảnh báo`;
      const byId = questionById(questions);
      const pending = (questions || []).filter(question =>
        ["relationship", "role", "grain"].includes(question.topic) && !answered(answers, question.id)).length;
      get("assistant-understand-status").textContent = `Còn ${pending} mục cần xác nhận.`;
    }

    function renderTables(modelView, questions, answers, onClick) {
      const container = get("assistant-understand-tables");
      container.replaceChildren();
      const byId = questionById(questions);
      for (const table of modelView.tables || []) {
        const item = element("div");
        item.className = "understand-item";
        const title = element("p", table.name);
        title.className = "understand-title";
        const facts = element("p", `${STRUCTURAL_LABELS[table.structural] || table.structural}`
          + ` · ${table.rowCount} dòng${table.measuredRows !== table.rowCount ? ` · đo ${table.measuredRows} dòng` : ""}`
          + ` · ${keySentence(table)} · ${GRAIN_LABELS[table.grainKind] || table.grainKind}`);
        facts.className = "hint";
        item.appendChild(title);
        item.appendChild(facts);
        const grainQuestion = table.grainQuestionId ? byId.get(table.grainQuestionId) : null;
        const roleQuestion = table.roleQuestionId ? byId.get(table.roleQuestionId) : null;
        const confirmations = [grainQuestion, roleQuestion].filter(Boolean);
        if (confirmations.length) {
          item.appendChild(questionLabel(confirmations[0].id, answers));
          for (const question of confirmations) {
            item.appendChild(optionButtons(question.id, question.options, answers, onClick));
          }
        }
        container.appendChild(item);
      }
    }

    function renderRelationshipList(modelView, questions, answers, onClick) {
      const container = get("assistant-understand-relationships");
      container.replaceChildren();
      const byId = questionById(questions);
      for (const link of modelView.relationships || []) {
        const fromTable = (modelView.tables || []).find(table => table.tableId === link.fromTable);
        const toTable = (modelView.tables || []).find(table => table.tableId === link.toTable);
        const item = element("div");
        item.className = "understand-item" + (link.wireState !== "safe" ? " understand-needs-confirm" : "");
        const line = element("p", `${fromTable ? fromTable.name : link.fromTable}.${link.fromColumns.join("+")}`
          + ` → ${toTable ? toTable.name : link.toTable}.${link.toColumns.join("+")}`
          + ` · ${link.cardinality} · ${link.wireState === "fanout" ? "nhân dòng" : link.wireState === "orphan" ? "có mã không khớp" : "an toàn"}`);
        item.appendChild(line);
        if (link.orphan > 0) {
          const orphan = element("p", `${link.orphan} dòng không khớp`);
          orphan.className = "hint";
          item.appendChild(orphan);
        }
        if (link.rowsBefore !== null && link.rowsAfter !== null && link.rowsBefore !== undefined) {
          const fanout = element("p", `${link.rowsBefore} → ${link.rowsAfter} dòng`);
          fanout.className = "hint";
          item.appendChild(fanout);
        }
        const question = link.questionId ? byId.get(link.questionId) : null;
        if (question) {
          item.appendChild(questionLabel(question.id, answers));
          item.appendChild(optionButtons(question.id, question.options, answers, onClick));
        }
        container.appendChild(item);
      }
    }

    function renderWarnings(modelView, questions, answers, onClick) {
      const container = get("assistant-understand-warnings");
      container.replaceChildren();
      const byId = questionById(questions);
      for (const warning of modelView.warnings || []) {
        const item = element("div");
        item.className = "understand-item";
        const line = element("p", `${warning.code} · ${warning.severity}`);
        item.appendChild(line);
        const question = warning.questionId ? byId.get(warning.questionId) : null;
        if (question) {
          item.appendChild(questionLabel(question.id, answers));
          item.appendChild(optionButtons(question.id, question.options, answers, onClick));
        }
        container.appendChild(item);
      }
    }

    function renderDiagram(modelView) {
      const container = get("assistant-understand-diagram");
      container.replaceChildren();
      if (!diagram || !modelView.tables || !modelView.tables.length) return;
      const selector = document.createElement("select");
      selector.className = "understand-center-select";
      const label = element("label", "Bảng trung tâm: ");
      for (const table of modelView.tables) {
        const option = document.createElement("option");
        option.value = table.tableId;
        option.textContent = table.name;
        if (table.tableId === centerTableId) option.selected = true;
        selector.appendChild(option);
      }
      selector.addEventListener("change", () => {
        centerTableId = selector.value;
        renderDiagram(modelView);
      });
      label.appendChild(selector);
      container.appendChild(label);
      const host = element("div");
      host.className = "understand-diagram-host";
      container.appendChild(host);
      try {
        const layout = diagram.layout(modelView, {mode: "focus", centerTableId: centerTableId || modelView.tables[0].tableId, width: 320});
        diagram.render(host, layout, {});
      } catch (error) {
        host.appendChild(element("p", `Chưa vẽ được sơ đồ: ${error.message}`));
      }
    }

    function switchView(modelView, next) {
      view = next;
      get("assistant-rel-list-button").setAttribute("aria-pressed", String(view === "list"));
      get("assistant-rel-diagram-button").setAttribute("aria-pressed", String(view === "diagram"));
      get("assistant-understand-relationships").hidden = view !== "list";
      get("assistant-understand-diagram").hidden = view !== "diagram";
      if (view === "diagram") renderDiagram(modelView);
    }

    function render() {
      const state = getState() || {};
      const modelView = state.modelView;
      const answers = state.answers || {};
      const questions = state.questions || [];
      if (!modelView) {
        get("assistant-understand-message").textContent = state.message || "Đang đo cấu trúc dữ liệu…";
        for (const id of ["assistant-understand-overview", "assistant-understand-tables",
                           "assistant-understand-relationships", "assistant-understand-diagram",
                           "assistant-understand-warnings"]) get(id).replaceChildren();
        get("assistant-understand-continue").disabled = true;
        return;
      }
      const onClick = (questionId, option) => { setAnswer(questionId, option); render(); };
      const message = get("assistant-understand-message");
      message.textContent = modelView.mode === "per_sheet"
        ? PER_SHEET_NOTE + (modelView.measuredOn === "sample" ? " " + SAMPLE_WARNING : "")
        : modelView.measuredOn === "sample" ? SAMPLE_WARNING : "";
      renderOverview(modelView, questions, answers);
      renderTables(modelView, questions, answers, onClick);
      renderRelationshipList(modelView, questions, answers, onClick);
      renderWarnings(modelView, questions, answers, onClick);
      get("assistant-understand-continue").disabled = false;
      switchView(modelView, view);
    }

    get("assistant-rel-list-button").addEventListener("click", () => switchView(getState()?.modelView, "list"));
    get("assistant-rel-diagram-button").addEventListener("click", () => switchView(getState()?.modelView, "diagram"));
    get("assistant-understand-continue").addEventListener("click", () => { if (typeof onContinue === "function") onContinue(); });
    render();
    return {render, keySentence, view: () => view};
  }

  const api = {mount};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.ReqwiseAssistantUnderstand = api;
})(typeof window !== "undefined" ? window : globalThis);