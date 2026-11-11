# AI Copilot — Backend Task List

Each task is one branch and one pull request. Paths are relative to `backend/`. Every task includes its own tests unless stated. Owner type: **senior** needs design judgement, **standard** is ordinary feature work, **boilerplate** is mechanical.

No task touches `frontend/` or the real planner implementation.

## Phase 0 — Foundation (days 1–2)

### T-001 — Make the app boot with a central router
- **Description:** fix the broken import in `app/main.py`; build `app/api/router.py` to include every API router; add CORS for the local frontend origin.
- **Inputs:** `ARCHITECTURE.md` (REST table).
- **Files:** `app/main.py`, `app/api/router.py`, `app/api/__init__.py`, `app/core/config.py` (allowed origins setting).
- **Accepted when:** `python -m uvicorn app.main:app` starts; `/docs` lists the task routes.
- **Depends on:** none. **Owner:** boilerplate.

### T-002 — Let Alembic see the ORM models
- **Description:** import `app.database.models` in `alembic/env.py` so `Base.metadata` is populated.
- **Inputs:** current `alembic/env.py`.
- **Files:** `alembic/env.py`.
- **Accepted when:** `python -m alembic check` no longer reports removed tables. Any real difference it then reports is listed in the pull request and **not** fixed here.
- **Depends on:** none. **Owner:** boilerplate.

### T-003 — Health endpoint
- **Description:** `GET /health` returning API status and whether a trivial database query succeeds.
- **Files:** `app/api/health.py`, `app/schemas/response.py` if needed.
- **Accepted when:** returns 200 with database `up`; returns 503 with database `down` when PostgreSQL is stopped.
- **Depends on:** T-001. **Owner:** boilerplate.

### T-004 — Test harness
- **Description:** add `pytest` and `httpx` as development dependencies; fixtures that create the `ai_copilot_test` database, apply migrations, and give each test a rolled-back session and an API client; register a `docker` marker.
- **Files:** `requirements-dev.txt`, `pytest.ini`, `tests/conftest.py`, `tests/test_health.py`.
- **Accepted when:** `python -m pytest` passes and never touches the development database.
- **Depends on:** T-002, T-003. **Owner:** standard.

### T-005 — Correct timestamp types in response schemas
- **Description:** several output schemas declare timestamps as `str` while the models return `datetime`; change them to `datetime`.
- **Files:** `app/schemas/graph.py`, `app/schemas/execution.py`, `app/schemas/validation.py`.
- **Accepted when:** a test serialises each output schema from an ORM object without error.
- **Depends on:** T-004. **Owner:** boilerplate.

### T-006 — Sandbox spike
- **Description:** add the `docker` SDK dependency; write a minimal runner and tests that prove each control in the sandbox profile: no network, memory limit, process limit, non-root user, read-only root, dropped capabilities, timeout kill, cleanup, and a non-root write to a per-plan volume.
- **Inputs:** `ARCHITECTURE.md` (sandbox profile).
- **Files:** `requirements.txt`, `app/integrations/docker/sandbox.py` (first version), `tests/sandbox/test_isolation.py`.
- **Accepted when:** every control has a passing test, or a documented replacement recorded in `DECISIONS.md`. No container or volume remains after the tests.
- **Depends on:** T-004. **Owner:** senior.

### T-007 — Graph contract v1 schemas
- **Description:** Pydantic models for the planner graph (contract version, planner metadata, intent, nodes, edges) and the `run_command` parameters; an action registry mapping action type to parameter model.
- **Inputs:** `ARCHITECTURE.md` (planner graph contract). Send the draft to the planner owner.
- **Files:** `app/schemas/graph_contract.py`, `app/validation/actions.py`, `tests/unit/test_graph_contract.py`.
- **Accepted when:** the example graph in `ARCHITECTURE.md` parses; malformed examples fail with field-level errors.
- **Depends on:** T-004. **Owner:** senior.

### T-008 — Seed script
- **Description:** idempotent script that creates the default user, the `local-docker-sandbox` environment and the starting safety rules (command allowlist and risk rules).
- **Files:** `scripts/seed.py`, `tests/test_seed.py`.
- **Accepted when:** running it twice leaves exactly one of each row.
- **Depends on:** T-004. **Owner:** standard.

### T-009 — Setup instructions
- **Description:** write the root and backend READMEs: prerequisites, Compose, virtual environment, `.env`, migrations, seed, run, test.
- **Files:** the repository-root `README.md` and `backend/README.md`.
- **Accepted when:** a teammate follows it on a clean machine without asking questions.
- **Depends on:** T-001 to T-008. **Owner:** boilerplate.

## Phase 1 — Plan pipeline (days 3–4)

### T-101 — State machine and audit helper
- **Description:** one module with `transition_node` and `transition_plan`. Each checks the transition is legal, updates the row and writes an `audit_logs` row in the same transaction.
- **Files:** `app/services/state.py`, `tests/unit/test_state.py`.
- **Accepted when:** every legal transition in `ARCHITECTURE.md` works; every illegal one raises; each writes exactly one audit row.
- **Depends on:** T-004. **Owner:** senior.

