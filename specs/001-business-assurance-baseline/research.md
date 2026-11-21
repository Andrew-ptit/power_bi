# Research: bằng chứng và lựa chọn thiết kế

Ngày 2026-11-05. Đọc docs/code và research agent chỉ đọc; không app/test/Excel/network execution. Line numbers là navigation khi lập plan, không là runtime evidence. Các Decision là lựa chọn thiết kế từ baseline được yêu cầu lập plan, chưa là capability hiện có.

## R01 — State/authority giữ trong owner

**Evidence**: ARCHITECTURE.md Boundaries; `sources/assistant_session.py` sở hữu lock/freeze/approve/apply; `powerquery/typed/store.py` giữ HEAD/staging/cache. `coordinator/endpoints/advanced.py` chưa có attempt lifecycle tương đương.

**Decision**: dùng owner hiện có; Advanced thêm `powerquery/advanced/attempts.py` được session manager tạo/close. Pure contract helpers không giữ state. HTTP thin adapter.

**Rationale**: giữ atomic guards, independent slots và auth boundary.

**Alternatives considered**: DB/global singleton (đổi storage không cần); trộn Advanced vào Typed approvals (trộn policy); browser-only authority (không đủ server binding).

## R02 — User review thresholds

**Evidence**: `adapters/codex/assistant_plan.py:283–314` nhận nonnegative tolerance và fan-out 1..100000; `assistant_reconcile_v2.py:234–285` default tolerance 0,01; UI `taskpane.js:1499–1592` chưa cho review đủ policy.

**Decision**: canonical explicit resolutions, unit/rationale/policy hash đúng branch/snapshot. Draft numbers được xem nhưng chưa là passed-under-reviewed-policy. Không mặc định tolerance cho measure chưa xác định đơn vị; thiếu R2 dùng acknowledgement riêng.

**Rationale**: threshold AI không là mức sai lệch người dùng chấp nhận.

**Alternatives considered**: mọi đơn vị dùng 0,01; domain pack tự duyệt; bỏ A/B exploration. Cả ba không đáp ứng đúng baseline.

## R03 — Artifact v3, giữ hash v2

**Evidence**: `assistant_freeze.py:13–16,63–95` closed shape/hashBasis; `assistant_record_v2.py` exact decisions; `assistant_approval.py` boundTo đúng hai fields. Typed history `document.py` đóng schema và required-null cancelled fields.

**Decision**: Spec/Decisions/Record 3.0 builders/validators riêng; reviewHash nằm trong decisionsHash và fingerprint. Approval shape không đổi. V2 historical đọc/export nguyên vẹn, không fill defaults. Production write không fallback v2 để vượt review. Reconciliation 1.0 chỉ giữ nếu không đổi closed shape/semantics; unit/rationale nằm trong review.

**Rationale**: artifact schema độc lập app release; không migrate history.

**Alternatives considered**: optional fields chèn vào v2 (phá hash); thêm reviewHash vào mọi approval (không cần transitive); upgrade tự động (không consent).

## R04 — Câu hỏi bắt buộc là structured state

**Evidence**: `assistant_plan.py:107–137` chấp nhận omission; `assistant_session.py:275–295` giữ plan khi schema bằng; Problem Chain PC-BR-028 có gating.

**Decision**: category/required/status/explicit definition, “chưa rõ” unresolved. Unknown planner question default blocking; advisory có lý do, critical categories không tự hạ. Full-data questions/evidence đổi thì review hết hiệu lực dù schema không đổi.

**Rationale**: schema và số học không định nghĩa gross/net.

**Alternatives considered**: chặn mọi note (quá mức); nonempty text là đủ (bỏ lọt); AI quyết user đã hiểu (sai authority).

## R05 — Keep-unmatched bằng helpers hiện có

**Evidence**: `typed/model.py:46–107`, `typed/validation.py:454–473`, `typed/compiler.py:36–61`; merge `typed_local/executor.py:205–233`, null test `tests/unit/test_typed_local.py:271`.

**Decision**: helper pair fresh: missing-left/missing-right khác nhau, present giống nhau; composite join nguyên keys+helper; remove helper cuối. Typed addColumn/if/compare/boolean/literal đủ, không index/raw M. Visible revision mới; count caps.

**Rationale**: bảo toàn original keys và sáu join kinds, không sentinel collision.

