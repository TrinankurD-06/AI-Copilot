"""End-to-end from the terminal: prompt -> plan -> human approval -> sandbox.

    cd backend
    python scripts/plan_and_run.py "Create a folder called Reports and move the PDFs into it"
    python scripts/plan_and_run.py --files a.pdf,b.pdf,notes.txt "count lines in every txt"
    python scripts/plan_and_run.py --yes "..."       # approve every node without asking
    python scripts/plan_and_run.py --plan-only "..." # no Docker needed

Files named with --files are created empty in the plan's workspace (runs/<plan_id>/)
so the demo has something to act on. Needs keys in backend/.env. Execution uses the
minimal prototype in app/integrations/docker/sandbox.py and needs Docker; without it
the plan is printed and nothing runs.
"""

from __future__ import annotations

import argparse
import logging
import sys

sys.path.insert(0, ".")

from app.core.config import settings  # noqa: E402
from app.integrations.llm.gateway import LLMGateway  # noqa: E402
from app.integrations.planner.llm_planner import LLMPlanner, PlanningRefused  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("prompt")
    ap.add_argument("--files", default="", help="comma-separated file names to seed the workspace with")
    ap.add_argument("--yes", action="store_true", help="approve every node")
    ap.add_argument("--plan-only", action="store_true")
    ap.add_argument("-v", action="store_true")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO if a.v else logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    files = [f for f in a.files.split(",") if f]
    planner = LLMPlanner(LLMGateway(settings), settings)
    try:
        out = planner.plan(a.prompt, {"workspace_files": files} if files else None)
    except PlanningRefused as e:
        print(f"REFUSED ({e.source}): {e.reason}")
        return 2

    g = out.graph
    print(f"\nIntent: {g.intent.summary}  (confidence {g.intent.confidence:.2f}, {out.provider}/{out.model}, {out.latency_ms} ms)")
    print("Plan:")
    for n in g.nodes:
        deps = [e.from_ for e in g.edges if e.to == n.key]
        print(f"  {n.key}: {' '.join(n.params.argv)}    # {n.description}" + (f"  after {','.join(deps)}" if deps else ""))
    if a.plan_only:
        return 0

    try:
        from app.integrations.docker.sandbox import SandboxRunner, SandboxUnavailable
        runner = SandboxRunner(settings)
    except Exception as e:  # SandboxUnavailable or missing package
        print(f"\nNot executed: {e}")
        return 0

    for f in files:
        runner.put(f, b"")

    def approve(node) -> bool:
        if a.yes:
            return True
        ans = input(f"\nRun {node.key} [{' '.join(node.params.argv)}]? (y/n) ").strip().lower()
        return ans == "y"

    results = runner.run_graph(g, approve=approve)
    ok = bool(results) and all(r.status == "succeeded" for r in results)
    print(f"\nRun {runner.plan_id}: {'OK' if ok else 'STOPPED'}")
    for r in results:
        print(f"  {r.key}: {r.status} exit={r.exit_code}")
        if r.output.strip():
            print("     output: " + r.output.strip().replace("\n", "\n             ")[:800])
    print("  workspace:", ", ".join(runner.files()) or "(empty)", f"  -> runs/{runner.plan_id}/")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
