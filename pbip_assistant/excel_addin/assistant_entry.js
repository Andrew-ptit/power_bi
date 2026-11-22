/* One assistant journey: 1. Nguồn → 2. Hiểu dữ liệu → 3. Đề bài (feature 004).
 * A verified source enables the understand step; the understand step being
 * ready (a modelView exists) is the gate to Đề bài. */
(function (root) {
  "use strict";
  function mount({document, selectWorkbook, scanWorkbook, onUnderstand, showProblem = () => {}, invalidateBusiness = () => {},
    onStepChange = () => {}, restartSession, canRestartAfterPartial = false, onBrowse, onImported = () => {}}) {
    const get = id => document.getElementById(id);
    const externalBrowser = typeof onBrowse === "function";
    const canMeasure = typeof onUnderstand === "function";
    let step = "source", busy = false, canUnderstand = false, understandReady = false, blocked = false, scanFailed = false;
    let measureFailed = false, retriedOnce = false;
    let renderedStep = null, canRestart = false;
    const progress = value => {
      const message = typeof value === "string" ? value : value?.message || "Đang xử lý…";
      get("assistant-source-message").textContent = message;
      get("assistant-understand-message").textContent = message;
    };
    const element = (tag, text) => { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; return node; };
    function render() {
      document.body?.classList?.toggle?.("assistant-source-entry", step === "source");
      get("assistant-source-choice").hidden = step !== "source";
      get("assistant-understand-section").hidden = step !== "understand";
      get("assistant-understand-retry").hidden = !measureFailed || step !== "understand";
      get("assistant-step-source").disabled = busy;
      get("assistant-step-understand").disabled = busy || !canUnderstand || blocked;
      get("assistant-step-problem").disabled = busy || !understandReady || blocked;
      for (const id of ["assistant-choose-folder", "assistant-choose-workbook", "assistant-add-source"]) get(id).disabled = busy || blocked;
      get("assistant-add-source").hidden = step === "source";
      get("assistant-retry-scan").hidden = !scanFailed;
      get("assistant-retry-scan").disabled = busy || blocked;
      get("assistant-new-session").hidden = !canRestart;
      get("assistant-new-session").disabled = busy || blocked && !canRestartAfterPartial;
      get("assistant-understand-continue").disabled = busy || !understandReady || blocked || !canMeasure;
      get("assistant-understand-back").disabled = busy;
      get("assistant-understand-retry").disabled = busy || blocked;
      get("flow-source-title").textContent = step === "source" ? "Bạn muốn lấy dữ liệu từ đâu?"
        : step === "understand" ? "Dữ liệu của bạn trông như thế nào?" : "Đề bài";
      get("assistant-step-source").setAttribute("aria-current", step === "source" ? "step" : "false");
      get("assistant-step-understand").setAttribute("aria-current", step === "understand" ? "step" : "false");
      get("assistant-step-problem").setAttribute("aria-current", step === "problem" ? "step" : "false");
      if (renderedStep !== step) { renderedStep = step; onStepChange(step); }
    }
    async function run(action) {
      if (busy || blocked) return;
      busy = true; progress("Đang xử lý…"); render();
      try { await action(); }
      catch (error) {
        canRestart = typeof restartSession === "function" && (["DP_POINT_EXPIRED", "DP_RESTORE_CONFLICT", "DP_BINDING_REQUIRED", "DP_SOURCE_STALE", "DP_REVIEW_STALE"].includes(error.code)
          || canRestartAfterPartial && error.code === "DP_PARTIAL_UNKNOWN");
        if (error.code === "DP_PARTIAL_UNKNOWN" || error.status === "partial_unknown") { blocked = true; canUnderstand = false; understandReady = false; }
        progress(`${error.message || "Không thể hoàn tất."}${blocked ? (canRestartAfterPartial
          ? " Kiểm tra các sheet hiện có rồi bắt đầu phiên mới; không đọc lại tự động."
          : " Thao tác có thể đã ghi một phần. Kiểm tra workbook và trạng thái phục hồi; không đọc lại tự động.") : ""}`);
      }
      finally { busy = false; render(); }
    }
    function dirty() { canUnderstand = false; understandReady = false; measureFailed = false; retriedOnce = false; invalidateBusiness(); }
    async function scan() {
      progress("Đang đọc lại nguồn…");
      const result = await scanWorkbook({onProgress: progress});
      const state = result?.state || result;
      if (!state?.sourceHash || !state.sources?.length) throw new Error("Chưa xác minh được dữ liệu trên toàn bộ sheet. Hãy kiểm tra rồi đọc lại nguồn.");
      canUnderstand = true; scanFailed = false;
      progress(`Đã đọc lại ${state.sources.length} nguồn. Đang đo cấu trúc dữ liệu…`);
      return state;
    }
    async function measure() {
      if (!canMeasure || !canUnderstand) return;
      progress("Đang đo cấu trúc dữ liệu…");
      try {
        const result = await onUnderstand();
        if (!result?.modelView) throw new Error("Chưa đo được cấu trúc dữ liệu. Hãy đọc lại nguồn.");
        understandReady = true; measureFailed = false;
        progress("Đã đo cấu trúc dữ liệu. Rà soát bên dưới rồi tiếp tục: Đề bài.");
        return result;
      } catch (error) {
        understandReady = false; measureFailed = true;
        if (error.code !== "AF_UNDERSTAND_LIMIT" && error.code !== "REQUEST_LIMIT") {
          progress(`${error.message || "Chưa đo được cấu trúc dữ liệu."} Bấm Đo lại hoặc Về Nguồn.`);
        }
        throw error;
      }
    }
    async function readSource({advance = false} = {}) {
      try { await scan(); }
      catch (error) { canUnderstand = false; scanFailed = true; render(); throw error; }
      render();
      if (advance && canUnderstand) {
        invalidateBusiness();
        step = "understand";
        render();
        try { await measure(); }
        catch (error) { render(); throw error; }
      }
    }
    get("assistant-new-session").addEventListener("click", () => {
      if (canRestartAfterPartial && canRestart && !busy) blocked = false;
      return run(async () => {
        if (!canRestart || typeof restartSession !== "function") return;
        await restartSession();
        canUnderstand = false; understandReady = false; scanFailed = false; canRestart = false;
        measureFailed = false; retriedOnce = false; step = "source";
        invalidateBusiness(); progress("Đã bắt đầu phiên mới. Chọn nguồn để tiếp tục.");
      });
    });
    get("assistant-choose-folder").addEventListener("click", () => {
      if (!busy && !blocked) onBrowse?.();
    });
    get("assistant-choose-workbook").addEventListener("click", () => run(async () => {
      if (selectWorkbook && !await selectWorkbook()) { progress("Workbook chưa có dữ liệu phù hợp để đọc. Hãy thêm dữ liệu rồi thử lại."); return; }
      await readSource({advance: true});
    }));
    get("assistant-retry-scan").addEventListener("click", () => run(() => readSource({advance: true})));
    function addSource() { if (!busy && !blocked) { step = "source"; render(); } }
    get("assistant-add-source").addEventListener("click", () => {
      if (busy || blocked) return;
      addSource();
      if (externalBrowser) onBrowse({reopen: true});
    });
    get("assistant-step-source").addEventListener("click", addSource);
    get("assistant-step-understand").addEventListener("click", () => {
      if (busy || !canUnderstand || blocked) return;
      return run(async () => {
        step = "understand";
        render();
        try { await measure(); }
        catch (error) { render(); throw error; }
      });
    });
    get("assistant-step-problem").addEventListener("click", () => {
      if (busy || !understandReady || blocked) return;
      return run(async () => {
        invalidateBusiness();
        try { await showProblem(); step = "problem"; }
        catch (error) { step = "understand"; canUnderstand = false; understandReady = false; throw error; }
      });
    });
    get("assistant-understand-continue").addEventListener("click", () => stepToProblem());
    get("assistant-understand-retry").addEventListener("click", () => run(() => measure()));
    get("assistant-understand-back").addEventListener("click", () => {
      if (busy || blocked) return;
      step = "source"; measureFailed = false; render();
    });
    function stepToProblem() {
      if (busy || !understandReady || blocked) return;
      return run(async () => {
        invalidateBusiness();
        try { await showProblem(); step = "problem"; }
        catch (error) { step = "understand"; understandReady = false; throw error; }
      });
    }
    render();
    return {addSource, state: () => ({step, busy, blocked, canUnderstand, understandReady, scanFailed, measureFailed}),
      setBusy(value) { busy = Boolean(value); render(); },
      invalidate: dirty,
      imported() { dirty(); return run(() => readSource({advance: true})); },
      readSource,
      stepToProblem,
      updateWorkbook(value) {
        step = "source"; canUnderstand = false; understandReady = false; scanFailed = false; blocked = false;
        measureFailed = false; retriedOnce = false;
        get("assistant-workbook-summary").textContent = `${value?.name || "Workbook"} · ${value?.hasData ? "Có dữ liệu trong workbook" : "Chưa có dữ liệu"}`;
        render();
      }};
  }
  const api = {mount};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.ReqwiseAssistantEntry = api;
})(typeof window !== "undefined" ? window : globalThis);