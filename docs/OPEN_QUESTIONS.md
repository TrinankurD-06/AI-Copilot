# AI Copilot — Open Questions

Move a question to `DECISIONS.md` once it is answered.

## For the planner owner (Samarth)

| # | Question | Needed by | Default if unanswered |
|---|---|---|---|
| Q-01 | Does graph contract v1 in `ARCHITECTURE.md` work for the planner (field names, node keys, edge format)? | Day 2 | Build against the draft |
| Q-02 | Will the real planner be called in-process (a Python adapter) or over HTTP? What timeout is realistic? | Day 5 | In-process adapter, 30-second timeout |
| Q-03 | Is it acceptable that the port and the mock live in `backend/app/integrations/planner/`, with the real adapter added beside them? | Day 3 | Yes |
| Q-04 | Can the planner restrict itself to the registered action types and the command allowlist, given as part of its prompt or configuration? | Day 5 | Backend rejects anything else |

## For the frontend owner (Sohit)

| # | Question | Needed by | Default if unanswered |
|---|---|---|---|
| Q-05 | Are the REST paths and the plan response shape (nodes plus edges) suitable for React Flow? | Day 3 | Ship as drafted |
| Q-06 | Is polling acceptable for status, or is a live stream needed for the demo? | Day 5 | Polling |
| Q-07 | Which origin and port does the frontend run on locally, for CORS? | Day 1 | `http://localhost:5173` |

## For the backend owner (Trinankur)

| # | Question | Needed by | Default if unanswered |
|---|---|---|---|
| Q-08 | Which executables go on the starting allowlist, and which count as low risk? | Day 2 | `echo`, `ls`, `cat` low; `python` medium |
| Q-09 | Is `python:3.12-alpine` the right sandbox image, or is a smaller or different one preferred? | Day 1 | `python:3.12-alpine` |
| Q-10 | Is there a specific demo scenario the MVP must show? | Day 3 | A three-node plan: one low-risk node, one approved node, one dependent node |

## For the whole team

| # | Question | Needed by | Default if unanswered |
|---|---|---|---|
| Q-11 | Who is the second reviewer when the usual reviewer is unavailable, so merges do not stall? | Day 1 | Either teammate may approve |
| Q-12 | Is the demo run on one machine, or does each person run their own part? | Day 7 | One machine, all three parts local |
| Q-13 | After the MVP, is a `payload_hash` column on `node_approvals` wanted? It needs a coordinated migration. | After day 10 | Not added |

## Known issues to resolve during the build

| # | Issue | Handled by |
|---|---|---|
| I-01 | `app/main.py` imports a module that does not exist, so the app cannot start | T-001 |
| I-02 | `alembic/env.py` does not import the models, so autogenerate proposes dropping every table | T-002 |
| I-03 | Output schemas type timestamps as `str` while models return `datetime` | T-005 |
| I-04 | `CONTRIBUTING.md` and the pull request template contain escaped Markdown and render as plain text on GitHub | Separate docs pull request |
| I-05 | Three sandbox behaviours are assumed, not yet proven (`cap_drop=["ALL"]`, no network interface, non-root write to a volume) | T-006 |
