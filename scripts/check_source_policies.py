#!/usr/bin/env python3
"""Repository architecture checks formerly hidden in source-reading pytest cases.

Run from any directory: python scripts/check_source_policies.py [--root PATH].
All checks are stdlib-only so CI can run them without installing Hermes.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _python_files(root: Path, *, resolution: bool = False):
    excluded = {"tests", "scripts", "docs", "website", "apps", "examples", ".git", ".worktrees", ".venv", "venv", "node_modules", "__pycache__", "build", "dist"}
    if resolution:
        excluded = (excluded | {"plugins", "skills", "optional-skills", "evals", ".cache"}) - {"apps"}
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in excluded and not d.endswith(".egg-info") and not (Path(base, d) / "PKG-INFO").exists()]
        for name in files:
            if name.endswith(".py"):
                yield Path(base, name)


def _tree(path: Path):
    return ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))


def _calls(tree):
    return (n for n in ast.walk(tree) if isinstance(n, ast.Call))


def _subprocess_call(node, names=("run",)):
    fn = node.func
    return (isinstance(fn, ast.Attribute) and fn.attr in names
            and isinstance(fn.value, ast.Name) and fn.value.id == "subprocess")


def _kw(node, name):
    return next((kw.value for kw in node.keywords if kw.arg == name), None)


def _literal(node):
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name) and node.id in ("True", "False"):
        return node.id == "True"
    return None


def check_cli_subprocess(root: Path):
    """Text decoders need explicit encoding; short utility probes need timeouts.

    Long-lived launch/update children are deliberately not bounded by this
    probe-specific rule. A caller using **kwargs is not presumed safe: when a
    local literal dict is resolvable its keys are inspected too.
    """
    for path in (root / "hermes_cli").rglob("*.py"):
        if "test" in path.name or "__pycache__" in path.parts:
            continue
        tree = _tree(path)
        rel = path.relative_to(root)
        shared_kwargs = {}
        for assignment in tree.body:
            if isinstance(assignment, ast.Assign) and len(assignment.targets) == 1 and isinstance(assignment.targets[0], ast.Name):
                value = assignment.value
                if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id == "dict":
                    shared_kwargs[assignment.targets[0].id] = {kw.arg: kw.value for kw in value.keywords if kw.arg}
                elif isinstance(value, ast.Dict):
                    shared_kwargs[assignment.targets[0].id] = {k.value: v for k, v in zip(value.keys, value.values)
                                                              if isinstance(k, ast.Constant) and isinstance(k.value, str)}
        for call in _calls(tree):
            if not _subprocess_call(call, ("run", "check_output", "check_call", "call", "Popen")):
                continue
            kwargs = {k.arg: k.value for k in call.keywords if k.arg}
            for kw in call.keywords:
                if kw.arg is None and isinstance(kw.value, ast.Name):
                    kwargs.update(shared_kwargs.get(kw.value.id, {}))
                if kw.arg is None and isinstance(kw.value, ast.Dict):
                    kwargs.update((k.value, v) for k, v in zip(kw.value.keys, kw.value.values)
                                  if isinstance(k, ast.Constant) and isinstance(k.value, str))
            text = kwargs.get("text", kwargs.get("universal_newlines"))
            if _literal(text) is True and "encoding" not in kwargs:
                yield f"{rel}:{call.lineno}: text-mode subprocess without encoding="
            # Doctor/status/clipboard/banner are short probes, not daemon launchers.
            if (path.stem.startswith(("doctor", "status")) or path.stem in ("clipboard", "banner")) and _subprocess_call(call) and "timeout" not in kwargs:
                yield f"{rel}:{call.lineno}: subprocess.run probe without timeout="


def check_gateway_utf8(root: Path):
    paths = list((root / "gateway").rglob("*.py"))
    paths += [root / f"plugins/platforms/{name}/adapter.py" for name in ("discord", "telegram", "feishu", "whatsapp", "google_chat")]
    paths += [root / "plugins/platforms/google_chat/oauth.py"]
    for path in paths:
        if not path.exists():
            continue
        lines = path.read_text(encoding="utf-8-sig").splitlines()
        for call in _calls(_tree(path)):
            if (isinstance(call.func, ast.Attribute) and call.func.attr in ("read_text", "write_text")
                    and _kw(call, "encoding") is None
                    and "# gateway-utf8: ok" not in lines[call.lineno - 1]):
                yield f"{path.relative_to(root)}:{call.lineno}: text file I/O without encoding="


def check_config_keys(root: Path):
    path = root / "hermes_cli/config_defaults.py"
    if not path.exists():
        yield "hermes_cli/config_defaults.py: DEFAULT_CONFIG owner missing; update policy scope"
        return
    found = False
    for assignment in _tree(path).body:
        if isinstance(assignment, (ast.Assign, ast.AnnAssign)):
            targets = assignment.targets if isinstance(assignment, ast.Assign) else [assignment.target]
            if not any(isinstance(t, ast.Name) and t.id == "DEFAULT_CONFIG" for t in targets):
                continue
            found = True
            dictionary = assignment.value
            if not isinstance(dictionary, ast.Dict):
                yield f"{path.relative_to(root)}:{assignment.lineno}: DEFAULT_CONFIG is not a literal dict"
                continue
            seen = set()
            for key in dictionary.keys:
                if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                    continue
                if key.value in seen:
                    yield f"{path.relative_to(root)}:{key.lineno}: duplicate DEFAULT_CONFIG key {key.value!r}"
                seen.add(key.value)
    if not found:
        yield f"{path.relative_to(root)}: DEFAULT_CONFIG literal not found; update policy scope"


_RAW_ENV_ALLOWED = {
    "tools/environments/local.py",  # The sanitizer itself snapshots ambient state.
    "hermes_cli/bang_shell.py",  # Fallback when tools package cannot import.
    "hermes_cli/gateway.py",  # Gateway respawn script is Hermes itself.
    "hermes_cli/stderr_timestamp.py",  # Launchd gateway wrapper needs full env.
    "hermes_cli/profiles.py",  # Profile seed/sync must inherit its owner's env.
    "tui_gateway/host_supervisor.py",  # Compute host needs agent provider credentials.
    "tools/bot_desktop/install.py",  # Root package manager should not inherit scratch TMPDIR.
    "tools/environments/remote_common.py",  # Docker/SSH client needs host HOME/config.
}
_SPAWN = re.compile(r"\bPopen\b|\bsubprocess\.run\b|\bcreate_subprocess|\bPtyProcess\.spawn\b|\bexecvpe\b|\bptyprocess\.PtyProcess\b|\bspawn\(")
_COPY = re.compile(r"\bos\.environ\.copy\(\)|\*\*os\.environ\b")


def check_spawn_env(root: Path):
    files = (p for directory in ("agent", "hermes_cli", "tools", "gateway", "cron", "tui_gateway", "plugins")
             for p in (root / directory).rglob("*.py"))
    files = list(files) + [root / name for name in ("cli.py", "hermes_constants.py")]
    for path in files:
        if not path.exists() or path.relative_to(root).as_posix() in _RAW_ENV_ALLOWED:
            continue
        lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
        for i, line in enumerate(lines):
            if line.lstrip().startswith("#") or not _COPY.search(line.split("#", 1)[0]):
                continue
            if _SPAWN.search("\n".join(lines[max(0, i - 20):i + 21])):
                yield f"{path.relative_to(root)}:{i + 1}: raw environment near child spawn"
    for rel in _RAW_ENV_ALLOWED:
        if not (root / rel).is_file():
            yield f"{rel}: stale raw-spawn-env exception"


_CONFIG_OWNERS = {"hermes_cli/config.py", "gateway/config.py", "gateway/config_loader.py", "gateway/run.py", "hermes_cli/managed_scope.py", "gateway/readiness.py", "hermes_cli/main.py"}

def check_config_reads(root: Path):
    config = re.compile(r'''["']config\.yaml["']''')
    loader = re.compile(r"\bsafe_load\s*\(")
    for path in _python_files(root):
        rel = path.relative_to(root).as_posix()
        if rel in _CONFIG_OWNERS:
            continue
        lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
        indices = [i for i, line in enumerate(lines) if config.search(line)]
        if not indices:
            continue
        for i, line in enumerate(lines):
            if loader.search(line) and not line.strip().startswith("#") and any(abs(i - j) <= 6 for j in indices):
                yield f"{rel}:{i + 1}: raw config.yaml parse outside loader owner"


_FORBIDDEN_CRYPTO = re.compile(r"ed25519|verify_key|verifykey|verify_signature|verify_ed25519|verify_webhook|bizmsg|hmac|x[-_]signature", re.I)
_FORBIDDEN_MODULES = ("wecom_crypto", "wecom_callback", "webhook")

def check_relay_crypto(root: Path):
    for path in (root / "gateway/relay").glob("*.py"):
        tree = _tree(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                imports = [node.module or ""] + [alias.name for alias in node.names]
            else:
                continue
            if any(token in imported.lower() for imported in imports for token in _FORBIDDEN_MODULES):
                yield f"{path.relative_to(root)}:{node.lineno}: platform crypto module in relay"
            elif path.name != "auth.py" and any(_FORBIDDEN_CRYPTO.search(imported) for imported in imports):
                yield f"{path.relative_to(root)}:{node.lineno}: platform crypto import in relay"
        if path.name == "auth.py":  # Channel HMAC authenticates connector⇄gateway, not platform payloads.
            continue
        for call in _calls(tree):
            fn = call.func
            symbol = fn.attr if isinstance(fn, ast.Attribute) else fn.id if isinstance(fn, ast.Name) else ""
            if _FORBIDDEN_CRYPTO.search(symbol):
                yield f"{path.relative_to(root)}:{call.lineno}: platform crypto verification in relay: {symbol}"


_EXEMPT_RESOLUTION = {"tests", "plugins", "skills", "optional-skills", "scripts", "evals", "website", "node_modules", ".cache", ".git", ".venv", "venv", ".worktrees"}
_ALLOWED_WHICH = {("tools/env_probe.py", "uv"), ("hermes_cli/main_tui_launch.py", "node"),
                  ("hermes_cli/main_tui_launch.py", "npm"), ("hermes_cli/source_build.py", "node"),
                  ("hermes_cli/source_build.py", "npm"), ("hermes_cli/main_desktop.py", "npm"),
                  ("pm/workspace.py", "npm"), ("apps/desktop/electron/fixtures/source-backend.py", "uv")}
_FRAGMENTS = (".local/bin", ".cargo/bin", "/opt/homebrew/bin", "LOCALAPPDATA", "scoop", "WinGet")

class _ResolutionVisitor(ast.NodeVisitor):
    def __init__(self):
        self.scope = []
        self.shutil = {"shutil"}
        self.which = set()
        self.sites = set()

    def visit_Import(self, node):
        for alias in node.names:
            if alias.name == "shutil":
                self.shutil.add(alias.asname or alias.name)

    def visit_ImportFrom(self, node):
        if node.module == "shutil":
            self.which.update(alias.asname or alias.name for alias in node.names if alias.name == "which")

    def _scope(self, node, name, function):
        self.scope.append((name, function))
        self.generic_visit(node)
        self.scope.pop()

    def visit_ClassDef(self, node): self._scope(node, node.name, False)
    def visit_FunctionDef(self, node): self._scope(node, node.name, True)
    def visit_AsyncFunctionDef(self, node): self._scope(node, node.name, True)

    def _symbol(self):
        if not any(function for _, function in self.scope):
            return "<module>"
        parts = []
        for i, (name, _) in enumerate(self.scope):
            if i and self.scope[i - 1][1]:
                parts.append("<locals>")
            parts.append(name)
        return ".".join(parts)

    def visit_Call(self, node):
        fn = node.func
        if (isinstance(fn, ast.Attribute) and fn.attr == "which" and isinstance(fn.value, ast.Name) and fn.value.id in self.shutil) or (isinstance(fn, ast.Name) and fn.id in self.which):
            self.sites.add((self._symbol(), "bare_which"))
        self.generic_visit(node)

    def visit_List(self, node):
        self._table(node)
        self.generic_visit(node)

    def visit_Tuple(self, node):
        self._table(node)
        self.generic_visit(node)

    def _table(self, node):
        joined = "/".join(n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str))
        if sum(fragment in joined for fragment in _FRAGMENTS) >= 2:
            self.sites.add((self._symbol(), "known_path_table"))


def check_resolution(root: Path):
    allowed_path = root / "tests/fixtures/resolution_allowlist.json"
    allowed_sites = {(row["path"], row["symbol"], row["kind"]) for row in json.loads(allowed_path.read_text(encoding="utf-8-sig"))} if allowed_path.exists() else set()
    actual_sites = set()
    actual_which = set()
    for path in _python_files(root, resolution=True):
        rel = path.relative_to(root).as_posix()
        if rel.startswith("hermes_platform/"):
            continue
        source = path.read_text(encoding="utf-8-sig", errors="replace")
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        visitor = _ResolutionVisitor()
        visitor.visit(tree)
        actual_sites.update((rel, symbol, kind) for symbol, kind in visitor.sites)
        for call in _calls(tree):
            fn = call.func
            if call.args and (isinstance(fn, ast.Name) and fn.id == "which" or isinstance(fn, ast.Attribute) and fn.attr == "which"):
                command = _literal(call.args[0])
                if command in ("uv", "node", "npm", "npx"):
                    actual_which.add((rel, command))
                    if (rel, command) not in _ALLOWED_WHICH:
                        yield f"{rel}:{call.lineno}: bare managed runtime lookup: {command}"
    for site in sorted(actual_sites - allowed_sites):
        yield f"{site[0]}::{site[1]}: unreviewed resolution site ({site[2]})"
    for site in sorted(allowed_sites - actual_sites):
        yield f"{site[0]}::{site[1]}: stale resolution allowlist row ({site[2]})"
    for rel, command in sorted(_ALLOWED_WHICH - actual_which):
        if (root / rel).exists() and not rel.startswith("apps/"):
            yield f"{rel}: stale managed runtime lookup exception ({command})"


CHECKS = (check_cli_subprocess, check_gateway_utf8, check_config_keys, check_spawn_env,
          check_config_reads, check_relay_crypto, check_resolution)


def check(root: Path):
    for rule in CHECKS:
        yield from rule(root)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    findings = list(check(args.root.resolve()))
    for finding in findings:
        print(finding)
    if findings:
        print(f"{len(findings)} source policy violation(s)")
    return bool(findings)


if __name__ == "__main__":
    raise SystemExit(main())
