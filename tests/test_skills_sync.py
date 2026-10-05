"""The .claude/skills mirrors must match docs/team/skills (runs the sync check)."""

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class TestSkillsSync(unittest.TestCase):
    def test_mirrors_in_sync(self) -> None:
        r = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "check_skills_sync.py")],
            capture_output=True,
            text=True,
            cwd=ROOT,
        )
        self.assertEqual(r.returncode, 0, msg=(r.stdout + r.stderr))


if __name__ == "__main__":
    unittest.main()
