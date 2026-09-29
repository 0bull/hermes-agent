#!/usr/bin/env python3
"""Content hygiene checks for optional skills; run independently of smoke tests.

Usage: python optional-skills/lint_skill_content.py self-paths [optional-skills-root]
       python optional-skills/lint_skill_content.py hangul [skill-root]
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

OPTIONAL = Path(__file__).resolve().parent
SCAN_SUFFIXES = {".md", ".py", ".ps1", ".txt", ".sh", ".yaml", ".yml", ".toml", ".json"}
MAX_SCAN_BYTES = 2 * 1024 * 1024
HANGUL = re.compile(r"[\uac00-\ud7a3]")


def scan_files(root: Path):
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix.lower() in SCAN_SUFFIXES and path.stat().st_size <= MAX_SCAN_BYTES:
            yield path


def stale_self_paths(optional: Path):
    """Yield path:line diagnostics for stale references to a skill's own name."""
    for skill_md in sorted(optional.rglob("SKILL.md")):
        root = skill_md.parent
        name = re.escape(root.name)
        joined = re.compile(rf"skills/([\w.-]+)/{name}\b")
        segmented = re.compile(rf'["\']skills["\']\s*/\s*["\']([\w.-]+)["\']\s*/\s*["\']{name}["\']')
        for path in scan_files(root):
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except (UnicodeDecodeError, OSError):
                continue
            for line_no, line in enumerate(lines, 1):
                for pattern in (joined, segmented):
                    for match in pattern.finditer(line):
                        if match.group(1) != root.parent.name:
                            yield f"{path}:{line_no}: stale self path {match.group(0)}"


def hangul_content(root: Path):
    for path in scan_files(root):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        for line_no, line in enumerate(lines, 1):
            if HANGUL.search(line):
                yield f"{path}:{line_no}: Hangul content"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Check optional skill content hygiene")
    parser.add_argument("rule", choices=("self-paths", "hangul"))
    parser.add_argument("root", nargs="?", type=Path)
    args = parser.parse_args(argv)
    root = args.root or OPTIONAL
    hits = list(stale_self_paths(root) if args.rule == "self-paths" else hangul_content(root))
    for hit in hits:
        print(hit)
    return 1 if hits else 0


if __name__ == "__main__":
    raise SystemExit(main())
