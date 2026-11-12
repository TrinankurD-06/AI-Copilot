"""Sandbox runner tests. Need Docker; skipped otherwise. Run: python -m pytest -m docker"""

import pytest

from app.core.config import Settings
from app.integrations.planner.contract import PlannerGraph

pytestmark = pytest.mark.docker


@pytest.fixture
def runner(tmp_path):
    from app.integrations.docker.sandbox import SandboxRunner, SandboxUnavailable

    try:
        yield SandboxRunner(Settings(SANDBOX_RUNS_DIR=str(tmp_path)))
    except SandboxUnavailable as e:
        pytest.skip(str(e))


def graph(*argvs, edges=()):
    return PlannerGraph.model_validate({
        "contract_version": "1", "planner": {"name": "t", "version": "0"},
        "intent": {"summary": "t", "confidence": 1.0},
        "nodes": [{"key": f"n{i}", "action_type": "run_command", "params": {"argv": list(a)}}
                  for i, a in enumerate(argvs, 1)],
        "edges": [{"from": f, "to": t} for f, t in edges],
    })


def test_runs_as_nobody_without_network_and_cleans_up(runner):
    r = runner.run_node("n1", ["id", "-u"])
    assert r.ok and r.stdout.strip() == "65534"
    r = runner.run_node("n2", ["wget", "-T", "2", "http://example.com"])
    assert not r.ok
    assert not runner._client.containers.list(all=True, filters={"label": "ai-copilot.sandbox=1"})


def test_root_fs_is_read_only_but_workspace_is_writable(runner):
    assert not runner.run_node("n1", ["touch", "/etc/x"]).ok
    assert runner.run_node("n2", ["touch", "/workspace/x"]).ok
    assert runner.files() == ["x"]


def test_timeout_kills_the_node(runner):
    r = runner.run_node("n1", ["sleep", "30"], timeout_s=1)
    assert r.status == "timed_out" and r.duration_ms < 10_000


def test_graph_runs_in_edge_order_and_shares_files(runner):
    runner.put("a.pdf", b"x")
    run = runner.run_graph(graph(["mkdir", "Reports"], ["mv", "a.pdf", "Reports/a.pdf"], edges=[("n1", "n2")]))
    assert run.ok and run.workspace_files == ["Reports/a.pdf"]


def test_output_is_capped_and_flagged(runner):
    r = runner.run_node("n1", ["head", "-c", "200000", "/dev/zero"])
    assert r.stdout_truncated and len(r.stdout) == 64 * 1024
