"""Historical source installer flags are discovered by executable help, not text."""
from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
COMMON = ROOT / "tests" / "install" / "e2e-assets" / "installer-common.sh"


@pytest.mark.parametrize("advertise,expected", [(True, 0), (False, 1)])
@pytest.mark.parametrize("manifest", [False, True])
def test_source_installer_desktop_flag_is_executable_capability(tmp_path, advertise, expected, manifest):
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    script = repo / "scripts" / "install.sh"
    script.write_text(
        '#!/usr/bin/env bash\n'
        '# --include-desktop occurs in this comment regardless of capability\n'
        'if [ "${1:-}" = --help ]; then\n'
        f'  printf "%s\\n" "Usage: install.sh --skip-setup --skip-browser'
        f'{" --manifest" if manifest else ""}{" --include-desktop" if advertise else ""}"\n'
        '  printf "%s\\n" "Unsupported --include-desktop in this release"\n'
        '  exit 0\n'
        'fi\n'
        'printf "%s\\n" "$@" > "$HERMES_TEST_ARGS"\n'
        'if [ "${2:-}" = --include-desktop ]; then\n'
        '  mkdir -p "$HERMES_TEST_ARTIFACT"\n'
        '  printf "built\\n" > "$HERMES_TEST_ARTIFACT/Hermes.exe"\n'
        'fi\n', encoding="utf-8")
    for args in (["init", "-q"], ["add", "scripts/install.sh"],
                 ["-c", "user.name=E2E", "-c", "user.email=e2e@example.test", "commit", "-qm", "fixture"]):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
    work = tmp_path / "work"
    logs = tmp_path / "logs"
    work.mkdir()
    logs.mkdir()
    artifact = tmp_path / "release"
    args_path = tmp_path / "installer-argv"
    cmd = (f'source {shlex.quote(str(COMMON))}\n'
           'fail() { printf "%s\\n" "$*" >&2; return 1; }\n'
           'ts_prefix() { cat; }\n'
           'log_group() { :; }\n'
           f'run_source_installer {shlex.quote(str(repo))} {shlex.quote(str(work))} '
           f'{shlex.quote(str(logs))} HEAD fixture desktop\n')
    result = subprocess.run(["bash", "-c", cmd],
                            env=dict(os.environ, HERMES_TEST_ARTIFACT=str(artifact), HERMES_TEST_ARGS=str(args_path)),
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == expected, result.stdout + result.stderr
    assert (artifact / "Hermes.exe").exists() is advertise
    if advertise:
        assert ("--skip-browser" in args_path.read_text(encoding="utf-8").splitlines()) is not manifest


def test_current_multiline_help_selects_bindable_flags(tmp_path):
    help_text = subprocess.run(["bash", str(ROOT / "scripts/install.sh"), "--help"],
                               capture_output=True, text=True, check=True, timeout=30).stdout
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / "scripts/install.sh").write_text(
        '#!/usr/bin/env bash\nif [ "${1:-}" = --help ]; then\n'
        f'  printf "%s\\n" {shlex.quote(help_text)}\n  exit 0\nfi\n'
        'printf "%s\\n" "$@" > "$HERMES_TEST_ARGS"\n', encoding="utf-8"
    )
    for args in (["init", "-q"], ["add", "scripts/install.sh"],
                 ["-c", "user.name=E2E", "-c", "user.email=e2e@example.test", "commit", "-qm", "fixture"]):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
    work, logs = tmp_path / "work", tmp_path / "logs"
    work.mkdir()
    logs.mkdir()
    args_path = tmp_path / "installer-argv"
    cmd = (f'source {shlex.quote(str(COMMON))}\n'
           'fail() { printf "%s\\n" "$*" >&2; return 1; }\n'
           'ts_prefix() { cat; }\nlog_group() { :; }\n'
           f'run_source_installer {shlex.quote(str(repo))} {shlex.quote(str(work))} '
           f'{shlex.quote(str(logs))} HEAD current\n')
    result = subprocess.run(["bash", "-c", cmd], env=dict(os.environ, HERMES_TEST_ARGS=str(args_path)),
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert args_path.read_text(encoding="utf-8").splitlines() == ["--non-interactive"]
