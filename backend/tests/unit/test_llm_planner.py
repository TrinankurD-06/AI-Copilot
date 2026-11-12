import json

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.integrations.llm.gateway import LLMGateway
from app.integrations.planner.contract import PlannerGraph
from app.integrations.planner.llm_planner import PLANNER_VERSION, LLMPlanner, PlanningRefused

GOOD = {
    "contract_version": "1",
    "intent": {"summary": "Show the Python version", "confidence": 0.9},
    "nodes": [
        {"key": "n1", "action_type": "run_command", "description": "version",
         "params": {"argv": ["python", "--version"], "timeout_s": 10}},
        {"key": "n2", "action_type": "run_command", "description": "list",
         "params": {"argv": ["ls", "-la"]}},
    ],
    "edges": [{"from": "n1", "to": "n2"}],
}


class Scripted:
    """Provider that returns canned JSON answers in order."""
    name, model = "fake", "fake-1"

    def __init__(self, *answers):
        self.answers, self.prompts = [json.dumps(a) for a in answers], []

    def complete(self, prompt, *, json_mode):
        self.prompts.append(prompt)
        return self.answers.pop(0)


def planner(*answers):
    provider = Scripted(*answers)
    gw = LLMGateway(Settings(LLM_SCHEMA_REPAIR_ATTEMPTS=1), providers=[provider])
    return LLMPlanner(gw), provider


def test_valid_graph_round_trips():
    p, provider = planner(GOOD)
    out = p.plan("show python version")
    snap = out.snapshot()
    assert out.planner_name == "llm"
    assert snap["planner"] == {"name": "llm", "version": PLANNER_VERSION}
    assert [n["key"] for n in snap["nodes"]] == ["n1", "n2"]
    assert snap["edges"] == [{"from": "n1", "to": "n2"}]
    assert snap["nodes"][1]["params"]["timeout_s"] == 30  # default applied
    assert len(provider.prompts) == 1


def test_context_reaches_the_prompt():
    p, provider = planner(GOOD)
    p.plan("x", {"allowed_commands": ["python", "rg", "ls"]})
    assert "ls, python, rg" in provider.prompts[0]


def test_invalid_answer_is_repaired_once():
    bad = {**GOOD, "edges": [{"from": "n1", "to": "zzz"}]}
    p, provider = planner(bad, GOOD)
    out = p.plan("x")
    assert len(provider.prompts) == 2
    assert "unknown node" in provider.prompts[1]
    assert len(out.graph.edges) == 1


def test_repair_failure_raises():
    bad = {**GOOD, "nodes": []}
    p, _ = planner(bad, bad)
    with pytest.raises(PlanningRefused) as exc:
        p.plan("x")
    assert exc.value.source == "policy"


def test_model_supplied_risk_and_planner_are_ignored():
    sneaky = {**GOOD, "planner": {"name": "evil", "version": "9"}}
    sneaky["nodes"] = [{**GOOD["nodes"][0], "risk": "low"}, GOOD["nodes"][1]]
    p, _ = planner(sneaky)
    snap = p.plan("x").snapshot()
    assert snap["planner"]["name"] == "llm"
    assert "risk" not in snap["nodes"][0]


@pytest.mark.parametrize("mutate, msg", [
    (lambda g: g["edges"].append({"from": "n2", "to": "n1"}), "cycle"),
    (lambda g: g["edges"].append({"from": "n1", "to": "n1"}), "self loop"),
    (lambda g: g["nodes"].append({**g["nodes"][0]}), "unique"),
    (lambda g: g["nodes"][0]["params"].update(argv=[]), "at least 1"),
    (lambda g: g["nodes"][0]["params"].update(timeout_s=999), "less than or equal to 120"),
    (lambda g: g["nodes"][0].update(action_type="shell"), "run_command"),
])
def test_contract_rejects(mutate, msg):
    g = json.loads(json.dumps(GOOD))
    g["planner"] = {"name": "llm", "version": "0.1.0"}
    mutate(g)
    with pytest.raises(ValidationError, match=msg):
        PlannerGraph.model_validate(g)


def test_model_json_refusal_raises_planning_refused():
    from app.integrations.planner.llm_planner import PlanningRefused

    p, provider = planner({"refusal": "Deleting the whole system is not allowed."})
    with pytest.raises(PlanningRefused) as exc:
        p.plan("rm -rf / with sudo")
    assert "not allowed" in exc.value.reason
    assert exc.value.provider == "fake"
    assert len(provider.prompts) == 1  # no repair attempt on a refusal


def test_provider_refusal_raises_planning_refused():
    from app.integrations.llm.providers import Refused
    from app.integrations.planner.llm_planner import PlanningRefused

    class Declining:
        name, model = "groq", "m"

        def complete(self, prompt, *, json_mode):
            raise Refused("groq declined: I can't comply with that request.")

    gw = LLMGateway(Settings(LLM_MAX_RETRIES=3), providers=[Declining(), Scripted(GOOD)])
    with pytest.raises(PlanningRefused, match="can't comply"):
        LLMPlanner(gw).plan("delete everything")


def test_prompt_offers_refusal_shape():
    p, provider = planner(GOOD)
    p.plan("x")
    assert '{"refusal"' in provider.prompts[0]
