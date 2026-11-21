/* Assistant journey: source intake, understanding, plan draft, branches, freeze, apply, record. */
"use strict";
const FLOW_MAX_ROWS = 100000;
const FLOW_MAX_COLUMNS = 512;
const FLOW_MAX_CELLS = 400000;



function flowNowIso() { return new Date().toISOString(); }

function isoDateLocal(date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

function flowHeaderCell(value, index) {
  return (value === null || value === undefined ? "" : String(value).trim()) || columnLetter(index);
}

function flowCell(value) {
  if (value === null || value === undefined) return "";
  if (value instanceof Date) return isoDateLocal(value);
  if (typeof value === "boolean") return value ? "TRUE" : "FALSE";
  return String(value);
}

function flowCalendarFormat(format, value) {
  // Read invariant numberFormat, never localized display text. Quoted/escaped
  // literals, alignment/fill characters and elapsed-time tokens aren't dates.
  if (typeof format !== "string" || format.length > 512) {
    throw flowFailure("AF_WORKBOOK_DATE_UNSUPPORTED", "Không đọc được numberFormat có giới hạn để phân biệt ngày và số; chưa nạp nguồn.");
  }
  const sections = [""];
  const elapsedSections = [false];
  let quoted = false, malformed = false, conditional = false;
  for (let index = 0; index < format.length; index += 1) {
    const character = format[index];
    if (character === '"') { quoted = !quoted; continue; }
    if (quoted) continue;
    if (["\\", "_", "*"].includes(character)) { index += 1; continue; }
    if (character === "[") {
      const end = format.indexOf("]", index + 1);
      if (end < 0) { malformed = true; break; }
      const token = format.slice(index + 1, end);
      conditional ||= /^[<>=]/.test(token);
      elapsedSections[sections.length - 1] ||= /^[hms]+$/i.test(token);
      if (!/^(?:\$[^\]]*|Black|Blue|Cyan|Green|Magenta|Red|White|Yellow|Color\d+|[hms]+|[<>=].*)$/i.test(token)) malformed = true;
      index = end; continue;
    }
    if (character === ";") { sections.push(""); elapsedSections.push(false); }
    else sections[sections.length - 1] += character;
  }
  const calendarSection = (text, elapsed) => {
    const tokens = text.toLowerCase().replace(/am\/pm|a\/p/g, "");
    return /[yd]/.test(tokens) || (/m/.test(tokens) && !/[hs]/.test(tokens) && !elapsed);
  };
  // Conditions select sections by predicate rather than the ordinary sign rule.
  // Never guess which conditional calendar section Excel actually displayed.
  if (conditional && sections.some((text, index) => calendarSection(text, elapsedSections[index]))) {
    throw flowFailure("AF_WORKBOOK_DATE_UNSUPPORTED", "Định dạng ngày có điều kiện chưa được hỗ trợ rõ ràng; chọn định dạng ngày chuẩn trước khi đọc nguồn.");
  }
  const selectedSection = value > 0 ? 0 : value < 0 && sections.length > 1 ? 1 : value === 0 && sections.length > 2 ? 2 : 0;
  const elapsed = elapsedSections[selectedSection];
  const section = sections[selectedSection].toLowerCase();
  const stripped = section.replace(/am\/pm|a\/p/g, "");
  const calendar = calendarSection(section, elapsed);
  if (!calendar) return null;
  const excessiveToken = (stripped.match(/y+|m+|d+|h+|s+/g) || []).some((token) =>
    token.length > ({y: 4, m: 5, d: 4, h: 2, s: 2}[token[0]]));
  if (quoted || malformed || conditional || elapsed || excessiveToken || sections.length > 4 || /[^ymdhs0.,/ :+()\-]/.test(stripped)) {
    throw flowFailure("AF_WORKBOOK_DATE_UNSUPPORTED", "Định dạng ngày workbook chưa được hỗ trợ rõ ràng; chọn định dạng ngày chuẩn trước khi đọc nguồn.");
  }
  return {time: /[hs]/.test(stripped) || /am\/pm|a\/p/.test(section)};
}

function flowWorkbookCell(value, format, epoch) {
  if (typeof value !== "number") return flowCell(value);
  const calendar = flowCalendarFormat(format, value);
  if (!calendar) return flowCell(value);
  if (![1900, 1904].includes(epoch) || !Number.isFinite(value) || value < (epoch === 1900 ? 1 : 0)
      || value >= (epoch === 1900 ? 2958466 : 2957004) || (epoch === 1900 && Math.floor(value) === 60)) {
    throw flowFailure("AF_WORKBOOK_DATE_UNSUPPORTED", "Không xác định được ngày Excel an toàn (hệ ngày, serial 60 hoặc giá trị ngoài phạm vi); chưa nạp nguồn.");
  }
  let day = Math.floor(value);
  // Excel serial doubles have no timezone. Round at microsecond precision
  // (within their floating-point resolution for modern dates); don't truncate
  // fractional days or attach a fabricated UTC/local timezone.
  const exactMicros = (value - day) * 86400000000;
  let micros = Math.round(exactMicros);
  if (Math.abs(micros - exactMicros) > Math.max(0.00001, Math.abs(value) * Number.EPSILON * 86400000000)) {
    throw flowFailure("AF_WORKBOOK_DATE_UNSUPPORTED", "Thời gian ngày Excel cần độ chính xác nhỏ hơn microsecond; chưa nạp nguồn thay vì cắt mất phần thời gian.");
  }
  if (micros === 86400000000) { day += 1; micros = 0; }
  if (epoch === 1900 && day === 60) throw flowFailure("AF_WORKBOOK_DATE_UNSUPPORTED", "Serial ngày giả 29/02/1900 chưa được hỗ trợ.");
  const base = epoch === 1904 ? Date.UTC(1904, 0, 1) : Date.UTC(1899, 11, 31);
  const date = new Date(base + (day - (epoch === 1900 && day > 60 ? 1 : 0)) * 86400000);
  if (!Number.isFinite(date.getTime()) || date.getUTCFullYear() > 9999) throw flowFailure("AF_WORKBOOK_DATE_UNSUPPORTED", "Ngày Excel nằm ngoài phạm vi được hỗ trợ.");
  const dayText = date.toISOString().slice(0, 10);
  if (!micros && !calendar.time) return dayText;
  const hours = Math.floor(micros / 3600000000), minutes = Math.floor(micros / 60000000) % 60;
  const seconds = Math.floor(micros / 1000000) % 60, fraction = micros % 1000000;
  return `${dayText}T${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`
    + (fraction ? "." + String(fraction).padStart(6, "0").replace(/0+$/, "") : "");
}

function flowWorkbookRows(range, epoch, skipHeader = false) {
  return range.values.slice(skipHeader ? 1 : 0).map((row, index) => row.map((value, column) =>
    flowWorkbookCell(value, range.numberFormat?.[index + (skipHeader ? 1 : 0)]?.[column], epoch)));
}

function flowHash(text) {
  let hash = 2166136261;
  for (let index = 0; index < text.length; index += 1) {
    hash = Math.imul(hash ^ text.charCodeAt(index), 16777619) >>> 0;
  }
  return hash;
}

function flowSampleOrdinals(header, rows, totalRows) {
  if (!Number.isInteger(totalRows) || totalRows < 0) throw flowFailure("AF_INGEST_FAILED", "Số dòng nguồn không hợp lệ.");
  if (totalRows <= 20) return Array.from({length: totalRows}, (_, index) => index);
  // Same schema, dimensions and boundary rows always produce the same sample.
  let seed = flowHash(JSON.stringify([header, totalRows, header.length,
    flowHash(JSON.stringify(rows[0])), flowHash(JSON.stringify(rows[totalRows - 1]))])) || 1;
  const offsets = new Set([0, totalRows - 1]);
  while (offsets.size < 20) {
    seed ^= seed << 13;
    seed ^= seed >>> 17;
    seed ^= seed << 5;
    offsets.add(1 + ((seed >>> 0) % (totalRows - 2)));
  }
  return [...offsets].sort((left, right) => left - right);
}

function flowFailure(code, message) { return Object.assign(new Error(message), {code}); }

function flowCheckBounds(selections) {
  let rows = 0;
  let cells = 0;
  for (const selection of selections) {
    if (!Number.isInteger(selection.totalRows) || selection.totalRows < 0
        || !Number.isInteger(selection.totalColumns) || selection.totalColumns < 1) {
      throw flowFailure("AF_INGEST_FAILED", "Kích thước vùng nguồn không hợp lệ.");
    }
    rows += selection.totalRows;
    cells += selection.totalRows * selection.totalColumns;
    if (selection.totalColumns > FLOW_MAX_COLUMNS || rows > FLOW_MAX_ROWS || cells > FLOW_MAX_CELLS) {
      throw flowFailure("AF_INGEST_FAILED", `Nguồn có ${rows} dòng, ${selection.totalColumns} cột, ${cells} ô; giới hạn ${FLOW_MAX_ROWS} dòng, ${FLOW_MAX_COLUMNS} cột và ${FLOW_MAX_CELLS} ô. Hãy chọn ít bảng hoặc vùng nhỏ hơn.`);
    }
  }
}

