"""The Nix wheel ships importable root modules, not just package directories."""
from __future__ import annotations

import os
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_pyproject_has_no_static_py_modules_list():
    cfg = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert "py-modules" not in cfg["tool"]["setuptools"], (
        "root modules are derived in setup.py::_root_py_modules(); a static py-modules list drifts "
        "from the tree and breaks installed wheels. Do not add it back."
    )


def test_nix_wheel_ships_importable_root_modules(tmp_path):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    config = tmp_path / "dist-extra.cfg"
    config.write_text(
        f"[build]\nbuild_base = {scratch / 'build'}\n\n[egg_info]\negg_base = {scratch}\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, "-c", "from setuptools.build_meta import build_wheel; build_wheel(%r)" % str(tmp_path)],
        cwd=REPO_ROOT,
        env={**os.environ, "HERMES_NIX_BUILD": "1", "DIST_EXTRA_CONFIG": str(config)},
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, result.stderr
    wheels = list(tmp_path.glob("*.whl"))
    assert len(wheels) == 1, wheels
    site = tmp_path / "unpacked-wheel"
    with zipfile.ZipFile(wheels[0]) as wheel:
        shipped = {Path(name).stem for name in wheel.namelist() if "/" not in name and name.endswith(".py")}
        expected = {path.stem for path in REPO_ROOT.glob("*.py") if path.name != "setup.py" and not path.name.startswith("_test_")}
        assert expected <= shipped, sorted(expected - shipped)
        assert "setup" not in shipped
        wheel.extractall(site)

    probe = subprocess.run(
        [sys.executable, "-I", "-c", (
            "import importlib, pathlib, sys; "
            "site = pathlib.Path(sys.argv[1]); sys.path.insert(0, str(site)); "
            "names = ('hermes_state', 'run_agent', 'toolsets'); "
            "assert all(pathlib.Path(importlib.import_module(n).__file__).is_relative_to(site) "
            "for n in names)"
        ), str(site)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert probe.returncode == 0, probe.stderr
