# Current contracts

These documents define current contracts and planned capabilities; their individual versions are independent of the application release. [Current status](CURRENT_STATUS.md) separates implemented behavior from pending verification. Historical reports are available through Git.

| Contract | Purpose |
|---|---|
| [Architecture](ARCHITECTURE.md) | Package boundaries, compatibility and refactor decisions |
| [Current status](CURRENT_STATUS.md) | Current tests, refactor decisions, deferred work and release readiness |
| [DeepSeek handoff](DEEPSEEK_HANDOFF.md) | Current source snapshot, constraints and next work |
| [History security](HISTORY_SECURITY.md) | Persisted XML/JSON trust boundaries and PC-SEC rules |
| [Task-pane UI](TASKPANE_UI.md) | Current UI-001 through UI-007 behavior and accessibility |
| [Product](SPEC.md) | Original local Excel/PBIP requirements and FR/AC IDs |
| [Excel track](EXCEL_MCP_SPEC.md) | Task-pane/MCP boundaries; unbuilt MCP work remains unbuilt |
| [Power Query](PQ_CODE_M_SPEC.md) | Advanced M and Typed runtime safety |
| [Problem Chain](PROBLEM_CHAIN_SPEC.md) | Immutable history, CAS, staging/cache and branch contracts |
| [Step diagnostics](TYPED_STEP_DIAGNOSTICS_SPEC.md) | Sampling, staging and diagnostics gates |
| [BPMN](BPMN_MODEL.md) | Task IDs and process model |
| [Delivery map](IMPLEMENTATION_PLAN.md) | Active work-package IDs and acceptance gates |
| [Source UI](UI_RAW_DATA.md) | Local source-only UI |
| [Connector](EXCEL_CONNECTOR_CONTRACT.md) | Fixture connector and sideload acceptance criteria |
| [Assistant fixtures](ASSISTANT_FIXTURES.md) | Fixture pack + test contract cho luồng Trợ lý (WL1–WL7) |
| [Assistant WL1](ASSISTANT_WL1.md) | Get Data: 4 connector, snapshot/fingerprint, guard read-only |
| [Assistant WL2](ASSISTANT_WL2.md) | Hiểu: vai/khoá/quan hệ, fan-out, assumption ledger |
| [Assistant WL3](ASSISTANT_WL3.md) | Khung + Decision Brief: DomainPack, findings, SP A/B, scenarios |
| [Assistant WL4](ASSISTANT_WL4.md) | Chốt + Compile: decisions, ExecutionSpec, invalidate |
| [Assistant WL5](ASSISTANT_WL5.md) | Preview + Reconcile: values-only, control total, bridge, gate duyệt |
| [Assistant WL6](ASSISTANT_WL6.md) | Duyệt + Ghi: approval một lần, values-only, read-back, không tự Save |
| [Assistant WL7](ASSISTANT_WL7.md) | Verify + Record: delta, Decision Record, stale |
| [Assistant traceability](ASSISTANT_TRACEABILITY.md) | Đối chiếu 47 FR và 45 test ID với case thực và phần còn thiếu |
| [Assistant audit findings](ASSISTANT_AUDIT_FINDINGS.md) | Tám nhóm guard hành vi và lỗi được giữ để chặn phase sau |

Annotation editing, semantic/runtime diff and persisted runtime summary are cancelled. Null placeholders in the persisted schema remain compatibility fields, not a future feature promise.
