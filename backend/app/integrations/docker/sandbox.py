"""Sandbox runner: executes one contract node in a fresh, locked-down container.

Profile (docs/ARCHITECTURE.md, D-12): pinned Alpine image, nobody user, no
network, memory/CPU/pids caps, no swap, read-only root with tmpfs /tmp, all
capabilities dropped, no-new-privileges, per-node timeout, output capped and
flagged when cut, container always removed. A per-plan directory on the host
is mounted at /workspace so files flow between nodes.

Commands are argv lists (D-11); nothing here ever builds a shell string.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from app.core.config import Settings, settings
from app.integrations.planner.contract import PlannerGraph

log = logging.getLogger(__name__)

WORKDIR = "/workspace"
LABEL = "ai-copilot.sandbox"


class SandboxUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class NodeResult:
    key: str
    argv: list[str]
    status: str            # succeeded | failed | timed_out
    exit_code: int | None
    stdout: str
    stderr: str
    stdout_truncated: bool
    stderr_truncated: bool
    duration_ms: int

    @property
    def ok(self) -> bool:
        return self.status == "succeeded"


@dataclass
class PlanRun:
    plan_id: str
    results: list[NodeResult] = field(default_factory=list)
    workspace_files: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.results) and all(r.ok for r in self.results)


class SandboxRunner:
    def __init__(self, cfg: Settings = settings, plan_id: str | None = None):
        try:
            import docker
            from docker.errors import DockerException
        except ImportError as e:  # pragma: no cover
            raise SandboxUnavailable("the docker package is not installed") from e
        try:
            self._client = docker.from_env()
            self._client.ping()
        except DockerException as e:
            raise SandboxUnavailable("Docker is not running or not installed") from e
        self.cfg = cfg
        self.plan_id = plan_id or uuid.uuid4().hex[:12]
        self.workspace = (Path(cfg.SANDBOX_RUNS_DIR) / self.plan_id).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.workspace.chmod(0o777)  # nobody must be able to write the bind mount
        self._ensure_image()

    # ---- files --------------------------------------------------------------

    def put(self, relative_path: str, data: bytes) -> None:
        p = self._safe(relative_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def get(self, relative_path: str) -> bytes:
        return self._safe(relative_path).read_bytes()

    def files(self) -> list[str]:
        return sorted(str(p.relative_to(self.workspace)) for p in self.workspace.rglob("*") if p.is_file())

    # ---- execution ----------------------------------------------------------

    def run_graph(self, graph: PlannerGraph, *, approve=None, stop_on_failure: bool = True) -> PlanRun:
        """Run nodes in dependency order. `approve(node) -> bool` is the human gate;
        a rejected node stops the run."""
        run = PlanRun(self.plan_id)
        for node in ordered(graph):
            if approve is not None and not approve(node):
                log.info("plan=%s node=%s rejected by operator", self.plan_id, node.key)
                break
            r = self.run_node(node.key, node.params.argv, node.params.timeout_s)
            run.results.append(r)
            if stop_on_failure and not r.ok:
                break
        run.workspace_files = self.files()
        return run

    def run_node(self, key: str, argv: list[str], timeout_s: int | None = None) -> NodeResult:
        import requests
        from docker.errors import ContainerError

        timeout = min(timeout_s or self.cfg.SANDBOX_TIMEOUT_S, 120)
        cfg = self.cfg
        container = self._client.containers.create(
            cfg.SANDBOX_IMAGE,
            command=list(argv),
            working_dir=WORKDIR,
            user=cfg.SANDBOX_USER,
            network_disabled=True,
            mem_limit=cfg.SANDBOX_MEMORY,
            memswap_limit=cfg.SANDBOX_MEMORY,
            nano_cpus=cfg.SANDBOX_NANO_CPUS,
            pids_limit=cfg.SANDBOX_PIDS_LIMIT,
            read_only=True,
            tmpfs={"/tmp": "size=64m"},
            cap_drop=["ALL"],
            security_opt=["no-new-privileges"],
            volumes={str(self.workspace): {"bind": WORKDIR, "mode": "rw"}},
            labels={LABEL: "1", f"{LABEL}.plan": self.plan_id, f"{LABEL}.node": key},
        )
        t0 = time.perf_counter()
        status, code = "failed", None
        try:
            container.start()
            try:
                code = container.wait(timeout=timeout)["StatusCode"]
                status = "succeeded" if code == 0 else "failed"
            except requests.exceptions.ReadTimeout:
                container.kill()
                status = "timed_out"
            out, out_cut = self._logs(container, stdout=True)
            err, err_cut = self._logs(container, stderr=True)
        finally:
            container.remove(force=True)
        ms = int((time.perf_counter() - t0) * 1000)
        log.info("plan=%s node=%s status=%s exit=%s ms=%d", self.plan_id, key, status, code, ms)
        return NodeResult(key, list(argv), status, code, out, err, out_cut, err_cut, ms)

    # ---- helpers ------------------------------------------------------------

    def _logs(self, container, **which) -> tuple[str, bool]:
        raw = container.logs(stdout=which.get("stdout", False), stderr=which.get("stderr", False))
        cut = len(raw) > self.cfg.SANDBOX_OUTPUT_CAP
        return raw[: self.cfg.SANDBOX_OUTPUT_CAP].decode(errors="replace"), cut

    def _safe(self, relative_path: str) -> Path:
        p = (self.workspace / relative_path).resolve()
        if p != self.workspace and self.workspace not in p.parents:
            raise ValueError(f"path escapes workspace: {relative_path}")
        return p

    def _ensure_image(self) -> None:
        from docker.errors import ImageNotFound

        try:
            self._client.images.get(self.cfg.SANDBOX_IMAGE)
        except ImageNotFound:
            log.info("pulling %s", self.cfg.SANDBOX_IMAGE)
            self._client.images.pull(self.cfg.SANDBOX_IMAGE)


def ordered(graph: PlannerGraph):
    """Nodes in an order that respects every edge (contract guarantees no cycles)."""
    by_key = {n.key: n for n in graph.nodes}
    deps: dict[str, set[str]] = {k: set() for k in by_key}
    for e in graph.edges:
        deps[e.to].add(e.from_)
    done: list[str] = []
    remaining = dict(deps)
    while remaining:
        ready = sorted(k for k, d in remaining.items() if d <= set(done))
        if not ready:
            raise ValueError("dependency cycle")
        for k in ready:
            done.append(k)
            del remaining[k]
    return [by_key[k] for k in done]
