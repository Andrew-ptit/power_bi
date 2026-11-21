# Assistant — Audit findings

Ngày rà: 30/10/2026. Phạm vi: engine WL1–WL7 và hành trình synthetic hiện có.
Trạng thái phần behavior guards: **BLOCKED** — một gap enum thật còn đỏ; không sửa engine.
Đây là engine kiểm bằng test tất định; không phải xác nhận runtime Excel/Power BI.

## Cách rà và giới hạn

Đã đọc master plan, CONTRACT_AUDIT, spec §9/§13, các boundary WL1–WL7 và test hiện có.
Chỉ thêm test hành vi, không đổi test cũ/golden/engine. Không chạy fast gate; LEAD sở hữu gate.
Các test mới nằm trong `tests/contracts/test_assistant_behavior_guards.py`, class
`AssistantBehaviorGuardTests`; các tên rút gọn trong bảng đều thuộc class đó.
SHA-256/mtime được kiểm trên toàn bộ cây fixture trong một lượt FIN + SALES hoàn chỉnh.
AST guard quét mọi `sources/assistant_*.py`; hiện có 17 module, không khóa tổng số module tương lai.
Read-only nguồn không cấm dựng ZIP/XML trong bộ nhớ hoặc file kết quả trong temp đã dọn sạch.

## Tám loại gap bắt buộc

| Loại | Kết luận | Bằng chứng đã có | Test mới và phần được bổ sung | Ưu tiên |
|---|---|---|---|---|
| Enum đóng | **partial; gap thật** | Pack schema, step graph, Spec/Record labels đã chặn nhiều enum sai; các test kiểm output quan hệ chỉ bảo vệ enum do builder sinh | `test_closed_status_provenance_label_and_step_kind_reject_invalid_values` xanh; `test_invalid_relationship_cardinality_is_rejected_before_brief` **FAIL** khi đưa cardinality ngoài enum qua boundary WL2→WL3 với hash đã tính lại | P1 |
| Hash tamper | already covered; thêm guard xuyên boundary | `tests.unit.test_assistant_record.AssistantRecordTests.test_cached_hash_tamper_is_rejected_by_freshness_and_marking`; `tests.unit.test_assistant_spec.AssistantSpecTests.test_hash_recomputes_independently_and_binds_step_content` | `test_tamper_changes_artifact_hash_and_cached_record_or_spec_is_stale`: sửa metadata làm hash khác, cached Record/Spec không được dùng lại | P1 |
| Offline | already covered từng slice; thêm AST guard toàn bộ module | `tests.contracts.test_assistant_wl7.AssistantWL7ContractTests.test_engine_offline_no_ai_com_or_file_io_during_record_build` chỉ quét hai module WL7; các WL trước có guard riêng | `test_all_assistant_source_modules_stay_stdlib_offline_and_never_open_for_write`: import stdlib/local, cấm network/external/subprocess và open mode ghi trên toàn bộ module Assistant nguồn | P1 |
| Determinism | already covered từng artifact; thêm pipeline chung | `tests.unit.test_assistant_preview.AssistantPreviewTests.test_preview_hash_and_workbook_are_deterministic_with_recompute`; `tests.unit.test_assistant_reconcile.AssistantReconcileTests.test_hash_determinism_recompute_and_input_immutability`; các WL có test hash riêng | `test_all_seven_artifacts_repeat_with_identical_hashes_and_content`: hai build độc lập FIN/SALES, so toàn nội dung và hash snapshot/understand/brief/spec/preview/reconcile/record | P1 |
| Nguồn bất biến | already covered nguồn được dùng; thêm cây fixture đầy đủ | `tests.contracts.test_assistant_e2e.AssistantEngineE2ETests.test_t_e2e_fin_full_wl1_through_record_bytes_and_source_preservation`; case SALES tương ứng | `test_complete_positive_journeys_preserve_every_fixture_byte_and_mtime`: trước–sau cả hai positive journey, toàn bộ 104 fixture giữ SHA-256/mtime/size, danh sách file không tăng/giảm; helper E2E kiểm temp/read-back | P1 |
| Không số bịa | already covered; thêm equality guard duyệt mọi formula-bearing value trong Brief | `tests.contracts.test_assistant_wl3.AssistantWL3ContractTests.test_af_bf_br_001_pack_has_no_money_and_every_numeric_value_has_engine_formula`; `tests.unit.test_assistant_pack.AssistantPackTests.test_numeric_money_numeric_strings_and_money_prose_are_rejected` | `test_every_formula_value_matches_engine_and_packs_cannot_supply_money`: formulaId có registry, value đúng Decimal/đơn vị engine; pack chứa tiền bị từ chối; Record không có verified label/status | P1 |
| Gate duyệt | already covered; thêm kiểm liền mạch | `tests.unit.test_assistant_reconcile.AssistantReconcileTests.test_forged_passed_flags_and_hash_do_not_bypass_arithmetic_gate`; `tests.unit.test_assistant_approval.AssistantApprovalTests.test_resetting_consumed_flag_cannot_replay_original_or_preconsume_copy` | `test_failed_reconciliation_and_reused_approval_do_not_grant_write`: drift làm assert_approvable trả AF_RECONCILE_FAILED; capability đã consume trả AF_SPEC_STALE | P1 |
| Fail-closed | already covered negative FIN-NOPACK và unresolved; positive FIN generic fallback chưa có | `tests.contracts.test_assistant_e2e.AssistantEngineE2ETests.test_t_e2e_nopack_fin_is_fail_closed_as_user_confirmed_without_fake_finance`; `test_t_e2e_unknown_three_unresolved_policies_never_freeze_or_choose_for_user` cùng class | `test_nopack_and_unresolved_policies_fail_closed_without_finance_fabrication`: pack không khớp bị chặn trước measure_set; không tự tạo choice; freeze vẫn blocked | P1 |

