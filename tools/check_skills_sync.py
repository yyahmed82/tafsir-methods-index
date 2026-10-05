"""Fail (exit 1) if any .claude/skills/<name> differs from docs/team/skills/<name>.

Canonical source: docs/team/skills/<name>/.
Auto-load mirror for Claude Code: .claude/skills/<name>/ (plain copies, no symlinks).
Run: python tools/check_skills_sync.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CANON = ROOT / "docs" / "team" / "skills"
MIRROR = ROOT / ".claude" / "skills"

# Skills mirrored for Claude Code auto-load. The three mirqah-* skills from
# PR #8 live only under docs/team/skills/ until that PR merges.
SKILLS = (
    "fahras-tafsir-indexing",
    "vibe-coding-project-auditor",
    "web-design-guidelines",
    "impeccable",
    "clean-code-guard",
    "test-guard",
)


def _files(base: Path) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    for p in sorted(base.rglob("*")):
        if p.is_file():
            out[p.relative_to(base).as_posix()] = p.read_bytes()
    return out


def main() -> int:
    errors: list[str] = []
    for name in SKILLS:
        src, dst = CANON / name, MIRROR / name
        if not src.is_dir():
            errors.append(f"missing canonical dir: {src}")
            continue
        if not dst.is_dir():
            errors.append(f"missing mirror dir: {dst}")
            continue
        a, b = _files(src), _files(dst)
        for rel in sorted(set(a) | set(b)):
            if rel not in a:
                errors.append(f"{name}: extra file in mirror: {rel}")
            elif rel not in b:
                errors.append(f"{name}: missing file in mirror: {rel}")
            elif a[rel] != b[rel]:
                errors.append(f"{name}: content differs: {rel}")
    for e in errors:
        print(f"skills-sync FAIL: {e}", file=sys.stderr)
    if errors:
        return 1
    print(f"skills-sync OK: {len(SKILLS)} skills in sync")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
