"""Minimal sandbox check, PROTOTYPE ONLY.

Enough to see a planned graph run end to end from scripts/plan_and_run.py.
The real runner is the backend owner's (T-006, T-202) and will replace this
file; nothing else imports it. Profile kept to the essentials of
docs/ARCHITECTURE.md: fresh container per node, nobody user, no network,
memory cap, read-only root, /workspace bind mount, timeout, always removed.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from app.core.config import Settings, settings
from app.integrations.planner.contract import PlannerGraph


class SandboxUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class NodeResult:
    key: str
    status: str  # succeeded | failed | timed_out
    exit_code: int | None
    output: str


class SandboxRunner:
    def __init__(self, cfg: Settings = settings):
        try:
            import docker

            self._client = docker.from_env()
            self._client.ping()
        except Exception as e:
            raise SandboxUnavailable(
                "Docker is not available (on macOS set DOCKER_HOST=unix://$HOME/.docker/run/docker.sock "
                "or enable the default socket in Docker Desktop settings)"
            ) from e
        self.cfg = cfg
        self.plan_id = uuid.uuid4().hex[:12]
        self.workspace = (Path("runs") / self.plan_id).resolve()
        self.workspace.mkdir(parents=True)
        self.workspace.chmod(0o777)
        try:
            self._client.images.get(cfg.SANDBOX_IMAGE)
        except docker.errors.ImageNotFound:
            self._client.images.pull(cfg.SANDBOX_IMAGE)

    def put(self, name: str, data: bytes = b"") -> None:
        (self.workspace / name).write_bytes(data)

    def files(self) -> list[str]:
        return sorted(p.name for p in self.workspace.rglob("*") if p.is_file())

    def run_graph(self, graph: PlannerGraph, approve=None) -> list[NodeResult]:
        results = []
        for node in ordered(graph):
            if approve and not approve(node):
                break
            r = self.run_node(node.key, node.params.argv, node.params.timeout_s)
            results.append(r)
            if r.status != "succeeded":
                break
        return results

    def run_node(self, key: str, argv: list[str], timeout_s: int) -> NodeResult:
        import requests

        c = self._client.containers.create(
            self.cfg.SANDBOX_IMAGE, command=list(argv), working_dir="/workspace",
            user="65534:65534", network_disabled=True, mem_limit="256m", read_only=True,
            tmpfs={"/tmp": ""}, cap_drop=["ALL"], security_opt=["no-new-privileges"],
            volumes={str(self.workspace): {"bind": "/workspace", "mode": "rw"}},
        )
        try:
            c.start()
            try:
                code = c.wait(timeout=min(timeout_s, self.cfg.SANDBOX_TIMEOUT_S))["StatusCode"]
                status = "succeeded" if code == 0 else "failed"
            except requests.exceptions.ReadTimeout:
                c.kill()
                code, status = None, "timed_out"
            output = c.logs().decode(errors="replace")[:4000]
        finally:
            c.remove(force=True)
        return NodeResult(key, status, code, output)


def ordered(graph: PlannerGraph):
    """Nodes in an order that respects every edge (the contract forbids cycles)."""
    deps = {n.key: {e.from_ for e in graph.edges if e.to == n.key} for n in graph.nodes}
    by_key, done = {n.key: n for n in graph.nodes}, []
    while deps:
        ready = sorted(k for k, d in deps.items() if d <= set(done))
        done.extend(ready)
        for k in ready:
            del deps[k]
    return [by_key[k] for k in done]
