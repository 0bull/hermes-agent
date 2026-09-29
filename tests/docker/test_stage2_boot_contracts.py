"""Exercise the wired stage2 hook across real container boots and restarts."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from tests.docker.conftest import docker_exec, restart_container, start_container, wait_for_container_ready


_HOME = "/opt/data"
_KEY = re.compile(r"^[0-9a-f]{64}$")
_ROUTING = ("HERMES_PORTAL_BASE_URL", "NOUS_PORTAL_BASE_URL", "NOUS_INFERENCE_BASE_URL")


def _probe(container: str, code: str, *, user: str = "hermes") -> dict:
    result = docker_exec(container, "python", "-c", code, user=user)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _env(container: str, path: str = f"{_HOME}/.env") -> dict:
    return _probe(container, f"""
import json, os, stat
from pathlib import Path
from agent.secret_scope import load_env_file
p = Path({path!r})
print(json.dumps({{'values': load_env_file(p), 'lines': p.read_text().splitlines(),
                  'mode': stat.S_IMODE(p.stat().st_mode), 'uid': p.stat().st_uid}}))
""")


def _lines(state: dict, key: str) -> list[str]:
    return [line for line in state["lines"] if line.startswith(key + "=")]


def test_key_bootstrap_on_blank_home_and_operator_keys(built_image: str, container_name: str) -> None:
    start_container(built_image, container_name)
    # Observe the copied template inside the image, not a .dockerignore rule.
    seed = _probe(container_name, """
import json
from pathlib import Path
example = Path('/opt/hermes/.env.example').read_text()
actual = Path('/opt/data/.env').read_text()
print(json.dumps({'seeded': bool(example) and actual.startswith(example)}))
""")
    assert seed["seeded"]
    state = _env(container_name)
    assert "API_SERVER_KEY" in state["values"], "boot did not provision the loopback key"
    assert _KEY.fullmatch(state["values"]["API_SERVER_KEY"])
    assert state["mode"] == 0o600
    assert len(_lines(state, "API_SERVER_KEY")) == 1

    # Reproduce a missing seed (e.g. a legacy image without .env.example) on a persisted home.
    docker_exec(container_name, "rm", f"{_HOME}/.env").check_returncode()
    restart_container(container_name)
    state = _env(container_name)
    assert _KEY.fullmatch(state["values"]["API_SERVER_KEY"])
    assert state["mode"] == 0o600

    key = "operator-file-key-0123456789"
    docker_exec(container_name, "sh", "-c",
                f"printf 'OTHER=kept\\nAPI_SERVER_KEY={key}\\n' > {_HOME}/.env").check_returncode()
    restart_container(container_name)
    state = _env(container_name)
    assert state["values"]["API_SERVER_KEY"] == key
    assert state["values"]["OTHER"] == "kept"
    assert _lines(state, "API_SERVER_KEY") == [f"API_SERVER_KEY={key}"]


def test_container_key_overrides_stale_empty_assignment(built_image: str, container_name: str) -> None:
    key = "operator-container-key-0123456789"
    start_container(built_image, container_name, f"API_SERVER_KEY={key}")
    state = _env(container_name)
    assert not _lines(state, "API_SERVER_KEY")
    docker_exec(container_name, "sh", "-c",
                f"printf 'OTHER=kept\\nAPI_SERVER_KEY=\\n' > {_HOME}/.env").check_returncode()
    restart_container(container_name)
    state = _env(container_name)
    assert state["values"]["OTHER"] == "kept"
    assert not _lines(state, "API_SERVER_KEY")
    # Read with the same dotenv override rule as the gateway, not just shell text.
    result = docker_exec(container_name, "python", "-c",
                         "import os; from dotenv import load_dotenv; "
                         "load_dotenv('/opt/data/.env', override=True); print(os.environ['API_SERVER_KEY'])")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == key


def test_readonly_env_warns_without_aborting_boot(
    built_image: str, container_name: str, tmp_path: Path,
) -> None:
    env_file = tmp_path / "operator.env"
    env_file.write_text("OTHER=kept\n")
    subprocess.run(
        ["docker", "run", "-d", "--name", container_name,
         "--mount", f"type=bind,source={env_file},target=/opt/data/.env,readonly",
         built_image, "sleep", "infinity"],
        capture_output=True, check=True, timeout=60,
    )
    wait_for_container_ready(container_name)
    assert env_file.read_text() == "OTHER=kept\n"
    logs = subprocess.run(["docker", "logs", container_name], capture_output=True, text=True, timeout=10)
    assert "could not write API_SERVER_KEY" in logs.stdout + logs.stderr


def test_weak_container_key_warns_without_shadowing_file_key(built_image: str, container_name: str) -> None:
    start_container(built_image, container_name, "API_SERVER_KEY=short-key")
    first = _env(container_name)
    assert not _lines(first, "API_SERVER_KEY")
    logs = subprocess.run(["docker", "logs", container_name], capture_output=True, text=True, timeout=10)
    assert "shorter than 16 characters" in logs.stdout + logs.stderr

    key = "operator-file-key-0123456789"
    docker_exec(container_name, "sh", "-c",
                f"printf 'API_SERVER_KEY={key}\\n' > {_HOME}/.env").check_returncode()
    restart_container(container_name)
    assert _env(container_name)["values"]["API_SERVER_KEY"] == key
    logs = subprocess.run(["docker", "logs", container_name], capture_output=True, text=True, timeout=10)
    # The persisted file key wins despite a weak container variable.
    assert "the .env value wins" in logs.stdout + logs.stderr
    assert (logs.stdout + logs.stderr).count("shorter than 16 characters") == 1


def test_routing_values_reach_profiles_and_reconcile_on_restart(built_image: str, container_name: str) -> None:
    portal = "https://portal.example.test"
    inference = "https://inference.example.test/v1"
    start_container(built_image, container_name,
                    f"HERMES_PORTAL_BASE_URL={portal}", f"NOUS_PORTAL_BASE_URL={portal}",
                    f"NOUS_INFERENCE_BASE_URL={inference}")
    docker_exec(container_name, "python", "-c", """
