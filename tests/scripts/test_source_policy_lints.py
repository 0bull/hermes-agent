"""Sabotage fixtures: source policy checks report violations outside pytest discovery."""
from pathlib import Path

from scripts import check_locked_readers, check_source_policies as lint


def _put(root: Path, name: str, source: str):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path


def test_cli_subprocess_checks_sibling_kwargs_and_timeout(tmp_path):
    _put(tmp_path, "hermes_cli/clipboard.py", "import subprocess\n_TEXT = dict(text=True)\nsubprocess.run(['child'], **_TEXT)\n")
    # The text option is spread through a shared dict; the probe timeout is also absent.
    findings = list(lint.check_cli_subprocess(tmp_path))
    assert any("timeout" in f and ":3:" in f for f in findings), findings
    assert any("encoding" in f and ":3:" in f for f in findings), findings


def test_config_defaults_duplicate_is_reported_at_real_owner(tmp_path):
    _put(tmp_path, "hermes_cli/config_defaults.py", "DEFAULT_CONFIG = {'model': 1, 'model': 2}\n")
    assert any("duplicate DEFAULT_CONFIG key" in f for f in lint.check_config_keys(tmp_path))


def test_raw_spawn_and_config_read_both_report_file_line(tmp_path):
    _put(tmp_path, "agent/child.py", "import os, subprocess\nenv = os.environ.copy()\nsubprocess.run(['child'], env=env)\n")
    _put(tmp_path, "agent/load.py", "import yaml\np = 'config.yaml'\nvalue = yaml.safe_load(p)\n")
    assert any("agent/child.py:2:" in f for f in lint.check_spawn_env(tmp_path))
    assert any("agent/load.py:3:" in f for f in lint.check_config_reads(tmp_path))


def test_gateway_utf8_and_relay_platform_crypto_but_not_channel_auth(tmp_path):
    _put(tmp_path, "gateway/config.py", "from pathlib import Path\nPath('a').read_text()\n")
    _put(tmp_path, "gateway/relay/auth.py", "import hmac\nhmac.digest(b'a', b'b', 'sha256')\n")
    _put(tmp_path, "gateway/relay/adapter.py", "from gateway.platforms.wecom_crypto import decrypt\nverify_signature(event)\n")
    assert list(lint.check_gateway_utf8(tmp_path)) == ["gateway/config.py:2: text file I/O without encoding="]
    assert len(list(lint.check_relay_crypto(tmp_path))) == 2
    _put(tmp_path, "gateway/relay/crypto.py", "from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey\n")
    assert any("crypto.py:1:" in f for f in lint.check_relay_crypto(tmp_path))


def test_resolution_bare_lookup_and_known_path_table(tmp_path):
    _put(tmp_path, "agent/probe.py", "import shutil\ndef probe():\n    return shutil.which('node')\n")
    findings = list(lint.check_resolution(tmp_path))
    assert any("agent/probe.py:3:" in f and "node" in f for f in findings)
    assert any("agent/probe.py::probe" in f for f in findings)
    _put(tmp_path, "agent/paths.py", "PATHS = ['.local/bin', '/opt/homebrew/bin']\n")
    assert any("agent/paths.py::<module>" in f and "known_path_table" in f
               for f in lint.check_resolution(tmp_path))


def test_state_lint_catches_reader_in_mixin_not_writer(tmp_path):
    _put(tmp_path, "hermes_state.py", "class SessionDB: pass\n")
    _put(tmp_path, "hermes_state_search.py", "class SessionSearchMixin:\n    def read(self):\n        with self._lock:\n            return self._conn.execute('SELECT 1').fetchone()\n    def write(self):\n        with self._lock:\n            self._conn.execute('UPDATE t SET x=1')\n")
    for name, cls in (("hermes_state_schema.py", "SessionSchemaMixin"), ("hermes_state_portability.py", "SessionPortabilityMixin")):
        _put(tmp_path, name, f"class {cls}: pass\n")
    violations = check_locked_readers._scan_all_state_sources(tmp_path)
    assert len(violations) == 1 and "hermes_state_search.py: read" in violations[0], violations
