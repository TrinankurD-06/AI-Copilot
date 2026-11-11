# AI Copilot — Project Brief

Status: approved 11 November 2026. Scope of this document set: the **backend MVP**. The planner and the frontend are owned by other team members and appear here only as contracts the backend consumes or exposes.

## Problem

LLM agents that execute their own output are fast but unaccountable. Nobody sees what will run before it runs, nothing independent checks it, and there is no reliable record afterwards.

AI Copilot puts a governed pipeline between "the model proposed it" and "it ran". A natural-language request becomes a typed action graph. The backend validates the graph, scores its risk, asks a human to approve where policy requires it, runs approved actions in an isolated container, and records everything.

## Users and stakeholders

| Who | What they need |
|---|---|
| Operator | Submit a task, see the proposed plan, follow its progress and result |
| Approver | See exactly what a risky action will do, then approve or reject it (same person as the operator in the MVP) |
| Admin | Manage safety rules and environments (seeded data in the MVP, no UI) |
| Planner owner | A stable, versioned contract for the graph the planner must return |
| Frontend owner | Stable REST endpoints for plan, approval, status, logs and results |
| Backend owner | A pipeline that is small enough to finish in 10 days and safe enough to demo |

## Goals

1. One task runs end to end: prompt, plan, validation, risk, approval, sandbox execution, observation, persisted result.
2. Planner output is treated as untrusted input and is checked by the backend before anything is stored as runnable.
3. Only validated and approved actions reach the sandbox.
4. The sandbox has explicit isolation, resource and time limits, and is cleaned up after every run.
5. Every state change that matters is written to the audit log.

## Success criteria

The MVP is done when all of these are demonstrated from a clean checkout using documented commands:

- `POST /tasks` with a prompt produces a stored plan whose graph can be fetched.
- A plan containing a disallowed action is rejected before execution, with reasons, and nothing runs.
- A node that needs approval does not run until it is approved, and never runs if it is rejected.
- An approved `run_command` node runs in a container with no network, a memory limit, a CPU limit, a process limit and a timeout, and the container is gone afterwards.
- Exit code, stdout, stderr and duration are stored and retrievable for each attempt.
- An automated end-to-end test covers one happy path and at least one denied path.
- `alembic upgrade head` and the test suite pass against the Compose PostgreSQL.

## Non-goals for the MVP

- Executing against real remote or production systems.
- Real authentication, SSO, multi-tenancy or billing.
- Redis. Runtime graph state is kept in PostgreSQL for now (see `DECISIONS.md`, D-04).
- Editing an action during approval. "Modify" means reject and re-plan.
- More than one or two action types.
- The original budgeting-app domain.
- Cloud hosting. The MVP runs locally with Docker Compose.

## Constraints

- **Time:** 10 days, 12–21 November 2026.
- **Team:** three people with separate ownership (backend, planner, frontend). Each person changes only their own area.
- **Process:** feature branches, pull requests into `main`, one teammate approval, squash merge (`CONTRIBUTING.md`).
- **Stack:** FastAPI, Pydantic, SQLAlchemy, Alembic, PostgreSQL 17, Docker. React and React Flow on the frontend.
- **Schema:** no database schema change in the MVP, so no migration needs cross-team coordination inside the 10 days.
- **Repository:** public. No secrets, `.env` files or virtual environments are ever committed.

## Assumptions

- A mock planner is acceptable until the real planner's contract is agreed and stable.
- A seeded user and a simple session endpoint are enough identity for the MVP.
- One worker thread inside the API process is enough throughput for a demo.
- Every team member can run Docker Desktop locally.

## Core difficulty

The hard part is the trust boundary, not the plumbing. The system must guarantee that only validated, approved, unmodified actions reach the sandbox, and that the sandbox really contains them. The rest is conventional API and persistence work.
