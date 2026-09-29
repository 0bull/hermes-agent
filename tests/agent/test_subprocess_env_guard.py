"""An assigned card's gh child runs with the target home, not launch credentials."""
import json
import os
import subprocess
import sys

from hermes_cli.kanban_pr_acceptance import _gh_env


def test_assigned_gh_child_does_not_inherit_launch_secrets(tmp_path, monkeypatch):
    launch = tmp_path / "launch"
    target = tmp_path / "assignee"
    launch.mkdir()
    target.mkdir()
    (target / ".env").write_text("GH_TOKEN=target-fake-token\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(launch))
    monkeypatch.setenv("GH_TOKEN", "launch-fake-token")
    monkeypatch.setenv("GATEWAY_RELAY_SECRET", "launch-fake-relay-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "launch-fake-provider-secret")
    env = _gh_env(str(target))
    assert env is not None
    code = ("import json, os; print(json.dumps({k: os.getenv(k) for k in "
            "('HERMES_HOME', 'GH_TOKEN', 'GATEWAY_RELAY_SECRET', 'OPENAI_API_KEY')}))")
    result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True,
                            text=True, encoding="utf-8", timeout=10)
    assert result.returncode == 0, result.stderr
    child = json.loads(result.stdout)
    assert child == {"HERMES_HOME": str(target), "GH_TOKEN": "target-fake-token",
                     "GATEWAY_RELAY_SECRET": None, "OPENAI_API_KEY": None}