from pathlib import Path
root = Path('/opt/data/profiles')
for name in ('work', 'ops'):
    (root / name).mkdir(parents=True, exist_ok=True)
(root / 'ops' / '.env').write_text('SLACK_BOT_TOKEN=preserved\\nHERMES_PORTAL_BASE_URL=https://old.example.test\\n')
""").check_returncode()
    restart_container(container_name)
    for path in (f"{_HOME}/.env", f"{_HOME}/profiles/work/.env", f"{_HOME}/profiles/ops/.env"):
        state = _env(container_name, path)
        assert state["values"]["HERMES_PORTAL_BASE_URL"] == portal
        assert state["values"]["NOUS_PORTAL_BASE_URL"] == portal
        assert state["values"]["NOUS_INFERENCE_BASE_URL"] == inference
        assert all(len(_lines(state, key)) == 1 for key in _ROUTING)
    assert _env(container_name, f"{_HOME}/profiles/ops/.env")["values"]["SLACK_BOT_TOKEN"] == "preserved"
    assert _env(container_name, f"{_HOME}/profiles/work/.env")["mode"] == 0o600
    before = [_env(container_name, path)["lines"] for path in
              (f"{_HOME}/.env", f"{_HOME}/profiles/work/.env", f"{_HOME}/profiles/ops/.env")]
    restart_container(container_name)
    assert before == [_env(container_name, path)["lines"] for path in
                      (f"{_HOME}/.env", f"{_HOME}/profiles/work/.env", f"{_HOME}/profiles/ops/.env")]


def test_unset_routing_removes_only_managed_lines_on_next_boot(built_image: str, container_name: str) -> None:
    portal = "https://portal.example.test"
    start_container(built_image, container_name, f"HERMES_PORTAL_BASE_URL={portal}")
    docker_exec(container_name, "sh", "-c",
                "printf 'HERMES_PORTAL_BASE_URL=https://by-hand.example.test\\nOTHER=kept\\n' "
                ">> /opt/data/.env").check_returncode()
    first = _env(container_name)
    assert len(_lines(first, "HERMES_PORTAL_BASE_URL")) == 2
    # A new container using the persisted volume has no deploy override at all.
    mount = subprocess.run(
        ["docker", "inspect", "--format",
         '{{range .Mounts}}{{if eq .Destination "/opt/data"}}{{.Name}}{{end}}{{end}}', container_name],
        capture_output=True, text=True, check=True, timeout=10,
    ).stdout.strip()
    assert mount, "the image must persist /opt/data in a Docker volume"
    # Readiness is append-only on the persisted volume; clear the previous boot's marker.
    docker_exec(container_name, "truncate", "-s", "0", "/opt/data/logs/container-boot.log").check_returncode()
    subprocess.run(["docker", "stop", container_name], capture_output=True, check=True, timeout=30)
    next_name = container_name + "-unset"
    try:
        subprocess.run(["docker", "run", "-d", "--name", next_name,
                        "-v", f"{mount}:/opt/data", built_image, "sleep", "infinity"],
                       capture_output=True, check=True, timeout=60)
        wait_for_container_ready(next_name)
        state = _env(next_name)
        logs = subprocess.run(["docker", "logs", next_name], capture_output=True, text=True, timeout=10)
        assert _lines(state, "HERMES_PORTAL_BASE_URL") == [
            "HERMES_PORTAL_BASE_URL=https://by-hand.example.test"
        ], logs.stdout + logs.stderr
        assert state["values"]["OTHER"] == "kept"
    finally:
        subprocess.run(["docker", "rm", "-f", next_name], capture_output=True, timeout=10)
        # The original container's anonymous volume is no longer needed.
        subprocess.run(["docker", "rm", "-f", "-v", container_name], capture_output=True, timeout=10)
        subprocess.run(["docker", "volume", "rm", mount], capture_output=True, timeout=10)


def test_symlinked_seed_and_ownership_targets_leave_outside_unchanged(
    built_image: str, container_name: str,
) -> None:
    start_container(built_image, container_name)
    docker_exec(container_name, "python", "-c", """