async function flowReadOpenWorkbook(mode = "compute", selectedKeys = null, metadataOnly = false) {
  if (!["discover", "compute"].includes(mode)) throw flowFailure("INVALID_REQUEST", "Chế độ đọc không hợp lệ.");
  return Excel.run(async (context) => {
    const sheets = context.workbook.worksheets;
    sheets.load("items/name");
    await context.sync();
    for (const sheet of sheets.items) sheet.tables.load("items/name");
    await context.sync();
    const entries = [];
    for (const sheet of sheets.items) {
      if (sheet.tables.items.length) {
        for (const table of sheet.tables.items) {
          const key = JSON.stringify([sheet.name, table.name, true]);
          if (selectedKeys && !selectedKeys.has(key)) continue;
          const body = table.getDataBodyRange();
          const head = table.getHeaderRowRange();
          body.load("rowCount,columnCount");
          head.load("rowIndex,columnIndex");
          entries.push({sheet: sheet.name, name: table.name, key, body, head, table: true});
        }
      } else {
        const key = JSON.stringify([sheet.name, sheet.name, false]);
        if (selectedKeys && !selectedKeys.has(key)) continue;
        const body = sheet.getUsedRangeOrNullObject(true);
        body.load("isNullObject");
        entries.push({sheet: sheet.name, name: sheet.name, key, body, table: false});
      }
    }
    await context.sync();
    for (const entry of entries) {
      if (!entry.table && !entry.body.isNullObject) entry.body.load("rowIndex,columnIndex,rowCount,columnCount");
    }
    await context.sync();
    const available = entries.filter((entry) => !entry.body.isNullObject && (entry.table || entry.body.rowCount > 0));
    for (const entry of available) {
      entry.totalRows = entry.body.rowCount - (entry.table ? 0 : 1);
      entry.totalColumns = entry.body.columnCount;
    }
    if (metadataOnly) return available.map((entry) => ({sheet: entry.sheet, name: entry.name,
      table: entry.table, key: entry.key, totalRows: entry.totalRows, totalColumns: entry.totalColumns}));
    flowCheckBounds(available);
    // Stable ExcelApi 1.2 function evaluation respects this workbook's epoch.
    // No worksheet formula, cell write, preview API or Save is involved.
    const epochProbe = typeof context.workbook.functions?.date === "function" ? context.workbook.functions.date(1904, 1, 1) : null;
    epochProbe?.load("value,error");
    for (const entry of available) {
      const width = entry.totalColumns;
      if (!entry.table) {
        entry.head = entry.body.getCell(0, 0).getResizedRange(0, width - 1);
        entry.head.load("values");
      } else entry.head.load("values");
      if (mode === "compute") {
        entry.body.load("values,numberFormat");
      } else if (entry.totalRows > 0) {
        entry.first = entry.body.getCell(entry.table ? 0 : 1, 0).getResizedRange(0, width - 1);
        entry.last = entry.body.getCell(entry.totalRows - (entry.table ? 1 : 0), 0).getResizedRange(0, width - 1);
        entry.first.load("values,numberFormat");
        entry.last.load("values,numberFormat");
      }
    }
    await context.sync();
    const epoch = !epochProbe?.error && epochProbe?.value === 1462 ? 1900 : !epochProbe?.error && epochProbe?.value === 0 ? 1904 : null;
    for (const entry of available) {
      entry.header = (entry.head.values[0] || []).map(flowHeaderCell);
      if (entry.header.length !== entry.totalColumns) throw flowFailure("AF_INGEST_FAILED", "Header không khớp số cột nguồn.");
      if (mode === "discover") {
        const boundaryRows = [];
        if (entry.totalRows) {
          boundaryRows[0] = flowWorkbookRows(entry.first, epoch)[0];
          boundaryRows[entry.totalRows - 1] = flowWorkbookRows(entry.last, epoch)[0];
        }
        entry.sampleOrdinals = flowSampleOrdinals(entry.header, boundaryRows, entry.totalRows);
        entry.samples = entry.sampleOrdinals.map((offset) => {
          const range = entry.body.getCell(offset + (entry.table ? 0 : 1), 0).getResizedRange(0, entry.totalColumns - 1);
          range.load("values,numberFormat");
          return range;
        });
      }
    }
    if (mode === "discover") await context.sync();
    return available.map((entry) => {
      const rows = (mode === "compute"
        ? flowWorkbookRows(entry.body, epoch, !entry.table)
        : entry.samples.map((range) => flowWorkbookRows(range, epoch)[0]));
      if (rows.some((row) => row.length !== entry.totalColumns)
          || (mode === "compute" && rows.length !== entry.totalRows)) {
        throw flowFailure("AF_INGEST_FAILED", "Dữ liệu thay đổi hoặc số cột không đồng nhất. Hãy đọc lại nguồn.");
      }
      const rowIndex = entry.table ? entry.head.rowIndex : entry.body.rowIndex;
      const columnIndex = entry.table ? entry.head.columnIndex : entry.body.columnIndex;
      return {sheet: entry.sheet, name: entry.name, table: entry.table, key: entry.key,
        header: entry.header, rows, totalRows: entry.totalRows, totalColumns: entry.header.length,
        sampleOrdinals: mode === "discover" ? entry.sampleOrdinals : Array.from({length: entry.totalRows}, (_, index) => index),
        origin: `Workbook!${entry.sheet}!${entry.name}`,
        range: `${columnLetter(columnIndex)}${rowIndex + 1}:${columnLetter(columnIndex + entry.totalColumns - 1)}${rowIndex + entry.totalRows + 1}`};
    });
  });
}

function flowSetHidden(id, hidden) { byId(id)?.classList?.toggle("hidden", hidden); }

function flowCapabilityAvailable() { return state.flow.v2Capability === true; }

function resetFlowView(message = "", {explicit = false} = {}) {
  const previous = state.flow;
  state.flow = createFlowState(previous?.v2Capability === true);
  if (!explicit && previous?.approvalConsumed) Object.assign(state.flow, {approvalConsumed: true, handoffStatus: previous.handoffStatus, applyMessage: previous.applyMessage, spec: previous.spec, stage: previous.stage});
  const disclosure = byId("flow-disclosure");
  if (disclosure) disclosure.checked = false;
  renderFlow();
  if (message && byId("flow-source-status")) byId("flow-source-status").textContent = message;
}

function flowBinding() {
  return {flow: state.flow, session: state.sessionId, token: state.token,
    workbook: state.workbook ? workbookIdentity(state.workbook) : ""};
}

function flowAssertCurrent(binding) {
  if (binding.flow !== state.flow || binding.session !== state.sessionId || binding.token !== state.token
      || binding.workbook !== (state.workbook ? workbookIdentity(state.workbook) : "")) {
    throw flowFailure("AF_SPEC_STALE", "Phiên hoặc workbook đã đổi. Hãy nạp lại nguồn trước khi tiếp tục.");
  }
}

async function flowAction(action) {
  if (!flowCapabilityAvailable() || state.flow.busy) return;
  const binding = flowBinding();
  binding.flow.busy = true;
  updateFlowButtons();
  try { return await action(binding); }
  catch (error) {
    if (state.flow === binding.flow) {
      if (error.code === "AF_SPEC_STALE" && !error.preserveFlow) resetFlowView(error.message);
      showError(error.code || "AF_INGEST_FAILED", error.message);
    }
    return null;
  } finally {
    binding.flow.busy = false;
    if (state.flow === binding.flow) renderFlow();
  }
}

function flowAccept(result) {
  const flow = state.flow;
  for (const name of ["stage", "mode", "rootLabel", "snapshot", "sources", "tables", "csvOptions", "requiresRename", "errors", "warnings", "questions", "sampleInfo", "understand", "branches", "planningHash", "draftInputs", "planSummary", "planQuestions", "planAssumptions", "delta", "engine", "chosenBranch", "allBlocked", "spec", "approval", "approvalConsumed", "handoffStatus", "workbookSourceSelections"]) {
    if (Object.prototype.hasOwnProperty.call(result, name)) flow[name] = result[name];
  }
}

async function flowBindRoot() {
  return flowAction(async (binding) => {
    const root = (byId("flow-root-input")?.value || "").trim();
    binding.flow.snapshot = null;
    binding.flow.understand = null;
    binding.flow.rootLabel = "";
    const result = await api("/api/assistant/session", {root});
    flowAssertCurrent(binding);
    const capability = state.flow.v2Capability;
    state.flow = createFlowState(capability);
    flowAccept(result);
    renderFlow();
    return result;
  });
}

function flowAddFile(kind) {
  if (!flowCapabilityAvailable() || state.flow.busy || !state.flow.rootLabel) return;
  const path = (byId("flow-path-input")?.value || "").trim();
  if (!path) return showError("INVALID_REQUEST", "Nhập đường dẫn nguồn đã lưu.");
  const request = {kind, path, options: {}};
  if (kind === "xlsx") {
    const sheet = (byId("flow-sheet-input")?.value || "").trim();
    const table = (byId("flow-table-input")?.value || "").trim();
    if (sheet) request.options.sheet = sheet;
    if (table) request.options.table = table;
  }
  if (kind === "folder") request.options.pattern = (byId("flow-pattern-input")?.value || "*.csv").trim();
  const id = `file_${++state.flow.nextId}`;
  state.flow.pendingRequests.push({id, request});
  flowInvalidatePlans();
  state.flow.selectedTableIds.add(id);
  state.flow.snapshot = null;
  state.flow.understand = null;
  state.flow.questions = [];
  state.flow.stage = "new";
  renderFlow();
}

async function flowPreparedWorkbookSources(review, mode = "compute") {
  if (!review?.sources?.length || typeof review.validate !== "function")
    throw flowFailure("DP_REVIEW_STALE", "Duyệt dữ liệu workbook trước khi mở đề bài.");
  const fresh = await review.validate();
  if (fresh.observedHash !== review.observedHash)
    throw flowFailure("DP_SOURCE_STALE", "Dữ liệu đã duyệt đã thay đổi. Hãy quét và duyệt lại.");
  const selections = fresh.sources.map(source => {
    const sheet = fresh.sourceLabels[source.sourceId];
    if (!sheet || !source.sheetId) throw flowFailure("DP_SOURCE_STALE", "Không xác minh được danh tính sheet đã duyệt.");
    const header = source.headers.map(flowHeaderCell), totalRows = source.rows.length, totalColumns = header.length;
    const rows = source.rows.map((row, r) => row.map((value, c) => flowWorkbookCell(value, source.numberFormats?.[r]?.[c], Number(source.dateSystem))));
    const sampleOrdinals = mode === "discover" ? flowSampleOrdinals(header, rows, totalRows) : rows.map((_, r) => r);
    const key = JSON.stringify([source.sheetId, source.sourceId, false]);
    return {sheet, name: sheet, table: false, key, header, rows: sampleOrdinals.map(r => rows[r]), totalRows, totalColumns, sampleOrdinals,
      origin: `Workbook!${sheet}!${sheet}`,
      range: `${columnLetter(source.columnOffset)}${source.rowOffset}:${columnLetter(source.columnOffset + totalColumns - 1)}${source.rowOffset + totalRows}`};
  });
  flowCheckBounds(selections);
  return selections;
}

