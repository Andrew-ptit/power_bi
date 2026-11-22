/* Boot: event binding, coordinator session and startup. */
"use strict";
function bindEvents() {
  bindFlowEvents();
  byId("tab-assistant-button").addEventListener("click", () => switchTab("assistant"));
  byId("tab-pq-button").addEventListener("click", () => switchTab("pq"));
  byId("pq-propose-button").addEventListener("click", proposePQ);
  byId("pq-preview-button").addEventListener("click", previewPQ);
  byId("pq-apply-source-button").addEventListener("click", applyPQPreviewToSource);
  byId("pq-code").addEventListener("input", invalidatePQPreview);
  byId("pq2-mode-button").addEventListener("click", () => switchPQMode("typed"));
  byId("pq-advanced-mode-button").addEventListener("click", () => switchPQMode("advanced"));
  byId("pq2-plan-button").addEventListener("click", createTypedPlan);
  byId("pq2-preview-button").addEventListener("click", previewTypedPlan);
  byId("pq2-approve-button").addEventListener("click", approveAndApplyTyped);
  byId("pq2-cancel-preview-button").addEventListener("click", cancelProblemPreview);
  byId("pq2-diagnostic-confirm").addEventListener("click", confirmTypedStepDiagnostic);
  byId("pq2-diagnostic-cancel").addEventListener("click", cancelTypedStepDiagnostic);
  byId("pq2-add-step").addEventListener("click", () => openTypedEditor());
  byId("pq2-editor-cancel").addEventListener("click", () => setHidden("pq2-editor", true));
  byId("pq2-editor-save").addEventListener("click", saveTypedEditor);
  byId("pq2-operation").addEventListener("change", renderTypedParameterFields);
  byId("pq2-inputs").addEventListener("change", renderTypedParameterFields);
  byId("pq2-prompt").addEventListener("input", () => {
    invalidateTypedPlan("Typed request changed. Create a new plan.");
    updatePQButtons();
  });
  byId("pq2-correction-submit").addEventListener("click", submitTypedCorrection);
  byId("pq2-correction-prompt").addEventListener("input", updatePQButtons);
  byId("pq2-correction-prompt").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && event.ctrlKey && !event.altKey && !event.metaKey && !event.shiftKey && !event.isComposing && !event.repeat && !byId("pq2-correction-submit").disabled) {
      event.preventDefault();
      byId("pq2-correction-submit").click();
    }
  });
  byId("pq2-prompt").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && event.ctrlKey && !event.altKey && !event.metaKey && !event.shiftKey && !event.isComposing && !event.repeat && !byId("pq2-plan-button").disabled) {
      event.preventDefault();
      byId("pq2-plan-button").click();
    }
  });
  byId("pq-prompt").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && event.ctrlKey && !event.altKey && !event.metaKey && !event.shiftKey && !event.isComposing && !event.repeat && !byId("pq-propose-button").disabled) {
      event.preventDefault();
      byId("pq-propose-button").click();
    }
  });
  byId("refresh-button").addEventListener("click", async () => {
    await refreshWorkbook();
    if (state.problemChainSupported) await hydrateProblemChain();
  });
  byId("prompt").addEventListener("input", updatePromptCount);
  bindFlowPromptShortcut();
  byId("pqpc-history-toggle")?.addEventListener("click", () => {
    setProblemChainHistoryExpanded(!state.problemChainHistoryExpanded);
  });
  byId("pqpc-clear-history")?.addEventListener("click", async () => {
    if (state.busy || !state.problemChainDocument || !state.problemChainDocument.revisions?.length) return;
    const count = state.problemChainDocument.revisions.length;
    const confirmed = await requestPQConfirmation(state.workbook?.name || "workbook", {
      title: "Xóa sạch toàn bộ lịch sử Problem Chain?",
      detail: `Thao tác này sẽ xóa toàn bộ ${count} revision và nhánh khỏi workbook. Workbook sẽ trở về trạng thái chưa có Problem Chain. Hãy Save workbook sau khi xóa để lưu lại.`,
      continueLabel: "Xóa sạch lịch sử",
    });
    if (!confirmed) return;
    await clearProblemChainHistory();
  });
  byId("pqpc-new-problem")?.addEventListener("click", () => {
    openProblemBranchEditor(state.problemChainDocument ? "newRoot" : "new");
  });
  byId("pq2-revision-info")?.addEventListener("click", () => {
    const panel = byId("pq2-info-panel");
    if (!panel) return;
    const isHidden = panel.hidden;
    panel.hidden = !isHidden;
    byId("pq2-revision-info")?.setAttribute("aria-expanded", String(!isHidden));
  });
  byId("pqpc-create-button").addEventListener("click", createProblemContinuation);
  byId("pqpc-branch-submit").addEventListener("click", submitProblemBranchDraft);
  byId("pqpc-branch-cancel").addEventListener("click", closeProblemBranchEditor);
  byId("pqpc-branch-prompt").addEventListener("input", handleProblemPromptInput);
  byId("pqpc-branch-prompt").addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || !event.ctrlKey || event.altKey || event.metaKey || event.shiftKey || event.isComposing || event.repeat) return;
    event.preventDefault();
    submitProblemBranchDraft();
  });
  byId("pqpc-source-changed").addEventListener("change", markProblemSourceChanged);
  byId("pqpc-prompt").addEventListener("input", updateProblemChainButtons);
  byId("pqpc-prompt").addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || !event.ctrlKey || event.altKey || event.metaKey || event.shiftKey || event.isComposing || event.repeat) return;
    const button = byId("pqpc-create-button");
    if (button.disabled) return;
    event.preventDefault();
    button.click();
  });
  document.addEventListener("click", (event) => {
    if (!event.target?.closest?.(".menu")) {
      document.querySelectorAll?.(".menu-pop").forEach((pop) => {
        pop.hidden = true;
      });
    }
  });
  updatePromptCount();
  switchPQMode("typed");
  updatePQButtons();
}

