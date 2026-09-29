"""The clipboard probe decodes real UTF-8 child output even with an ASCII locale."""
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_clipboard_probe_decodes_utf8_child_under_ascii_locale(tmp_path):
    env = dict(os.environ, HERMES_HOME=str(tmp_path), PYTHONPATH=str(REPO_ROOT), LC_ALL="C",
               PYTHONCOERCECLOCALE="0")
    child = (
        "import locale, sys\n"
        "from hermes_cli.clipboard import _probe\n"
        "assert locale.getpreferredencoding(False).lower() != 'utf-8'\n"
        "assert _probe([sys.executable, '-c', \"import sys; sys.stdout.buffer.write(chr(0x96ea).encode('utf-8') + bytes([10]))\"], 5, "
        "lambda result: result.stdout == chr(0x96ea) + '\\n')\n"
    )
    result = subprocess.run([sys.executable, "-X", "utf8=0", "-c", child],
                            cwd=tmp_path, env=env, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