**Alternatives considered**: sentinel đè keys; filter để giả preserve-unmatched; operation mới; silent compiler change. Loại vì mất dữ liệu hoặc phá compatibility.

**Definition**: missing=null hoặc text rỗng; whitespace chỉ missing khi user chọn trim; composite thiếu nếu bất kỳ phần thiếu. 0/false/"0" không thiếu; không tự bỏ leading zeros/đổi collation. Alternative key cần cột cụ thể, không fuzzy guessing.

## R06 — Full package expectation và bounded comparison

**Evidence**: Assistant `taskpane.js:951–1006` full compare; PQ writers `4733–4945` chỉ 21 rows/200 columns; Typed `store.py:932–949` reported metadata; `advanced/runtime.py:_static_values_payload` validated full package. Null-tail code cố ý không dùng usedRange.

**Decision**: expected từ full package/result; comparison version `excel-values-v1`, streamed actual coverage; marker thật khi có/no-formula/tails/structural checks. Explicit logical rectangle cho null-tail. Không coi expected dimensions là observed dimensions.

**Rationale**: lỗi ngoài mẫu phải bị bắt; transport types cần luật viết trước code.

**Alternatives considered**: sample checksum; one huge request; binary .xlsx equality. Không chứng minh đủ nội dung hoặc vượt bounds.

## R07 — Unknown/recovery không retry

**Evidence**: Assistant complete ở `assistant_session.py:687` handoff-only; `taskpane.js:1010–1066` consumed latch; Advanced catch `5016–5018` phủ lỗi sau import. Assistant XML metadata-only.

**Decision**: monotonic attempt và read-only observation; expected bounded session-local; lookup lost response theo exact binding. Completion idempotent trả stored receipt, không re-promote cache. Historical receipt khác current verification. TTL/reopen không restore authority. Advanced source recheck target mới/tails, không đòi pre-write fingerprint sau intentional overwrite.

**Rationale**: fetch fail không chứng minh chưa ghi; metadata không đủ khôi phục expected.

**Alternatives considered**: tự retry; persist raw expected; rerun M để recover. Đều trái boundary hoặc khác result đã duyệt.

## R08 — Limits theo action

**Evidence**: `taskpane.js:317–319,463–475` cumulative workbook rows/cells/512 cols; `assistant_plan.py:63,277` 200 cols/20 steps; `assistant_session.py:671` output includes header; `advanced/runtime.py:27–35` result/diagnostic caps.

**Decision**: giữ cap, sửa scope, show eligibility trước approval và recheck lúc write. Không áp cumulative workbook limit vào file/folder như một thay đổi ngầm.

**Rationale**: input 100000×4 không có nghĩa output cùng kích thước ghi được vì header.

**Alternatives considered**: nâng cap; truncate result; chỉ chặn lúc Apply. Không phù hợp.

## R09 — Consent/reuse/trust

**Evidence**: PC-BR-017/022, PC-FR-021; `taskpane.js:2847–2855,3436–3446`; renderFlowRecord luôn nói workbook chưa lưu dù không đo user Save.

**Decision**: checkout consent target-impact; five trust axes; Save unknown nếu chưa đo. Typed reuse vẫn full preflight/Preview/approval; Assistant metadata-only; M values-only. Unsupported ngoài catalog không tự chuyển mode.

**Alternatives considered**: bỏ cache restore; auto-refresh; một green badge. Hoặc mở lại quyết định đã có hoặc thêm scope.

## R10 — Evidence boundaries

**Evidence**: CURRENT_STATUS.md:16–23 parity/Assistant Office.js unverified; tests/live/README.md synthetic Gate_Run_Id, Advanced M Deferred; live drivers/support hiện có.

**Decision**: automated/runtime parity/real Codex/real Office.js tách riêng. Synthetic disposable workbook only. Advanced live vẫn Deferred, không Passed nhờ Typed tests. Không bump app/npm/HTTP/manifest ở planning hoặc trước required release gates.

**Alternatives considered**: user workbook; fake receipt như live evidence; giao implementer verification cho user. Đều trái project rules.

## Closure

Unknown kỹ thuật đã có lựa chọn thiết kế; không còn NEEDS CLARIFICATION. Advanced live defer, recovery hết TTL không bảo đảm và backlog định kỳ là scope, không phải task ngầm được mở. Budget mới là giới hạn thiết kế bảo thủ cần đo, không là performance đã đạt. Product contracts được cập nhật trong task tương lai; chưa sửa canonical docs ở lượt này.
