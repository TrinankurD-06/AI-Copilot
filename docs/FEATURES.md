# AI Copilot — Features and MVP Definition

Backend features only. Complexity: S is up to half a day, M is about one day, L is two days or more.

## MVP definition

The smallest set that proves the core value: **a prompt becomes a validated graph, risky nodes wait for a human, approved nodes run in a locked-down container, and the result and audit trail are stored and readable.**

The MVP is every item under **Must**. It supports one action type, `run_command`.

### The `run_command` action

| Parameter | Rule |
|---|---|
| `argv` | List of strings, 1–32 items, each at most 1024 characters. Never a shell string. |
| `timeout_s` | Integer, default 30, maximum 120 |

`argv[0]` must be on the allowlist held in the safety rules. The command runs in the pinned sandbox image.

## Must

### M1 — Application boots, health route
- **What:** the app starts, mounts one central router, allows the frontend origin through CORS, and exposes `GET /health`.
- **Value:** everyone can run the backend and tell whether it and the database are up.
- **Accepted when:** `uvicorn app.main:app` starts with no import error; `/health` returns API status and database reachability; `/docs` loads.
- **Depends on:** nothing. **Size:** S.

### M2 — Session bootstrap
- **What:** a seed script creates a default user, the sandbox environment row and the starting safety rules. `POST /sessions` creates a session for that user.
- **Value:** tasks can be attached to a valid session without building authentication.
- **Accepted when:** the seed script is idempotent; `POST /sessions` returns a `session_id` that `POST /tasks` accepts; an unknown `session_id` gets a 404.
- **Depends on:** M1. **Size:** S.

### M3 — Task submission
- **What:** `POST /tasks` stores the intent, calls the planner port, validates and scores the graph, and persists the plan and nodes. `GET /tasks` and `GET /tasks/{task_id}` read them back.
- **Value:** the single entry point for the operator.
- **Accepted when:** a valid prompt returns 201 with `task_id`, `plan_id` and status `PLANNED`; a plan that fails validation returns the task with status `FAILED` and the reasons; nothing is stored half-written.
- **Depends on:** M2, M4, M5, M6. **Size:** M.

### M4 — Planner port and mock planner
- **What:** an interface the backend calls to get a graph, plus a deterministic mock implementation. The real planner is plugged in behind the same interface by its owner.
- **Value:** the backend pipeline can be built and tested without waiting on LLM behaviour.
- **Accepted when:** the mock returns a fixed, valid contract-v1 graph for known prompts and a deliberately invalid one for a test prompt; which planner is used is a config setting.
- **Depends on:** the graph contract (see `ARCHITECTURE.md`). **Size:** S.

### M5 — Graph validation
- **What:** checks contract version, node count, unique node keys, known action types, parameter schemas, edges that reference real nodes, and that the graph has no cycles.
- **Value:** planner output cannot reach storage or execution in a shape the system does not understand.
- **Accepted when:** each failure class has a unit test and produces a machine-readable reason; a valid graph passes.
- **Depends on:** M4. **Size:** M.

### M6 — Risk and policy engine
- **What:** computes a risk level for each node from the active safety rules. Low is ready to run, medium and high need approval, critical rejects the whole plan. A node no rule matches is medium.
- **Value:** the decision about what needs a human is made by the backend, never by the planner.
- **Accepted when:** risk supplied by the planner is ignored; each level and the no-match default have unit tests; a critical node rejects the plan before anything is runnable.
- **Depends on:** M5, M2 (seeded rules). **Size:** M.

### M7 — Approval API
- **What:** list nodes waiting for approval; approve or reject one with an optional comment.
- **Value:** the human-in-the-loop gate.
- **Accepted when:** approving moves the node to ready; rejecting moves it and its dependents to skipped; a decision on a node that is not waiting returns 409; every decision writes a `node_approvals` row and an audit row.
- **Depends on:** M6. **Size:** M.

### M8 — Orchestrator
- **What:** after the operator starts a plan, a worker runs ready nodes in dependency order, one at a time, and finishes the plan when no node can still run.
- **Value:** turns an approved graph into ordered execution.
- **Accepted when:** a node never runs before its dependencies complete; a failed node causes its dependents to be skipped; a node waiting for approval blocks only its own dependents; plan status ends as `completed` or `failed`.
- **Depends on:** M5, M6, M7, M9. **Size:** L.

### M9 — Sandbox runner
- **What:** runs one `run_command` in a throwaway container with the profile in `ARCHITECTURE.md`, enforces the timeout, captures output and removes the container.
- **Value:** containment of whatever the plan asks to run.
- **Accepted when:** tests prove no network access, the memory limit, the process limit, a non-root user, a read-only root filesystem and the timeout kill; no container is left behind after success, failure or timeout.
- **Depends on:** nothing (built against Docker directly). **Size:** L.

### M10 — Observations and results
- **What:** each attempt stores an `executions` row and `execution_observations` rows for exit code, stdout, stderr and duration. Output is truncated at a fixed size and marked as truncated.
- **Value:** the operator sees what happened, and it is kept.
- **Accepted when:** all four observations exist for a finished attempt; a timeout is recorded as `timed_out`; oversized output is cut and flagged.
- **Depends on:** M8, M9. **Size:** S.

### M11 — Read APIs for the UI
- **What:** fetch a plan with its nodes and edges, the executions and observations for a node, and audit log entries filtered by entity.
- **Value:** the frontend can draw the graph, show status and show logs by polling.
- **Accepted when:** the response shapes match `ARCHITECTURE.md`; list endpoints are paginated; unknown IDs return 404.
- **Depends on:** M3. **Size:** M.

### M12 — Tests
- **What:** unit tests for validation, risk and state transitions; API tests; sandbox tests; one end-to-end happy path and one denied path.
- **Value:** proof that the trust boundary holds.
- **Accepted when:** `pytest` passes from a clean checkout against the Compose PostgreSQL and a running Docker engine.
- **Depends on:** everything above. **Size:** M.

## Should (only after every Must is done)

| ID | Feature | Value | Accepted when | Depends on | Size |
|---|---|---|---|---|---|
| S1 | Cancel a plan | Operator can stop a run | Running container is killed, remaining nodes skipped, status recorded | M8, M9 | M |
| S2 | Retry a failed node | Recover from transient failure | New execution row with the next `attempt_number`; previous attempt kept | M8 | S |
| S3 | Per-user permissions | Restrict who may run which action type | A denied permission rejects the plan with a reason | M6 | M |
| S4 | CI workflow | Checks run on every PR | Lint and unit tests run in GitHub Actions on PRs | M12 | S |
| S5 | Live updates over SSE | UI updates without polling | A stream emits node and plan state changes | M8 | M |
| S6 | `write_file` action | Plans can prepare inputs for commands | File is written inside the plan workspace only; path traversal is rejected | M9 | M |

## Could

- Redis for runtime graph state and coordination.
- Modify an action during approval, with re-validation.
- Several sandbox images selected per action.
- A payload hash stored on the approval row (needs a coordinated migration).

## Won't for now

- Remote targets (SSH, cloud APIs).
- Authentication and role enforcement beyond the seeded user.
- Multi-tenancy, quotas, billing.
- A separate worker process or job queue.
