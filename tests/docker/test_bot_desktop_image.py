"""The published desktop image must have the Bot Screen runtime, not just apt metadata."""

from __future__ import annotations

import json

from tests.docker.conftest import docker_exec, start_container


def test_desktop_variant_supplies_screen_binaries_and_chromium(desktop_image: str, container_name: str) -> None:
    start_container(desktop_image, container_name)
    result = docker_exec(container_name, "python", "-c", """
import json, shutil
from tools.bot_desktop import runtime
print(json.dumps({'missing': runtime.missing_binaries(), 'chromium': shutil.which('chromium'),
                  'packages': runtime.PACKAGES['apt'],
                  'installed': {p: __import__('subprocess').run(
                      ['dpkg-query', '-W', '-f=${Status}', p], capture_output=True, text=True).stdout
                      for p in runtime.PACKAGES['apt']}}))
""")
    assert result.returncode == 0, result.stderr
    state = json.loads(result.stdout)
    assert state["missing"] == []
    assert state["chromium"] and state["chromium"].startswith("/usr/bin/")
    assert all(status == "install ok installed" for status in state["installed"].values()), state["installed"]
