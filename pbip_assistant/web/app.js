"use strict";

const state = {
  token: "",
  files: [],
  result: null,
  datasets: [],
  activeDataset: 0,
  activeTab: "preview",
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

const elements = {
  fileInput: $("#file-input"),
  browse: $("#browse-button"),
  drop: $("#drop-zone"),
  list: $("#file-list"),
  empty: $("#empty-files"),
  clear: $("#clear-button"),
  analyze: $("#analyze-button"),
  sourceView: $("#sources-view"),
  profileView: $("#profile-view"),
  profileStep: $('.step[data-view="profile"]'),
  sourceStep: $('.step[data-view="sources"]'),
  status: $("#server-status"),
  loading: $("#loading-overlay"),
  toast: $("#toast"),
};

function formatBytes(value) {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KiB`;
  return `${(value / 1024 / 1024).toFixed(1)} MiB`;
}

function showToast(message) {
  elements.toast.textContent = message;
  elements.toast.hidden = false;
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => { elements.toast.hidden = true; }, 4200);
}

function setLoading(active) {
  elements.loading.hidden = !active;
  elements.analyze.disabled = active || state.files.length === 0;
}

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (options.mutate) headers.set("X-Local-Token", state.token);
  const response = await fetch(path, {...options, headers});
  const payload = await response.json();
  if (!response.ok) {
    const error = payload.error || {};
    throw new Error(`${error.code || "REQUEST_FAILED"}: ${error.detail || "Không thể xử lý yêu cầu"}`);
  }
  return payload;
}

async function bootstrap() {
  try {
    const payload = await api("/api/bootstrap");
    state.token = payload.token;
    state.files = payload.files || [];
    elements.status.innerHTML = "<span></span> Local server sẵn sàng";
    renderFiles();
  } catch (error) {
    elements.status.textContent = "Mất kết nối";
    showToast(error.message);
  }
}

async function uploadFiles(files) {
  const accepted = [...files].filter((file) => /\.(xlsx|csv)$/i.test(file.name));
  if (accepted.length !== files.length) showToast("Chỉ .xlsx và .csv được đưa vào danh sách.");
  if (!accepted.length) return;
  setLoading(true);
  try {
    for (const file of accepted) {
      const payload = await api("/api/files", {
        method: "POST",
        mutate: true,
        headers: {"X-File-Name": encodeURIComponent(file.name), "Content-Type": "application/octet-stream"},
        body: file,
      });
      state.files.push(payload.file);
    }
    renderFiles();
    showToast(`Đã thêm ${accepted.length} file vào phiên local.`);
  } catch (error) {
    showToast(error.message);
  } finally {
    setLoading(false);
  }
}

function createSelect(label, name, values) {
  const field = document.createElement("div");
  field.className = "field";
  const labelElement = document.createElement("label");
  labelElement.textContent = label;
  const select = document.createElement("select");
  select.dataset.option = name;
  for (const [value, text] of values) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = text;
    select.append(option);
  }
  field.append(labelElement, select);
  return field;
}

function renderFiles() {
  elements.list.replaceChildren();
  elements.empty.hidden = state.files.length > 0;
  elements.clear.disabled = state.files.length === 0;
  elements.analyze.disabled = state.files.length === 0;
  for (const file of state.files) {
    const card = document.createElement("article");
    card.className = "file-card";
    card.dataset.id = file.id;
    const badge = document.createElement("div");
    badge.className = "file-badge";
    badge.textContent = file.kind.toUpperCase();
    const info = document.createElement("div");
    info.className = "file-info";
    const name = document.createElement("strong");
    name.textContent = file.name;
    name.title = file.name;
    const meta = document.createElement("span");
    meta.textContent = `${formatBytes(file.size)} · SHA-256 ${file.sha256.slice(0, 10)}…`;
    info.append(name, meta);

    let options;
    if (file.kind === "csv") {
      options = document.createElement("div");
      options.className = "file-options";
      options.append(
        createSelect("Encoding", "encoding", [["", "Tự nhận diện"], ["utf-8", "UTF-8"], ["utf-8-sig", "UTF-8 BOM"], ["utf-16", "UTF-16"], ["cp1252", "Windows-1252"], ["iso8859-1", "ISO-8859-1"]]),
        createSelect("Dấu phân cách", "delimiter", [["", "Tự nhận diện"], [",", "Dấu phẩy"], [";", "Chấm phẩy"], ["\t", "Tab"], ["|", "Pipe"]])
      );
      const field = document.createElement("div");
      field.className = "field";
      const label = document.createElement("label");
      label.textContent = "Dòng header";
      const input = document.createElement("input");
      input.type = "number";
      input.min = "1";
      input.value = "1";
      input.dataset.option = "header_row";
      field.append(label, input);
      options.append(field);
    } else {
      options = document.createElement("div");
      options.className = "file-note";
      options.textContent = "Tất cả worksheet sẽ được profile. Công thức dùng cached value và không được Excel tính lại.";
    }

    const remove = document.createElement("button");
    remove.className = "icon-button";
    remove.type = "button";
    remove.title = `Xóa ${file.name}`;
    remove.setAttribute("aria-label", `Xóa ${file.name}`);
    remove.textContent = "×";
    remove.addEventListener("click", () => removeFile(file.id));
    card.append(badge, info, options, remove);
    elements.list.append(card);
  }
}

async function removeFile(id) {
  try {
    await api(`/api/files/${encodeURIComponent(id)}`, {method: "DELETE", mutate: true});
    state.files = state.files.filter((item) => item.id !== id);
    renderFiles();
  } catch (error) {
    showToast(error.message);
  }
}

async function clearFiles() {
  try {
    await api("/api/reset", {method: "POST", mutate: true, body: "{}"});
    state.files = [];
    state.result = null;
    renderFiles();
  } catch (error) {
    showToast(error.message);
  }
}

function profileRequest() {
  return {
    preview_limit: 20,
    files: state.files.map((file) => {
      const card = elements.list.querySelector(`[data-id="${CSS.escape(file.id)}"]`);
      const options = {};
      if (file.kind === "csv") {
        const encoding = card.querySelector('[data-option="encoding"]').value;
        const delimiter = card.querySelector('[data-option="delimiter"]').value;
        const headerRow = Number(card.querySelector('[data-option="header_row"]').value);
        if (encoding) options.encoding = encoding;
        if (delimiter) options.delimiter = delimiter;
        options.header_row = headerRow;
      }
      return {id: file.id, options};
    }),
  };
}

async function analyze() {
  setLoading(true);
  try {
    state.result = await api("/api/profile", {
      method: "POST",
      mutate: true,
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(profileRequest()),
    });
    buildDatasets();
    renderResults();
    showView("profile");
  } catch (error) {
    showToast(error.message);
  } finally {
    setLoading(false);
  }
}

function buildDatasets() {
  state.datasets = [];
  for (const workbook of state.result.workbooks || []) {
    for (const sheet of workbook.sheets || []) {
      state.datasets.push({
        kind: "xlsx",
        file: workbook.path,
        name: sheet.name,
        source: workbook,
        profile: sheet,
      });
    }
  }
  for (const csv of state.result.csv_files || []) {
    state.datasets.push({kind: "csv", file: csv.path, name: csv.path, source: csv, profile: csv});
  }
  state.activeDataset = 0;
}

function showView(name) {
  const profile = name === "profile";
  elements.sourceView.hidden = profile;
  elements.profileView.hidden = !profile;
  elements.sourceStep.classList.toggle("active", !profile);
  elements.profileStep.classList.toggle("active", profile);
  elements.profileStep.disabled = !state.result;
  $("#page-title").textContent = profile ? "Dữ liệu đã được đọc. Quyết định vẫn thuộc về bạn." : "Kiểm tra dữ liệu trước khi phân tích.";
  window.scrollTo({top: 0, behavior: "smooth"});
}

function renderResults() {
  const summary = state.result.summary || {file_count: 0, row_count: 0, column_count: 0, issue_count: 0};
  const metrics = [
    ["Nguồn", summary.file_count, "file đã đọc"],
    ["Dòng dữ liệu", summary.row_count.toLocaleString("vi-VN"), "không tính header"],
    ["Cột đã profile", summary.column_count, "trên mọi dataset"],
    ["Vấn đề", summary.issue_count, summary.mapping_ready ? "không có lỗi chặn" : "cần xử lý trước mapping"],
  ];
  const grid = $("#metric-grid");
  grid.replaceChildren();
  for (const [label, value, note] of metrics) {
    const card = document.createElement("div");
    card.className = "metric";
    card.innerHTML = `<span></span><strong></strong><small></small>`;
    card.children[0].textContent = label;
    card.children[1].textContent = value;
    card.children[2].textContent = note;
    grid.append(card);
  }

  const blocking = $("#blocking-banner");
  if ((state.result.errors || []).length) {
    blocking.hidden = false;
    blocking.textContent = `${state.result.errors.length} lỗi chặn được phát hiện. Mở tab “Vấn đề” để xem mã lỗi và cách xử lý.`;
  } else {
    blocking.hidden = true;
  }
  const schema = state.result.schema_comparison || {};
  const warning = $("#warning-banner");
  warning.hidden = schema.status !== "schema_drift";
  if (!warning.hidden) warning.textContent = "Schema giữa các nguồn không đồng nhất. Hệ thống chưa tự ghép hoặc đổi kiểu dữ liệu.";

  const buttons = $("#dataset-buttons");
  buttons.replaceChildren();
  state.datasets.forEach((dataset, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `dataset-button${index === state.activeDataset ? " active" : ""}`;
    const title = document.createElement("strong");
    title.textContent = dataset.kind === "xlsx" ? dataset.name : dataset.file;
    const meta = document.createElement("span");
    meta.textContent = dataset.kind === "xlsx" ? dataset.file : "CSV";
    button.append(title, meta);
    button.addEventListener("click", () => {
      state.activeDataset = index;
      renderResults();
    });
    buttons.append(button);
  });
  renderDataset();
}

function datasetIssues(dataset) {
  const result = [];
  for (const issue of dataset.source.issues || []) result.push({code: "SOURCE_WARNING", detail: issue, error: false});
  for (const issue of dataset.profile.issues || []) result.push({code: "PROFILE_WARNING", detail: issue, error: false});
  for (const column of dataset.profile.columns || []) {
    for (const issue of column.issues || []) result.push({code: "COLUMN_WARNING", detail: `${column.name}: ${issue}`, error: false});
  }
  for (const row of dataset.profile.row_errors || []) {
    result.push({code: row.code, detail: `Dòng/record ${row.row_number || row.record_number}: mong đợi ${row.expected_columns} cột, nhận ${row.actual_columns}.`, error: true});
  }
  for (const error of state.result.errors || []) {
    if (!error.path || error.path === dataset.file) result.push({code: error.code, detail: error.detail, error: true});
  }
  return result;
}

function renderDataset() {
  const dataset = state.datasets[state.activeDataset];
  if (!dataset) {
    $("#dataset-name").textContent = "Không có dataset đọc được";
    $("#dataset-meta").textContent = "Kiểm tra lỗi import và thử lại.";
    $(".tab-list").hidden = true;
    $("#tab-preview").innerHTML = '<div class="clean-panel"><div><strong>Không có preview</strong><span>Parser chưa tạo được dataset hợp lệ.</span></div></div>';
    return;
  }
  $(".tab-list").hidden = false;
  $("#dataset-kind").textContent = dataset.kind.toUpperCase();
  $("#dataset-name").textContent = dataset.kind === "xlsx" ? dataset.name : dataset.file;
  const rows = dataset.profile.row_count || 0;
  const columns = (dataset.profile.columns || []).length;
  $("#dataset-meta").textContent = dataset.kind === "xlsx" ? `${dataset.file} · ${rows.toLocaleString("vi-VN")} dòng · ${columns} cột` : `${rows.toLocaleString("vi-VN")} dòng · ${columns} cột · ${dataset.source.encoding} · delimiter “${dataset.source.delimiter === "\t" ? "tab" : dataset.source.delimiter}”`;
  const ready = dataset.profile.mapping_ready !== false;
  const badge = $("#mapping-badge");
  badge.textContent = ready ? "Mapping ready" : "Needs input fix";
  badge.classList.toggle("blocked", !ready);

  const issues = datasetIssues(dataset);
  $("#issue-count").textContent = issues.length ? `(${issues.length})` : "";
  renderPreview(dataset);
  renderColumns(dataset);
  renderIssues(issues);
  renderSchema();
  activateTab(state.activeTab);
}

function renderPreview(dataset) {
  const panel = $("#tab-preview");
  panel.replaceChildren();
  const preview = dataset.profile.preview;
  if (!preview || !preview.columns.length) {
    panel.innerHTML = '<div class="clean-panel"><div><strong>Không có dòng để preview</strong><span>File có thể chỉ có header hoặc sheet đang rỗng.</span></div></div>';
    return;
  }
  const heading = document.createElement("div");
  heading.className = "panel-title";
  heading.innerHTML = `<h4>Dữ liệu mẫu</h4><span></span>`;
  heading.querySelector("span").textContent = `Hiển thị ${preview.rows.length}/${dataset.profile.row_count || 0} dòng hợp lệ${preview.excluded_error_rows ? ` · loại ${preview.excluded_error_rows} dòng lỗi` : ""}`;
  const wrap = document.createElement("div");
  wrap.className = "table-wrap";
  const table = document.createElement("table");
  const thead = document.createElement("thead");
  const headerRow = document.createElement("tr");
  for (const column of preview.columns) {
    const th = document.createElement("th");
    th.textContent = column || "(trống)";
    headerRow.append(th);
  }
  thead.append(headerRow);
  const tbody = document.createElement("tbody");
  for (const row of preview.rows) {
    const tr = document.createElement("tr");
    preview.columns.forEach((_, index) => {
      const td = document.createElement("td");
      const value = row[index];
      td.textContent = value === null || value === "" ? "null" : String(value);
      if (value === null || value === "") td.className = "null-value";
      tr.append(td);
    });
    tbody.append(tr);
  }
  table.append(thead, tbody);
  wrap.append(table);
  panel.append(heading, wrap);
}

function renderColumns(dataset) {
  const panel = $("#tab-columns");
  panel.replaceChildren();
  const wrap = document.createElement("div");
  wrap.className = "table-wrap";
  const table = document.createElement("table");
  table.innerHTML = "<thead><tr><th>Cột</th><th>Kiểu dữ liệu</th><th>Null</th><th>Trùng</th><th>Mẫu giới hạn</th><th>Cảnh báo</th></tr></thead>";
  const tbody = document.createElement("tbody");
  for (const column of dataset.profile.columns || []) {
    const tr = document.createElement("tr");
    const cells = [
      column.name,
      "",
      column.null_count,
      column.duplicate_count,
      (column.sample || []).join(" · "),
      (column.issues || []).join(" "),
    ];
    cells.forEach((value, index) => {
      const td = document.createElement("td");
      if (index === 1) {
        for (const [type, count] of Object.entries(column.data_types || {})) {
          const chip = document.createElement("span");
          chip.className = "type-chip";
          chip.textContent = `${type} · ${count}`;
          td.append(chip);
        }
      } else {
        td.textContent = String(value ?? "");
      }
      tr.append(td);
    });
    tbody.append(tr);
  }
  table.append(tbody);
  wrap.append(table);
  panel.append(wrap);
}

function renderIssues(issues) {
  const panel = $("#tab-issues");
  panel.replaceChildren();
  if (!issues.length) {
    panel.innerHTML = '<div class="clean-panel"><div><strong>Không phát hiện vấn đề cấu trúc</strong><span>Đây vẫn là kiểm tra tĩnh; chưa xác nhận logic nghiệp vụ.</span></div></div>';
    return;
  }
  const list = document.createElement("div");
  list.className = "issue-list";
  for (const issue of issues) {
    const item = document.createElement("div");
    item.className = `issue-item${issue.error ? " error" : ""}`;
    const icon = document.createElement("strong");
    icon.textContent = issue.error ? "!" : "i";
    const copy = document.createElement("div");
    const code = document.createElement("strong");
    code.textContent = issue.code;
    const detail = document.createElement("p");
    detail.textContent = issue.detail;
    copy.append(code, detail);
    item.append(icon, copy);
    list.append(item);
  }
  panel.append(list);
}

function renderSchema() {
  const panel = $("#tab-schema");
  panel.replaceChildren();
  const schema = state.result.schema_comparison || {};
  const status = document.createElement("div");
  status.className = `schema-status${schema.status === "schema_drift" ? " drift" : ""}`;
  status.textContent = schema.status === "consistent" ? "✓ Schema nhất quán" : schema.status === "schema_drift" ? "△ Phát hiện schema drift" : "Chưa đủ nguồn để so schema";
  panel.append(status);
  if (!schema.comparisons || !schema.comparisons.length) {
    const note = document.createElement("p");
    note.textContent = "Thêm từ hai dataset trở lên để xem khác biệt cột và kiểu dữ liệu.";
    note.style.color = "var(--muted)";
    panel.append(note);
    return;
  }
  const wrap = document.createElement("div");
  wrap.className = "table-wrap";
  const table = document.createElement("table");
  table.innerHTML = "<thead><tr><th>Nguồn</th><th>Thiếu cột</th><th>Thêm cột</th><th>Đổi thứ tự</th><th>Đổi kiểu</th></tr></thead>";
  const tbody = document.createElement("tbody");
  for (const item of schema.comparisons) {
    const tr = document.createElement("tr");
    const values = [
      item.name ? `${item.path} / ${item.name}` : item.path,
      (item.missing_columns || []).join(", ") || "—",
      (item.added_columns || []).join(", ") || "—",
      item.order_changed ? "Có" : "Không",
      Object.keys(item.type_changes || {}).join(", ") || "—",
    ];
    for (const value of values) {
      const td = document.createElement("td");
      td.textContent = value;
      tr.append(td);
    }
    tbody.append(tr);
  }
  table.append(tbody);
  wrap.append(table);
  panel.append(wrap);
}

function activateTab(name) {
  state.activeTab = name;
  $$(".tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.tab === name));
  $$(".tab-panel").forEach((panel) => { panel.hidden = panel.id !== `tab-${name}`; });
}

elements.browse.addEventListener("click", (event) => {
  event.stopPropagation();
  elements.fileInput.click();
});
elements.fileInput.addEventListener("change", () => {
  uploadFiles(elements.fileInput.files);
  elements.fileInput.value = "";
});
elements.drop.addEventListener("click", () => elements.fileInput.click());
elements.drop.addEventListener("keydown", (event) => {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    elements.fileInput.click();
  }
});
["dragenter", "dragover"].forEach((name) => elements.drop.addEventListener(name, (event) => {
  event.preventDefault();
  elements.drop.classList.add("dragging");
}));
["dragleave", "drop"].forEach((name) => elements.drop.addEventListener(name, (event) => {
  event.preventDefault();
  elements.drop.classList.remove("dragging");
}));
elements.drop.addEventListener("drop", (event) => uploadFiles(event.dataTransfer.files));
elements.clear.addEventListener("click", clearFiles);
elements.analyze.addEventListener("click", analyze);
$("#back-button").addEventListener("click", () => showView("sources"));
elements.sourceStep.addEventListener("click", () => showView("sources"));
elements.profileStep.addEventListener("click", () => { if (state.result) showView("profile"); });
$$(".tab").forEach((tab) => tab.addEventListener("click", () => activateTab(tab.dataset.tab)));

bootstrap();
