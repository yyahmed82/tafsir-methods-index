"""Static + Playwright checks for the grounding UI (G-UI-1..4)."""

from __future__ import annotations

import json
import re
import sys
import threading
import unittest
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from grounding_contract import COMMITTEE_REASON_CODES, REASON_CODES  # noqa: E402

WEB = ROOT / "web"
TEMPLATE_FAHRAS = ROOT / "src" / "fahras_template.html"
TEMPLATE_READER = ROOT / "src" / "fahras_v2_template.html"
BUILT_FAHRAS = WEB / "fahras.html"
BUILT_READER = WEB / "reader.html"
SHOT_DIR = ROOT / "docs" / "branches" / "build-ui-grounding" / "shots"

LABEL_WAIT = "بانتظار المتخصص"
LABEL_CANDIDATE = "مرشّح للمراجعة — ليس اعتماداً"
LABEL_NOTES = "ملاحظة النموذج — غير مُسنَدة، ليست دليلاً"
LABEL_DISCLAIMER = (
    "وجود الشاهد لا يثبت صحة الاستنتاج؛ الاعتماد للمتخصص بعد فحص الدلالة"
)

HIGHLIGHT_ALL_NEEDLES = (
    'querySelectorAll(".hl, .mk")',
    "querySelectorAll('.hl, .mk')",
    "evidence_span_ids || curMove.span_ids",
    "evidence_span_ids || move.span_ids",
    "evidence_span_ids || m.span_ids",
)

DATA_RE = re.compile(
    r'<script type="application/json" id="methods-data">([^<]+)</script>'
)


def _payload(html: str) -> dict:
    m = DATA_RE.search(html)
    if not m:
        raise AssertionError("methods-data JSON missing")
    return json.loads(m.group(1))


def _fn_body(src: str, name: str) -> str:
    needle = "function " + name + "("
    start = src.find(needle)
    if start < 0:
        raise AssertionError(f"missing function {name}")
    nxt = src.find("\n  function ", start + len(needle))
    return src[start : nxt if nxt > 0 else len(src)]


class TestUiGroundingStatic(unittest.TestCase):
    def test_injected_reason_map_matches_contract(self) -> None:
        for path in (BUILT_FAHRAS, BUILT_READER):
            html = path.read_text(encoding="utf-8")
            data = _payload(html)
            self.assertEqual(data["reason_codes"], dict(REASON_CODES), path.name)
            self.assertEqual(
                data["committee_reason_codes"],
                dict(COMMITTEE_REASON_CODES),
                path.name,
            )

    def test_templates_do_not_hardcode_reason_arabic(self) -> None:
        blobs = [
            TEMPLATE_FAHRAS.read_text(encoding="utf-8"),
            TEMPLATE_READER.read_text(encoding="utf-8"),
        ]
        for ar in list(REASON_CODES.values()) + list(COMMITTEE_REASON_CODES.values()):
            for blob in blobs:
                self.assertNotIn(ar, blob, ar[:40])

    def test_three_labels_and_disclaimer_exist(self) -> None:
        for path in (
            TEMPLATE_FAHRAS,
            TEMPLATE_READER,
            BUILT_FAHRAS,
            BUILT_READER,
        ):
            html = path.read_text(encoding="utf-8")
            self.assertIn(LABEL_WAIT, html, path.name)
            self.assertIn(LABEL_CANDIDATE, html, path.name)
            self.assertIn(LABEL_NOTES, html, path.name)
            self.assertIn(LABEL_DISCLAIMER, html, path.name)

    def test_highlight_uses_evidence_ids_without_all_fallback(self) -> None:
        for path in (TEMPLATE_FAHRAS, TEMPLATE_READER, BUILT_FAHRAS, BUILT_READER):
            src = path.read_text(encoding="utf-8")
            hl = _fn_body(src, "highlightEvidenceSpans")
            flash = _fn_body(src, "flashEvidence")
            self.assertIn("evidenceIds", hl, path.name)
            self.assertIn("evidence_span_ids", flash, path.name)
            joined = hl + "\n" + flash
            for needle in HIGHLIGHT_ALL_NEEDLES:
                self.assertNotIn(needle, joined, f"{path.name}: {needle}")
            self.assertNotIn('querySelectorAll(".hl, .mk")', src)
            self.assertNotIn("evidence_span_ids || curMove.span_ids", src)


