"""Planner graph contract, version 1, as pydantic models.

Mirrors docs/ARCHITECTURE.md. The backend enforces these rules again at the
boundary (T-007); the planner validates here so it can ask the model to repair
its output before handing a graph over. Any `risk` field is ignored (D-07).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class PlannerInfo(BaseModel):
    name: str = Field(max_length=64)
    version: str = Field(max_length=32)


class IntentSpec(BaseModel):
    summary: str = Field(min_length=1, max_length=512)
    confidence: float = Field(ge=0.0, le=1.0)


class RunCommandParams(BaseModel):
    argv: list[str] = Field(min_length=1, max_length=32)
    timeout_s: int = Field(default=30, ge=1, le=120)

    @field_validator("argv")
    @classmethod
    def argv_items(cls, argv: list[str]) -> list[str]:
        for a in argv:
            if not a.strip() or len(a) > 1024:
                raise ValueError("each argv item must be 1-1024 non-blank characters")
        return argv


class Node(BaseModel):
    model_config = ConfigDict(extra="ignore")

    key: str = Field(min_length=1)
    action_type: Literal["run_command"]
    description: str = Field(default="", max_length=512)
    params: RunCommandParams


class Edge(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_: str = Field(alias="from")
    to: str


class PlannerGraph(BaseModel):
    contract_version: Literal["1"] = "1"
    planner: PlannerInfo
    intent: IntentSpec
    nodes: list[Node] = Field(min_length=1, max_length=20)
    edges: list[Edge] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_graph(self) -> PlannerGraph:
        keys = [n.key for n in self.nodes]
        if len(keys) != len(set(keys)):
            raise ValueError("node keys must be unique")
        known = set(keys)
        adj: dict[str, list[str]] = {k: [] for k in keys}
        for e in self.edges:
            if e.from_ not in known or e.to not in known:
                raise ValueError(f"edge {e.from_}->{e.to} references an unknown node")
            if e.from_ == e.to:
                raise ValueError(f"edge {e.from_}->{e.to} is a self loop")
            adj[e.from_].append(e.to)

        state: dict[str, int] = {}  # 1 = visiting, 2 = done

        def visit(k: str) -> None:
            if state.get(k) == 2:
                return
            if state.get(k) == 1:
                raise ValueError(f"dependency cycle through node {k}")
            state[k] = 1
            for nxt in adj[k]:
                visit(nxt)
            state[k] = 2

        for k in keys:
            visit(k)
        return self

    def to_snapshot(self) -> dict:
        """Plain dict in contract shape, suitable for plans.graph_snapshot."""
        return self.model_dump(by_alias=True)
