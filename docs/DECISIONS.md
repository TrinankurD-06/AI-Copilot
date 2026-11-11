# AI Copilot — Decision Log

Each entry records what was decided, what else was considered and why. Add a new entry rather than rewriting an old one; mark the old one "superseded by D-xx".

| ID | Date | Decision | Status |
|---|---|---|---|
| D-01 | 2026-11-11 | MVP actions are sandboxed commands | Accepted |
| D-02 | 2026-11-11 | Keep the existing repository structure | Accepted |
| D-03 | 2026-11-11 | Modular monolith with an in-process worker | Accepted |
| D-04 | 2026-11-11 | Defer Redis; edges live in `plans.graph_snapshot` | Accepted |
| D-05 | 2026-11-11 | No database schema change in the MVP | Accepted |
| D-06 | 2026-11-11 | A task is an intent plus its latest plan | Accepted |
| D-07 | 2026-11-11 | Risk is computed only by the backend | Accepted |
| D-08 | 2026-11-11 | A critical or invalid node rejects the whole plan | Accepted |
| D-09 | 2026-11-11 | Nodes are immutable after validation | Accepted |
| D-10 | 2026-11-11 | Execution starts only on an explicit request | Accepted |
| D-11 | 2026-11-11 | Commands are argument lists, never shell strings | Accepted |
| D-12 | 2026-11-11 | One container per node, fixed sandbox profile | Accepted |
| D-13 | 2026-11-11 | Planner sits behind a port, with a mock | Accepted |
| D-14 | 2026-11-11 | ORM models stay in `app/database/models.py` | Accepted |
| D-15 | 2026-11-11 | Compose PostgreSQL defaults to port 5432, overridable | Accepted |
| D-16 | 2026-11-11 | Unmatched actions default to medium risk | Accepted |

## D-01 — MVP actions are sandboxed commands
- **Alternatives:** remote operations over SSH or cloud APIs; domain-specific business actions.
- **Why:** it proves the whole governed pipeline with the smallest surface. Remote operations add credential handling and real blast radius; domain actions need a domain to be defined first.

## D-02 — Keep the existing repository structure
- **Alternatives:** a generic `/src`, `/tests`, `/config`, `/scripts` layout.
- **Why:** the current structure was merged as the team's canonical layout, and changing it would touch every team member's area. The generic layout maps onto it: source is `backend/app`, tests are `backend/tests`, configuration is `backend/app/core` and `.env.example`, scripts are `backend/scripts`.

## D-03 — Modular monolith with an in-process worker
- **Alternatives:** a Redis queue with a separate worker process; LangGraph orchestration.
- **Why:** fastest to build and simplest to operate for a single-user demo. See the matrix in `ARCHITECTURE.md`. The executor is behind an interface so the queue option remains open.
- **Consequence:** one node runs at a time, and a process restart interrupts a run (handled by the startup sweep).

## D-04 — Defer Redis; edges live in `plans.graph_snapshot`
- **Alternatives:** keep runtime graph edges in Redis, as planned earlier.
- **Why:** the snapshot column already exists, one store means one source of truth, and Redis would add a service, a client and outage handling inside ten days with no benefit at this scale.
- **Revisit when:** execution moves to a separate worker or more than one worker runs.

## D-05 — No database schema change in the MVP
- **Alternatives:** add a tasks table, a "running" node state, or a payload hash on approvals.
- **Why:** schema changes need a coordinated migration and review. The existing tables can represent everything the MVP needs.
- **Consequence:** some concepts are derived rather than stored (D-06) and some guarantees rest on rules rather than columns (D-09).

## D-06 — A task is an intent plus its latest plan
- **Alternatives:** a dedicated tasks table.
- **Why:** follows from D-05. `task_id` is the intent ID and status is derived from the plan (mapping in `ARCHITECTURE.md`).

## D-07 — Risk is computed only by the backend
- **Alternatives:** accept a risk level proposed by the planner.
- **Why:** planner output is untrusted. A model saying an action is safe must never be what makes it runnable.

## D-08 — A critical or invalid node rejects the whole plan
- **Alternatives:** block only the offending node and run the rest.
- **Why:** failing closed is simpler to reason about and to test, and a plan that contains a forbidden step is suspect as a whole.

## D-09 — Nodes are immutable after validation
- **Alternatives:** allow edits during approval with re-validation; store a payload hash on the approval.
- **Why:** it ties an approval to exactly what was shown without a schema change. Changing an action means rejecting and re-planning.
- **Revisit when:** modify-on-approval is wanted; that needs the hash column.

## D-10 — Execution starts only on an explicit request
- **Alternatives:** run low-risk nodes automatically as soon as the plan is validated.
- **Why:** the operator sees the graph before anything runs, which is the product's central promise, at the cost of one extra endpoint.

## D-11 — Commands are argument lists, never shell strings
- **Alternatives:** accept a shell command string.
- **Why:** removes shell injection and makes the allowlist check on the executable meaningful.

## D-12 — One container per node, fixed sandbox profile
- **Alternatives:** one long-lived container per plan with commands executed inside it.
- **Why:** a fresh container per node gives clean limits, a clean timeout and no state leaking between nodes. Files shared between nodes go through the per-plan volume only.

## D-13 — Planner sits behind a port, with a mock
- **Alternatives:** call the planner directly from the task service.
- **Why:** the backend can be built and tested without the real planner, and the planner owner can change the implementation without backend changes as long as the contract holds.

## D-14 — ORM models stay in `app/database/models.py`
- **Alternatives:** move them to the empty `app/models/` folder.
- **Why:** they already work where they are, and moving them changes imports across the persistence layer for no gain. `app/models/` stays unused.

## D-15 — Compose PostgreSQL defaults to port 5432, overridable
- **Alternatives:** default to another port.
- **Why:** matches the existing configuration defaults. A machine where 5432 is taken sets `POSTGRES_PORT` in a local `.env`.

## D-16 — Unmatched actions default to medium risk
- **Alternatives:** default to low; default to critical.
- **Why:** anything the rules do not recognise should need a human, but should not make every new plan fail outright.