function closeCoordinatorSession() {
  if (!state.token) return;
  if (typeof state.preparationDetach === "function") {
    try {
      const detaching = state.preparationDetach();
      if (detaching) { Promise.resolve(detaching).catch(() => {}); return; }
    } catch { return; }
  }
  try {
    fetch("/api/session/close", {
      method: "POST",
      headers: {"Content-Type": "application/json", "X-Local-Token": state.token},
      body: "{}",
      keepalive: true,
    }).catch(() => {});
  } catch {
    // Page teardown is best-effort; never block Excel from closing the pane.
  }
}

let startupInProgress = false;
async function connectTaskpane() {
  if (startupInProgress) return;
  startupInProgress = true;
  const reconnect = byId("assistant-reconnect");
  if (reconnect) { reconnect.disabled = true; reconnect.hidden = true; }
  for (const id of ["assistant-choose-folder", "assistant-choose-workbook"]) byId(id).disabled = true;
  byId("assistant-source-message").textContent = "Đang kết nối với Excel…";
  clearError();
  try {
    await bootstrap();
  if (!window.Office) {
    throw Object.assign(new Error("Trang này phải được mở từ Excel task pane, không phải browser thường."), {code: "OFFICE_NOT_READY"});
  }
  const info = await Office.onReady();
    if (info.host !== Office.HostType.Excel) {
      throw Object.assign(new Error("Add-in hiện không chạy trong Excel."), {code: "OFFICE_NOT_READY"});
    }
    state.officeReady = true;
    if (!state.preparationReadCapability || !window.ReqwisePreparation || !window.ReqwisePreparationRuntime
        || !window.ReqwisePreparationBridge || !window.ReqwiseAssistantEntry || !window.ReqwiseAssistantBrowser) {
      throw Object.assign(new Error("Chưa tải đủ bộ hỗ trợ trợ lý. Bấm Kết nối lại; nếu vẫn lỗi, mở lại panel."), {code: "ASSISTANT_STARTUP_FAILED"});
    }
    if (state.preparationReadCapability && window.ReqwisePreparation && window.ReqwisePreparationRuntime) {
      const preparationPost = async (action, fields) => {
          const response = await fetch("/api/preparation/" + action, {method: "POST",
            headers: {"Content-Type": "application/json", "X-Local-Token": state.token},
            body: JSON.stringify({schemaVersion: 1, action, ...fields}), keepalive: action === "detach"});
          const result = await response.json();
          if (!response.ok) {
            const code = result.error?.code;
            const detail = code === "INVALID_REQUEST" ? "Không thể đọc lựa chọn hiện tại. Hãy chọn lại nguồn dữ liệu."
              : code === "DP_SOURCE_STALE" ? "Nguồn đã thay đổi hoặc không đọc được. Hãy chọn lại."
              : result.error?.detail || result.detail || "Không thể xử lý chuẩn bị dữ liệu.";
            throw Object.assign(new Error(detail), {code});
          }
          return result;
        };
      let preparation = null, bridge = null, browser = null;
      const updatePreparation = value => preparation?.acceptState(value);
      const unavailable = () => { throw flowFailure("DP_UNSUPPORTED_PRESERVATION", "Bộ hỗ trợ chuẩn bị dữ liệu chưa được cập nhật. Hãy mở lại panel."); };
      preparation = window.ReqwisePreparation.mount({document, environment: window,
        runtime: window.ReqwisePreparationRuntime, post: preparationPost, deferOpen: !!window.ReqwiseAssistantEntry,
        scanWorkbook: options => bridge ? bridge.scanWorkbook(options) : unavailable(),

        onDirty: () => { window.ReqwiseAssistantEntryUI?.invalidate(); flowInvalidateSourceAuthority(state.flow); renderFlow(); },
        onBusy: value => window.ReqwiseAssistantEntryUI?.setBusy(value)});
      if (window.ReqwisePreparationBridge && preparation) {
        bridge = window.ReqwisePreparationBridge.create({post: preparationPost, runtime: window.ReqwisePreparationRuntime,
          backupEnabled: state.preparationBackupEnabled,
          environment: window, getState: () => preparation.wizard.state, setState: updatePreparation});
        state.preparationDetach = () => preparation.wizard.state ? bridge.detach() : null;
      }
      if (window.ReqwiseAssistantEntry && preparation) {
        const measureUnderstand = async (mode) => {
          window.ReqwiseAssistantEntryUI.setBusy(true);
          try {
            const review = await bridge.businessSourcesFromScan();
            const handoff = await preparationBusinessHandoff(review, mode);
            // H21: a compute ingest measures every scanned row; the existing
            // full re-read path still serves the sample fallback.
            const result = await flowUnderstand();
            return {...handoff, ...result, modelView: state.flow.modelView,
              measuredOn: state.flow.measuredOn || result.modelView?.measuredOn || "full"};
          } catch (error) {
            renderFlow();
            throw error;
          } finally {
            window.ReqwiseAssistantEntryUI.setBusy(false);
            renderFlow();
          }
        };
        window.ReqwiseAssistantEntryUI = window.ReqwiseAssistantEntry.mount({document,
          onBrowse: options => options?.reopen ? browser?.reopen() : browser?.open(),
          // Scan every worksheet; a blank active sheet does not exclude data on other sheets.
          selectWorkbook: async () => true,
          restartSession: () => bridge ? bridge.restart() : unavailable(),
          canRestartAfterPartial: state.preparationBackupEnabled === false,
          scanWorkbook: options => bridge ? bridge.scanWorkbook(options) : unavailable(),
          onUnderstand: async () => {
            // H19/H20: measure on compute by default; a bounded limit falls
            // back to discover exactly once and keeps the sample warning.
            try {
              return await measureUnderstand("compute");
            } catch (error) {
              if ((error.code === "AF_UNDERSTAND_LIMIT" || error.code === "REQUEST_LIMIT")
                  && !window.ReqwiseAssistantEntryUI.state().measureFailed) {
                return await measureUnderstand("discover");
              }
              throw error;
            }
          },
          showProblem: async () => {
            if (!state.flow.modelView || !state.flow.understand) {
              throw flowFailure("AF_STAGE_INVALID", "Đo cấu trúc dữ liệu trước khi sang Đề bài.");
            }
          },
          invalidateBusiness: () => { flowInvalidateSourceAuthority(state.flow); renderFlow(); },
          onStepChange: step => { state.preparationJourneyStep = step; renderFlow(); }});
        if (window.ReqwiseAssistantUnderstand && window.ReqwiseAssistantModelDiagram) {
          state.understandView = window.ReqwiseAssistantUnderstand.mount({document,
            getState: () => ({modelView: state.flow.modelView, questions: state.flow.questions,
              answers: state.flow.answers, message: ""}),
            setAnswer: (questionId, option) => {
              if (state.flow.busy) return;
              state.flow.answers[questionId] = option;
              flowInvalidatePlans();
              state.understandView?.render();
              renderFlow();
            },
            onContinue: () => window.ReqwiseAssistantEntryUI?.stepToProblem?.(),
            diagram: window.ReqwiseAssistantModelDiagram});
        }
        if (window.ReqwiseAssistantBrowser && bridge) {
          browser = window.ReqwiseAssistantBrowser.create({document, bridge,
            onImported: receipt => window.ReqwiseAssistantEntryUI?.imported(receipt)});
        }
      }
    }
    await refreshWorkbook();
    if (flowCapabilityAvailable()) {
      await flowLoadState();
    }
    await hydrateProblemChain();
    byId("assistant-source-message").textContent = "";
  } catch (error) {
    byId("assistant-source-message").textContent = error.message || "Chưa khởi tạo được trợ lý. Bấm Kết nối lại để thử lại.";
    byId("assistant-workbook-summary").textContent = "Workbook · Chưa kết nối";
    for (const id of ["assistant-choose-folder", "assistant-choose-workbook"]) byId(id).disabled = true;
    if (reconnect) reconnect.hidden = false;
    showError(error.code || "ASSISTANT_STARTUP_FAILED", error.message);
  } finally {
    startupInProgress = false;
    if (reconnect) reconnect.disabled = false;
  }
}

async function start() {
  bindEvents();
  byId("assistant-reconnect")?.addEventListener("click", connectTaskpane);
  await connectTaskpane();
}

document.addEventListener("DOMContentLoaded", start);
if (typeof window !== "undefined" && window.addEventListener) {
  window.addEventListener("pagehide", closeCoordinatorSession);
}
