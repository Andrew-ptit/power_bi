/* Source -> formats -> exceptions -> review. Navigation never restores Excel. */
(function (root) {
  "use strict";
  const steps = ["Nguồn", "Định dạng", "Ngoại lệ", "Xem trước"];
  const labels = {keep_text: "Giữ dạng chữ", DMY: "Ngày / tháng / năm", MDY: "Tháng / ngày / năm", YMD: "Năm / tháng / ngày",
    decimal_dot: "Dấu chấm thập phân (1,234.56)", decimal_comma: "Dấu phẩy thập phân (1.234,56)"};
  const findings = {trim: "Khoảng trắng đầu/cuối", missing: "Ô thiếu", duplicate_row: "Dòng trùng",
    formula_error: "Lỗi công thức", invisible_character: "Tab, xuống dòng hoặc khoảng trắng đặc biệt"};
  class Wizard {
    constructor(post) { this.post = post; this.state = null; this.step = 0; this.epoch = 0; }
    accept(state) { this.state = state; this.epoch++; }
    go(step) { if (!Number.isInteger(step) || step < 0 || step > 3) throw new Error("Bước không hợp lệ"); this.step = step; }
    async request(action, fields) {
      if (!this.state) throw new Error("Đọc nguồn trước khi tiếp tục.");
      const epoch = this.epoch;
      const result = await this.post(action, {preparationId: this.state.preparationId, ...fields});
      if (epoch === this.epoch) this.accept(result);
    }
    async answer(questionId, choice) {
      const question = this.state && this.state.questions.find(q => q.questionId === questionId);
      if (!question || !question.choices.includes(choice)) throw new Error("Câu trả lời không còn phù hợp với nguồn hiện tại.");
      await this.request("answer", {questionId, expectedAnswerRevision: this.state.answerRevision, answer: {choice, reason: null}});
    }
    async preview() {
      if (!this.state || this.state.questions.some(q => !this.state.answers[q.questionId])) throw new Error("Hãy trả lời các câu hỏi định dạng trước.");
      await this.request("preview", {kind: "cleanup", sourceRevision: this.state.sourceRevision,
        answerRevision: this.state.answerRevision, expectedFingerprint: this.state.sourceHash});
      this.go(3);
    }
  }
  function mount({document, post, runtime, environment, deferOpen = false, scanWorkbook,
    applyCleanup, undo, redo, onApplied = () => {}, onDirty = () => {}, onBusy = () => {}}) {
    const host = document.getElementById("preparation-wizard");
    if (!host) return null;
    const wizard = new Wizard(post);
    let busy = false, blocked = false, questionIndex = 0, inventory = null, warnings = [];
    const sourceLabels = new Map();
    const node = (tag, text, className) => {
      const el = document.createElement(tag);
      if (text !== undefined) el.textContent = text;
      if (className) el.className = className;
      return el;
    };
    const message = document.getElementById("preparation-message");
    const panel = document.getElementById("preparation-panel");
    const dates = document.getElementById("preparation-date-system");
    const scanButton = document.getElementById("preparation-scan");
    const progress = value => { message.textContent = typeof value === "string" ? value : value?.message || "Đang xử lý tại máy…"; };
    async function run(action, reportApplyFailure = true) {
      if (busy || blocked) return;
      busy = true; scanButton.disabled = true; dates.disabled = true; onBusy(true); render();
      message.textContent = "Đang xử lý tại máy…";
      try { await action(); }
      catch (error) {
        if (wizard.state?.backupEnabled === false && reportApplyFailure && error.code !== "DP_PARTIAL_UNKNOWN" && error.status !== "partial_unknown") {
          onApplied({status: "failed", code: error.code});
        }
        if (error.code === "DP_PARTIAL_UNKNOWN" || error.status === "partial_unknown") {
          blocked = true; onDirty(); if (reportApplyFailure) onApplied({status: "partial_unknown"});
        }
        message.textContent = /Preparation request does not match/.test(error.message || "")
        ? "Không thể đọc nguồn với lựa chọn hiện tại. Hãy quay lại Nguồn và chọn lại."
        : `${error.message || "Không thể hoàn tất. Hãy đọc lại nguồn."}${blocked ? (wizard.state?.backupEnabled === false
          ? " Kiểm tra các sheet hiện có rồi bắt đầu phiên mới để quét lại."
          : " Kiểm tra workbook và trạng thái phục hồi; không áp dụng lại tự động.") : ""}`; }
      finally { busy = false; scanButton.disabled = blocked; dates.disabled = blocked; onBusy(false); render(); }
    }
    function button(text, action, disabled = false) {
      const el = node("button", text, "button button-ghost"); el.type = "button"; el.disabled = disabled || busy || blocked;
      el.addEventListener("click", () => { if (!busy && !blocked) return action(); }); return el;
    }
    function render() {
      panel.replaceChildren();
      const state = wizard.state;
      if (warnings.length) {
        const warningList = node("ul"); warningList.setAttribute("aria-label", "Sheet chưa được quét");
        for (const warning of warnings) warningList.append(node("li", typeof warning === "string" ? warning
          : `${warning.sheetName || warning.name || warning.sheetId || "Sheet"}: ${warning.code || "Cần kiểm tra"}${warning.message ? " · " + warning.message : ""}`));
        panel.append(warningList);
      }
      const navigation = node("nav"); navigation.setAttribute("aria-label", "Các bước làm sạch");
      steps.forEach((label, i) => {
        if (deferOpen && i === 0) return;
        const el = button(deferOpen ? label : `${i + 1} · ${label}`, () => { wizard.go(i); render(); }, !state?.sourceHash && i > 0);
        el.setAttribute("aria-current", wizard.step === i ? "step" : "false"); navigation.append(el);
      });
      if (!deferOpen || state?.sourceHash) panel.append(navigation);
      if (wizard.step === 0) {
        panel.append(node("p", typeof scanWorkbook === "function"
          ? "Xác nhận hệ ngày của workbook rồi quét toàn bộ sheet có dữ liệu. File đã nhập được giữ lại; không cần nhập lại."
          : "Chọn vùng chữ nhật gồm dòng tiêu đề và dữ liệu trong Excel, xác nhận hệ ngày rồi bấm Quét vùng đã chọn."));
        if (state && !deferOpen) panel.append(node("p", `${state.sources.length} nguồn · phiên bản dữ liệu ${state.sourceRevision}. Quét lại khi sửa ô trong Excel.`));
        if (inventory) {
          panel.append(node("p", "Danh sách folder để rà soát; chức năng nhập sheet đang chờ kiểm chứng."));
          const list = node("ul");
          for (const file of inventory.files || []) list.append(node("li", `${file.fileName} · ${file.kind}`));
          for (const sheet of inventory.sheets || []) list.append(node("li", `${sheet.sourceSheetName || sheet.sourceName || "CSV"} → ${sheet.proposedName || ""}`));
          panel.append(list);
          for (const error of inventory.errors || []) panel.append(node("p", `${error.fileName}: ${error.code} · ${error.detail || "Cần kiểm tra trước khi nhập"}`));
        }
      } else if (!state || !state.sourceHash) {
        panel.append(node("p", "Hãy quét vùng dữ liệu ở bước 1 trước."));
      } else if (wizard.step === 1) {
        const questions = state.questions;
        if (!questions.length) panel.append(node("p", "Không có câu hỏi chuyển kiểu. Bạn có thể xem các ngoại lệ."));
        else {
          questionIndex = Math.min(questionIndex, questions.length - 1);
          const question = questions[questionIndex];
          panel.append(node("p", `Câu ${questionIndex + 1}/${questions.length} · cột ${question.label}`));
          if (question.leadingZeroWarning) panel.append(node("p", "Cột có thể là mã có số 0 đầu. Chuyển sang số sẽ mất số 0; hãy kiểm tra trước."));
          for (const choice of question.choices) {
            const selected = state.answers[question.questionId]?.choice === choice;
            const el = button(`${selected ? "✓ " : ""}${labels[choice] || choice}`, () => run(async () => { await wizard.answer(question.questionId, choice); onDirty(); progress("Đã cập nhật câu trả lời; cần tạo lại bản xem trước."); }));
            el.setAttribute("aria-pressed", String(selected)); panel.append(el);
          }
          panel.append(button("Câu trước", () => { questionIndex--; render(); }, questionIndex === 0),
            button("Câu tiếp", () => { questionIndex++; render(); }, questionIndex === questions.length - 1));
          const index = node("details"); index.append(node("summary", "Xem lại tất cả câu trả lời"));
          questions.forEach((q, i) => index.append(button(`${q.label}: ${labels[state.answers[q.questionId]?.choice] || "Chưa trả lời"}`,
            () => { questionIndex = i; render(); })));
          panel.append(index);
        }
      } else if (wizard.step === 2) {
        panel.append(node("p", "Ô thiếu, dòng trùng và lỗi công thức chỉ được báo để bạn kiểm tra. Không tự điền hoặc xóa."));
        const list = node("ul");
        for (const f of state.findings) {
          const source = sourceLabels.get(f.sourceId) || f.sheetId || f.sourceId;
          const item = node("li", `${source} · ${f.columnLabel || "Toàn dòng"} · ${findings[f.kind] || f.kind}: ${f.count} · toàn bộ vùng đã chọn`);
          const examples = node("ul");
          for (const example of f.examples || []) examples.append(node("li",
            `${example.address}: ${example.value === null ? (f.column === null ? "dòng cần kiểm tra" : "trống") : JSON.stringify(example.value)}`));
          if (!(f.examples || []).length && f.firstAddress) examples.append(node("li", `Vị trí đầu tiên: ${f.firstAddress}`));
          item.append(examples); list.append(item);
        }
        panel.append(list, button("Tạo bản xem trước", () => run(() => wizard.preview())));
      } else {
        const preview = state.preview;
        if (!preview) panel.append(node("p", "Chưa có bản xem trước hiện hành. Sửa quy tắc hoặc quét lại sẽ hủy bản cũ."),
          button("Tạo bản xem trước", () => run(() => wizard.preview())));
        else {
          panel.append(node("p", `${preview.changeCount} ô được đề xuất thay đổi · hiển thị tối đa 20 ví dụ.`));
          const list = node("ul");
          for (const item of preview.examples) list.append(node("li", `${item.address}: ${JSON.stringify(item.before)} → ${JSON.stringify(item.after)}${item.numberFormat ? " · " + item.numberFormat : ""}${item.displayTruncated ? " (rút gọn hiển thị)" : ""}`));
          panel.append(list);
        }
        const noChanges = preview?.changeCount === 0;
        panel.append(node("p", noChanges
          ? "Duyệt dữ liệu hiện tại sau khi kiểm tra lại nguồn; không thay đổi ô nào."
          : state.writeEnabled && applyCleanup
          ? state.backupEnabled === false
            ? "Duyệt bản xem trước để áp dụng. Add-in không lưu bản khôi phục. Sheet cá nhân tạo kết quả trên bản sao riêng."
            : "Duyệt đúng bản xem trước này để áp dụng. Sheet cá nhân được giữ nguyên; kết quả nằm trên bản sao riêng."
          : "Chưa bật Áp dụng. Hãy kiểm tra nguồn và bản xem trước hiện tại."),
          button(noChanges ? "Dùng dữ liệu này" : "Áp dụng", () => run(async () => {
            const receipt = await applyCleanup({state: wizard.state, onProgress: progress});
            if (!["verified", "noop_verified"].includes(receipt?.status)) {
              const error = new Error("Chưa xác minh được kết quả áp dụng."); error.code = "DP_PARTIAL_UNKNOWN"; throw error;
            }
            onApplied(receipt); progress("Đã xác minh kết quả. Bạn có thể tiếp tục tới Đề bài.");
          }), !preview || !noChanges && !state.writeEnabled || typeof applyCleanup !== "function"));
      }
      if (state && state.backupEnabled !== false) {
        const restore = (direction, callback) => run(async () => {
          const receipt = await callback({state: wizard.state, onProgress: progress});
          if (receipt?.status !== "verified" || !receipt.state) {
            const error = new Error("Chưa xác minh được kết quả khôi phục."); error.code = "DP_PARTIAL_UNKNOWN"; throw error;
          }
          wizard.accept(receipt.state); onDirty(); progress(direction === "undo" ? "Đã xác minh khôi phục." : "Đã xác minh làm lại.");
        }, false);
        const journalReady = state.writeEnabled && state.journal?.status === "ready";
        panel.append(button("↶ Khôi phục", () => restore("undo", undo), !journalReady || !(state.journal.undoCount > 0) || typeof undo !== "function"),
          button("↷ Làm lại", () => restore("redo", redo), !journalReady || !(state.journal.redoCount > 0) || typeof redo !== "function"));
      }
      const footer = node("div", undefined, "flow-actions");
      footer.append(button("← Quay lại", () => { wizard.go(wizard.step - 1); render(); }, wizard.step === 0 || deferOpen && wizard.step === 1),
        button("Tiếp →", () => { wizard.go(wizard.step + 1); render(); }, wizard.step === 3 || !state?.sourceHash
          || wizard.step === 1 && state.questions.some(q => !state.answers[q.questionId])));
      if (!deferOpen || wizard.step > 0) panel.append(footer);
    }
    async function ensureAttachment(read) {
      if (wizard.state) return;
      const bytes = new TextEncoder().encode(JSON.stringify({name: read.workbookName, sheet: read.sheetId || read.snapshot.sheetId}));
      const digest = await environment.crypto.subtle.digest("SHA-256", bytes);
      const fingerprint = "sha256:" + Array.from(new Uint8Array(digest), b => b.toString(16).padStart(2, "0")).join("");
      wizard.accept(await post("attach", {claim: {marker: null, semanticFingerprint: fingerprint, targetConfirmed: true,
        expectedClaimVersion: 0, workbookName: read.workbookName, locationHash: null}}));
    }
    async function scanAll(options = {}) {
      if (typeof scanWorkbook !== "function") throw new Error("Chưa có bộ quét toàn bộ workbook.");
      const result = await scanWorkbook({dateSystem: dates.value || null, append: true, onProgress: progress, ...options});
      const state = result?.state || result;
      if (!state?.sourceHash || !state.sources?.length) throw new Error("Chưa xác minh được các sheet đã quét.");
      if (result?.sourceLabels) {
        const entries = result.sourceLabels instanceof Map ? result.sourceLabels.entries()
          : Array.isArray(result.sourceLabels) ? result.sourceLabels.map(item => Array.isArray(item) ? item : [item.sourceId, item.sheetName || item.name])
          : Object.entries(result.sourceLabels);
        for (const [sourceId, label] of entries) sourceLabels.set(sourceId, label);
      }
      warnings = result?.warnings || [];
      if (["1900", "1904"].includes(result?.dateSystem)) dates.value = result.dateSystem;
      wizard.accept(state); questionIndex = 0; wizard.go(1); onDirty(); render();
      return state;
    }
    scanButton.addEventListener("click", () => run(async () => {
      if (typeof scanWorkbook === "function") { await scanAll(); progress("Đã quét toàn bộ sheet có dữ liệu. Chưa thay đổi ô nào."); return; }
      const read = await runtime.readSelection(environment, dates.value);
      sourceLabels.set(read.snapshot.sourceId, read.sheetName);
      await ensureAttachment(read);
      wizard.accept(await post("source-snapshot", {preparationId: wizard.state.preparationId, snapshot: read.snapshot}));
      const state = wizard.state;
      wizard.accept(await post("scan", {preparationId: state.preparationId, sourceRevision: state.sourceRevision,
        expectedFingerprint: state.sourceHash, sources: state.sources.map(s => ({sourceId: s.sourceId, sheetId: s.sheetId,
          fingerprint: s.fingerprint, kind: "usedRange"}))}));
      questionIndex = 0; wizard.go(1);
    }));
    async function inventoryRoot(root) {
      if (typeof root !== "string" || !root.trim()) throw new Error("Hãy chọn một thư mục trước.");
      const read = await runtime.describeWorkbook(environment);
      await ensureAttachment(read);
      const state = await post("inventory", {preparationId: wizard.state.preparationId,
        root, relativePath: "."});
      inventory = state.inventory; wizard.accept(state); wizard.go(0);
      return inventory;
    }
    document.getElementById("preparation-inventory").addEventListener("click", () => run(() =>
      inventoryRoot(document.getElementById("flow-root-input").value)));
    host.hidden = deferOpen; render();
    return {wizard, inventoryRoot, scanWorkbook: scanAll,
      acceptState(state) {
        if (state?.backupEnabled === false && state.preparationId !== wizard.state?.preparationId) {
          blocked = false; warnings = []; inventory = null; questionIndex = 0;
          scanButton.disabled = false; dates.disabled = false;
        }
        wizard.accept(state); render();
      },
      acceptScan(state) { wizard.accept(state); questionIndex = 0; wizard.go(1); render(); },
      show({state, scanRequired = false} = {}) {
      if (state) { wizard.accept(state); questionIndex = 0; wizard.go(1); }
      if (scanRequired) {
        if (wizard.state) wizard.accept({...wizard.state, sourceHash: null, preview: null, writeEnabled: false});
        wizard.go(0); progress("Dữ liệu được giữ nguyên. Xác nhận hệ ngày và quét workbook để tiếp tục.");
      }
      host.hidden = false; host.open = true; render();
    }};
  }
  const api = {Wizard, mount};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.ReqwisePreparation = api;
})(typeof window !== "undefined" ? window : globalThis);