## Gap chặn: cardinality ngoài enum được chấp nhận

Case đầy đủ:
`tests.contracts.test_assistant_behavior_guards.AssistantBehaviorGuardTests.test_invalid_relationship_cardinality_is_rejected_before_brief`.

Reproduction chỉ trên bản sao in-memory của FIN runtime:

1. Thay `understand.relationships[0].cardinality` bằng token synthetic `INVALID_CARDINALITY`.
2. Tính lại `understandHash` qua hàm engine; hash mới khác hash cũ và khớp payload đã đổi.
3. Gọi `build_brief` với raw/snapshot/pack hợp lệ còn nguyên.
4. Guard yêu cầu `InputError` hoặc `ValueError`; engine hiện trả Brief thành công.

Đây là thiếu semantic validation tại boundary nhận artifact WL2, không phải hash tamper thông thường.
Hash xác nhận nội dung đã được bind, không chứng minh cardinality thuộc tập 1:1/1:N/N:1/N:N.
Probe độc lập trên `structural_roles(snapshot, key_report)` cũng nhận relationship có cardinality sai.
Test mới tập trung boundary công khai WL2→WL3, không thay helper bằng validator trong test để che gap.

Rủi ro: artifact tự khai cardinality ngoài hợp đồng có thể đi tiếp vào Brief thay vì fail-closed.
Chưa có bằng chứng đây là ghi nguồn hoặc khai thác từ network; không suy rộng thành claim bảo mật.
Các builder hiện sinh cardinality hợp lệ và test output đang xanh; điều đó không bảo vệ input enum sai.
Theo CONTRACT_AUDIT §3.1 và master §1/§3.1, giữ nguyên failure và dừng trước phase UI.
Không được tự sửa WL2/WL3 trong phạm vi audit hoặc nới assertion thành “chấp nhận được”.

## Kết quả focused của B và lịch sử

Suite được chạy qua unittest loader/runner trong bộ nhớ, cùng module với lệnh sau;
stdout đã thay repo root bằng `[repo]`, không in source cell hoặc đường dẫn riêng tư:

```text
py -m unittest tests.contracts.test_assistant_behavior_guards -v
```

Lượt đầu: 9 run, 7 pass, 1 fail, 1 error, 0 skip, 4.357s.
Error thuộc test mới của B: gọi `consume_approval` với ba positional args trong khi API nhận một.
Đã sửa đúng lời gọi API trong test mới, giữ nguyên mọi assertion; không đổi engine hoặc test cũ.
Cardinality failure được giữ nguyên ở cả hai lượt.

Lượt cuối sau sửa lỗi lời gọi test:

```text
FAIL: test_invalid_relationship_cardinality_is_rejected_before_brief
(tests.contracts.test_assistant_behavior_guards.AssistantBehaviorGuardTests)
tests/contracts/test_assistant_behavior_guards.py:81
with self.assertRaises((InputError, ValueError)):
AssertionError: (<class 'pbip_assistant.core.errors.InputError'>, <class 'ValueError'>) not raised
----------------------------------------------------------------------
Ran 9 tests in 4.014s

FAILED (failures=1)
```

Kết quả: run=9, pass=8, fail=1, error=0, skip=0.
Chưa phát hiện bằng chứng test cũ sai; phát hiện trên là hành vi chưa được chặn ở engine.
Kết quả combined/fast do LEAD chạy và ghi trong `reports/audit/REPORT.md`.

## Các giới hạn đã biết không được trình bày thành covered đầy đủ

- FIN Record giữ 5 assumptions từ Brief runtime theo chốt người dùng; golden WL7 vẫn có 8.
- NOPACK trên đầy đủ FIN là negative fail-closed đã chốt; generic fallback dương tính chưa triển khai.
- Không có bằng chứng UI/Office.js/Excel/Power BI runtime hoặc AI live từ các test audit này.
- AST guard chỉ kiểm mã module nguồn Assistant, không phải sandbox cho mọi lời gọi tương lai.
- Case đọc-only dùng fixture synthetic, không dùng workbook người dùng đang mở.

## Câu hỏi cho người review

Phase audit không được sửa engine. Cần một thay đổi được cho phép riêng để bổ sung semantic enum
validation tại boundary WL2→WL3 rồi chạy lại guard hiện giữ đỏ. Trước khi có thay đổi đó, phase này
**BLOCKED**, không chuyển UI hoặc seam AI; không gán “100% covered”.