### T-102 — Sessions endpoint
- **Description:** `POST /sessions` creating a session for the seeded user.
- **Files:** `app/api/session.py`, `app/services/session_service.py`, `app/schemas/session.py`, `app/api/router.py`.
- **Accepted when:** returns 201 with a `session_id`; returns a clear error if the seed has not been run.
- **Depends on:** T-008. **Owner:** boilerplate.

### T-103 — Planner port and mock planner
- **Description:** the `PlannerPort` interface, a `PlannerResult` type, a mock that maps known prompts to fixed graphs (including one invalid graph and one with a critical node, for tests), and a config setting that selects the planner.
- **Files:** `app/integrations/planner/port.py`, `app/integrations/planner/mock.py`, `app/core/config.py`.
- **Accepted when:** the mock is deterministic; selecting an unknown planner name fails at startup.
- **Depends on:** T-007. **Owner:** standard.

### T-104 — Graph validator
- **Description:** validate a parsed graph: node count, unique keys, known action types, parameter schemas, edge endpoints, no cycles. Returns a list of reasons, never raises on bad input.
- **Files:** `app/validation/graph_validator.py`, `tests/unit/test_graph_validator.py`.
- **Accepted when:** each failure class has a test; a diamond-shaped valid graph passes; a cycle is rejected.
- **Depends on:** T-007. **Owner:** senior.

### T-105 — Risk engine
- **Description:** load active safety rules, match them against each node, return risk level and matched rules. Unmatched nodes are medium. Commands outside the allowlist are critical.
- **Files:** `app/validation/risk_engine.py`, `tests/unit/test_risk_engine.py`.
- **Accepted when:** each level, the no-match default and the allowlist rule have tests; a planner-supplied risk value has no effect.
- **Depends on:** T-007, T-008. **Owner:** senior.

### T-106 — Plan persistence
- **Description:** in one transaction, write the plan, its nodes with initial states, and the graph snapshot with the key-to-ID map. A rejected plan is stored with its reasons and no runnable nodes.
- **Files:** `app/services/plan_service.py`, `tests/test_plan_service.py`.
- **Accepted when:** a failure midway leaves nothing behind; node states match risk levels.
- **Depends on:** T-101, T-104, T-105. **Owner:** standard.

### T-107 — Task service and endpoints
- **Description:** implement `create_task`, `list_tasks`, `get_task`: store the intent, call the planner port, validate, score, persist, and derive task status.
- **Files:** `app/services/task_service.py`, `app/api/task.py`, `app/schemas/task.py`, `tests/api/test_tasks.py`.
- **Accepted when:** the three task routes meet the criteria in feature M3; an unknown session returns 404.
- **Depends on:** T-102, T-103, T-106. **Owner:** standard.

### T-108 — Plan read endpoint
- **Description:** `GET /plans/{plan_id}` returning the plan, its nodes and its edges in the agreed shape.
- **Files:** `app/api/plan.py`, `app/schemas/planner.py`, `app/schemas/graph.py`, `tests/api/test_plans.py`.
- **Accepted when:** the response matches the shape in `ARCHITECTURE.md`; unknown ID returns 404.
- **Depends on:** T-106. **Owner:** boilerplate.

## Phase 2 — Approve and execute (days 5–7), outline

| ID | Task | Files | Accepted when | Depends on | Owner |
|---|---|---|---|---|---|
| T-201 | Approval service and endpoints | `app/services/approval_service.py`, `app/api/approval.py` | Feature M7 criteria met | T-101, T-106 | standard |
| T-202 | Sandbox runner, production version | `app/integrations/docker/sandbox.py` | Returns a result object for success, failure and timeout; output capped; always cleans up | T-006 | senior |
| T-203 | Orchestrator worker | `app/execution/orchestrator.py`, `app/main.py` (lifespan) | Feature M8 criteria met, tested first with a fake runner | T-101, T-202 | senior |
| T-204 | Plan start endpoint | `app/api/execution.py` | Only a `validated` plan can start; returns 409 otherwise | T-203 | boilerplate |
| T-205 | Observations and execution read endpoint | `app/execution/recorder.py`, `app/api/execution.py` | Feature M10 criteria met; attempts readable per node | T-203 | standard |
| T-206 | Audit log endpoint | `app/api/logs.py` | Filter by entity; paginated | T-101 | boilerplate |
| T-207 | Startup sweep | `app/execution/recovery.py`, `app/main.py` | Orphaned executions failed; labelled containers removed | T-203 | standard |

## Phase 3 — Integrate and harden (days 8–10), outline

| ID | Task | Files | Accepted when | Depends on | Owner |
|---|---|---|---|---|---|
| T-301 | End-to-end happy path test | `tests/e2e/test_happy_path.py` | Submit, approve, start, complete, read output | Phase 2 | standard |
| T-302 | End-to-end denied paths | `tests/e2e/test_denied.py` | Rejected plan, rejected approval and timeout each behave as designed | Phase 2 | standard |
| T-303 | Connect the real planner behind the port | `app/core/config.py` only on the backend side | The planner owner's adapter is selectable by config; the mock remains the default | Adapter delivered | standard |
| T-304 | Fixes from frontend integration | As reported | Agreed response shapes hold; issues raised by the frontend owner closed | Phase 2 | standard |
| T-305 | Demo script and final README pass | `scripts/demo.py`, READMEs | Demo runs start to finish on a clean checkout | T-301 | boilerplate |
