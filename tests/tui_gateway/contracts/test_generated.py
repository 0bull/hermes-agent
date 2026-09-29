"""Generated artifacts stay fresh; live gateway frames stay in the declared contract."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[3]
GEN = REPO / "scripts" / "gen_gateway_contracts.py"


@pytest.fixture(scope="module")
def gen():
    spec = importlib.util.spec_from_file_location("gen_gateway_contracts", GEN)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_generated_files_are_current(gen):
    """Both committed artefacts equal an in-memory regeneration (byte-for-byte)."""
    stale = [path.relative_to(REPO) for path, text in gen.render_all().items()
             if (path.read_text(encoding="utf-8") if path.exists() else None) != text]
    assert not stale, f"stale generated contract files {stale}: run scripts/gen_gateway_contracts.py"


def test_live_event_frames_obey_contract_and_display_gate(monkeypatch):
    from tui_gateway import server
    from tui_gateway.contracts import registry

    frames = []
    sid = "wire-contract-gate"
    monkeypatch.setattr(server, "write_json", lambda frame: frames.append(frame) or True)
    monkeypatch.setitem(server._sessions, sid, {
        "show_reasoning": False, "tool_progress_mode": "off", "tool_started_at": {},
        "edit_snapshots": {}, "agent": SimpleNamespace(reasoning_config={"enabled": True, "effort": "high"}),
    })
    server._on_tool_start(sid, "card-1", "image_generate", {"prompt": "cat"})
    server._on_tool_complete(sid, "card-1", "image_generate", {"prompt": "cat"}, '{"success": true}')
    server._agent_cbs(sid)["reasoning_callback"]("private thought")
    assert [frame["params"]["type"] for frame in frames] == ["tool.start", "tool.complete"]
    for frame in frames:
        assert frame["jsonrpc"] == "2.0" and frame["method"] == "event"
        assert frame["params"]["session_id"] == sid
        assert frame["params"]["type"] in registry.EVENTS
        registry.check_payload(frame["params"]["type"], frame["params"]["payload"])
        assert frame["params"]["payload"]["tool_id"] == "card-1"
        assert frame["params"]["payload"]["name"] == "image_generate"
