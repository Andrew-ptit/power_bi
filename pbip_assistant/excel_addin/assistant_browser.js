/* Folder browser, file selection and import report for the single Nguồn tab. */
(function (root) {
  "use strict";
  const REASON_LABELS = {
    DECIMAL_DOT: "số · dấu chấm thập phân",
    DECIMAL_COMMA: "số · dấu phẩy thập phân",
    GROUP_SEPARATOR: "số · dấu phân cách nghìn",
    DATE_ORDER_DETECTED: "ngày · thứ tự tự nhận",
    DATE_DMY_DEFAULT: "ngày · mặc định ngày/tháng/năm",
    INVALID_DATE_TEXT: "ngày không hợp lệ · giữ chữ",
    DATE_UNSUPPORTED_TEXT: "ngày chưa hỗ trợ · giữ chữ",
    LEADING_ZERO_TEXT: "mã có số 0 đầu · giữ chữ",
    MIXED_TYPE_TEXT: "cột trộn kiểu · giữ chữ",
    PRECISION_TEXT: "số vượt độ chính xác · giữ chữ",
    FORMULA_LIKE_TEXT: "giống công thức · giữ chữ",
    EMPTY_COLUMN: "cột rỗng",
    ENCODING_FALLBACK: "đã tự chọn bảng mã",
    DELIMITER_INFERRED: "đã tự chọn dấu phân cách"
  };
  const KIND_LABELS = {number: "Number", date: "Date", text: "Text"};
  const EMPTY_FOLDER = "Thư mục này không có file .csv hoặc .xlsx.";
  const EMPTY_CHOICE = "Chưa chọn thư mục.";

  function create({document, bridge, onImported = () => {}}) {
    if (!document || !bridge) throw new Error("Trình duyệt nguồn cần document và bridge.");
    const get = id => document.getElementById(id);
    const element = (tag, text) => { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; return node; };
    const group = value => String(value).replace(/\B(?=(\d{3})+(?!\d))/g, ".");
    let relativePath = "";
    let rootName = "";
    let entries = [];
    let breadcrumb = [];
    let parent = null;
    let selection = new Map();
    let busy = false;
    let report = null;

    const key = (path, name) => `${path}\u0000${name}`;
    const itemKey = item => key(item.relativePath, item.fileName);
    const files = () => entries.filter(entry => entry.kind === "file");
    const status = message => { get("assistant-browser-status").textContent = message; };
    const summary = () => {
      const count = selection.size;
      get("assistant-selected-summary").textContent = count
        ? `Đã chọn ${count} file · nhập để xem số sheet sẽ tạo`
        : "Đã chọn 0 file";
      get("assistant-import-selected").disabled = busy || !count;
    };
    const canImport = () => !busy && selection.size > 0;

    function renderPath() {
      const names = breadcrumb.map(crumb => crumb.name).filter(Boolean);
      get("assistant-browser-path").textContent = names.length ? names.join(" / ") : (rootName || "");
      get("assistant-browser-up").disabled = busy || parent === null || parent === undefined;
    }
    function renderList() {
      const list = get("assistant-browser-list");
      list.replaceChildren();
      if (!entries.length) { status(EMPTY_FOLDER); return; }
      for (const entry of entries) {
        if (entry.kind === "folder") {
          const row = element("div");
          row.className = "assistant-browser-row";
          const open = element("button", entry.name);
          open.type = "button";
          open.className = "button button-ghost assistant-browser-folder";
          open.disabled = busy;
          open.addEventListener("click", () => { if (!busy) navigate(entry.name); });
          row.append(open);
          list.append(row);
          continue;
        }
        const row = element("label");
        row.className = "assistant-browser-row assistant-file-option";
        const check = element("input");
        check.type = "checkbox";
        check.setAttribute("aria-label", entry.name);
        const item = {relativePath, fileName: entry.name};
        check.checked = selection.has(itemKey(item));
        check.disabled = busy;
        check.addEventListener("change", () => { if (busy) return; check.checked ? selection.set(itemKey(item), item) : selection.delete(itemKey(item)); summary(); });
        const detail = element("span", `${entry.name} · ${entry.extension ? entry.extension.toUpperCase() : "file"}${entry.extension === "xlsx" ? " (nhập toàn bộ nhóm)" : ""}`);
        row.append(check, detail);
        list.append(row);
      }
      if (!entries.some(entry => entry.kind === "file")) status(EMPTY_FOLDER);
      else status("");
    }
    function render() { renderPath(); renderList(); summary(); }

    async function browse(path) {
      if (busy) return;
      busy = true;
      get("assistant-browser-up").disabled = true;
      status("Đang đọc thư mục…");
      try {
        const result = await bridge.browse(path);
        relativePath = result.relativePath || "";
        rootName = result.rootName || rootName;
        entries = Array.isArray(result.entries) ? result.entries : [];
        breadcrumb = Array.isArray(result.breadcrumb) ? result.breadcrumb : [];
        parent = result.parentRelativePath ?? null;
        busy = false;
        render();
        if (result.truncated) status("Thư mục có quá nhiều mục; chỉ hiện 500 mục đầu tiên.");
      } catch (error) {
        status(error.message || "Không đọc được thư mục đã chọn.");
        throw error;
      } finally {
        busy = false;
        busy = false;
        renderPath();
        summary();
      }
    }
    const navigate = path => browse(path);
    async function open() {
      if (busy) return;
      busy = true;
      get("assistant-browser").hidden = true;
      get("assistant-import-report").hidden = true;
      status("Đang mở hộp chọn thư mục…");
      try {
        const chosen = await bridge.pickRoot();
        if (!chosen || chosen.cancelled) { status(EMPTY_CHOICE); busy = false; summary(); return; }
        rootName = chosen.rootName || "";
        selection = new Map();
        report = null;
        busy = false;
        get("assistant-browser").hidden = false;
        get("assistant-import-report").hidden = true;
        await browse("");
      } catch (error) {
        status(error.message || "Chưa mở được thư mục nguồn.");
        busy = false;
      } finally {
        summary();
      }
    }
    function selectAll() {
      if (busy) return;
      const current = files();
      const all = current.length > 0 && current.every(entry => selection.has(key(relativePath, entry.name)));
      for (const entry of current) {
        const item = {relativePath, fileName: entry.name};
        all ? selection.delete(itemKey(item)) : selection.set(itemKey(item), item);
      }
      renderList();
      summary();
    }
    function renderReport(result) {
      report = result;
      const imported = result.report?.totals?.files || 0;
      const sheets = result.report?.totals?.sheets || 0;
      get("assistant-import-summary").textContent = `Đã nhập ${imported} file → ${sheets} sheet`;
      const decisions = (result.report?.files || []).flatMap(file => (file.decisions || []).map(decision => ({file, decision})));
      const reading = (result.report?.files || []).flatMap(file => (file.readingDecisions || []).map(decision => ({file, decision})));
      const exceptions = get("assistant-import-exceptions");
      exceptions.replaceChildren();
      const heading = element("h3", `Ngoại lệ đã tự xử lý (${decisions.length + reading.length})`);
      exceptions.append(heading);
      const content = element("ul");
      for (const {file, decision} of decisions) {
        content.append(element("li", `${file.fileName} · ${decision.column}: ${REASON_LABELS[decision.reasonCode] || decision.reasonCode} → ${KIND_LABELS[decision.kind] || decision.kind} · ${group(decision.affectedRows)} ô`));
      }
      for (const {file, decision} of reading) {
        content.append(element("li", `${file.fileName} · ${REASON_LABELS[decision.reasonCode] || decision.reasonCode}`));
      }
      exceptions.append(content);
      exceptions.hidden = !(decisions.length + reading.length);
      const skippedFiles = (result.report?.files || []).filter(file => file.status === "skipped");
      const skipped = get("assistant-import-skipped");
      skipped.replaceChildren();
      skipped.append(element("h3", `Bỏ qua (${skippedFiles.length})`));
      const reasons = element("ul");
      for (const file of skippedFiles) reasons.append(element("li", `${file.fileName} · ${file.issues?.[0]?.message || file.issues?.[0]?.code || "Không nhập được file."}`));
      skipped.append(reasons);
      skipped.hidden = !skippedFiles.length;
      get("assistant-import-report").hidden = false;
    }
    async function runImport() {
      if (!canImport()) return;
      const items = Array.from(selection.values());
      busy = true;
      summary();
      get("assistant-import-report").hidden = true;
      let dateSystem;
      try {
        status("Đang xác định hệ ngày của workbook…");
        dateSystem = await bridge.probeDateSystem();
      } catch (error) {
        busy = false;
        summary();
        status(error.message || "Không xác định được hệ ngày của workbook (1900/1904). Không nhập để tránh sai ngày.");
        return;
      }
      try {
        status(`Đang đọc ${items.length} file đã chọn…`);
        const result = await bridge.importSelection({items, dateSystem, onProgress: value => {
          const name = value.fileName || value.fileId || "";
          const position = value.processed && value.total ? `${value.processed}/${value.total}` : "";
          status(position ? `Đang nhập ${position}: ${name}…` : `Đang nhập: ${name}…`);
        }});
        const importedNames = new Set((result.report?.files || []).filter(file => file.status === "imported").map(file => file.fileName));
        for (const item of items) if (importedNames.has(item.fileName)) selection.delete(itemKey(item));
        renderList();
        renderReport(result);
        const skipped = (result.report?.totals?.skipped) || 0;
        status(skipped ? `Đã nhập xong. Còn ${skipped} file bị bỏ qua.` : "Đã nhập xong vào workbook.");
        onImported(result);
      } catch (error) {
        status(error.message || "Chưa nhập được nguồn đã chọn.");
      } finally {
        busy = false;
        summary();
      }
    }
    get("assistant-browser-up").addEventListener("click", () => { if (!busy && parent !== null) navigate(parent); });
    get("assistant-select-all").addEventListener("click", selectAll);
    get("assistant-import-selected").addEventListener("click", runImport);
    get("assistant-browser").hidden = true;
    get("assistant-import-report").hidden = true;
    summary();
    return {open, browse, selectAll, runImport, state: () => ({relativePath, rootName, entries, selection: Array.from(selection.values()), busy, report})};
  }
  const api = {create};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.ReqwiseAssistantBrowser = api;
})(typeof window !== "undefined" ? window : globalThis);
