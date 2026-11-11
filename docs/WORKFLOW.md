# AI Copilot — Workflows

## Development workflow

This follows `CONTRIBUTING.md`; that file wins if the two ever disagree.

1. Update local `main`.
2. Create a short-lived branch: `feature/...`, `fix/...`, `infra/...` or `docs/...`.
3. Make one logical change. Keep the pull request small (about 300 changed lines or fewer where possible).
4. Run the checks below locally.
5. Commit with a subject in the form `type: summary`, for example `feature: add graph validator`.
6. Push the branch and open a pull request into `main` using the template.
7. Request review from both teammates. One approval is required.
8. Squash-merge, delete the branch, update local `main`.

Never push to `main`. Never commit `.env` files, credentials, virtual environments or generated files.

### Local checks before every pull request

Run from `backend/` with the virtual environment active and the Compose PostgreSQL running:

| Check | Command |
|---|---|
| Unit and API tests | `python -m pytest` |
| Sandbox tests (need Docker running) | `python -m pytest -m docker` |
| Migrations apply | `python -m alembic upgrade head` |
| Models match migrations | `python -m alembic check` |
| App imports and starts | `python -m uvicorn app.main:app` |

### Testing layers

| Layer | What it covers | Needs |
|---|---|---|
| Unit | Graph validation, risk scoring, state transitions | Nothing external |
| API | Routes, status codes, error shape | Test database |
| Sandbox | Each isolation limit, timeout, cleanup | Docker engine |
| End to end | Submit, approve, start, run, read result; and a denied path | Both |

Tests use a separate database, `ai_copilot_test`, on the same Compose PostgreSQL, created by the test fixtures.

### Changes that need coordination first

- Anything in `backend/app/database/models.py` or a new Alembic migration.
- The planner graph contract.
- Any REST path or response shape the frontend uses.

Raise these with the affected teammate before opening the pull request, and name them in the "Dependencies / coordination" section of the template.

### CI

Not part of the Must list. When added (feature S4), it runs lint and the unit and API tests on every pull request.

## Runtime workflows

### A. Submit a task

1. The UI calls `POST /sessions` once and keeps the `session_id`.
2. The UI calls `POST /tasks` with the prompt.
3. The backend stores the intent, gets a graph from the planner, validates it and scores risk.
4. The UI receives `task_id`, `plan_id` and a status of `PLANNED`, or `FAILED` with reasons.
5. The UI calls `GET /plans/{plan_id}` and draws the graph with each node's risk and state.

### B. Approve or reject

1. The UI shows nodes in `waiting_approval` with their action, parameters and risk.
2. The approver calls `POST /nodes/{node_id}/approval`.
3. Approved: the node becomes `ready`. Rejected: the node and everything depending on it become `skipped`.

### C. Execute

1. The operator calls `POST /plans/{plan_id}/start`.
2. The worker runs each ready node whose dependencies have completed, one at a time, in a fresh container.
3. A node still waiting for approval holds back only the nodes that depend on it.
4. The UI polls `GET /plans/{plan_id}` for states and `GET /nodes/{node_id}/executions` for output.
5. The plan ends as `completed` or `failed`.

### D. A plan the backend refuses

1. Validation or risk scoring finds an invalid or critical node.
2. The plan is stored as `rejected` with the reasons; no node becomes runnable.
3. The task reads as `FAILED`, and the reasons are in the response and the audit log.

### E. Restart during a run

1. On startup the backend finds executions still marked `running`.
2. Each is set to `failed` with a message saying the process restarted; its node is failed and dependents skipped.
3. Leftover sandbox containers are removed.

## Team workflow

| Area | Owner | Others may |
|---|---|---|
| Backend: API, services, validation, execution, persistence, Compose | Backend owner: Trinankur (`TrinankurD-06`) | Review; request changes through an issue or a pull request comment |
| Planner and LLM integration | Planner owner: Samarth (`sam987-dek`) | Review |
| Frontend | Frontend owner: Sohit (`Sohit007-SST`) | Review |

Each person changes only their own area. Work that crosses a boundary is done through a contract, not by editing the other person's code.

### Handoffs

| Handoff | From | To | Gate |
|---|---|---|---|
| Graph contract v1 | Backend owner drafts | Planner owner agrees | Agreed by end of day 2 |
| REST response shapes | Backend owner drafts | Frontend owner agrees | Agreed by end of day 3 |
| Mock planner available | Backend | Frontend and planner | End of day 3 |
| Real planner adapter | Planner owner | Backend integrates behind the port | Days 8–9 |
| Running backend for UI integration | Backend | Frontend | From day 5, complete by day 8 |

### Review gates

- Every pull request: one teammate approval.
- Contract changes after they are agreed: approval from the teammate who depends on the contract.
- Sandbox profile changes: the pull request must include the isolation tests passing.

### Working with coding agents

- An agent works on one task from `TASKS.md` at a time, on its own branch.
- It reads `ARCHITECTURE.md` and `DECISIONS.md` first and does not change a recorded decision without the owner's agreement.
- It reports status precisely: implemented, tested, or verified end to end.
- It does not push or open a pull request unless asked, and never touches files outside the task's listed modules.
