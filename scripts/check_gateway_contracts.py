#!/usr/bin/env python3
"""Lint the gateway wire catalog against static emitter/request declarations.

Runtime frame tests prove delivery for exercised paths; this independent lint
keeps unexercised literal event and request sites in the contract catalog.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_EMIT_HELPERS = ("_emit", "_broadcast_global_event", "_voice_emit", "_pet_emit", "_emit_tool_lifecycle")
_LITERAL_EMIT = re.compile(r'\b(?:%s)\(\s*"([a-z_][a-z0-9_.]*)"' % "|".join(_EMIT_HELPERS))
_REQUEST_HELPERS = ("server_requests\\.send", "server_requests\\.send_async", "_ask", "_read_block")
_LITERAL_REQUEST = re.compile(r'\b(?:%s)\(\s*"([a-z_][a-z0-9_.]*)"' % "|".join(_REQUEST_HELPERS))
_LITERAL_FRAME = re.compile(r'"method":\s*"event".{0,120}?"type":\s*"([a-z_][a-z0-9_.]*)"', re.S)
_SIDE_AGENT = re.compile(r'_spawn_side_agent\((?:[^()]|\([^()]*\))*?"([a-z_][a-z0-9_.]*\.complete)"', re.S)
_SUBAGENT_RELAY = re.compile(r'"(subagent\.[a-z_]+)"')
_DESKTOP_UI_EMIT = re.compile(r'desktop_ui\.(?:emit|emit_or_error)\(\s*"([a-z_][a-z0-9_.]*)"')
_BROKER_FRAME = re.compile(r'^FRAME_[A-Z_]+ = "(browser\.controller\.[a-z_]+)"', re.M)
_SETUP_READY = re.compile(r'^SETUP_READY_EVENT = "([a-z_.]+)"', re.M)


def scan_literal_wire_names(root: Path, tool_modules) -> tuple[set[str], set[str]]:
    events: set[str] = set()
    requests: set[str] = set()
    for path in (root / "tui_gateway").glob("*.py"):
        text = path.read_text(encoding="utf-8-sig")
        events.update(_LITERAL_EMIT.findall(text))
        events.update(_LITERAL_FRAME.findall(text))
        events.update(_SIDE_AGENT.findall(text))
        requests.update(_LITERAL_REQUEST.findall(text))
    for path in (root / "tools").glob("delegate_tool*.py"):
        events.update(_SUBAGENT_RELAY.findall(path.read_text(encoding="utf-8-sig")))
    events.discard("subagent.text")  # mirrored as message.delta, never emitted
    for path in tool_modules:
        events.update(_DESKTOP_UI_EMIT.findall(path.read_text(encoding="utf-8-sig")))
    events.update(_BROKER_FRAME.findall((root / "gateway/browser_control_broker.py").read_text(encoding="utf-8-sig")))
    events.update(_SETUP_READY.findall((root / "hermes_cli/free_tier_bootstrap.py").read_text(encoding="utf-8-sig")))
    return events, requests


def main() -> int:
    sys.path.insert(0, str(ROOT))
    from tools.registry import _tool_module_candidates
    from tui_gateway import server
    from tui_gateway.agent_callbacks import _CHILD_DELTA_EVENTS
    from tui_gateway.change_watcher import _CHANGE_WATCHES
    from tui_gateway.contracts import registry

    events, requests = scan_literal_wire_names(ROOT, _tool_module_candidates(ROOT / "tools"))
    events.update(_CHANGE_WATCHES)
    events.update(_CHILD_DELTA_EVENTS.values())
    registry.assert_complete(server._methods, events, requests)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
