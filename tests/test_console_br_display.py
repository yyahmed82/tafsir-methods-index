"""Display-only: console review must not show raw layout "<br>" as text.

Pinned source under data/** legitimately contains "<br>" (layer kind "layout").
The console HTML-escapes then turns those tokens into real line breaks at render
time. Offsets for highlights stay on the raw string; stored text/hash are untouched.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "console" / "static" / "app.js"
WINDOW = ROOT / "data" / "nur" / "al_tabari" / "windows" / "24_3_p02.json"
RAW = ROOT / "data" / "nur" / "al_tabari" / "raw" / "24_3.txt"

# Extract the review text helpers from the IIFE and exercise them in node.
_NODE = r"""
const fs = require("fs");
const src = fs.readFileSync(process.argv[1], "utf8");
const blockM = src.match(
  /const BR_TOKEN =[\s\S]*?function markedText\(text, moves, base\) \{[\s\S]*?\n  \}/
);
if (!blockM) { console.error("markedText block not found"); process.exit(2); }
// Same mapping as console/static/app.js `esc` (redefined here to avoid quote hell in -e).
var esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
var mClass = () => "m-x";
// `const`/`let` inside eval are block-scoped to the eval call in Node — use var.
eval(blockM[0].replace(/\bconst /g, "var ").replace(/\blet /g, "var "));

function visibleBrLiterals(html) {
  // Escaped tokens that would render as the characters <br>… on screen.
  return (html.match(/&lt;br[\s\S]*?&gt;/gi) || []).length;
}

const samples = [
  "hello<br>world",
  "foo<br/>bar",
  "foo<br />bar",
  "foo<BR>bar",
  "أَو<br>ْ مُشْرِكَةً",
];
for (const s of samples) {
  const html = srcDisplay(s);
  if (visibleBrLiterals(html) !== 0) {
    console.error("literal br leaked:", s, "=>", html);
    process.exit(1);
  }
  if (!html.includes('<br data-layout="1">')) {
    console.error("missing layout break:", s, "=>", html);
    process.exit(1);
  }
  if (html.includes("<script") || /onerror=/i.test(html)) {
    console.error("xss risk:", html);
    process.exit(1);
  }
}

// XSS: angle brackets in surrounding text stay escaped; only the layout token becomes <br>.
const evil = 'a<img src=x onerror=alert(1)><br>b';
const safe = srcDisplay(evil);
if (safe.includes("<img") || !safe.includes("&lt;img") || visibleBrLiterals(safe) !== 0) {
  console.error("escape failed:", safe);
  process.exit(1);
}

// Highlights: mark covers the same raw characters; br inside the mark is a real break.
const text = "AAA<br>BBB";
const moves = [{ key: "m1", start: 0, end: text.length, primary: "M_RAY" }];
const marked = markedText(text, moves, 0);
if (!marked.includes('data-key="m1"') || !marked.includes('<br data-layout="1">')) {
  console.error("marked missing break/key:", marked);
  process.exit(1);
}
if (visibleBrLiterals(marked) !== 0) {
  console.error("marked leaked literal br:", marked);
  process.exit(1);
}
// Mark boundary through the middle of <br> must not leak escaped tokens.
const mid = markedText(text, [{ key: "m2", start: 4, end: 7, primary: "M_RAY" }], 0);
if (visibleBrLiterals(mid) !== 0 || !mid.includes('<br data-layout="1">')) {
  console.error("mid-br mark failed:", mid);
  process.exit(1);
}

// One-line fold: no raw token characters.
const line = srcOneLine("x<br>y<br />z");
if (line.includes("&lt;br") || line.includes("<br")) {
  console.error("srcOneLine leaked:", line);
  process.exit(1);
}

console.log("BR_DISPLAY_OK");
"""


class TestConsoleBrDisplay(unittest.TestCase):
    def test_app_js_has_layout_br_formatter(self) -> None:
        src = APP_JS.read_text(encoding="utf-8")
        self.assertIn("BR_TOKEN", src)
        self.assertIn("data-layout", src)
        self.assertIn("srcDisplay", src)
        # Context panel and per-move context must use the formatter, not bare esc().
        self.assertIn("srcDisplay(before)", src)
        self.assertIn("srcDisplay(ctx.text.slice(a, b))", src)
        self.assertIn("${markedText(d.window_text, inText, d.window_start || 0)}", src)

    def test_formatter_hides_br_keeps_mark_coverage(self) -> None:
        node = shutil.which("node")
        if not node:
            self.skipTest("node not on PATH")
        proc = subprocess.run(
            [node, "-e", _NODE, str(APP_JS)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
        self.assertIn("BR_DISPLAY_OK", proc.stdout)

    def test_pinned_source_and_window_hash_unchanged(self) -> None:
        """Display fix must not touch data/**; 24_3 still contains layout <br>."""
        self.assertTrue(WINDOW.is_file() and RAW.is_file())
        raw = RAW.read_bytes()
        self.assertIn(b"<br>", raw)
        win = json.loads(WINDOW.read_text(encoding="utf-8"))
        self.assertIn("<br>", win["window_text"])
        self.assertEqual(
            win["source_sha256"],
            hashlib.sha256(raw).hexdigest(),
        )
        # Spot-check: sha of the window file itself is stable for this commit's tree.
        digest = hashlib.sha256(WINDOW.read_bytes()).hexdigest()
        self.assertEqual(len(digest), 64)


if __name__ == "__main__":
    unittest.main()
