"""A new literal gateway event cannot evade the standalone wire lint."""
from pathlib import Path

import pytest

from scripts.check_gateway_contracts import scan_literal_wire_names
from tui_gateway.contracts import registry


def test_uncontracted_emitter_is_discovered_and_rejected(tmp_path: Path):
    for directory in ("tui_gateway", "tools", "gateway", "hermes_cli"):
        (tmp_path / directory).mkdir()
    (tmp_path / "tui_gateway" / "new_event.py").write_text(
        '_emit("missing.fixture", sid, {})\nserver_requests.send("missing.request", {})\n', encoding="utf-8"
    )
    (tmp_path / "gateway" / "browser_control_broker.py").write_text("", encoding="utf-8")
    (tmp_path / "hermes_cli" / "free_tier_bootstrap.py").write_text("", encoding="utf-8")

    events, requests = scan_literal_wire_names(tmp_path, [])
    assert "missing.fixture" in events
    assert "missing.request" in requests
    with pytest.raises(registry.ContractViolation, match="missing.fixture"):
        registry.assert_complete({}, events, requests)
