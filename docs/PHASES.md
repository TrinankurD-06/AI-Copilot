# AI Copilot — Phased Roadmap

Ten working days, 12–21 November 2026, for the backend MVP. Effort is for one backend developer, with coding-agent help. Dates slip together if a phase overruns; the order does not change.

| Phase | Days | Dates | Goal |
|---|---|---|---|
| 0. Foundation | 1–2 | 12–13 Nov | A backend that boots, tests that run, a proven sandbox, an agreed contract |
| 1. Plan pipeline | 3–4 | 14–15 Nov | A prompt becomes a validated, risk-scored, stored plan |
| 2. Approve and execute | 5–7 | 16–18 Nov | Approved nodes run in the sandbox and results are stored |
| 3. Integrate and harden | 8–10 | 19–21 Nov | End-to-end tests, planner and UI integration, demo |
| 4. Expansion | after | — | Should and Could features |

## Phase 0 — Foundation

- **Features:** M1, groundwork for M2, M9 and M12.
- **Deliverables:**
  - App starts; central router; `/health`; CORS.
  - Alembic sees the models; `alembic check` is clean.
  - Test harness with a test database.
  - Sandbox spike: a script and tests proving each isolation limit.
  - Graph contract v1 drafted and sent to the planner owner.
  - Seed script for user, environment and safety rules.
  - Setup instructions in the README.
- **Entry criteria:** Compose PostgreSQL runs and the initial migration applies (done).
- **Exit criteria:** `uvicorn` starts; `pytest` runs and passes; every sandbox control in `ARCHITECTURE.md` has a passing test or a recorded replacement; the contract draft is with the planner owner.
- **Key risk:** a sandbox control does not behave as designed on Docker Desktop. **Spike:** T-006, on day 1.
- **Effort:** 2 days.

## Phase 1 — Plan pipeline

- **Features:** M2, M3, M4, M5, M6, M11 (plan read).
- **Deliverables:** sessions endpoint; planner port and mock; graph validator; action registry; risk engine; plan persistence; task endpoints working; plan read endpoint; state machine and audit helper.
- **Entry criteria:** Phase 0 exit criteria met.
- **Exit criteria:** `POST /tasks` with a mock prompt returns a stored plan; `GET /plans/{id}` returns nodes and edges with risk and state; an invalid graph and a critical node are each rejected with reasons; unit tests cover every validation and risk rule.
- **Key risk:** the contract is not agreed in time. **Mitigation:** build against the draft and the mock; contract changes are then limited to the schema module and its tests.
- **Effort:** 2 days.

## Phase 2 — Approve and execute

- **Features:** M7, M8, M9, M10, M11 (executions and logs).
- **Deliverables:** approval endpoints; sandbox runner; orchestrator worker; plan start endpoint; observations; execution and log read endpoints; startup sweep.
- **Entry criteria:** plans are stored with correct node states.
- **Exit criteria:** a plan with a low-risk node and an approval-required node runs to completion after approval; a rejected node never runs; a timed-out command is killed and recorded; no containers remain afterwards.
- **Key risk:** ordering or locking bugs in the orchestrator. **Mitigation:** a single worker, one state-machine module, and tests for diamond-shaped and failing graphs before wiring the real sandbox.
- **Effort:** 3 days.

## Phase 3 — Integrate and harden

- **Features:** M12, integration support.
- **Deliverables:** end-to-end tests (happy path, rejected plan, rejected approval, timeout); real planner adapter connected behind the port, if delivered; fixes from frontend integration; README and demo script.
- **Entry criteria:** the pipeline works with the mock planner.
- **Exit criteria:** every success criterion in `BRIEF.md` is demonstrated; the full test suite passes from a clean checkout; the demo script runs start to finish.
- **Key risk:** the real planner returns graphs that fail validation. **Mitigation:** the mock stays as the demo fallback, selectable by config.
- **Effort:** 3 days, including a buffer of about one day.

## Phase 4 — Expansion (after the MVP)

In suggested order:

1. CI workflow (S4).
2. Cancel and retry (S1, S2).
3. `write_file` action (S6).
4. Per-user permissions (S3).
5. Live updates over SSE (S5).
6. Separate worker process with a queue, and Redis for runtime state.
7. Approval payload hash column (coordinated migration).
8. Authentication on the API.

Each item needs its own entry in `DECISIONS.md` before work starts if it changes the schema or a contract.

## What to cut if time runs short

In this order, none of which breaks the core demonstration:

1. `GET /logs` filtering and pagination (return the latest entries only).
2. Per-plan workspace volume (each node gets only a `tmpfs`; nodes then share no files).
3. Real planner integration (demo on the mock).
