/* One assistant journey: 1. Nguồn → 2. Đề bài. Only a verified re-read enables the problem step. */
(function (root) {
  "use strict";
  function mount({document, selectWorkbook, scanWorkbook, showProblem = () => {}, invalidateBusiness = () => {},
    onStepChange = () => {}, restartSession, canRestartAfterPartial = false, onBrowse, onImported = () => {}}) {
    const get = id => document.getElementById(id);
    const externalBrowser = typeof onBrowse === "function";
    let step = "source", busy = false, canProblem = false, blocked = false, scanFailed = false;
    let renderedStep = null, canRestart = false;
    const progress = value => {
      const message = typeof value === "string" ? value : value?.message || "Đang xử lý…";
      get("assistant-source-message").textContent = message;
    };
    const element = (tag, text) => { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; return node; };
    function render() {
      document.body?.classList?.toggle?.("assistant-source-entry", step === "source");
      get("assistant-source-choice").hidden = step !== "source";
      get("assistant-step-source").disabled = busy;
      get("assistant-step-problem").disabled = !canProblem || busy || blocked;
      for (const id of ["assistant-choose-folder", "assistant-choose-workbook", "assistant-add-source"]) get(id).disabled = busy || blocked;
      get("assistant-add-source").hidden = step === "source";
      get("assistant-retry-scan").hidden = !scanFailed;
      get("assistant-retry-scan").disabled = busy || blocked;
      get("assistant-new-session").hidden = !canRestart;
      get("assistant-new-session").disabled = busy || blocked && !canRestartAfterPartial;
      get("flow-source-title").textContent = step === "source" ? "Bạn muốn lấy dữ liệu từ đâu?" : "Đề bài";
      get("assistant-step-source").setAttribute("aria-current", step === "source" ? "step" : "false");
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
        if (error.code === "DP_PARTIAL_UNKNOWN" || error.status === "partial_unknown") { blocked = true; canProblem = false; }
        progress(`${error.message || "Không thể hoàn tất."}${blocked ? (canRestartAfterPartial
          ? " Kiểm tra các sheet hiện có rồi bắt đầu phiên mới; không đọc lại tự động."
          : " Thao tác có thể đã ghi một phần. Kiểm tra workbook và trạng thái phục hồi; không đọc lại tự động.") : ""}`);
      }
      finally { busy = false; render(); }
    }
    function dirty() { canProblem = false; invalidateBusiness(); }
    async function scan() {
      progress("Đang đọc lại nguồn…");
      const result = await scanWorkbook({onProgress: progress});
      const state = result?.state || result;
      if (!state?.sourceHash || !state.sources?.length) throw new Error("Chưa xác minh được dữ liệu trên toàn bộ sheet. Hãy kiểm tra rồi đọc lại nguồn.");
      canProblem = true; scanFailed = false;
      progress(`Đã đọc lại ${state.sources.length} nguồn. Bạn có thể tiếp tục: Đề bài.`);
      return state;
    }
    async function readSource() {
      try { return await scan(); }
      catch (error) { canProblem = false; scanFailed = true; throw error; }
      finally { render(); }
    }
    get("assistant-new-session").addEventListener("click", () => {
      if (canRestartAfterPartial && canRestart && !busy) blocked = false;
      return run(async () => {
        if (!canRestart || typeof restartSession !== "function") return;
        await restartSession();
        canProblem = false; scanFailed = false; canRestart = false; step = "source";
        invalidateBusiness(); progress("Đã bắt đầu phiên mới. Chọn nguồn để tiếp tục.");
      });
    });
    get("assistant-choose-folder").addEventListener("click", () => {
      if (!busy && !blocked) onBrowse?.();
    });
    get("assistant-choose-workbook").addEventListener("click", () => run(async () => {
      if (selectWorkbook && !await selectWorkbook()) { progress("Workbook chưa có dữ liệu phù hợp để đọc. Hãy thêm dữ liệu rồi thử lại."); return; }
      await readSource();
    }));
    get("assistant-retry-scan").addEventListener("click", () => run(readSource));
    function addSource() { if (!busy && !blocked) { step = "source"; render(); } }
    get("assistant-add-source").addEventListener("click", () => {
      if (busy || blocked) return;
      addSource();
      if (externalBrowser) onBrowse({reopen: true});
    });
    get("assistant-step-source").addEventListener("click", addSource);
    get("assistant-step-problem").addEventListener("click", () => {
      if (busy || !canProblem || blocked) return;
      return run(async () => {
        invalidateBusiness();
        try { await showProblem(); step = "problem"; }
        catch (error) { step = "source"; canProblem = false; throw error; }
      });
    });
    render();
    return {addSource, state: () => ({step, busy, blocked, canProblem, scanFailed}),
      setBusy(value) { busy = Boolean(value); render(); },
      invalidate: dirty,
      imported() { dirty(); return run(readSource); },
      readSource,
      updateWorkbook(value) {
        step = "source"; canProblem = false; scanFailed = false; blocked = false;
        get("assistant-workbook-summary").textContent = `${value?.name || "Workbook"} · ${value?.hasData ? "Có dữ liệu trong workbook" : "Chưa có dữ liệu"}`;
        render();
      }};
  }
  const api = {mount};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.ReqwiseAssistantEntry = api;
})(typeof window !== "undefined" ? window : globalThis);