from pathlib import Path
import os
home = Path('/opt/data')
(home / '.env').unlink()
outside = Path('/opt/outside-stage2.env')
outside.write_text('SENTINEL=untouched\\n')
(home / '.env').symlink_to(outside)
cron = home / 'cron'
cron.rmdir()
target = Path('/opt/outside-stage2-cron')
target.mkdir()
(target / 'sentinel').write_text('untouched')
cron.symlink_to(target, target_is_directory=True)
(home / 'profiles').mkdir(exist_ok=True)
(home / 'profiles' / 'owned').mkdir(exist_ok=True)
(home / 'profiles' / 'owned' / 'sample').write_text('repair me')
os.chown(home / 'profiles' / 'owned' / 'sample', 0, 0)
""", user="root").check_returncode()
    before = _probe(container_name, """
import json, os
from pathlib import Path
paths = ['/opt/outside-stage2.env', '/opt/outside-stage2-cron/sentinel']
print(json.dumps({p: [Path(p).read_text(), os.stat(p).st_uid, os.stat(p).st_gid] for p in paths}))
""", user="root")
    restart_container(container_name)
    after = _probe(container_name, """
import json, os
from pathlib import Path
paths = ['/opt/outside-stage2.env', '/opt/outside-stage2-cron/sentinel']
print(json.dumps({p: [Path(p).read_text(), os.stat(p).st_uid, os.stat(p).st_gid] for p in paths}))
""", user="root")
    assert after == before
    state = _probe(container_name, """
import json, os
from pathlib import Path
h = Path('/opt/data')
print(json.dumps({'env_link': (h / '.env').is_symlink(), 'cron_link': (h / 'cron').is_symlink(),
                  'repaired_uid': (h / 'profiles/owned/sample').stat().st_uid,
                  'hermes_uid': os.getuid()}))
""")
    assert state["env_link"] and state["cron_link"]
    assert state["repaired_uid"] == state["hermes_uid"]
    logs = subprocess.run(["docker", "logs", container_name], capture_output=True, text=True, timeout=10)
    assert "refusing" in logs.stdout + logs.stderr
