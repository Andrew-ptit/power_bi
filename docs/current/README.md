# Current contracts

These documents define current contracts and planned capabilities; their individual versions are independent of the application release. [Current status](CURRENT_STATUS.md) separates implemented behavior from pending verification. Historical reports are available through Git.

| Contract | Purpose |
|---|---|
| [Architecture](ARCHITECTURE.md) | Package boundaries, compatibility and refactor decisions |
| [Current status](CURRENT_STATUS.md) | Current tests, deferred work and release readiness |
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

Annotation editing, semantic/runtime diff and persisted runtime summary are cancelled. Null placeholders in the persisted schema remain compatibility fields, not a future feature promise.
