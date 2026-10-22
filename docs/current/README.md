# Current contracts

These documents define supported behavior and planned work; their individual versions are independent of the application release. Read release evidence before interpreting a delivery status.

| Contract | Purpose |
|---|---|
| [Architecture](ARCHITECTURE.md) | Package boundaries, compatibility and refactor decisions |
| [Product](SPEC.md) | Original local Excel/PBIP requirements and FR/AC IDs |
| [Excel track](EXCEL_MCP_SPEC.md) | Task-pane/MCP boundaries; unbuilt MCP work remains unbuilt |
| [Power Query](PQ_CODE_M_SPEC.md) | Advanced M and Typed runtime safety |
| [Problem Chain](PROBLEM_CHAIN_SPEC.md) | Immutable history, CAS, staging/cache and branch contracts |
| [Step diagnostics](TYPED_STEP_DIAGNOSTICS_SPEC.md) | Sampling, staging and diagnostics gates |
| [BPMN](BPMN_MODEL.md) | Task IDs and process model |
| [Delivery ledger](IMPLEMENTATION_PLAN.md) | Work packages and historical exit gates |
| [Source UI](UI_RAW_DATA.md) | Local source-only UI |
| [Connector](W21_EXCEL_TASKPANE_SPEC.md) | Fixture connector and sideload acceptance criteria |

Annotation editing, semantic/runtime diff and persisted runtime summary are cancelled. Null placeholders in the persisted schema remain compatibility fields, not a future feature promise.
