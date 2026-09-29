#!/usr/bin/env python3
"""Lint SessionDB writer-lock purity across facade and mixins."""
from __future__ import annotations

import ast
import re
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[1]
_STATE_PY = _REPO_ROOT / "hermes_state.py"

# SessionDB's own class body lives in hermes_state.py; the rest of its
# methods come from these mixins (see module docstring). Each entry is
# (source file, class name to scan in that file).
_ALL_STATE_SOURCES: list[tuple[Path, str]] = [
    (_STATE_PY, "SessionDB"),
    (_REPO_ROOT / "hermes_state_search.py", "SessionSearchMixin"),
    (_REPO_ROOT / "hermes_state_schema.py", "SessionSchemaMixin"),
    (_REPO_ROOT / "hermes_state_portability.py", "SessionPortabilityMixin"),
]

_WRITE_RE = re.compile(
    r"^\s*(INSERT|UPDATE|DELETE|REPLACE|CREATE|DROP|ALTER|VACUUM|BEGIN|COMMIT|ANALYZE)\b",
    re.IGNORECASE,
)
# PRAGMA is read-only EXCEPT the checkpoint/optimize family, which mutates
# the database file and legitimately belongs on the writer connection.
_PRAGMA_WRITE_RE = re.compile(
    r"^\s*PRAGMA\s+(wal_checkpoint|optimize|incremental_vacuum|integrity_check)",
    re.IGNORECASE,
)
_READ_RE = re.compile(r"^\s*(SELECT|PRAGMA)\b", re.IGNORECASE)

# Methods allowed to keep a pure-read body under the writer lock, each with
# the reason. Keep this list SHRINKING — never add to it without the same
# scrutiny a new blocking call would get.
_ALLOWED_LOCKED_READERS: dict[str, str] = {
    # get_meta stays on the writer lock BY DESIGN (see its inline comment):
    # fts_rebuild_step reads rebuild progress before entering a write
    # transaction, and a pooled WAL reader sees only committed data — the
    # writer's own just-staged meta updates would be invisible to it.
    "get_meta": "read-your-writes: rebuild progress read before write txn",
}


def _first_sql_text(call: ast.Call) -> str | None:
    """Best-effort SQL text from an execute()'s first argument."""
    if not call.args:
        return None
    arg = call.args[0]
    text = None
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        text = arg.value
    elif isinstance(arg, ast.JoinedStr):
        parts = [
            v.value for v in arg.values
            if isinstance(v, ast.Constant) and isinstance(v.value, str)
        ]
        text = "".join(parts)
    if not text or not text.strip():
        return None
    return text.strip()


def _is_self_conn_execute(call: ast.Call, aliases: set[str]) -> bool:
    """Match ``self._conn.execute*`` and ``<alias>.execute*`` where the
    alias was bound from ``self._conn`` (``conn = self._conn``)."""
    f = call.func
    if not (
        isinstance(f, ast.Attribute)
        and f.attr in ("execute", "executemany", "executescript")
    ):
        return False
    target = f.value
    if (
        isinstance(target, ast.Attribute)
        and target.attr == "_conn"
        and isinstance(target.value, ast.Name)
        and target.value.id == "self"
    ):
        return True
    return isinstance(target, ast.Name) and target.id in aliases


def _collect_conn_aliases(method: ast.AST) -> set[str]:
    """Names bound from ``self._conn`` anywhere in the method body."""
    aliases: set[str] = set()
    for node in ast.walk(method):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Attribute):
            v = node.value
            if (
                v.attr == "_conn"
                and isinstance(v.value, ast.Name)
                and v.value.id == "self"
            ):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        aliases.add(t.id)
    return aliases


def _is_self_lock_with(item: ast.withitem) -> bool:
    ctx = item.context_expr
    return (
        isinstance(ctx, ast.Attribute)
        and ctx.attr == "_lock"
        and isinstance(ctx.value, ast.Name)
        and ctx.value.id == "self"
    )


def _scan_locked_readers(
    state_py: "Path | None" = None, class_name: str = "SessionDB"
) -> list[str]:
    target = state_py if state_py is not None else _STATE_PY
    tree = ast.parse(target.read_text(encoding="utf-8-sig"))
    violations: list[str] = []

    session_db = None
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            session_db = node
            break
    assert session_db is not None, f"{class_name} class not found in {target}"

    for method in session_db.body:
        if not isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        aliases = _collect_conn_aliases(method)
        for node in ast.walk(method):
            if not isinstance(node, ast.With):
                continue
            if not any(_is_self_lock_with(i) for i in node.items):
                continue
            reads, writes, unknown = 0, 0, 0
            for inner in ast.walk(node):
                if isinstance(inner, ast.Call) and _is_self_conn_execute(inner, aliases):
                    word_full = _first_sql_text(inner)
                    word = word_full.split(None, 1)[0].upper() if word_full else None
                    if word is None:
                        # SQL held in a variable or built f-string: the
                        # scanner cannot prove it reads. A lock block whose
                        # ONLY statements are unprovable is still flagged
                        # below — writers name their verbs in literals
                        # throughout this file, so opacity correlates with
                        # composed SELECTs, and silently skipping these is
                        # how 5 readers hid from the first version of this
                        # gate.
                        unknown += 1
                    elif _PRAGMA_WRITE_RE.match(word_full or ""):
                        writes += 1
                    elif _WRITE_RE.match(word):
                        writes += 1
                    elif _READ_RE.match(word):
                        reads += 1
                    else:
                        unknown += 1
                # Method calls under the lock may write internally
                # (e.g. self._execute_write, cursor ops) — treat any
                # self.<something>() as potentially writing.
                elif isinstance(inner, ast.Call):
                    f = inner.func
                    if (
                        isinstance(f, ast.Attribute)
                        and isinstance(f.value, ast.Name)
                        and f.value.id == "self"
                        and (
                            "write" in f.attr
                            or "commit" in f.attr
                            or f.attr.startswith(("set_", "record_", "insert_",
                                                  "update_", "delete_", "clear_"))
                        )
                    ):
                        writes += 1
            if writes == 0 and (reads > 0 or unknown > 0):
                if method.name not in _ALLOWED_LOCKED_READERS:
                    kind = "pure-read" if unknown == 0 else "no-proven-write"
                    violations.append(
                        f"{method.name} (line {node.lineno}): {kind} "
                        f"body under `with self._lock:` — route through "
                        f"_read_ctx() instead (or add a justified "
                        f"allowlist entry)"
                    )
    return violations


def _scan_all_state_sources(root: Path | None = None) -> list[str]:
    """Run ``_scan_locked_readers`` over every file that contributes methods
    to ``SessionDB`` — the class body in ``hermes_state.py`` plus each mixin
    it inherits from (see module docstring). Violations are prefixed with
    their source filename since methods can share names across mixins.
    """
    violations: list[str] = []
    sources = _ALL_STATE_SOURCES if root is None else [(root / p.relative_to(_REPO_ROOT), cls) for p, cls in _ALL_STATE_SOURCES]
    for path, class_name in sources:
        for v in _scan_locked_readers(path, class_name):
            violations.append(f"{path.name}: {v}")
    return violations



def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=_REPO_ROOT)
    args = parser.parse_args()
    violations = _scan_all_state_sources(args.root.resolve())
    for violation in violations:
        print(violation)
    return bool(violations)


if __name__ == "__main__":
    raise SystemExit(main())
