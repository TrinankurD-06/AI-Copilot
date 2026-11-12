"""Planner-side policy: the first gate a graph passes before the backend sees it.

The backend's validator and risk engine remain the authority (D-07). This
check exists so the planner can (a) repair a graph the model got wrong and
(b) refuse outright instead of handing over a plan that would be rejected,
or worse, one that smuggles arbitrary code through an allowed program.

Design rule: deny by construction. Interpreters may take no options at all
except a version flag, so there is no flag-spelling trick to find (`-c x`,
`-cx`, `-Bc`, `-m mod`, `--command=x` are all the same case: an option).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

from app.integrations.planner.contract import Node, PlannerGraph

DEFAULT_ALLOWED_COMMANDS: tuple[str, ...] = (
    "python", "python3", "ls", "cat", "echo", "mkdir", "cp", "mv", "wc",
    "head", "tail", "sort", "uniq", "grep", "find", "touch", "diff", "tr", "cut",
)

# Programs that run code or spawn processes. Never allowed, even if a teammate
# adds them to the allowlist by mistake.
_INTERPRETERS = {"python", "python3", "perl", "ruby", "node", "php", "lua"}
_SHELLS = {"sh", "bash", "zsh", "dash", "ash", "ksh", "fish", "busybox", "env", "xargs", "eval", "exec", "nohup", "timeout"}
# The only options an interpreter may take. Everything else is an option that
# can run code (-c, -m, -e, -r, -p, combined clusters, --flag=value, ...).
_SAFE_INTERPRETER_FLAGS = {"-V", "--version", "-u", "-B", "-I"}
# find primitives that execute, delete or write.
_FIND_ACTIONS = {"-delete", "-fprint", "-fprint0", "-fprintf", "-fputs", "-fls", "-ls"}
_FIND_ACTION_PREFIXES = ("-exec", "-ok")
# Programs that create or rename files: they must not produce code files.
_FILE_WRITERS = {"cp", "mv", "touch", "sort", "tr", "uniq", "cut"}
_CODE_SUFFIXES = (".py", ".pyc", ".pyw", ".sh", ".bash", ".zsh", ".pl", ".rb", ".js", ".mjs", ".php", ".lua")

_PROGRAM_NAME = re.compile(r"^[a-z][a-z0-9_.+-]*$")
_URL = re.compile(r"^[a-z][a-z0-9+.-]*://", re.IGNORECASE)
_PROSE_PROGRAMS = {"echo", "printf"}


@dataclass(frozen=True)
class PlannerPolicy:
    allowed_commands: frozenset[str] = frozenset(DEFAULT_ALLOWED_COMMANDS)
    allow_inline_code: bool = False
    workspace: str = "/workspace"
    max_arg_chars: int = 160          # one argument longer than this is text, not an argument
    max_prose_chars: int = 400        # total free text through echo/printf across the whole plan
    min_confidence: float = 0.5
    extra_denied: frozenset[str] = field(default_factory=frozenset)

    @classmethod
    def from_context(cls, ctx: dict | None, *, allow_inline_code: bool, min_confidence: float) -> PlannerPolicy:
        ctx = ctx or {}
        allowed = ctx.get("allowed_commands")
        return cls(
            allowed_commands=_names("allowed_commands", allowed) if allowed is not None else frozenset(DEFAULT_ALLOWED_COMMANDS),
            allow_inline_code=allow_inline_code,
            min_confidence=min_confidence,
            extra_denied=_names("denied_commands", ctx.get("denied_commands") or ()),
        )


def _names(field_name: str, value) -> frozenset[str]:
    """Backend context is untrusted config: a bare string must not become its letters."""
    if isinstance(value, (str, bytes)) or not isinstance(value, Iterable):
        raise ValueError(f"context[{field_name!r}] must be a list of program names")
    out = set()
    for v in value:
        if not isinstance(v, str) or not _PROGRAM_NAME.match(v):
            raise ValueError(f"context[{field_name!r}] contains an invalid program name: {v!r}")
        out.add(v)
    return frozenset(out)


def lint(graph: PlannerGraph, policy: PlannerPolicy) -> list[str]:
    """Return human-readable violations; empty means the graph may be handed over."""
    problems: list[str] = []
    if graph.intent.confidence < policy.min_confidence:
        problems.append(
            f"intent confidence {graph.intent.confidence:.2f} is below {policy.min_confidence:.2f}; "
            "the request is too unclear to act on"
        )
    prose = 0
    for n in graph.nodes:
        problems.extend(f"node {n.key}: {p}" for p in _lint_node(n, policy))
        if n.params.argv[0] in _PROSE_PROGRAMS:
            prose += sum(len(a) for a in n.params.argv[1:])
    if prose > policy.max_prose_chars:
        problems.append(
            f"the plan prints {prose} characters of free text in total; the planner must not "
            "answer questions or produce content, only plan sandbox actions"
        )
    return problems


def _lint_node(n: Node, policy: PlannerPolicy) -> list[str]:
    argv = n.params.argv
    prog = argv[0]
    out: list[str] = []

    # argv[0]: a bare, lowercase program name. No paths, so "./python3", "bin/ls"
    # and "/workspace/x" cannot resolve to something that is not on the list.
    if not _PROGRAM_NAME.match(prog):
        out.append(f"program {prog!r} must be a bare lowercase name without a path")
        return out
    if prog in _SHELLS or prog in policy.extra_denied:
        out.append(f"program {prog!r} is denied")
    elif prog not in policy.allowed_commands:
        out.append(f"program {prog!r} is not on the allowlist")

    for i, a in enumerate(argv[1:], 1):
        base = a.rsplit("/", 1)[-1]
        if base in _SHELLS or base in _INTERPRETERS:
            out.append(f"argument {a!r} names another program; nested execution is not allowed")
        if "\n" in a or "\r" in a or "\x00" in a:
            out.append("an argument contains a control character; that is code, not an argument")
        if len(a) > policy.max_arg_chars:
            out.append(f"argument {i} is {len(a)} characters long; that is text, not an argument")
        if _URL.match(a):
            out.append(f"argument {a!r} is a URL; the sandbox has no network")
        if a.startswith("~"):
            out.append(f"argument {a!r} refers to a home directory outside the workspace")
        if a.startswith("/") and not (a == policy.workspace or a.startswith(policy.workspace + "/")):
            out.append(f"path {a!r} is outside {policy.workspace}")
        if ".." in a.split("/"):
            out.append(f"path {a!r} climbs out of the workspace")

    if prog in _INTERPRETERS and not policy.allow_inline_code:
        out.extend(_lint_interpreter(argv))
    if prog == "find":
        out.extend(_lint_find(argv))
    if prog in _FILE_WRITERS:
        for a in argv[1:]:
            if a.lower().endswith(_CODE_SUFFIXES):
                out.append(f"{prog} would create or rename a code file {a!r}; writing code to run later is not allowed")
    return out


def _lint_interpreter(argv: list[str]) -> list[str]:
    """`python3 [safe-flags] script.py [args...]`: no other option before the script."""
    for a in argv[1:]:
        if not a.startswith("-"):
            return []  # the script path; what follows belongs to the script
        if a not in _SAFE_INTERPRETER_FLAGS:
            return [f"interpreter option {a!r} is not allowed; run a script file instead of inline code"]
    return []


def _lint_find(argv: list[str]) -> list[str]:
    out = []
    for a in argv[1:]:
        if a in _FIND_ACTIONS or a.startswith(_FIND_ACTION_PREFIXES):
            out.append(f"find action {a!r} executes, deletes or writes; use a separate allowed command instead")
    return out
