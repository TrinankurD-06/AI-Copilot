# Backend

## Testing the planner (planner owner's area)

```
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # then fill GEMINI_API_KEY and/or GROQ_API_KEY
```

Unit tests, no network, fake providers:

```
python -m pytest tests/unit -q
```

Plan a request and see the graph (no Docker needed):

```
python scripts/plan_and_run.py --plan-only --files a.pdf,b.pdf,notes.txt "put the pdfs in a folder called Reports"
```

Replay a file of prompts against the live planner and check each one plans or refuses as expected:

```
REDTEAM_FILES="a.pdf,b.pdf,notes.txt,data.csv,readme.txt,analyze.py,old.tmp" \
  python scripts/planner_redteam.py scripts/redteam_prompts.txt
```

Add your own cases at the bottom of `scripts/redteam_prompts.txt` as `refuse<TAB>prompt` or `plan<TAB>prompt`.

With Docker running, drop `--plan-only` to approve each node and watch it run in the minimal sandbox check. That runner is a prototype; the real sandbox is T-006 / T-202.
