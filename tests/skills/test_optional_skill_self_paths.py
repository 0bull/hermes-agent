"""Fixture checks for the standalone optional-skill content lint.

Run the whole-tree policy separately:
    python optional-skills/lint_skill_content.py self-paths
    python optional-skills/lint_skill_content.py hangul optional-skills/software-development/ast-grep
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LINT = REPO / "optional-skills" / "lint_skill_content.py"


def _lint(rule, root):
    return subprocess.run([sys.executable, str(LINT), rule, str(root)],
                          capture_output=True, text=True, timeout=30)


def test_self_paths_lint_fixtures(tmp_path):
    moved = tmp_path / "new-category" / "moved-skill"
    moved.mkdir(parents=True)
    (moved / "SKILL.md").write_text("---\nname: moved-skill\n---\n", encoding="utf-8")
    notes = moved / "references.md"
    notes.write_text(
        'skills/old-category/moved-skill/run.sh\n'
        'Path("~") / "skills" / "old-category" / "moved-skill" / "script.py"\n'
        'skills/other-category/other-skill/run.sh\n'
        'skills/new-category/moved-skill/run.sh\n', encoding="utf-8")
    bad = _lint("self-paths", tmp_path)
    assert bad.returncode == 1, bad.stderr
    assert f"{notes}:1:" in bad.stdout
    assert f"{notes}:2:" in bad.stdout
    assert f"{notes}:3:" not in bad.stdout
    assert f"{notes}:4:" not in bad.stdout

    notes.write_text('skills/other-category/other-skill/run.sh\n'
                     'skills/new-category/moved-skill/run.sh\n', encoding="utf-8")
    ok = _lint("self-paths", tmp_path)
    assert ok.returncode == 0, ok.stdout + ok.stderr


def test_hangul_lint_fixture(tmp_path):
    reference = tmp_path / "references" / "intro.md"
    reference.parent.mkdir()
    reference.write_text("English\n한국어\n", encoding="utf-8")
    bad = _lint("hangul", tmp_path)
    assert bad.returncode == 1, bad.stderr
    assert f"{reference}:2:" in bad.stdout
    reference.write_text("English\n", encoding="utf-8")
    installer = tmp_path / "install.ps1"
    installer.write_text("Write-Output '한국어'\n", encoding="utf-8")
    powershell = _lint("hangul", tmp_path)
    assert powershell.returncode == 1
    assert f"{installer}:1:" in powershell.stdout
    installer.write_text("Write-Output 'English'\n", encoding="utf-8")
    assert _lint("hangul", tmp_path).returncode == 0
