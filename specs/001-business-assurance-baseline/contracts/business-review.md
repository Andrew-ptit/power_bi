# Proposed business-review contract

Contract thiết kế, chưa là API triển khai. Current `{error:{code,detail,path}}` envelope, auth/origin/session/slot/state-lock và privacy vẫn áp dụng. Không cấp canonical FR/AC ID trong file này.

## UI contract

Mỗi nhánh hiển thị source/result total, chênh lệch, unit, tolerance, rationale, join rows trước/sau, approved fan-out và full-data per-key metrics. Không biết unit/basis thì ghi không xác định, không default giả. Trước consent hiện `Policy chưa duyệt`; sau consent có thể đánh giá `Đối soát đạt theo policy đã duyệt`. Missing-control ack và final write checkbox vẫn riêng.

Required Q&A có nhãn/ảnh hưởng/câu trả lời rõ; unfinished có thể exploratory preview nhưng disable freeze/approve/write cả UI lẫn handler/backend. Không coi info panel bị collapse là đã giải quyết. “Chưa rõ” vẫn blocker. Full source phát sinh câu hỏi mới làm review stale trước khi chọn/chốt.

## Proposed routes và guards

| Route | Owner | Input chính | Kết quả |
|---|---|---|---|
| POST `/api/assistant/business-reviews` | AssistantSessionStore | expected snapshot/planning/branch/plan/questionSet hashes; resolutions; policy unit/rationale; join choices; explicit acknowledged | Canonical reviewed envelope+reviewHash nếu đủ; stale/unresolved thì current error envelope |
| Existing `/api/assistant/freeze` | Same | Existing reviewed fields + expectedReviewHash của contract mới | Spec3 fingerprint bind Review3; không fallback v2 |
| Existing `/api/assistant/approvals` và `/apply` | Same | Exact Spec3/preview/result bindings | Registry approval một lần theo fingerprint; stale review không được issue/consume |
| Existing Typed new revision/problem paths | Typed/history stores | Explicit reviewed typed changes/prompt clarification | Candidate→XML CAS/read-back→commit; no authority trước commit |

`/business-reviews` dùng state slot, không gọi Codex/Excel. Unknown fields, duplicate/stale question IDs, unsupported categories/policies, nonfinite tolerance, mismatched unit hoặc missing rationale bị chặn. User action đánh dấu authority; payload AI không đủ. New route phải được khai báo trong dispatcher và route fixture, không bỏ guard để test.

Draft `/branches` vẫn có thể tính cho exploration khi unresolved nhưng public eligibility và label phải thể hiện chưa được chốt. Numeric execution cache không cache policy pass; reconciliation luôn bind current reviewed policy. Existing hard cap 1..100000 cho maxFanOut giữ; user không override result/schema/security blockers.

## Versions và compatibility

Spec/Decisions/Record3 có validators riêng. Review1 canonical hash, Spec3 decisionsHash và fingerprint bind transitively. `assistant_approval` giữ boundTo đúng hai fields; binder v3 validate live review trước issue/consume. Legacy v2 read/export/hash tests giữ; new protocol không tự upgrade stored v2 và không authorizes write từ v2 thiếu review.

Bootstrap capability phải nêu hỗ trợ business-review và comparison policy. Client/server mismatch fail closed, hướng dẫn mở đúng bản/review lại; không tự restart coordinator hoặc replay failed POST. Product/API release version không bị bump chỉ vì artifact v3.

## Missing-key proposals trong Typed

Keep-unmatched là visible helper-column operations được xem/chọn như proposal; Typed new immutable revision qua CAS, Assistant new planHash và review. Helpers dùng fresh names và original ordered keys; all six join kinds giữ nguyên compiler semantics. Không index op, sentinel thay business key hoặc hidden mutation. Projected width bao gồm intermediate nested/helper schema; step/column/M-length caps vẫn chặn.

Exclude, alternativeKey, explicitMissingGroup có user choice/rationale; thống kê source missing/nonunique/unmatched/fan-out được hiện trước review. Không lưu raw key group metrics vào history. User choice semantic giữ trong prompt/steps/descriptions hợp lệ, không mở required-null annotation/runtimeSummary.

## Eligibility và labels

| Action | Scope/cap giữ hiện hành | Header |
|---|---|---|
| Assistant Office source read | Tổng selected workbook sources: ≤100000 data rows, ≤400000 data cells, ≤512 columns/source | Không tính header trong read-cell cap hiện có |
| Assistant planning | ≤200 input columns/source, ≤20 steps | Headers là schema, không phải sample row |
| Assistant execution | ≤100000 rows/intermediate, ≤256 columns | Dùng exact schema |
| Assistant result write | `(dataRows+1)×columns ≤400000`; write-ineligible hiện trước freeze/approval | Có header; không cắt result |
| Typed plan | ≤20 sources, ≤50 steps, M ≤16000 chars | Helpers tính vào caps |
| Typed/Advanced result | ≤100000 rows, ≤200 cols, ≤2000000 cells; package/export existing 32 MiB guard | Theo validated package, gồm header trong cell count |
| Typed diagnostics | ≤100000 rows, ≤75 cols, ≤1000000 cells; session cache/staging budgets giữ nguyên | `(rows+1)×cols` |

File/folder ingest vẫn per-file/per-session bytes và existing parser caps; không suy cumulative workbook read cap áp vào mọi loại source. UI sample budgets phân biệt Assistant tổng20 across sources và Typed tối đa20/source; không gọi là mẫu đại diện thống kê.

Five axes: reconciliation `passed/failed/notApplicable/policyUnreviewed`; quality `measuredWarnings/unavailable`; parity `none/runtimeEvidence`; write `notWritten/sampleOnly/fullMatched/unknown/mismatch`; Save `observed/unknown`. Labels không cấp authority, không equate business correctness.

## Contract acceptance

S01–S03, S10–S18 và S25–S27 phải có frontend+backend negative cases, edited same-schema full-source case, existing v2 hashes giữ và no raw logs/history. Không coi drafted contracts là sản phẩm đã đạt.
