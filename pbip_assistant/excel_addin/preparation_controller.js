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
    onDirty = () => {}, onBusy = () => {}}) {
    const wizard = new Wizard(post);
    let busy = false, blocked = false, questionIndex = 0, inventory = null, warnings = [];
    const sourceLabels = new Map();
    const node = (tag, text, className) => {
      const el = document.createElement(tag);
      if (text !== undefined) el.textContent = text;
      if (className) el.className = className;
      return el;
    };
    const message = document.getElementById("preparation-message") || {textContent: ""};
    const panel = document.getElementById("preparation-panel") || {replaceChildren() {}, append() {}};
    const dates = document.getElementById("preparation-date-system") || {value: "", disabled: false};
    const scanButton = document.getElementById("preparation-scan") || {disabled: false, addEventListener() {}};
    const progress = value => { message.textContent = typeof value === "string" ? value : value?.message || "Đang xử lý tại máy…"; };
    function render() {}
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
    async function inventoryRoot(root) {
      if (typeof root !== "string" || !root.trim()) throw new Error("Hãy chọn một thư mục trước.");
      const read = await runtime.describeWorkbook(environment);
      await ensureAttachment(read);
      const state = await post("inventory", {preparationId: wizard.state.preparationId,
        root, relativePath: "."});
      inventory = state.inventory; wizard.accept(state); wizard.go(0);
      return inventory;
    }
    render();
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
      render();
    }};
  }
  const api = {Wizard, mount};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.ReqwisePreparation = api;
})(typeof window !== "undefined" ? window : globalThis);
