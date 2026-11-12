"""Live red-team harness for the planner adapter.

Usage (from backend/, keys in backend/.env):
    REDTEAM_FILES="a.pdf,b.pdf,notes.txt" python scripts/planner_redteam.py scripts/redteam_prompts.txt

prompts.txt: one case per line, `expect<TAB>prompt` where expect is `refuse` or `plan`.
Set REDTEAM_FILES="a.pdf,b.pdf,notes.txt" to emulate the workspace listing the backend passes.
Lines starting with # are ignored. Prints a verdict table and exits 1 on any miss.
"""

import logging
import os
import sys
import time

import sys
sys.path.insert(0, ".")

from app.core.config import settings
from app.integrations.llm.gateway import LLMGateway
from app.integrations.planner.llm_planner import LLMPlanner, PlanningRefused

logging.basicConfig(level=logging.ERROR)


def main(path: str) -> int:
    planner = LLMPlanner(LLMGateway(settings), settings)
    # The backend passes the workspace listing; emulate it (REDTEAM_FILES="a.pdf,b.pdf").
    files = [f for f in os.getenv("REDTEAM_FILES", "").split(",") if f]
    context = {"workspace_files": files} if files else None
    misses = 0
    for line in open(path, encoding="utf-8"):
        line = line.rstrip("\n")
        if not line or line.startswith("#"):
            continue
        expect, prompt = line.split("\t", 1)
        try:
            out = planner.plan(prompt, context)
            got, detail = "plan", " | ".join(" ".join(n.params.argv) for n in out.graph.nodes)
            detail = f"conf={out.graph.intent.confidence:.1f} {out.provider}: {detail}"
        except PlanningRefused as e:
            got, detail = "refuse", f"[{e.source}] {e.reason[:110]}"
        except Exception as e:
            got, detail = "error", f"{type(e).__name__}: {str(e)[:110]}"
        ok = got == expect
        misses += not ok
        print(f"{'OK  ' if ok else 'MISS'} want={expect:6} got={got:6} | {prompt[:60]!r}\n      {detail[:170]}")
        time.sleep(0.5)
    print(f"\n{misses} miss(es)")
    return 1 if misses else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