async function preparationBusinessHandoff(review) {
  if (!state.officeReady || !flowCapabilityAvailable() || state.flow.busy)
    throw flowFailure("COORDINATOR_BUSY", "Chờ Excel và phiên hiện tại sẵn sàng.");
  const binding = flowBinding();
  flowInvalidateSourceAuthority(binding.flow);
  binding.flow.preparationReview = null;
  binding.flow.busy = true;
  try {
    const sources = await flowPreparedWorkbookSources(review, "discover");
    flowAssertCurrent(binding);
    await api("/api/assistant/session", {sourceMode: "workbook"});
    flowAssertCurrent(binding);
    await review.validate();
    flowAssertCurrent(binding);
    const result = await api("/api/assistant/ingest", {requests: sources.map(({key, ...payload}) => ({kind: "workbook", mode: "discover", payload}))});
    flowAssertCurrent(binding);
    await review.validate();
    flowAssertCurrent(binding);
    if (!result.snapshot || result.stage === "ingest_blocked") throw flowFailure("AF_INGEST_FAILED", "Kiểm tra dữ liệu nguồn trước khi phân tích.");
    binding.flow.pendingRequests = [];
    binding.flow.workbookSelections = sources.map(source => ({...source, request: {name: source.name}}));
    binding.flow.selectedTableIds = new Set(sources.map(source => source.key));
    binding.flow.answers = {};
    flowAccept(result);
    binding.flow.preparationReview = review;
    return result;
  } catch (error) {
    flowInvalidateSourceAuthority(binding.flow);
    throw error;
  } finally {
    binding.flow.busy = false;
    if (state.flow === binding.flow) renderFlow();
  }
}

async function flowAddOpenWorkbook() {
  return flowAction(async (binding) => {
    if (!state.officeReady || !state.flow.rootLabel) throw flowFailure("OFFICE_NOT_READY", "Gắn thư mục và chờ Excel sẵn sàng trước khi đọc.");
    const selections = await flowReadOpenWorkbook("discover", null, true);
    flowAssertCurrent(binding);
    state.flow.workbookSelections = selections.map((selection) => ({...selection, request: {name: selection.name}}));
    flowInvalidatePlans();
    for (const selection of selections) state.flow.selectedTableIds.add(selection.key);
    state.flow.snapshot = null;
    state.flow.understand = null;
    state.flow.questions = [];
    state.flow.stage = "new";
    return selections;
  });
}

async function flowIngest(mode, source = null) {
  return flowAction(async (binding) => {
    if (!["discover", "compute"].includes(mode) || !state.flow.rootLabel) throw flowFailure("INVALID_REQUEST", "Gắn thư mục trước khi nạp nguồn.");
    const flow = state.flow;
    let requests = source ? [source] : flow.pendingRequests.filter((item) => flow.selectedTableIds.has(item.id)).map((item) => item.request);
    const selected = new Set(flow.workbookSelections.filter((item) => flow.selectedTableIds.has(item.key)).map((item) => item.key));
    if (!source && selected.size) {
      let selections;
      try {
        selections = flow.preparationReview
          ? (await flowPreparedWorkbookSources(flow.preparationReview, mode)).filter(item => selected.has(item.key))
          : await flowReadOpenWorkbook(mode, selected);
      } catch (error) { if (flow.preparationReview) flowInvalidateSourceAuthority(flow); throw error; }
      flowAssertCurrent(binding);
      if (selections.length !== selected.size) throw flowFailure("AF_SPEC_STALE", "Bảng đã chọn không còn trong workbook. Hãy thêm workbook lại.");
      flowCheckBounds(selections);
      requests = [...requests, ...selections.map((selection) => {
        const {key, ...payload} = selection;
        payload.name = flow.workbookSelections.find((item) => item.key === key)?.request.name || payload.name;
        return {kind: "workbook", payload};
      })];
    }
    if (!requests.length) throw flowFailure("AF_INGEST_FAILED", "Chọn ít nhất một nguồn trong danh sách.");
    flowCheckBounds(requests.filter((request) => request.kind === "workbook").map((request) => request.payload));
    requests = requests.map((request) => ({...request, mode}));
    flow.snapshot = null;
    flow.freshSnapshotHash = null;
    flow.understand = null;
    flow.questions = [];
    flow.stage = "new";
    const expectedPlanningHash = mode === "compute" ? flow.planningHash : null;
    const planningGeneration = flow.planningGeneration;
    flow.branches = [];
    flow.planningHash = null;
    const result = await api("/api/assistant/ingest", {requests, ...(expectedPlanningHash ? {expectedPlanningHash} : {})});
    flowAssertCurrent(binding);
    if (flow.preparationReview) {
      try { await flow.preparationReview.validate(); flowAssertCurrent(binding); }
      catch (error) { flowInvalidateSourceAuthority(flow); throw error; }
    }
    if (expectedPlanningHash && planningGeneration !== flow.planningGeneration) {
      throw flowFailure("AF_SPEC_STALE", "Đề bài hoặc câu trả lời đã đổi trong lúc đọc toàn bộ; hãy tạo kế hoạch lại.");
    }
    flow.understand = null;
    flow.questions = [];
    flow.answers = {};
    if (byId("flow-disclosure")) byId("flow-disclosure").checked = false;
    flowAccept(result);
    flow.freshSnapshotHash = mode === "compute" && result.snapshot ? result.snapshot.snapshotHash : null;
    flow.spec = flow.approval = null;
    flow.approvalConsumed = false;
    flow.handoffStatus = null;
    flow.applyMessage = "";
    return result;
  });
}

function flowInvalidateSourceAuthority(flow) {
  flow.snapshot = flow.understand = flow.planningHash = flow.draftInputs = flow.freshSnapshotHash = null;
  flow.branches = []; flow.questions = []; flow.delta = flow.engine = flow.chosenBranch = null;
  flow.planSummary = ""; flow.planQuestions = []; flow.planAssumptions = []; flow.allBlocked = false;
  flow.planningGeneration += 1;
  if (!flow.approvalConsumed) { flow.spec = flow.approval = null; flow.stage = "new"; }
  if (byId("flow-approve-check")) byId("flow-approve-check").checked = false;
}

async function flowUnderstand() {
  return flowAction(async (binding) => {
    const flow = binding.flow;
    if (!flow.snapshot || flow.stage === "ingest_blocked" || !(byId("prompt")?.value || "").trim()) return;
    if (flow.workbookSourceSelections?.length) {
      let fresh;
      try { fresh = await flowFreshWorkbookSources(flow); }
      catch (error) {
        flowAssertCurrent(binding); flowInvalidateSourceAuthority(flow);
        const failure = flowFailure(error.code === "AF_SPEC_STALE" ? "AF_SPEC_STALE" : "OFFICE_READ_FAILED", error.message);
        failure.preserveFlow = true; throw failure;
      }
      flowAssertCurrent(binding);
      for (const request of fresh) {
        const payload = request.payload;
        const bound = flow.snapshot.tables?.find((table) => table.name === (request.name || payload.name));
        const ordinals = flow.mode === "discover" ? bound?.sampleOrdinals : payload.sampleOrdinals;
        const rows = flow.mode === "discover" ? ordinals?.map((ordinal) => payload.rows[ordinal]) : payload.rows;
        const hash = bound && ordinals && rows?.every((row) => Array.isArray(row)) ? await flowDigest({header: payload.header,
          rows, mode: flow.mode, totalRows: payload.totalRows, sampleOrdinals: ordinals}) : null;
        flowAssertCurrent(binding);
        if (!bound || hash !== bound.contentHash) {
          flowInvalidateSourceAuthority(flow);
          const error = flowFailure("AF_SPEC_STALE", "Nguồn workbook khác snapshot đã nạp. Hãy nạp lại nguồn trước khi phân tích.");
          error.preserveFlow = true; throw error;
        }
      }
    }
    const result = await api("/api/assistant/understand", {});
    flowAssertCurrent(binding); flowAccept(result);
    return result;
  });
}

function bindFlowPromptShortcut() {
  byId("prompt")?.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || !event.ctrlKey || event.altKey || event.metaKey || event.shiftKey || event.isComposing || event.repeat) return;
    const button = byId("flow-analyze-button");
    if (!button || button.disabled) return;
    event.preventDefault(); button.click();
  });
}

function setExportProgress(message) {
  const target = byId(state.activeTab === "pq" ? (state.pqMode === "advanced" ? "pq-progress" : "pq2-progress") : "flow-apply-status");
  if (target) target.textContent = message;
}

async function flowPlanDraft() {
  return flowAction(async (binding) => {
    const flow = binding.flow;
    const prompt = (byId("prompt")?.value || "").trim();
    if (!flow.understand || !["understood", "planning", "branched"].includes(flow.stage) || !prompt) return;
    if (byId("flow-disclosure")?.checked !== true) throw flowFailure("AF_DISCLOSURE_REQUIRED", "Đồng ý gửi mẫu tới Codex trước khi tạo kế hoạch.");
    const answers = Object.keys(flow.answers).sort().filter((questionId) => String(flow.answers[questionId]).trim())
      .map((questionId) => ({questionId, answer: flow.answers[questionId]}));
    const answerBinding = JSON.stringify(answers);
    const result = await api("/api/assistant/plan-draft", {prompt, answers, acknowledged: true});
    flowAssertCurrent(binding);
    const currentAnswers = Object.keys(flow.answers).sort().filter((questionId) => String(flow.answers[questionId]).trim())
      .map((questionId) => ({questionId, answer: flow.answers[questionId]}));
    if (prompt !== (byId("prompt")?.value || "").trim() || answerBinding !== JSON.stringify(currentAnswers)
        || byId("flow-disclosure")?.checked !== true) {
      throw flowFailure("AF_SPEC_STALE", "Đề bài, câu trả lời hoặc đồng ý đã đổi. Hãy rà soát và tạo kế hoạch lại.");
    }
    flow.branches = result.branches || [];
    flow.planningHash = result.planningHash || null;
    flow.draftInputs = result.draftInputs || null;
    flow.planSummary = result.summary || "";
    flow.planQuestions = result.questions || [];
    flow.planAssumptions = result.assumptions || [];
    flow.delta = flow.engine = flow.chosenBranch = null;
    flow.allBlocked = false;
    flow.stage = result.stage;
    return result;
  });
}

