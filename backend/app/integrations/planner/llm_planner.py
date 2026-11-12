"""Real planner adapter: one LLM call turns a prompt into a contract-v1 graph.

The intent (summary + confidence) and the node graph come from the same call,
so a plan costs one request. Output is validated against the contract; on a
schema failure the model is asked once to repair its own answer.

Interface matches the planner port described in docs/ARCHITECTURE.md:
    plan(prompt, context) -> PlanOutcome
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from app.integrations.llm.gateway import LLMGateway
from app.integrations.planner.contract import PlannerGraph

log = logging.getLogger(__name__)

PLANNER_NAME = "llm"
PLANNER_VERSION = "0.1.0"

_PROMPT = """You are the planner for an AI copilot. Convert the user's request into a small
graph of sandboxed actions.

Environment: Alpine Linux container, non-root, no network, working directory /workspace.
Only the action types below exist. Commands are argument lists, never shell strings:
no pipes, globs, redirects, `sh -c`, sudo, package managers or network tools.
If a task needs a shell feature, split it into separate nodes instead.

Action types:
{action_types}

Allowed programs for argv[0] (anything else is rejected):
{allowed_commands}

Return ONE JSON object with exactly this shape:
{{
  "contract_version": "1",
  "intent": {{"summary": "<one sentence of what the user wants>", "confidence": <0.0-1.0>}},
  "nodes": [
    {{"key": "n1", "action_type": "run_command", "description": "<why this node>",
      "params": {{"argv": ["<program>", "<arg>"], "timeout_s": 30}}}}
  ],
  "edges": [{{"from": "n1", "to": "n2"}}]
}}

Rules:
- 1 to 20 nodes, unique keys n1, n2, ...; an edge "from" A "to" B means B runs after A.
- Keep the graph minimal. Do not add a node to verify another node.
- Do not include a risk field; risk is decided elsewhere.

User request:
{prompt}"""

_REPAIR = """

Your previous answer did not satisfy the contract.
Previous answer:
{previous}
Errors:
{errors}
Return ONLY a corrected JSON object."""

DEFAULT_ACTION_TYPES = {"run_command": {"argv": "list[str], 1-32 items", "timeout_s": "int, 1-120"}}
DEFAULT_ALLOWED_COMMANDS = ["python", "python3", "ls", "cat", "echo", "mkdir", "cp", "mv", "wc", "head", "tail", "sort", "grep", "find", "touch"]


@dataclass(frozen=True)
class PlanOutcome:
    graph: PlannerGraph
    planner_name: str
    planner_version: str
    latency_ms: int
    provider: str
    model: str

    def snapshot(self) -> dict[str, Any]:
        return self.graph.to_snapshot()


class LLMPlanner:
    name = PLANNER_NAME
    version = PLANNER_VERSION

    def __init__(self, gateway: LLMGateway):
        self.llm = gateway

    def plan(self, prompt: str, context: dict[str, Any] | None = None) -> PlanOutcome:
        """`context` may carry `action_types` (dict) and `allowed_commands` (list)
        so the backend's registry and allowlist reach the model (Q-04)."""
        ctx = context or {}
        rendered = _PROMPT.format(
            action_types=json.dumps(ctx.get("action_types", DEFAULT_ACTION_TYPES), indent=2),
            allowed_commands=", ".join(ctx.get("allowed_commands", DEFAULT_ALLOWED_COMMANDS)),
            prompt=prompt.strip(),
        )

        t0 = time.perf_counter()
        data, completion = self.llm.complete_json(rendered)
        attempts = self.llm.repair_attempts
        for attempt in range(attempts + 1):
            data["planner"] = {"name": self.name, "version": self.version}
            try:
                graph = PlannerGraph.model_validate(data)
                break
            except ValidationError as e:
                if attempt == attempts:
                    raise
                log.warning("planner schema repair %d/%d: %s", attempt + 1, attempts, e.errors()[0]["msg"])
                data, completion = self.llm.complete_json(
                    rendered + _REPAIR.format(previous=json.dumps(data), errors=e)
                )

        latency_ms = int((time.perf_counter() - t0) * 1000)
        log.info("plan ok nodes=%d edges=%d provider=%s latency_ms=%d",
                 len(graph.nodes), len(graph.edges), completion.provider, latency_ms)
        return PlanOutcome(graph, self.name, self.version, latency_ms, completion.provider, completion.model)
