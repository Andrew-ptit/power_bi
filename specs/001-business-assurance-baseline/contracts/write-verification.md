# Proposed write-verification và read-only recovery contract

Thiết kế để thay sample-only success claims, chưa triển khai. Normal approved write và read-only recheck là hai hành động khác nhau. Recovery không gọi mutation, runner, M, Save hoặc XML write.

## Expected evidence và chính sách so sánh

Expected luôn từ complete validated result/package đã được duyệt và bound exact artifact/workbook/target. Policy `excel-values-v1` theo data-model.md; không dùng preview sample hoặc nguồn đã thay để sinh expected mới. So sánh từng cell theo ordered full explicit rectangle gồm header; actual no-formula, actual marker cho managed sheet, actual Table structure và old tails theo scope.

Date/numeric comparison dùng transport types/epoch đã định nghĩa, không business tolerance. Null-tail logical rows không suy từ usedRange. Input/source ô ngoài scope tuyệt đối không được reader/writer sửa. New helper cần resources qua owner hiện hành, no private paths/credentials/cells logged.

## Ownership

AssistantSessionStore giữ attempt và approval consumed. TypedPlanStore giữ final/restore attempt, staging/cache promotion. AdvancedAttemptStore mới giữ preview-sheet và source-Apply attempt riêng, dưới session state lifecycle; HTTP không giữ state. Preview M risk consent không thay source-Apply consent. Không reuse Typed approval cho Advanced.

## Proposed protocol

| Operation | Route dự kiến | Guards/response |
|---|---|---|
| Bind expected/prepare PQ | POST `/api/pq/write-attempts/prepare` | mode, revision/preview binding, target, current export/identity, user action; dispatch owning store; no write payload trước consent/preflight |
| Begin read-only observation | POST `/api/excel/write-checks/begin` | exact attempt hoặc lookup binding nếu lost response; trả observationId, nonce, expected scope/dimensions và bounded chunk limit; không approval |
| Submit measured chunk | POST `/api/excel/write-checks/chunks` | observationId/nonce, exact target, ordinal/rectangle, actual literal values, formula status; so với expected slice; ≤10000 cells và ≤1 MiB JSON/current cap nhỏ hơn |
| Finish observation | POST `/api/excel/write-checks/finish` | exact coverage, current actual identity/marker/structural/tail checks; trả `matches/mismatch/incomplete/insufficient`, evidence hash và observedAt |
| Normal completion | Existing Assistant `/apply` receipt hoặc Typed `/applies/complete`; Advanced POST `/api/pq/write-attempts/complete` | Yêu cầu same-attempt completed full observation, exact bindings và consumed write authority. Old metadata-only/boolean proof không đủ |
| Inspect attempt | POST `/api/excel/write-checks/inspect` | Returns redacted descriptor/stored historical receipt/current last observation; không trả raw expected, không write/approval/cache mutation |

All new paths giữ auth/origin/session/independent slots/state lock. Read-only observation nhận measured values qua local HTTP để compare, không gửi Codex. Chunks được consume so sánh rồi bỏ, không giữ accumulated actual table. State-changing completion locked; replay success chỉ trả stored receipt, không lặp cache promotion. Legacy authorizing requests phải đạt new full-verification precondition, không fallback sample-only.

Observation có mục đích `normalCompletion` hoặc `recheck`. `recheck` không được dùng thay completion hoặc promote cache/Record. Full matched hiện tại sau unknown cho phép người dùng biết nội dung đang có, không tự biến attempt cũ thành lịch sử applied mới. Server completed trước lost response có thể cung cấp historical receipt; cần current read để nói target hiện tại khớp.

## Attempt/budget constraints

≤5 outstanding expectations, ≤64 MiB canonical expected/session owner, một active observation/attempt; không tăng existing result/cache/HTTP caps. Expected không còn hoặc budget không đủ thì trước write block; recovery sau expiry trả insufficient. Không evict active uncertain expected để tạo quyền ghi mới. Close session/workbook switch invalidate authority; pane giữ cảnh báo bound workbook khi còn sống, không giấu bằng refresh message.

Chunk gap/overlap/reordered/duplicate, invalid nonce/target/identity, expiry, dropped final receipt hoặc missing special-cell support đều không có fully matched verdict. Server TTL không gia hạn absolute deadline. Concurrent Excel/Codex job fail-fast như hiện có. Không hứa transactional snapshot nếu user/coauthor sửa cell trong lúc verify; detected change làm incomplete/mismatch.

## Mutation latch và failure copy

Set `mutationPossible` trước mutation dispatch, không sau context.sync. Bao gồm worksheet import/add/delete, copy, Table resize, clear-tail và marker changes. Exact proof error trước dispatch mới nói chưa ghi. Sau dispatch hoặc không biết: ghi rõ có thể partial và target; disable duplicate write/action.

Advanced preview catch không được nói “chưa ghi gì” nếu sheet import/update đã có thể bắt đầu. Source Apply unknown giữ scope gốc kể cả active sheet thay đổi. Read-only recheck không đòi old source fingerprint bằng pre-write fingerprint vì source overwrite là intentional; compare expected new values và cleared tails, đồng thời không ghi chỗ khác.

## Reopen và persistence

Attempt expected/results không persist trong XML/history/localStorage. Reopen chỉ metadata không cấp proof/approval. No reliable expected → insufficient; không rerun M, không tự dựng full Record từ recordHash. Old completed immutable Record giữ nguyên; current mismatch là observation riêng, không sửa lịch sử.

## Checkout consent

Quay về dialog nêu revision + sheet kết quả có marker sẽ thay + cache/full checks; không dùng lời “chỉ chuyển HEAD”. Consent bind resolved destination; đích đổi sau consent thì không ghi. Keep/delete descendants là lựa chọn riêng. Cache stale/miss thì normal Preview→explicit approval; không auto-write. View zero Office/coordinator writes.

## Negative/positive acceptance

S04–S09 và S19–S21: row25/column201 tamper, exact decimals, false-vs-zero, typed number-vs-text, blank/null tail, date epoch, formula, marker duplicate/rename/delete, Table totals/resize/collision, stale source, 5/6 attempts, 64MiB boundary, chunk/body bounds, busy/expired/nonce, response loss at each boundary và replay. Assert no new writes/runner/cache promotion trong recheck; prior cache/history/source preserved. Advanced live acceptance giữ Deferred tới khi được mở lại, không suy từ fake Office/Typed live pass.
