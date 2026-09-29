"""Bundled gateway platform manifests must decode UTF-8 independent of locale."""
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_bundled_manifest_name_under_ascii_locale(tmp_path):
    plugin_dir = tmp_path / "platform"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.yaml").write_bytes("name: 雪橋\n".encode("utf-8"))
    env = dict(os.environ, HERMES_HOME=str(tmp_path), PYTHONPATH=str(REPO_ROOT), LC_ALL="C",
               PYTHONCOERCECLOCALE="0")
    child = (
        "import locale, sys\n"
        "from pathlib import Path\n"
        "from gateway.config import _bundled_platform_manifest_name\n"
        "assert locale.getpreferredencoding(False).lower() != 'utf-8'\n"
        "assert _bundled_platform_manifest_name(Path(sys.argv[1])) == '\\u96ea\\u6a4b'\n"
    )
    result = subprocess.run([sys.executable, "-X", "utf8=0", "-c", child, str(plugin_dir)],
                            cwd=tmp_path, env=env, capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