def _playwright_available() -> tuple[bool, str]:
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except ImportError:
        return False, "playwright Python package not importable"
    return True, ""


def _build_fixture_html() -> str:
    html = BUILT_READER.read_text(encoding="utf-8")
    data = _payload(html)
    window = data["tafsirs"]["al_tabari"]["windows"]["2_255"]
    by = {s["id"]: s for s in window["spans"]}

    def rng(*ids: str) -> tuple[int, int]:
        return min(by[i]["start"] for i in ids), max(by[i]["end"] for i in ids)

    spec_start, spec_end = rng("s007", "s008", "s009")
    auto_start, auto_end = rng("s012", "s013")
    evid_auto = "s012"
    specialist = {
        "move_id": "g-spec",
        "span_ids": ["s007", "s008", "s009"],
        "start": spec_start,
        "end": spec_end,
        "text": window["window_text"][
            spec_start - window["window_start"] : spec_end - window["window_start"]
        ],
        "primary": "M_LUGHA",
        "secondary": [],
        "certainty": "insufficient",
        "route": "specialist",
        "reason_code": "EVIDENCE_EMPTY",
        "evidence_span_ids": ["s-missing-no-such"],
        "author_verdict_span_ids": [],
        "rationale_ar": "تعليل اختباري غير مسند",
        "alternatives": ["M_RAY"],
        "unverified_model_notes": {
            "rationale_ar": "تعليل اختباري غير مسند",
            "alternatives": ["M_RAY"],
        },
        "score": {"total": 20, "parts": {}},
        "flags": [],
        "review_status": "pending",
        "origin": "ai",
    }
    auto = {
        "move_id": "g-auto",
        "span_ids": ["s012", "s013"],
        "start": auto_start,
        "end": auto_end,
        "text": window["window_text"][
            auto_start - window["window_start"] : auto_end - window["window_start"]
        ],
        "primary": "M_QURAN",
        "secondary": [],
        "certainty": "strong",
        "route": "auto_candidate",
        "reason_code": None,
        "evidence_span_ids": [evid_auto],
        "author_verdict_span_ids": ["s013"],
        "rationale_ar": "ملاحظة نموذج بلا إسناد",
        "alternatives": [],
        "score": {"total": 90, "parts": {}},
        "flags": [],
        "review_status": "pending",
        "origin": "ai",
    }
    block = {
        "annotator": "fixture",
        "moves": [specialist, auto],
        "summary": {},
    }
    committee = {
        "annotator": "committee",
        "moves": [
            {
                "move_id": "g-spec",
                "route": "specialist",
                "committee_reason_code": "weak_evidence",
            }
        ],
        "summary": {"route": "specialist"},
    }
    data["verified"]["2_255"] = {"fixture": block}
    data["tafsirs"]["al_tabari"]["verified"]["2_255"] = {"fixture": block}
    data["committee"] = {"2_255": committee}
    data["tafsirs"]["al_tabari"]["committee"] = {"2_255": committee}
    data["default_window"] = "2_255"
    data["default_tafsir"] = "al_tabari"
    embedded = json.dumps(data, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    embedded = embedded.replace("<", "\\u003c")
    m = DATA_RE.search(html)
    if not m:
        raise AssertionError("failed to find methods-data")
    patched = (
        html[: m.start()]
        + '<script type="application/json" id="methods-data">'
        + embedded
        + "</script>"
        + html[m.end() :]
    )
    return patched


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return


class TestUiGroundingPlaywright(unittest.TestCase):
    def test_reader_drawers_and_precise_highlight(self) -> None:
        ok, why = _playwright_available()
        if not ok:
            self.skipTest(why)
        from playwright.sync_api import sync_playwright

        fixture_html = _build_fixture_html()
        SHOT_DIR.mkdir(parents=True, exist_ok=True)
        fixture_path = WEB / "_grounding_fixture.html"
        fixture_path.write_text(fixture_html, encoding="utf-8")

        meaning = REASON_CODES["EVIDENCE_EMPTY"]
        committee_ar = COMMITTEE_REASON_CODES["weak_evidence"]

        class Handler(_QuietHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(WEB), **kwargs)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{port}/_grounding_fixture.html?mode=review"
        shots: list[str] = []
        try:
            with sync_playwright() as p:
                try:
                    browser = p.chromium.launch()
                except Exception as exc:
                    self.skipTest(f"chromium unavailable: {exc}")
                    return
                context = browser.new_context()
                page = context.new_page()
                for theme in ("light", "dark"):
                    for width, height in ((1440, 900), (375, 812)):
                        page.set_viewport_size({"width": width, "height": height})
                        page.goto(base, wait_until="domcontentloaded")
                        page.evaluate(
                            "(t) => document.documentElement.setAttribute('data-theme', t)",
                            theme,
                        )
                        page.wait_for_selector("#dec-route-host .g-route")
                        page.evaluate(
                            """() => {
                              var h = document.querySelector('.app-header');
                              if (h) h.style.display = 'none';
                            }"""
                        )
                        host = page.locator("#dec-route-host")
                        self.assertIn(LABEL_WAIT, host.inner_text())
                        self.assertIn(meaning, host.inner_text())
                        self.assertIn(committee_ar, host.inner_text())
                        panel = page.locator(".dec-panel")
                        panel.scroll_into_view_if_needed()
                        spec_name = f"reader-specialist-{theme}-{width}.png"
                        panel.screenshot(path=str(SHOT_DIR / spec_name))
                        shots.append(spec_name)

                        evid_spec = page.locator(".cite-evidence").count()
                        self.assertEqual(
                            evid_spec,
                            0,
                            "missing evidence id must not highlight anything",
                        )

                        if width == 375:
                            toggle = page.locator("#btn-toggle-mobile-queue")
                            if toggle.is_visible():
                                toggle.click()
                        page.locator("#tab-candidate").click()
                        page.locator(".q-it").first.click()
                        page.wait_for_selector("#dec-route-host .g-route.is-auto")
                        auto_host = page.locator("#dec-route-host")
                        self.assertIn(LABEL_CANDIDATE, auto_host.inner_text())
                        self.assertNotIn(meaning, auto_host.inner_text())
                        panel.scroll_into_view_if_needed()
                        auto_name = f"reader-auto-{theme}-{width}.png"
                        panel.screenshot(path=str(SHOT_DIR / auto_name))
                        shots.append(auto_name)

                        page.locator("#act-show-evidence").click()
                        page.wait_for_timeout(200)
                        counts = page.evaluate(
                            """() => {
                              const evid = document.querySelectorAll('.cite-evidence');
                              const verd = document.querySelectorAll('.cite-verdict');
                              const cur = document.querySelectorAll('.cur-move .src-run');
                              const curEvid = document.querySelectorAll('.cur-move .src-run.cite-evidence');
                              return {
                                evid: evid.length,
                                verd: verd.length,
                                cur: cur.length,
                                curEvid: curEvid.length
                              };
                            }"""
                        )
                        self.assertGreater(counts["evid"], 0)
                        self.assertGreater(counts["verd"], 0)
                        self.assertGreater(counts["cur"], counts["curEvid"])
                        self.assertEqual(counts["evid"], counts["curEvid"])
                context.close()
                browser.close()
        finally:
            server.shutdown()
            try:
                fixture_path.unlink()
            except OSError:
                pass
        self.assertEqual(len(shots), 8)


if __name__ == "__main__":
    unittest.main()