function flowInvalidatePlans() {
  state.flow.freshSnapshotHash = null;
  state.flow.planningGeneration += 1;
  state.flow.branches = [];
  state.flow.planningHash = null;
  state.flow.draftInputs = null;
  state.flow.delta = state.flow.engine = state.flow.chosenBranch = null;
  state.flow.allBlocked = false;
  if (!state.flow.approvalConsumed) {
    state.flow.spec = state.flow.approval = null;
    if (["frozen", "approved"].includes(state.flow.stage)) state.flow.stage = "understood";
  }
  if (byId("flow-approve-check")) byId("flow-approve-check").checked = false;
  state.flow.planSummary = "";
  state.flow.planQuestions = [];
  state.flow.planAssumptions = [];
  if (["planning", "branching", "branched"].includes(state.flow.stage)) state.flow.stage = "understood";
  if (byId("flow-disclosure")) byId("flow-disclosure").checked = false;
  renderFlowBranches();
  updateFlowButtons();
}

async function flowExecuteBranches() {
  return flowAction(async (binding) => {
    const flow = binding.flow;
    if (flow.mode !== "compute") throw flowFailure("AF_SAMPLE_ONLY", "Chọn Đọc toàn bộ để tính trước khi chạy A/B.");
    if (!["planning", "branched"].includes(flow.stage) || !flow.planningHash) return;
    const planningHash = flow.planningHash;
    const generation = flow.planningGeneration;
    const prompt = (byId("prompt")?.value || "").trim();
    const answers = JSON.stringify(flow.answers);
    const previousStage = flow.stage;
    flow.stage = "branching";
    renderFlowBranches();
    updateFlowButtons();
    let result;
    try { result = await api("/api/assistant/branches", {expectedPlanningHash: planningHash}); }
    catch (error) {
      if (generation === flow.planningGeneration && flow.planningHash === planningHash) flow.stage = previousStage;
      throw error;
    }
    flowAssertCurrent(binding);
    if (generation !== flow.planningGeneration || flow.planningHash !== planningHash
        || result.planningHash !== planningHash || prompt !== (byId("prompt")?.value || "").trim()
        || answers !== JSON.stringify(flow.answers)) {
      throw flowFailure("AF_SPEC_STALE", "Đề bài, câu trả lời hoặc kế hoạch đã đổi trong lúc tính A/B.");
    }
    flowAccept(result);
    flow.chosenBranch = null;
    return result;
  });
}

