/* One assistant journey; only verified runtime receipts advance source/clean gates. */
(function (root) {
  "use strict";
  function mount({document, chooseFolder, inventory, selectWorkbook, showCleaning, importFiles, scanWorkbook,
    canImport = () => true, importBlocker = () => "Chưa hoàn tất kiểm chứng bảo toàn dữ liệu khi nhập file.",
    showProblem = () => {}, invalidateBusiness = () => {}, onStepChange = () => {}, restartSession, canRestartAfterPartial = false,
    onBrowse, onImported = () => {}}) {
    const get = id => document.getElementById(id);
    const externalBrowser = typeof onBrowse === "function";
    let step = "source", busy = false, canClean = false, canProblem = false, folder = null, preparation = null, blocked = false;
    const selected = new Set();
    let renderedStep = null, canRestart = false;
    const progress = value => {
      const message = typeof value === "string" ? value : value?.message || "Đang xử lý…";
      get("assistant-source-message").textContent = message;
      const importMessage = get("assistant-import-message");
      if (importMessage) importMessage.textContent = message;
      if (step === "clean") {
        const cleaningMessage = get("preparation-message");
        if (cleaningMessage) cleaningMessage.textContent = message;
      }
    };
    const element = (tag, text) => { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; return node; };
    const files = () => folder?.files || [];
    const blockers = file => (folder?.errors || []).filter(error => error.fileId === file.fileId || error.fileName === file.fileName);
    const sheets = file => (folder?.sheets || []).filter(sheet => sheet.fileId === file.fileId);
    const eligible = file => !blockers(file).length && sheets(file).length > 0 && file.importable !== false;
    function render() {
      document.body?.classList?.toggle("assistant-source-entry", step === "source");
      get("assistant-source-choice").hidden = step !== "source";
      if (!externalBrowser) {
        get("assistant-folder-result").hidden = step !== "source" || !folder;
        get("assistant-import-actions").hidden = step !== "source" || !folder;
        get("assistant-select-all").disabled = busy || blocked;
        get("assistant-import-selected").disabled = busy || blocked || !selected.size || !canImport();
        get("assistant-selected-count").textContent = `${selected.size} / ${files().length} file được chọn`;
        for (const control of controls) control.disabled = busy || blocked || !eligible(control.sourceFile);
      }
      get("preparation-wizard").hidden = step !== "clean";
      get("flow-source-legacy").hidden = true;
      get("assistant-step-source").disabled = busy;
      get("assistant-step-clean").disabled = !canClean || busy || blocked;
      get("assistant-step-problem").disabled = !canProblem || busy || blocked;
      for (const id of ["assistant-choose-folder", "assistant-choose-workbook", "assistant-add-source"]) get(id).disabled = busy || blocked;
      get("assistant-add-source").hidden = step === "source";
      get("assistant-import-selected").disabled = busy || blocked || !selected.size || !canImport();
      get("assistant-new-session").hidden = !canRestart;
      get("assistant-new-session").disabled = busy || blocked && !canRestartAfterPartial;
      get("flow-source-title").textContent = step === "source" ? "Bạn muốn lấy dữ liệu từ đâu?" : "Làm sạch dữ liệu";
      for (const name of ["source", "clean", "problem"]) get("assistant-step-" + name).setAttribute("aria-current", step === name ? "step" : "false");
      get("assistant-selected-count").textContent = `${selected.size} / ${files().length} file được chọn`;
      for (const control of controls) control.disabled = busy || blocked || !eligible(control.sourceFile);
      if (renderedStep !== step) { renderedStep = step; onStepChange(step); }
    }
    const controls = [];
    function renderFiles() {
      const target = get("assistant-folder-result"); target.replaceChildren(); controls.length = 0;
      target.append(element("p", `${folder.folderName || "Thư mục đã chọn"} · ${files().length} file`));
      for (const file of files()) {
        const label = element("label"); label.className = "assistant-file-option";
        const check = element("input"); check.type = "checkbox"; check.value = file.fileId; check.sourceFile = file;
        check.checked = selected.has(file.fileId); check.disabled = !eligible(file);
        check.setAttribute("aria-label", file.fileName);
        check.addEventListener("change", () => { if (!busy && eligible(file)) { check.checked ? selected.add(file.fileId) : selected.delete(file.fileId); render(); } });
        const detail = element("span", `${file.fileName} · ${sheets(file).length} sheet${file.kind === "xlsx" ? " (nhập toàn bộ nhóm)" : ""}`);
        label.append(check, detail);
        for (const error of blockers(file)) label.append(element("small", `${error.code}: ${error.detail || "Kiểm tra định dạng file trước khi nhập."}`));
        if (!eligible(file) && !blockers(file).length) label.append(element("small", "Chưa có sheet được hỗ trợ để nhập."));
        for (const sheet of sheets(file)) label.append(element("small", `${sheet.sourceName || sheet.sourceSheetName || "CSV"} → ${sheet.proposedName}`));
        controls.push(check); target.append(label);
      }
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
          ? " Kiểm tra các sheet hiện có rồi bắt đầu phiên mới; không nhập lại tự động."
          : " Thao tác có thể đã ghi một phần. Kiểm tra workbook và trạng thái phục hồi; không nhập lại tự động.") : ""}`);
      }
      finally { busy = false; render(); }
    }
    function dirty() { canProblem = false; invalidateBusiness(); }
    get("assistant-new-session").addEventListener("click", () => {
      if (canRestartAfterPartial && canRestart && !busy) blocked = false;
      return run(async () => {
      if(!canRestart||typeof restartSession!=="function")return;
      await restartSession();
      folder=null;preparation=null;selected.clear();canClean=false;canProblem=false;canRestart=false;step="source";
      invalidateBusiness();progress("Đã bắt đầu phiên mới. Chọn nguồn để tiếp tục.");
      });
    });
    async function scan() {
      if (typeof scanWorkbook !== "function") throw new Error("Chưa có bộ quét toàn bộ workbook.");
      canClean = true; step = "clean"; showCleaning({scanRequired: true}); render();
      progress("Đang quét các sheet trong workbook…");
      let result;
      try { result = await scanWorkbook({onProgress: progress, append: true}); }
      catch (error) {
        if (error.code !== "DP_PARTIAL_UNKNOWN" && error.status !== "partial_unknown") {
          canClean = true; step = "clean"; showCleaning({scanRequired: true});
        }
        throw error;
      }
      const state = result?.state || result;
      if (!state?.sourceHash || !state.sources?.length) throw new Error("Chưa xác minh được dữ liệu trên toàn bộ sheet. Hãy kiểm tra rồi quét lại.");
      preparation = state; canClean = true; dirty(); step = "clean"; showCleaning({state}); progress("Đã quét workbook. Xem và duyệt các đề xuất làm sạch.");
    }
    const browseFolder = () => run(async () => {
      const chosen = await chooseFolder();
      if (!chosen || chosen.cancelled) { progress("Chưa chọn thư mục."); return; }
      folder = await inventory(chosen.path); folder = {...folder, folderName: chosen.name}; selected.clear(); renderFiles();
      progress(canImport() ? "Chọn file để nhập vào workbook đang mở. XLSX nhập toàn bộ sheet cùng nhóm." : importBlocker());
    });
    get("assistant-choose-folder").addEventListener("click", () => {
      if (externalBrowser) { if (!busy && !blocked) onBrowse(); return; }
      return browseFolder();
    });
    if (!externalBrowser) {
      get("assistant-select-all").addEventListener("click", () => {
        if (busy || blocked) return;
        const allowed = files().filter(eligible); const all = allowed.every(file => selected.has(file.fileId));
        for (const file of allowed) all ? selected.delete(file.fileId) : selected.add(file.fileId);
        for (const control of controls) control.checked = selected.has(control.sourceFile.fileId);
        render();
      });
      get("assistant-import-selected").addEventListener("click", () => run(async () => {
        if (!canImport()) throw new Error(importBlocker());
        if (!selected.size || typeof importFiles !== "function") throw new Error("Chọn ít nhất một file được hỗ trợ.");
        const fileIds = Array.from(selected);
        const receipt = await importFiles({inventory: folder, fileIds, mappings: folder.sheets.filter(sheet => selected.has(sheet.fileId)), onProgress: progress});
        if (receipt?.status !== "verified") { const error = new Error("Chưa xác minh được kết quả nhập. Kiểm tra workbook và trạng thái phục hồi trước khi tiếp tục."); error.code = "DP_PARTIAL_UNKNOWN"; throw error; }
        dirty(); selected.clear(); for (const control of controls) control.checked = false;
        onImported(receipt);
        await scan();
      }));
    }
    get("assistant-choose-workbook").addEventListener("click", () => run(async () => {
      if (selectWorkbook && !await selectWorkbook()) { progress("Workbook chưa có dữ liệu phù hợp để quét. Hãy thêm dữ liệu rồi thử lại."); return; }
      await scan();
    }));
    function addSource() { if (!busy && !blocked) { step = "source"; render(); } }
    get("assistant-add-source").addEventListener("click", () => { if(!busy&&!blocked){addSource();if(externalBrowser){onBrowse();return;}return browseFolder();} });
    get("assistant-step-source").addEventListener("click", addSource);
    get("assistant-step-clean").addEventListener("click", () => { if (!busy && canClean && !blocked) { step = "clean"; showCleaning(); render(); } });
    get("assistant-step-problem").addEventListener("click", () => {
      if (busy || !canProblem || blocked) return;
      return run(async () => {
        invalidateBusiness();
        try { await showProblem(); step = "problem"; }
        catch (error) { step = "clean"; canProblem = false; invalidateBusiness(); showCleaning(); throw error; }
      });
    });
    render();
    return {addSource, state: () => ({step, busy, blocked, preparation, canProblem}),
      imported(receipt) { dirty(); selected.clear(); return onImported(receipt); },
      setBusy(value) { busy = Boolean(value); render(); },
      invalidate: dirty,
      cleaningComplete(receipt) {
        if (["verified", "noop_verified"].includes(receipt?.status)) { canProblem = true; blocked = false; }
        else {
          canProblem = false;
          if (canRestartAfterPartial && typeof restartSession === "function" &&
              (receipt?.status === "partial_unknown" || ["DP_SOURCE_STALE", "DP_REVIEW_STALE", "DP_BINDING_REQUIRED"].includes(receipt?.code))) canRestart = true;
          if (receipt?.status === "partial_unknown") {
            blocked = true;
            progress(canRestartAfterPartial
              ? "Chưa xác minh được lần áp dụng. Kiểm tra các sheet hiện có rồi bắt đầu phiên mới để đọc lại dữ liệu."
              : "Áp dụng chưa xác định. Kiểm tra workbook và trạng thái phục hồi trước khi tiếp tục.");
          }
        }
        render();
      },
      updateWorkbook(value) {
        step = "source"; canClean = false; canProblem = false; preparation = null; folder = null; blocked = false; selected.clear();
        get("assistant-workbook-summary").textContent = `${value?.name || "Workbook"} · ${value?.hasData ? "Có dữ liệu trong workbook" : "Chưa có dữ liệu"}`; render();
      }};
  }
  const api = {mount};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.ReqwiseAssistantEntry = api;
})(typeof window !== "undefined" ? window : globalThis);
