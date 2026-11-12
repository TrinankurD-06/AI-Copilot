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
import pathlib
import sys

sys.path.insert(0, ".")

from app.core.config import settings  # noqa: E402
from app.integrations.llm.gateway import LLMGateway  # noqa: E402
from app.integrations.planner.llm_planner import LLMPlanner, PlanningRefused  # noqa: E402


def write_html(out, prompt: str, path: str) -> None:
    """Self-contained page: a zig-zag SVG diagram of the graph plus the contract JSON."""
    import html
    import json

    g = out.graph
    nodes = list(g.nodes)
    by_key = {n.key: n for n in nodes}
    parents = {n.key: [e.from_ for e in g.edges if e.to == n.key] for n in nodes}

    # depth = longest path from a root; nodes at the same depth share a row
    depth: dict[str, int] = {}
    def d(k):
        if k not in depth:
            depth[k] = 1 + max((d(pk) for pk in parents[k]), default=-1)
        return depth[k]
    for n in nodes:
        d(n.key)
    rows: dict[int, list[str]] = {}
    for n in nodes:
        rows.setdefault(depth[n.key], []).append(n.key)

    W, CARD_W, CARD_H, ROW_H, AMP = 900, 360, 104, 170, 190
    H = 80 + ROW_H * len(rows) + 40
    pos: dict[str, tuple[float, float]] = {}
    for r, keys in sorted(rows.items()):
        anchor = W / 2 + (AMP if r % 2 else -AMP)          # the zig-zag
        span = CARD_W + 40
        x0 = anchor - span * (len(keys) - 1) / 2
        for i, k in enumerate(keys):
            x = min(max(x0 + i * span, CARD_W / 2 + 20), W - CARD_W / 2 - 20)
            pos[k] = (x, 80 + r * ROW_H)

    esc = lambda t: html.escape(t, quote=True)
    def trunc(t, n):
        return t if len(t) <= n else t[: n - 1] + "\u2026"

    svg = [f'<svg viewBox="0 0 {W} {H}" width="100%" xmlns="http://www.w3.org/2000/svg" font-family="ui-sans-serif,system-ui,sans-serif">',
           '<defs>',
           '<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#0f172a"/><stop offset="1" stop-color="#1e1b4b"/></linearGradient>',
           '<linearGradient id="card" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#1e293b"/><stop offset="1" stop-color="#312e81"/></linearGradient>',
           '<linearGradient id="edge" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#22d3ee"/><stop offset="1" stop-color="#a78bfa"/></linearGradient>',
           '<filter id="glow" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="6" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>',
           '<marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="9" markerHeight="9" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="#a78bfa"/></marker>',
           '</defs>',
           f'<rect width="{W}" height="{H}" rx="18" fill="url(#bg)"/>']
    for e in g.edges:
        (x1, y1), (x2, y2) = pos[e.from_], pos[e.to]
        y1 += CARD_H / 2; y2 -= CARD_H / 2
        c = (y2 - y1) * 0.6
        svg.append(f'<path d="M{x1:.0f} {y1:.0f} C{x1:.0f} {y1 + c:.0f} {x2:.0f} {y2 - c:.0f} {x2:.0f} {y2:.0f}" '
                   'fill="none" stroke="url(#edge)" stroke-width="3" marker-end="url(#arrow)" opacity="0.9"/>')
    for n in nodes:
        x, y = pos[n.key]
        left, top = x - CARD_W / 2, y - CARD_H / 2
        cmd = esc(trunc(" ".join(n.params.argv), 46))
        desc = esc(trunc(n.description, 52))
        svg.append(f'<g filter="url(#glow)"><rect x="{left:.0f}" y="{top:.0f}" width="{CARD_W}" height="{CARD_H}" rx="16" fill="url(#card)" stroke="#6366f1" stroke-width="1.5"/></g>')
        step_no = nodes.index(n) + 1
        svg.append(f'<rect x="{left + 16:.0f}" y="{top + 16:.0f}" width="64" height="24" rx="12" fill="#22d3ee"/>'
                   f'<text x="{left + 48:.0f}" y="{top + 33:.0f}" text-anchor="middle" font-size="12" font-weight="800" fill="#0f172a">STEP {step_no}</text>')
        svg.append(f'<text x="{left + 92:.0f}" y="{top + 33:.0f}" font-size="12" fill="#94a3b8">id {esc(n.key)} \u00b7 run_command \u00b7 timeout {n.params.timeout_s}s</text>')
        svg.append(f'<text x="{left + 18:.0f}" y="{top + 64:.0f}" font-family="ui-monospace,Menlo,monospace" font-size="15" font-weight="600" fill="#e2e8f0">$ {cmd}</text>')
        svg.append(f'<text x="{left + 18:.0f}" y="{top + 88:.0f}" font-size="12.5" font-style="italic" fill="#c7d2fe">{desc}</text>')
    svg.append("</svg>")

    step_boxes = []
    for i, n in enumerate(nodes, 1):
        waits = ", ".join(f"step {nodes.index(by_key[k]) + 1} ({k})" for k in parents[n.key]) or "nothing, can start first"
        step_boxes.append(
            f'<div class="step"><div class="head"><span class="badge">STEP {i}</span><span class="meta">id {esc(n.key)}</span></div>'
            f'<div class="cmd">$ {esc(" ".join(n.params.argv))}</div>'
            f'<div class="why">{esc(n.description)}</div>'
            f'<div class="meta">Waits for: {esc(waits)} &middot; timeout {n.params.timeout_s}s</div></div>'
        )
    snapshot = json.dumps(out.snapshot(), indent=2)
    page = f"""<!doctype html><html><head><meta charset="utf-8"><title>Plan graph</title>
<style>body{{font-family:ui-sans-serif,system-ui,sans-serif;max-width:960px;margin:2rem auto;padding:0 1rem;color:#e2e8f0;background:#020617}}
h2{{font-weight:800;letter-spacing:-.02em}} .meta{{color:#94a3b8}} b{{color:#c7d2fe}}
pre{{background:#0f172a;color:#cbd5e1;padding:1rem;overflow:auto;border-radius:10px;border:1px solid #1e293b;font-size:12.5px}}
.step{{background:linear-gradient(135deg,#1e293b,#312e81);border:1px solid #6366f1;border-radius:14px;padding:14px 16px;margin:12px 0}}
.head{{display:flex;gap:12px;align-items:center;margin-bottom:8px}} .badge{{background:#22d3ee;color:#0f172a;font-weight:800;font-size:12px;padding:3px 10px;border-radius:999px}}
.cmd{{font-family:ui-monospace,Menlo,monospace;font-size:15px;font-weight:600;color:#e2e8f0;margin:4px 0}} .why{{font-style:italic;color:#c7d2fe;margin:4px 0}}</style></head><body>
<h2>Plan graph</h2>
<p><b>Request:</b> {esc(prompt)}</p>
<p><b>Intent:</b> {esc(g.intent.summary)} <span class="meta">&middot; confidence {g.intent.confidence:.2f} &middot; {esc(out.provider)}/{esc(out.model)} &middot; {out.latency_ms} ms &middot; {len(nodes)} nodes, {len(g.edges)} edges</span></p>
{"".join(svg)}
<h3>Steps <span class="meta">(one box per node; "waits for" comes from the edges)</span></h3>
{"".join(step_boxes)}
<h3>Contract v1 JSON <span class="meta">(what the backend stores as graph_snapshot)</span></h3>
<pre>{esc(snapshot)}</pre>
</body></html>"""
    pathlib.Path(path).write_text(page, encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("prompt")
    ap.add_argument("--files", default="", help="comma-separated file names to seed the workspace with")
    ap.add_argument("--yes", action="store_true", help="approve every node")
    ap.add_argument("--plan-only", action="store_true")
    ap.add_argument("--html", metavar="FILE", help="write the graph as an HTML page (diagram + contract JSON)")
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
    if a.html:
        write_html(out, a.prompt, a.html)
        print(f"Graph written to {a.html}")
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
    if len(results) < len(g.nodes):
        nxt = g.nodes[len(results)].key
        verdict = f"STOPPED, {nxt} rejected by you" if ok else f"STOPPED, {results[-1].key} {results[-1].status}"
        ok = False
    else:
        verdict = "COMPLETED" if ok else "FAILED"
    print(f"\nRun {runner.plan_id}: {verdict}")
    for r in results:
        print(f"  {r.key}: {r.status} exit={r.exit_code}")
        if r.output.strip():
            print("     output: " + r.output.strip().replace("\n", "\n             ")[:800])
    print("  workspace:", ", ".join(runner.files()) or "(empty)", f"  -> runs/{runner.plan_id}/")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