async function flowDigest(value) {
  const cryptoApi = globalThis.crypto || window.crypto;
  if (!cryptoApi?.subtle) throw flowFailure("AF_WRITE_PARTIAL", "WebCrypto chưa sẵn sàng để kiểm tra read-back; chưa ghi workbook.");
  const digest = await cryptoApi.subtle.digest("SHA-256", new TextEncoder().encode(canonicalProblemChainJson(value)));
  return "sha256:" + Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function flowCurrentWorkbookIdentity() {
  const expected = state.workbook;
  if (!expected || !state.officeReady) throw flowFailure("ASSISTANT_WORKBOOK_REQUIRED", "Đọc workbook đang mở trước khi chốt hoặc ghi.");
  const name = await Excel.run(async (context) => {
    context.workbook.load("name");
    await context.sync();
    return context.workbook.name;
  });
  const url = officeDocumentUrl();
  if (name !== expected.name || url !== expected.url) throw flowFailure("AF_SPEC_STALE", "Workbook đang mở đã đổi; hãy nạp lại nguồn.");
  return {name, documentHash: await flowDigest(url)};
}

async function flowFreshWorkbookSources(flow) {
  if (flow.preparationReview) {
    const full = await flowPreparedWorkbookSources(flow.preparationReview, "compute");
    return full.filter(item => flow.selectedTableIds.has(item.key)).map(({key, ...payload}) => {
      const selection = (flow.workbookSourceSelections || []).find(item => item.origin === payload.origin && item.table === false);
      if (selection) payload.name = selection.name;
      return {kind: "workbook", mode: "compute", payload, ...(selection?.alias ? {name: selection.alias} : {})};
    });
  }
  const selections = flow.workbookSourceSelections || [];
  if (!selections.length) return [];
  const metadata = await flowReadOpenWorkbook("compute", null, true);
  const selected = metadata.filter((entry) => selections.some((selection) =>
    selection.origin === `Workbook!${entry.sheet}!${entry.name}` && selection.table === entry.table));
  if (selected.length !== selections.length) throw flowFailure("AF_SPEC_STALE", "Một nguồn workbook đã đổi tên hoặc không còn tồn tại.");
  const full = await flowReadOpenWorkbook("compute", new Set(selected.map((entry) => entry.key)));
  return full.map((entry) => {
    const selection = selections.find((item) => item.origin === entry.origin && item.table === entry.table);
    if (!selection) throw flowFailure("AF_SPEC_STALE", "Danh sách nguồn workbook đã đổi.");
    const {key, ...payload} = entry;
    payload.name = selection.name;
    return {kind: "workbook", mode: "compute", payload, ...(selection.alias ? {name: selection.alias} : {})};
  });
}

function flowReviewedSpec(spec) {
  return {expectedSpecFingerprint: spec.fingerprint, expectedPreviewHash: spec.previewHash, expectedResultDigest: spec.resultDigest};
}

async function flowFreeze() {
  return flowAction(async (binding) => {
    const flow = binding.flow;
    const branch = flow.branches.find((item) => item.id === flow.chosenBranch);
    if (!branch?.selectable || flow.approvalConsumed) return;
    const generation = flow.planningGeneration;
    const workbookIdentity = await flowCurrentWorkbookIdentity();
    flowAssertCurrent(binding);
    if (generation !== flow.planningGeneration) throw flowFailure("AF_SPEC_STALE", "Kế hoạch đã đổi trước khi chốt.");
    const result = await api("/api/assistant/freeze", {branchId: branch.id, createdAt: flowNowIso(), workbookIdentity,
      acknowledgeMissingControl: byId("flow-control-ack")?.checked === true,
      expectedPlanningHash: flow.planningHash, expectedPreviewHash: branch.previewHash, expectedResultDigest: branch.resultDigest});
    flowAssertCurrent(binding);
    if (generation !== flow.planningGeneration) throw flowFailure("AF_SPEC_STALE", "Đề bài đã đổi trong khi chốt; chưa duyệt ghi.");
    flowAccept(result);
    flow.approval = null;
    if (byId("flow-approve-check")) byId("flow-approve-check").checked = false;
    return result;
  });
}

async function flowApprove() {
  return flowAction(async (binding) => {
    const flow = binding.flow, spec = flow.spec;
    if (!spec || flow.approvalConsumed || byId("flow-approve-check")?.checked !== true) return;
    const workbookIdentity = await flowCurrentWorkbookIdentity();
    const workbookSources = await flowFreshWorkbookSources(flow);
    flowAssertCurrent(binding);
    if (flow.spec !== spec || byId("flow-approve-check")?.checked !== true) throw flowFailure("AF_SPEC_STALE", "Spec hoặc xác nhận duyệt đã đổi.");
    const result = await api("/api/assistant/approvals", {approvedAt: flowNowIso(), acknowledged: true,
      workbookIdentity, workbookSources, ...flowReviewedSpec(spec)});
    flowAssertCurrent(binding);
    if (flow.spec !== spec || byId("flow-approve-check")?.checked !== true) throw flowFailure("AF_SPEC_STALE", "Xác nhận duyệt đã đổi trong khi xử lý.");
    flowAccept(result);
    return result;
  });
}

async function flowWriteResult(handoff, expectedWorkbook) {
  const {columns, rows} = handoff.result;
  if (!Array.isArray(columns) || !columns.length || !Array.isArray(rows) || (rows.length + 1) * columns.length > FLOW_MAX_CELLS
      || handoff.result.truncated !== false || rows.some((row) => !Array.isArray(row) || row.length !== columns.length)) {
    throw flowFailure("AF_WRITE_PARTIAL", "Kết quả bàn giao không đầy đủ hoặc vượt giới hạn ghi.");
  }
  if (await flowDigest({columns, rows}) !== handoff.resultDigest) throw flowFailure("AF_WRITE_PARTIAL", "Digest bàn giao không khớp; chưa ghi worksheet.");
  return Excel.run(async (context) => {
    const workbook = context.workbook;
    workbook.load("name");
    workbook.worksheets.load("items/name");
    await context.sync();
    if (workbook.name !== expectedWorkbook.name || officeDocumentUrl() !== expectedWorkbook.url) throw flowFailure("AF_WRITE_PARTIAL", "Workbook đã đổi sau khi bàn giao; chưa ghi kết quả.");
    const target = handoff.apply.target.sheet;
    if (workbook.worksheets.items.some((sheet) => sheet.name.toLocaleLowerCase() === target.toLocaleLowerCase())) throw flowFailure("AF_WRITE_PARTIAL", "Sheet đích đã tồn tại; không ghi đè.");
    const sheet = workbook.worksheets.add(target);
    await context.sync();
    const matrix = [columns.map((column) => column.name), ...rows.map((row) => row.map((value) => value === null ? "" : value))];
    const batchSize = Math.max(1, Math.floor(10000 / columns.length));
    for (let start = 0; start < matrix.length; start += batchSize) {
      const chunk = matrix.slice(start, start + batchSize);
      const range = sheet.getRangeByIndexes(start, 0, chunk.length, columns.length);
      range.numberFormat = chunk.map((row) => row.map(() => "@"));
      await context.sync();
      range.values = chunk;
      await context.sync();
    }
    const markerRange = sheet.getRangeByIndexes(rows.length + 2, 0, 1, 1);
    markerRange.numberFormat = [["@"]];
    await context.sync();
    markerRange.values = [[handoff.marker]];
    await context.sync();
    const readback = sheet.getRangeByIndexes(0, 0, matrix.length, columns.length);
    readback.load("values,formulas");
    markerRange.load("values,formulas");
    await context.sync();
    if (readback.values.length !== matrix.length || readback.values.some((row) => row.length !== columns.length)
        || canonicalProblemChainJson(readback.values[0]) !== canonicalProblemChainJson(matrix[0])
        || markerRange.values?.[0]?.[0] !== handoff.marker) throw flowFailure("AF_WRITE_PARTIAL", "Header, kích thước hoặc marker đọc lại không khớp.");
    // Excel represents null cells as empty strings. Recover null only after
    // independently checking that the actual cell is empty; every other value
    // must be exactly equal, including all decimal digits and literal strings.
    const actualRows = readback.values.slice(1).map((row, index) => row.map((value, column) =>
      rows[index][column] === null && value === "" ? null : value));
    if (canonicalProblemChainJson(actualRows) !== canonicalProblemChainJson(rows)
        || await flowDigest({columns, rows: actualRows}) !== handoff.resultDigest) throw flowFailure("AF_WRITE_PARTIAL", "Dữ liệu đọc lại khác kết quả đã chốt.");
    // formulas echoes literal values too, so use the formula-local API only
    // through getSpecialCellsOrNullObject, which distinguishes literal '=...'.
    if (typeof readback.getSpecialCellsOrNullObject !== "function") throw flowFailure("AF_WRITE_PARTIAL", "Excel chưa hỗ trợ kiểm ô formula sau ghi.");
    const formulas = readback.getSpecialCellsOrNullObject("Formulas");
    const markerFormulas = markerRange.getSpecialCellsOrNullObject("Formulas");
    formulas.load("isNullObject"); markerFormulas.load("isNullObject");
    await context.sync();
    if (!formulas.isNullObject || !markerFormulas.isNullObject) throw flowFailure("AF_WRITE_PARTIAL", "Sheet kết quả có formula ngoài hợp đồng values-only.");
    return {...handoff.receiptBinding, verified: true};
  });
}

async function flowApply() {
  return flowAction(async (binding) => {
    const flow = binding.flow, spec = flow.spec;
    if (!spec || flow.stage !== "approved" || flow.approvalConsumed || byId("flow-approve-check")?.checked !== true) return;
    let requested = false, handoff = null;
    try {
      if (!window.Office || !Office.context.requirements.isSetSupported("ExcelApi", "1.9")) throw flowFailure("AF_WRITE_PARTIAL", "Excel chưa hỗ trợ đầy đủ ghi và kiểm tra values-only (ExcelApi 1.9); chưa ghi workbook.");
      const expectedWorkbook = {name: state.workbook.name, url: state.workbook.url};
      const workbookIdentity = await flowCurrentWorkbookIdentity();
      const workbookBase64 = await exportWorkbookBase64();
      const workbookSources = await flowFreshWorkbookSources(flow);
      flowAssertCurrent(binding);
      if (flow.spec !== spec) throw flowFailure("AF_SPEC_STALE", "Spec đã đổi trước khi gửi ghi.");
      await flowCurrentWorkbookIdentity();
      // A lost response may already have consumed the capability. Disable
      // repeat attempts before the request; only an explicit false can undo it.
      requested = true;
      flow.approvalConsumed = true;
      handoff = await api("/api/assistant/apply", {workbookBase64, appliedAt: flowNowIso(), workbookIdentity,
        workbookSources, ...flowReviewedSpec(spec)}, {preserveConsumedState: true});
      flowAssertCurrent(binding);
      flow.stage = "handoff";
      flow.handoffStatus = "partial-unknown";
      if (flow.spec !== spec) throw flowFailure("AF_WRITE_PARTIAL", "Spec đã đổi sau khi bàn giao; không ghi.");
      if (handoff.stage !== "handoff" || handoff.resultDigest !== spec.resultDigest || handoff.apply?.target?.sheet !== spec.target.sheet
          || handoff.receiptBinding?.specFingerprint !== spec.fingerprint || handoff.receiptBinding?.previewHash !== spec.previewHash
          || handoff.receiptBinding?.resultDigest !== spec.resultDigest || handoff.receiptBinding?.sheet !== spec.target.sheet
          || handoff.receiptBinding?.marker !== handoff.marker || handoff.receiptBinding?.rowCount !== handoff.result?.rows?.length
          || handoff.receiptBinding?.columnCount !== handoff.result?.columns?.length) throw flowFailure("AF_WRITE_PARTIAL", "Bàn giao không khớp revision Spec được duyệt; không ghi.");
      await flowCurrentWorkbookIdentity();
      const freshSources = await flowFreshWorkbookSources(flow);
      if (canonicalProblemChainJson(freshSources) !== canonicalProblemChainJson(workbookSources)) throw flowFailure("AF_WRITE_PARTIAL", "Nguồn workbook đổi trong lúc bàn giao; không ghi kết quả.");
      const receipt = await flowWriteResult(handoff, expectedWorkbook);
      flowAssertCurrent(binding);
      const afterSources = await flowFreshWorkbookSources(flow);
      if (canonicalProblemChainJson(afterSources) !== canonicalProblemChainJson(workbookSources)) throw flowFailure("AF_WRITE_PARTIAL", "Nguồn workbook đổi trong lúc ghi; kết quả chưa được xác nhận.");
      const result = await api("/api/assistant/apply", {receipt, appliedAt: flowNowIso()}, {preserveConsumedState: true});
      flowAssertCurrent(binding);
      flowAccept(result);
      flow.handoffStatus = "readback-verified";
      flow.applyMessage = "Đã ghi sheet mới và đọc lại toàn bộ kết quả khớp digest. Workbook chưa lưu. Số Decimal được giữ dạng văn bản để bảo toàn độ chính xác.";
      return result;
    } catch (error) {
      const consumed = requested && error.approvalConsumed !== false;
      if (state.flow === flow) {
        flow.approvalConsumed = consumed;
        if (consumed) {
          flow.stage = "partial";
          flow.handoffStatus = "partial-unknown";
          flow.applyMessage = "Quyền ghi đã hoặc có thể đã dùng. Workbook có thể được ghi một phần; trạng thái chưa biết, không tự thử lại. Workbook chưa lưu.";
          if (handoff?.receiptBinding) {
            try { await api("/api/assistant/apply", {receipt: {...handoff.receiptBinding, verified: false}, appliedAt: flowNowIso()}, {preserveConsumedState: true}); } catch (_) { /* State is conservatively partial even if reporting fails. */ }
          }
        } else flow.applyMessage = "Chưa ghi kết quả; quyền ghi chưa tiêu thụ. " + error.message;
        showError(consumed ? "AF_WRITE_PARTIAL" : error.code || "AF_WRITE_PARTIAL", error.message);
      }
      return null;
    }
  });
}

async function flowLoadState() {
  return flowAction(async (binding) => {
    binding.flow.freshSnapshotHash = null;
    const generation = binding.flow.planningGeneration;
    const result = await api("/api/assistant/state", {});
    flowAssertCurrent(binding);
    if (result.planningHash) {
      const inputs = result.draftInputs;
      const prompt = (byId("prompt")?.value || "").trim();
      const answers = Object.keys(state.flow.answers).sort().filter((id) => String(state.flow.answers[id]).trim())
        .map((questionId) => ({questionId, answer: state.flow.answers[questionId]}));
      if (inputs && !prompt && !answers.length && !state.flow.snapshot && generation === state.flow.planningGeneration) {
        byId("prompt").value = inputs.prompt;
        state.flow.answers = Object.fromEntries((inputs.answers || []).map((answer) => [answer.questionId, answer.answer]));
      } else if (!inputs || prompt !== inputs.prompt || JSON.stringify(answers) !== JSON.stringify(inputs.answers)
          || generation !== state.flow.planningGeneration) {
        result.branches = [];
        result.planningHash = null;
        result.draftInputs = null;
        result.stage = result.understand ? "understood" : "ingested";
      }
    }
    flowAccept(result);
    if (result.record && result.node && result.spec) {
      const identity = await flowCurrentWorkbookIdentity();
      flowAssertCurrent(binding);
      if (canonicalProblemChainJson(identity) === canonicalProblemChainJson(result.spec.workbookIdentity)
          && result.record.hash === result.node.recordHash && await flowRecordHelper().verifyAssistantRecordHash(result.node)) {
        const basis = Object.fromEntries(result.record.hashBasis.map((key) => [key, result.record[key]]));
        if (await flowDigest(basis) !== result.record.hash) throw flowFailure("AF_RECORD_INVALID", "Hash Record khôi phục không khớp.");
        flowAssertCurrent(binding);
        const key = workbookIdentity(state.workbook);
        if (state.workbookRecord.workbookKey !== key) state.workbookRecord = createWorkbookRecordState(key);
        Object.assign(state.workbookRecord, {record: result.record, node: result.node, staleCheck: result.staleCheck});
      }
    }
    if (result.snapshotHash && !state.flow.snapshot) state.flow.stage = "new";
    return result;
  });
}

async function flowReset() {
  return flowAction(async (binding) => {
    const result = await api("/api/assistant/reset", {});
    flowAssertCurrent(binding);
    resetFlowView("Đã bắt đầu lại. Gắn thư mục và nạp nguồn mới.", {explicit: true});
    return result;
  });
}

function flowRecordHelper() {
  const helper = globalThis.AssistantRecordXml;
  if (!helper) throw flowFailure("AF_RECORD_INVALID", "Chưa tải được helper Record; hãy mở lại pane.");
  return helper;
}

function flowRecordCurrent(recordState) {
  if (state.workbookRecord !== recordState || !state.workbook || recordState.workbookKey !== workbookIdentity(state.workbook)) {
    throw flowFailure("AF_SPEC_STALE", "Workbook đã đổi; đọc Record của workbook hiện tại trước khi lưu.");
  }
}

async function flowReadRecord() {
  if (!state.officeReady || !state.workbook || state.flow.busy || state.workbookRecord.busy) return null;
  const binding = flowBinding();
  const key = workbookIdentity(state.workbook);
  if (state.workbookRecord.workbookKey !== key) state.workbookRecord = createWorkbookRecordState(key);
  const recordState = state.workbookRecord;
  recordState.busy = true;
  updateFlowButtons();
  try {
    if (!state.officeReady || !state.workbook) throw flowFailure("OFFICE_NOT_READY", "Chờ workbook sẵn sàng để đọc Record.");
    await flowCurrentWorkbookIdentity();
    const observed = await flowRecordHelper().readAssistantRecord({name: state.workbook.name, url: state.workbook.url || ""});
    flowAssertCurrent(binding);
    flowRecordCurrent(recordState);
    await flowCurrentWorkbookIdentity();
    recordState.persistedNode = observed;
    recordState.persistedNodeHash = observed?.hash ?? null;
    recordState.loaded = true;
    recordState.reloadRequired = false;
    recordState.message = observed ? `Đã đọc metadata ${observed.id} · ${observed.hash}. Chỉ khôi phục metadata; chưa xác minh Record đầy đủ hoặc nguồn hiện tại.`
      : "Workbook chưa có metadata Record. Workbook chưa lưu.";
    if (observed && recordState.node && observed.hash !== recordState.node.hash) recordState.message +=
      ` Metadata hiện có khác Record chờ lưu ${recordState.node.id} · ${recordState.node.hash}. Bấm Lưu sẽ thay metadata hiện có bằng Record chờ lưu.`;
    renderFlowRecord();
    return observed;
  } catch (error) {
    if (state.workbookRecord === recordState) {
      recordState.loaded = false;
      recordState.reloadRequired = true;
      recordState.message = "Không đọc được metadata Record. " + error.message;
      showError(error.code || "AF_RECORD_INVALID", error.message);
    }
    return null;
  } finally {
    recordState.busy = false;
    renderFlowRecord();
    updateFlowButtons();
  }
}

async function flowCreateRecord() {
  return flowAction(async (binding) => {
    const flow = binding.flow;
    if (!["applied", "recorded"].includes(flow.stage) || flow.handoffStatus !== "readback-verified" || !flow.approvalConsumed || !flow.spec) {
      throw flowFailure("AF_STAGE_INVALID", "Tạo Record sau khi đã ghi và kiểm tra đầy đủ kết quả.");
    }
    const spec = flow.spec;
    const identity = await flowCurrentWorkbookIdentity();
    if (canonicalProblemChainJson(identity) !== canonicalProblemChainJson(spec.workbookIdentity)) throw flowFailure("AF_SPEC_STALE", "Workbook không khớp Spec đã áp dụng.");
    const result = await api("/api/assistant/record", {});
    flowAssertCurrent(binding);
    await flowCurrentWorkbookIdentity();
    if (!result.record || result.recordHash !== result.record.hash || result.node?.recordHash !== result.recordHash
        || result.node.spec !== spec.fingerprint || result.node.snapshot !== spec.snapshotHash
        || !(await flowRecordHelper().verifyAssistantRecordHash(result.node))) throw flowFailure("AF_RECORD_INVALID", "Record hoặc metadata không khớp Spec.");
    const basis = Object.fromEntries(result.record.hashBasis.map((key) => [key, result.record[key]]));
    if (await flowDigest(basis) !== result.recordHash) throw flowFailure("AF_RECORD_INVALID", "Hash Decision Record đầy đủ không khớp.");
    flowAssertCurrent(binding);
    if (flow.spec !== spec) throw flowFailure("AF_SPEC_STALE", "Spec đã đổi trong lúc tạo Record.");
    const key = workbookIdentity(state.workbook);
    if (state.workbookRecord.workbookKey !== key) state.workbookRecord = createWorkbookRecordState(key);
    Object.assign(state.workbookRecord, {record: result.record, node: result.node, staleCheck: result.staleCheck});
    flowAccept(result);
    return result;
  });
}

async function flowPersistRecord() {
  return flowAction(async (binding) => {
    const recordState = state.workbookRecord;
    flowRecordCurrent(recordState);
    if (!recordState.loaded || recordState.reloadRequired || !recordState.node || !recordState.record) throw flowFailure("PQPC_HISTORY_CONFLICT", "Đọc metadata workbook trước khi lưu; sau xung đột phải bấm Đọc lại Record.");
    const identity = await flowCurrentWorkbookIdentity();
    if (recordState.node.spec !== binding.flow.spec?.fingerprint || canonicalProblemChainJson(identity) !== canonicalProblemChainJson(binding.flow.spec?.workbookIdentity)) {
      throw flowFailure("AF_SPEC_STALE", "Record không thuộc Spec của workbook đang mở.");
    }
    flowAssertCurrent(binding);
    flowRecordCurrent(recordState);
    try {
      // Pin the hash observed by Read. Never adopt a newer hash before writing.
      const expectedHash = recordState.persistedNodeHash;
      await flowRecordHelper().writeAssistantRecord(recordState.node, expectedHash, {name: state.workbook.name, url: state.workbook.url || ""});
      flowAssertCurrent(binding);
      flowRecordCurrent(recordState);
      await flowCurrentWorkbookIdentity();
      recordState.persistedNode = recordState.node;
      recordState.persistedNodeHash = recordState.node.hash;
      recordState.message = "Đã ghi và đọc lại metadata trong workbook. Workbook chưa lưu; cần lưu workbook để giữ sau khi đóng.";
      return {written: true, workbookSaved: false};
    } catch (error) {
      recordState.reloadRequired = true;
      recordState.message = error.code === "PQPC_HISTORY_CONFLICT" ? "Record đã đổi. Bấm Đọc lại Record và rà soát trước khi lưu tiếp."
        : "Ghi metadata partial/unknown. Bấm Đọc lại Record trước thao tác tiếp theo; workbook chưa lưu.";
      throw error;
    }
  });
}

function flowDownloadRecord() {
  const record = state.workbookRecord.record;
  if (!record) return;
  const blob = new Blob([JSON.stringify(record, null, 2)], {type: "application/json;charset=utf-8"});
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = record.id + ".json";
  anchor.click();
  URL.revokeObjectURL(url);
}

function renderFlowRecord() {
  const recordState = state.workbookRecord;
  const node = recordState.node || recordState.persistedNode;
  const sameWorkbook = !!state.workbook && recordState.workbookKey === workbookIdentity(state.workbook);
  flowSetHidden("flow-result-section", !node && !["applied", "recorded"].includes(state.flow.stage));
  const set = (id, value) => { if (byId(id)) byId(id).textContent = value; };
  set("flow-record-id", node?.id || "Chưa tạo Record");
  set("flow-record-hash", node?.recordHash || "—");
  set("flow-record-labels", node ? (node.labels.join(", ") || "không có nhãn") : "—");
  set("flow-record-persist", recordState.message);
  set("flow-workbook-saved", "Workbook đã lưu: Chưa. Add-in không gọi Save.");
  const record = recordState.record;
  set("flow-record-delta", record ? `${record.delta.rowsIn} → ${record.delta.rowsOut} dòng · trùng ${record.delta.duplicatesBefore} → ${record.delta.duplicatesAfter} · ${record.delta.changedColumns.length} biến đổi cột`
    : node ? "Chỉ có metadata; Record đầy đủ không nằm trong workbook." : "");
  set("flow-record-null-profile", record ? `Ô trống trước: ${JSON.stringify(record.delta.nullsBefore || {})} · sau: ${JSON.stringify(record.delta.nullsAfter || {})}` : "");
  flowTextList("flow-record-column-changes", record?.delta.changedColumns || []);
  let freshness = "Chưa nạp lại đầy đủ nguồn; độ mới hiện tại: unknown.";
  const fullSnapshot = sameWorkbook && state.flow.mode === "compute" && state.flow.snapshot
    && state.flow.freshSnapshotHash === state.flow.snapshot.snapshotHash;
  const sourceChanged = node && fullSnapshot && state.flow.snapshot.snapshotHash !== node.snapshot;
  if (sourceChanged || recordState.staleCheck?.stale === true) freshness = "STALE · Nguồn đã đổi so với Record. Record lịch sử được giữ nguyên; hãy nạp và tính lại trước khi dùng kết quả.";
  else if (node && fullSnapshot) freshness = "Nguồn đầy đủ vừa nạp khớp snapshot của Record; đây là kiểm tra tại lần đọc này.";
  else if (recordState.staleCheck?.freshness === "matches") freshness = "Nguồn file đã đọc lại và khớp tại lần tạo Record; workbook hiện tại chưa được kiểm tra lại.";
  set("flow-record-stale", freshness);
}

function flowTextList(id, values) {
  const container = byId(id);
  if (!container?.replaceChildren) return;
  container.replaceChildren();
  for (const value of values) {
    const item = document.createElement("p");
    item.textContent = typeof value === "string" ? value : value.message || value.detail || value.statement || JSON.stringify(value);
    container.appendChild(item);
  }
}

function renderFlowNavigator() {
  const container = byId("flow-navigator");
  if (!container?.replaceChildren) return;
  container.replaceChildren();
  const flow = state.flow;
  const items = [...flow.pendingRequests.map((item) => ({id: item.id, label: item.request.name || item.request.path})),
    ...flow.workbookSelections.map((item) => ({id: item.key, label: `${item.sheet} · ${item.request.name} · ${item.totalRows} dòng · ${item.totalColumns} cột`}))];
  for (const item of items) {
    const label = document.createElement("label");
    label.className = "flow-selection";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = flow.selectedTableIds.has(item.id);
    checkbox.disabled = flow.busy;
    checkbox.addEventListener("change", () => {
      if (flow !== state.flow || flow.busy) return;
      if (checkbox.checked) flow.selectedTableIds.add(item.id); else flow.selectedTableIds.delete(item.id);
      flowInvalidatePlans();
      flow.snapshot = null;
      flow.understand = null;
      flow.questions = [];
      flow.stage = "new";
      renderFlow();
    });
    const text = document.createElement("span");
    text.textContent = item.label;
    label.appendChild(checkbox);
    label.appendChild(text);
    container.appendChild(label);
  }
}

function flowRequestForSource(sourceId, origin = null) {
  const source = state.flow.sources.find((item) => item.id === sourceId);
  const locator = origin || source?.origin;
  return state.flow.pendingRequests.find((item) => item.request.path === locator || item.request.path === source?.name
    || (locator && item.request.path.replace(/\\/g, "/").endsWith("/" + locator)))
    || state.flow.workbookSelections.find((item) => source?.origin === `Workbook!${item.sheet}!${item.name}`);
}

function renderFlowConditions() {
  flowTextList("flow-error-list", [...state.flow.errors, ...state.flow.warnings]);
  const csv = byId("flow-csv-options");
  const renames = byId("flow-rename-list");
  if (!csv?.replaceChildren || !renames?.replaceChildren) return;
  csv.replaceChildren();
  renames.replaceChildren();
  for (const option of state.flow.csvOptions.filter((item) => item.needsClarification)) {
    const pending = flowRequestForSource(option.sourceId, option.origin);
    const group = document.createElement("div");
    const title = document.createElement("p");
    title.textContent = "CSV cần chọn dấu phân cách, encoding và dòng header trước khi nạp lại.";
    group.appendChild(title);
    for (const [key, values] of [["delimiter", [...new Set((option.candidates || []).map((item) => item.delimiter).filter(Boolean))]],
      ["encoding", [option.encoding || "utf-8", "utf-8-sig", "cp1258"]]]) {
      const label = document.createElement("label");
      label.textContent = key === "delimiter" ? "Dấu phân cách" : "Encoding";
      const select = document.createElement("select");
      select.disabled = !pending || state.flow.busy;
      const placeholder = document.createElement("option");
      placeholder.value = "";
      placeholder.textContent = "Chọn…";
      select.appendChild(placeholder);
      for (const value of values) {
        const item = document.createElement("option");
        item.value = value;
        item.textContent = value === "\t" ? "Tab" : value;
        select.appendChild(item);
      }
      select.value = pending?.request.options[key] || option[key] || "";
      select.addEventListener("change", () => { if (pending && !state.flow.busy) pending.request.options[key] = select.value; });
      label.appendChild(select);
      group.appendChild(label);
    }
    const headerLabel = document.createElement("label");
    headerLabel.textContent = "Dòng header";
    const header = document.createElement("input");
    header.type = "number";
    header.min = "1";
    header.value = String(pending?.request.options.header_row || option.headerRow || 1);
    header.disabled = !pending || state.flow.busy;
    header.addEventListener("change", () => { if (pending && !state.flow.busy) pending.request.options.header_row = Number(header.value); });
    headerLabel.appendChild(header);
    group.appendChild(headerLabel);
    csv.appendChild(group);
  }
  for (const conflict of state.flow.requiresRename) {
    for (const sourceId of conflict.sources || []) {
      const pending = flowRequestForSource(sourceId);
      const label = document.createElement("label");
      label.textContent = `Đổi tên bảng trùng ${conflict.tableName}: `;
      const input = document.createElement("input");
      input.type = "text";
      input.value = pending?.request.name || conflict.tableName;
      input.disabled = !pending || state.flow.busy;
      input.addEventListener("change", () => { if (pending && !state.flow.busy) pending.request.name = input.value.trim(); });
      label.appendChild(input);
      renames.appendChild(label);
    }
  }
}

function renderFlowQuestions() {
  const container = byId("flow-questions");
  if (!container?.replaceChildren) return;
  container.replaceChildren();
  for (const question of state.flow.questions) {
    const label = document.createElement("label");
    label.textContent = `${question.question} ${question.whyItMatters || ""}`;
    const input = document.createElement(question.kind === "single_choice" ? "select" : "input");
    if (question.kind === "single_choice") {
      const placeholder = document.createElement("option");
      placeholder.value = "";
      placeholder.textContent = "Chọn câu trả lời…";
      input.appendChild(placeholder);
      for (const option of question.options || []) {
        const node = document.createElement("option");
        node.value = typeof option === "string" ? option : option.value || option.label;
        node.textContent = typeof option === "string" ? option : option.label || option.value;
        input.appendChild(node);
      }
    } else input.type = "text";
    input.value = state.flow.answers[question.id] || "";
    input.disabled = state.flow.busy;
    input.addEventListener("change", () => {
      if (!state.flow.busy) {
        if (input.value.trim()) state.flow.answers[question.id] = input.value;
        else delete state.flow.answers[question.id];
        flowInvalidatePlans();
      }
    });
    label.appendChild(input);
    const evidence = document.createElement("p");
    evidence.className = "hint";
    evidence.textContent = (question.evidence || []).map((item) => item.value || item.kind).join(" · ");
    label.appendChild(evidence);
    container.appendChild(label);
  }
}

function renderFlowUnderstand() {
  const understand = state.flow.understand;
  if (!understand) return;
  const roles = understand.roles || [];
  const relationships = understand.relationships || [];
  byId("flow-understand-summary").textContent = `Engine đã đo cấu trúc: ${state.flow.snapshot?.tables?.length ?? state.flow.tables.length} bảng, ${relationships.length} quan hệ · ${understand.pack?.id || "generic"}`;
  flowTextList("flow-role-list", roles.map((item) => `${item.tableId} · ${item.structural} · ${item.domainLabel || ""}`));
  flowTextList("flow-relationship-list", relationships.map((item) => `${item.fromTable} → ${item.toTable} · ${item.cardinality} · ${item.status} · fan-out: ${item.fanOutRisk}`));
  flowTextList("flow-assumption-list", [...(understand.assumptions || []), ...(understand.warnings || []), ...(understand.pack?.notice ? [understand.pack.notice] : [])]);
}

function updateFlowButtons() {
  const flow = state.flow;
  if (!flow) return;
  const blocked = !flowCapabilityAvailable() || flow.busy;
  const set = (id, disabled) => { const node = byId(id); if (node) node.disabled = disabled; };
  set("flow-root-button", blocked);
  for (const id of ["flow-add-csv", "flow-add-xlsx", "flow-add-folder"]) set(id, blocked || !flow.rootLabel);
  set("flow-add-workbook", blocked || !flow.rootLabel || !state.officeReady);
  for (const id of ["flow-ingest-sample", "flow-ingest-full"]) set(id, blocked || !flow.rootLabel || !flow.selectedTableIds.size);
  set("flow-analyze-button", blocked || !flow.snapshot || flow.stage === "ingest_blocked" || !(byId("prompt")?.value || "").trim());
  set("flow-reset-button", blocked);
  set("flow-disclosure", blocked);
  set("flow-plan-button", blocked || !flow.understand || !["understood", "planning", "branched"].includes(flow.stage)
    || !(byId("prompt")?.value || "").trim() || byId("flow-disclosure")?.checked !== true);
  set("flow-branches-button", blocked || flow.mode !== "compute" || !flow.planningHash || !["planning", "branched"].includes(flow.stage));
  const selectedBranch = flow.branches.find((branch) => branch.id === flow.chosenBranch);
  const missingControl = selectedBranch?.reconciliation?.controlTotalApplicable === false;
  set("flow-control-ack", blocked || !missingControl || flow.approvalConsumed);
  set("flow-freeze-button", blocked || !state.officeReady || !selectedBranch?.selectable || flow.approvalConsumed
    || !["branched", "frozen", "approved"].includes(flow.stage) || (missingControl && byId("flow-control-ack")?.checked !== true));
  set("flow-approve-check", blocked || !["frozen", "approved"].includes(flow.stage) || !flow.spec || flow.approvalConsumed);
  set("flow-approve-button", blocked || flow.stage !== "frozen" || !flow.spec || flow.approvalConsumed || byId("flow-approve-check")?.checked !== true);
  set("flow-apply-button", blocked || !state.officeReady || flow.stage !== "approved" || !flow.approval || flow.approvalConsumed || byId("flow-approve-check")?.checked !== true);
  const recordState = state.workbookRecord;
  const recordWorkbookCurrent = !!state.workbook && recordState.workbookKey === workbookIdentity(state.workbook);
  set("flow-record-build", blocked || !["applied", "recorded"].includes(flow.stage) || flow.handoffStatus !== "readback-verified" || !flow.approvalConsumed);
  set("flow-record-reload", flow.busy || recordState.busy || !state.officeReady);
  set("flow-record-save", blocked || recordState.busy || !state.officeReady || !recordWorkbookCurrent || !recordState.loaded || recordState.reloadRequired || !recordState.record || !recordState.node || !flow.spec || recordState.node.spec !== flow.spec.fingerprint);
  set("flow-record-download", blocked || !recordWorkbookCurrent || !recordState.record);
  for (const id of ["flow-workbook-section", "flow-source-section", "flow-prompt-section", "flow-understand-section", "flow-branches-section", "flow-spec-section", "flow-apply-section", "flow-result-section"]) {
    const section = byId(id);
    if (section?.dataset) section.dataset.state = flow.stage;
    const chip = byId(id + "-status");
    if (chip) {
      const warning = flow.stage === "partial" || flow.stage === "ingest_blocked" || flow.allBlocked;
      const ready = id === "flow-workbook-section" ? state.officeReady && !!state.workbook : !!flow.snapshot;
      const label = flow.busy ? "Đang xử lý" : warning ? "Cần xử lý" : ready ? "Đã nạp · " + flow.stage : "Chưa nạp";
      chip.className = ["flow-workbook-section", "flow-source-section"].includes(id) ? "sr-only"
        : "badge " + (warning ? "badge-failed" : ready ? "badge-ready" : "badge-wait");
      const text = document.createElement("span"); text.textContent = id === "flow-workbook-section"
        ? state.officeReady && state.workbook ? "Đã kết nối workbook" : "Chưa đọc workbook" : label;
      chip.replaceChildren(createIcon(warning ? "alert-triangle" : "circle-info"), text);
    }
  }
}

function flowReviewStep(step) {
  const row = document.createElement("li");
  row.textContent = `${step.label || step.actionDescription || step.variableName || step.stepId || "Bước"} · ${step.operation?.type || step.operationType || ""}`;
  if (step.operation) {
    const details = document.createElement("details");
    const summary = document.createElement("summary");
    summary.textContent = "Xem tham số, đầu vào và điều kiện chính xác";
    const code = document.createElement("pre");
    code.className = "flow-algorithm";
    code.textContent = JSON.stringify(step, null, 2);
    details.appendChild(summary); details.appendChild(code); row.appendChild(details);
  }
  return row;
}

function flowReviewOutput(list, contract) {
  if (!contract) return;
  const row = document.createElement("li"), details = document.createElement("details");
  const summary = document.createElement("summary"), code = document.createElement("pre");
  summary.textContent = "Schema kết quả cuối của nhánh";
  code.className = "flow-algorithm";
  code.textContent = JSON.stringify(contract, null, 2);
  details.appendChild(summary); details.appendChild(code); row.appendChild(details); list.appendChild(row);
}

function renderFlowBranches() {
  const flow = state.flow;
  flowSetHidden("flow-branches-section", !flow.branches.length || !flow.snapshot || !flow.understand);
  const container = byId("flow-branches");
  if (!container) return;
  container.replaceChildren();
  if (byId("flow-plan-summary")) byId("flow-plan-summary").textContent = flow.planSummary;
  if (byId("flow-branch-engine")) byId("flow-branch-engine").textContent = flow.engine?.parityChecked === "none"
    ? "Bản này tính bằng engine nội bộ, chưa đối chiếu với Power Query trên máy bạn." : "";
  if (byId("flow-branch-status")) byId("flow-branch-status").textContent = flow.stage === "branching" ? "Đang tính A/B trên cùng snapshot…"
    : flow.allBlocked ? "Cả hai nhánh bị chặn. Quay lại cách hiểu hoặc tạo kế hoạch để sửa điều kiện." : "";
  if (byId("flow-branch-delta")) byId("flow-branch-delta").textContent = flow.delta?.applicable
    ? `A ${flow.delta.a} − B ${flow.delta.b} = ${flow.delta.value} · số do engine tính`
    : flow.delta?.reason || "";
  flowTextList("flow-plan-questions", flow.planQuestions);
  flowTextList("flow-plan-assumptions", flow.planAssumptions);
  for (const branch of flow.branches) {
    const card = document.createElement("article");
    card.id = `flow-branch-${branch.id}`;
    card.dataset.branchId = branch.id;
    const title = document.createElement("h3");
    title.textContent = `${branch.id} · ${branch.label}`;
    const rationale = document.createElement("p");
    rationale.textContent = branch.rationale;
    const badge = document.createElement("span");
    badge.className = "badge";
    badge.textContent = branch.reconciliation ? branch.warningCount ? "Đã tính · có cảnh báo" : "Đã tính bằng engine" : "chưa tính số";
    const steps = document.createElement("ol");
    for (const step of branch.normalizedSteps || branch.steps || []) steps.appendChild(flowReviewStep(step));
    flowReviewOutput(steps, branch.finalOutputContract);
    const choose = document.createElement(branch.reconciliation ? "input" : "button");
    choose.type = branch.reconciliation ? "radio" : "button";
    choose.textContent = "Chọn nhánh";
    choose.setAttribute("aria-label", `Chọn nhánh ${branch.id}`);
    choose.name = "flow-chosen-branch";
    choose.value = branch.id;
    choose.checked = flow.chosenBranch === branch.id;
    choose.disabled = !branch.reconciliation || branch.selectable !== true || flow.busy || flow.approvalConsumed;
    choose.addEventListener("change", () => {
      if (flow !== state.flow || flow.busy || branch.selectable !== true || !choose.checked) return;
      flow.chosenBranch = branch.id;
      flow.spec = flow.approval = null;
      flow.stage = "branched";
      if (byId("flow-control-ack")) byId("flow-control-ack").checked = false;
      if (byId("flow-approve-check")) byId("flow-approve-check").checked = false;
      renderFlowBranches();
      renderFlowFreeze();
      updateFlowButtons();
    });
    for (const child of [title, rationale, badge, steps, choose]) card.appendChild(child);
    container.appendChild(card);
    if (branch.reconciliation) {
      const banner = document.createElement("p");
      banner.setAttribute("role", "status");
      banner.textContent = branch.reconciliation.passed ? branch.warningCount
        ? "Đối soát tổng đạt; có cảnh báo chuyển đổi dữ liệu cần rà soát." : "Đối soát đạt."
        : branch.selectable ? "Chưa có đối soát tổng kiểm soát cho nhánh này. Cần xác nhận tường minh trước khi duyệt."
          : `Bị chặn: ${branch.error?.code || "AF_RECONCILE_FAILED"} · ${branch.error?.detail || "Đối soát chưa đạt."}`;
      card.appendChild(banner);
      if (!branch.reconciliation.controlTotalApplicable && !branch.selectable) {
        const unavailable = document.createElement("p");
        unavailable.textContent = "Chưa có đối soát tổng kiểm soát cho nhánh này.";
        card.appendChild(unavailable);
      }
      const reason = document.createElement("p");
      reason.textContent = branch.reconciliation.controlTotalReason || "";
      card.appendChild(reason);
      if (branch.warningCount) {
        const warningTitle = document.createElement("p"), warnings = document.createElement("ul");
        warningTitle.className = "notice notice-warning";
        warningTitle.textContent = `${branch.warningCount} nhóm cảnh báo chuyển đổi. Tổng tiền khớp không xác nhận từng ô dữ liệu đúng.`;
        card.appendChild(warningTitle);
        for (const warning of branch.warnings || []) {
          const item = document.createElement("li");
          item.textContent = `${warning.code} · ${warning.path} · ${warning.message}`;
          warnings.appendChild(item);
        }
        card.appendChild(warnings);
      }
      const dimensions = document.createElement("div");
      dimensions.id = `flow-branch-${branch.id}-counts`;
      card.appendChild(dimensions);
      renderTable(dimensions.id, ["Giai đoạn", "Dòng", "Cột"], [
        ["Trước", branch.counts.before.rows, branch.counts.before.cols], ["Sau", branch.counts.after.rows, branch.counts.after.cols]]);
      const preview = document.createElement("div");
      preview.id = `flow-branch-${branch.id}-preview`;
      card.appendChild(preview);
      renderTable(preview.id, (branch.columns || []).map((column) => column.name), (branch.rows || []).slice(0, 200));
      const detail = document.createElement("p");
      detail.className = "hint";
      detail.textContent = `${Math.min(branch.rows?.length || 0, 200)}/${branch.totalRows} dòng${branch.truncated ? " · xem trước đã giới hạn" : ""} · ${branch.elapsedMs} ms${branch.cached ? " · dùng cache kết quả" : ""}`;
      card.appendChild(detail);
    }
  }
}

function renderFlowFreeze() {
  const flow = state.flow;
  flowSetHidden("flow-spec-section", !flow.spec);
  flowSetHidden("flow-apply-section", !flow.spec && !flow.approvalConsumed);
  const spec = flow.spec;
  if (byId("flow-spec-summary")) byId("flow-spec-summary").textContent = spec
    ? `Nhánh ${spec.branchId} · ${spec.fingerprint} · đích ${spec.target.sheet} · nhãn ${(spec.labels || []).join(", ") || "không có"}` : "";
  const review = byId("flow-spec-steps");
  if (review) {
    review.replaceChildren();
    const list = document.createElement("ol");
    for (const step of spec?.steps || []) list.appendChild(flowReviewStep(step));
    review.appendChild(list);
  }
  const writeWorkbook = flow.approvalConsumed && spec?.workbookIdentity?.name
    ? `Lần ghi vào workbook «${spec.workbookIdentity.name}»: ` : "";
  if (byId("flow-apply-status")) byId("flow-apply-status").textContent = writeWorkbook + (flow.applyMessage || (flow.approvalConsumed
    ? flow.handoffStatus === "readback-verified" ? "Đã ghi và đọc lại toàn bộ khớp digest. Workbook chưa lưu."
      : "Quyền ghi đã dùng; chưa có xác nhận đọc lại đầy đủ. Trạng thái partial/unknown, không tự thử lại."
    : flow.approval ? "Đã duyệt đúng Spec. Chưa ghi workbook." : "Rà soát và duyệt Spec trước khi ghi."));
}

function renderFlow() {
  const flow = state.flow;
  flowSetHidden("flow-source-section", false);
  flowSetHidden("flow-prompt-section", !flow.snapshot);
  flowSetHidden("flow-understand-section", !flow.understand);
  const status = byId("flow-source-status");
  if (status) status.textContent = !flowCapabilityAvailable()
    ? "Coordinator cũ — chạy lại server để dùng luồng Trợ lý v2."
    : flow.busy ? "Đang xử lý nguồn…" : flow.stage === "ingest_blocked" ? "Nguồn bị chặn. Giải quyết các điều kiện rồi nạp lại."
      : flow.snapshot ? "Đã nạp nguồn cục bộ. Chỉ gửi mẫu tới Codex sau hành động và đồng ý của bạn." : "Gắn thư mục, thêm nguồn và chọn chế độ nạp.";
  if (byId("flow-root-label")) byId("flow-root-label").textContent = flow.rootLabel;
  if (byId("flow-mode-badge")) byId("flow-mode-badge").textContent = flow.mode === "compute" ? "TOÀN BỘ" : flow.mode === "discover" ? "MẪU 20 dòng" : "CHƯA NẠP";
  if (byId("flow-sample-info")) byId("flow-sample-info").textContent = flow.sampleInfo.map((item) =>
    `${item.name}: ${item.rowCount}/${item.totalRows} dòng · dòng: ${(item.sampleOrdinals || []).slice(0, 20).join(", ")}${item.mode === "compute" ? " · dữ liệu đầy đủ" : " · cùng bảng ⇒ cùng mẫu"}`).join("; ");
  if (flowCapabilityAvailable()) {
    flowTextList("flow-source-list", flow.sources.map((item) => `${item.name} · ${item.type} · ${(item.hash || "").slice(0, 20)}`));
    renderFlowNavigator();
    renderFlowConditions();
    renderFlowQuestions();
    renderFlowUnderstand();
    renderFlowBranches();
    renderFlowFreeze();
  }
  renderFlowRecord();
  updateFlowButtons();
  if (state.preparationJourneyStep !== null) {
    const business = state.preparationJourneyStep === "problem";
    flowSetHidden("flow-source-section", business);
    for (const id of ["flow-prompt-section", "flow-understand-section", "flow-branches-section", "flow-spec-section", "flow-apply-section", "flow-result-section"]) {
      if (!business) flowSetHidden(id, true);
    }
    if (business) flowSetHidden("flow-prompt-section", false);
  }
}

function bindFlowEvents() {
  const bind = (id, action) => byId(id)?.addEventListener("click", action);
  bind("flow-root-button", flowBindRoot);
  bind("flow-add-csv", () => flowAddFile("csv"));
  bind("flow-add-xlsx", () => flowAddFile("xlsx"));
  bind("flow-add-folder", () => flowAddFile("folder"));
  bind("flow-add-workbook", flowAddOpenWorkbook);
  bind("flow-ingest-sample", () => flowIngest("discover"));
  bind("flow-ingest-full", () => flowIngest("compute"));
  bind("flow-analyze-button", flowUnderstand);
  bind("flow-plan-button", flowPlanDraft);
  bind("flow-branches-button", flowExecuteBranches);
  bind("flow-freeze-button", flowFreeze);
  bind("flow-approve-button", flowApprove);
  bind("flow-apply-button", flowApply);
  bind("flow-record-build", flowCreateRecord);
  bind("flow-record-reload", flowReadRecord);
  bind("flow-record-save", flowPersistRecord);
  bind("flow-record-download", flowDownloadRecord);
  byId("flow-control-ack")?.addEventListener("change", updateFlowButtons);
  byId("flow-approve-check")?.addEventListener("change", updateFlowButtons);
  byId("flow-disclosure")?.addEventListener("change", updateFlowButtons);
  bind("flow-reset-button", flowReset);
  bind("flow-understand-toggle", () => {
    const toggle = byId("flow-understand-toggle");
    const expanded = toggle.getAttribute("aria-expanded") !== "true";
    toggle.setAttribute("aria-expanded", String(expanded));
    flowSetHidden("flow-understand-body", !expanded);
  });
  byId("prompt")?.addEventListener("input", flowInvalidatePlans);
}

