"""Static + Playwright checks for the grounding UI (G-UI-1..4)."""

from __future__ import annotations

import hashlib
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
LABEL_LEGACY = "لا رمز سبب: تشغيل سابق لعقد الإسناد"
LABEL_UNKNOWN = "رمز سبب غير معروف: "
UNKNOWN_CODE = "NEW_CODE"
XSS_RATIONALE = "<img src=x onerror=alert(1)>"

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

    def test_reason_maps_are_inside_hashed_payload(self) -> None:
        html = BUILT_FAHRAS.read_text(encoding="utf-8")
        data = _payload(html)
        ver = data.pop("data_version")
        data.pop("build_date")
        self.assertIn("reason_codes", data)
        self.assertIn("committee_reason_codes", data)
        core = json.dumps(data, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        self.assertEqual(hashlib.sha256(core.encode("utf-8")).hexdigest()[:12], ver)

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
            self.assertIn(LABEL_LEGACY, html, path.name)
            self.assertIn(LABEL_UNKNOWN, html, path.name)

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

    def test_unknown_reason_uses_textcontent_not_innerhtml(self) -> None:
        for path in (TEMPLATE_FAHRAS, TEMPLATE_READER):
            body = _fn_body(path.read_text(encoding="utf-8"), "fillRouteStatus")
            self.assertIn("is-unknown", body, path.name)
            self.assertIn("LABEL_UNKNOWN_REASON", body, path.name)
            self.assertIn("p.textContent = LABEL_UNKNOWN_REASON + String(code)", body, path.name)
            self.assertNotIn("innerHTML", body, path.name)


def _playwright_available() -> tuple[bool, str]:
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except ImportError:
        return False, "playwright Python package not importable"
    return True, ""


def _fixture_moves(window: dict) -> list[dict]:
    by = {s["id"]: s for s in window["spans"]}

    def rng(*ids: str) -> tuple[int, int]:
        return min(by[i]["start"] for i in ids), max(by[i]["end"] for i in ids)

    def slice_text(start: int, end: int) -> str:
        return window["window_text"][start - window["window_start"] : end - window["window_start"]]

    spec_start, spec_end = rng("s007", "s008", "s009")
    auto_start, auto_end = rng("s012", "s013")
    legacy_start, legacy_end = rng("s014", "s015")
    unknown_start, unknown_end = rng("s010", "s011")
    specialist = {
        "move_id": "g-spec",
        "span_ids": ["s007", "s008", "s009"],
        "start": spec_start,
        "end": spec_end,
        "text": slice_text(spec_start, spec_end),
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
    legacy = {
        "move_id": "g-legacy",
        "span_ids": ["s014", "s015"],
        "start": legacy_start,
        "end": legacy_end,
        "text": slice_text(legacy_start, legacy_end),
        "primary": "M_RAY",
        "secondary": [],
        "certainty": "weak",
        "route": "specialist",
        "evidence_span_ids": [],
        "author_verdict_span_ids": [],
        "rationale_ar": XSS_RATIONALE,
        "alternatives": [],
        "unverified_model_notes": {
            "rationale_ar": XSS_RATIONALE,
            "alternatives": [],
        },
        "score": {"total": 30, "parts": {}},
        "flags": [],
        "review_status": "pending",
        "origin": "ai",
    }
    unknown = {
        "move_id": "g-unknown",
        "span_ids": ["s010", "s011"],
        "start": unknown_start,
        "end": unknown_end,
        "text": slice_text(unknown_start, unknown_end),
        "primary": "M_HADITH",
        "secondary": [],
        "certainty": "weak",
        "route": "specialist",
        "reason_code": UNKNOWN_CODE,
        "evidence_span_ids": [],
        "author_verdict_span_ids": [],
        "rationale_ar": "رمز غير موجود في العقد",
        "alternatives": [],
        "unverified_model_notes": {
            "rationale_ar": "رمز غير موجود في العقد",
            "alternatives": [],
        },
        "score": {"total": 25, "parts": {}},
        "flags": [],
        "review_status": "pending",
        "origin": "ai",
    }
    auto = {
        "move_id": "g-auto",
        "span_ids": ["s012", "s013"],
        "start": auto_start,
        "end": auto_end,
        "text": slice_text(auto_start, auto_end),
        "primary": "M_QURAN",
        "secondary": [],
        "certainty": "strong",
        "route": "auto_candidate",
        "reason_code": None,
        "evidence_span_ids": ["s012"],
        "author_verdict_span_ids": ["s013"],
        "rationale_ar": "ملاحظة نموذج بلا إسناد",
        "alternatives": [],
        "score": {"total": 90, "parts": {}},
        "flags": [],
        "review_status": "pending",
        "origin": "ai",
    }
    return [specialist, legacy, unknown, auto]


def _patch_html(src: Path) -> str:
    html = src.read_text(encoding="utf-8")
    data = _payload(html)
    window = data["tafsirs"]["al_tabari"]["windows"]["2_255"]
    moves = _fixture_moves(window)
    block = {"annotator": "fixture", "moves": moves, "summary": {}}
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
    return (
        html[: m.start()]
        + '<script type="application/json" id="methods-data">'
        + embedded
        + "</script>"
        + html[m.end() :]
    )


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return


def _start_web_server() -> tuple[ThreadingHTTPServer, int]:
    class Handler(_QuietHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(WEB), **kwargs)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, server.server_address[1]


class TestUiGroundingPlaywright(unittest.TestCase):
    def test_reader_drawers_and_precise_highlight(self) -> None:
        ok, why = _playwright_available()
        if not ok:
            self.skipTest(why)
        from playwright.sync_api import sync_playwright

        fixture_html = _patch_html(BUILT_READER)
        SHOT_DIR.mkdir(parents=True, exist_ok=True)
        fixture_path = WEB / "_grounding_fixture.html"
        fixture_path.write_text(fixture_html, encoding="utf-8")

        meaning = REASON_CODES["EVIDENCE_EMPTY"]
        committee_ar = COMMITTEE_REASON_CODES["weak_evidence"]

        server, port = _start_web_server()
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
                first = True
                for theme in ("light", "dark"):
                    for width, height in ((1440, 900), (375, 812)):
                        page.set_viewport_size({"width": width, "height": height})
                        page.goto(base, wait_until="domcontentloaded")
                        page.evaluate(
                            "(t) => document.documentElement.setAttribute('data-theme', t)",
                            theme,
                        )
                        # Public ?mode=review stays closed. The fixture still checks
                        # the review markup by opening that dormant surface in-test.
                        page.wait_for_function(
                            """() => {
                              var v = document.getElementById('review-view');
                              return v && v.hidden;
                            }"""
                        )
                        page.evaluate(
                            "() => document.getElementById('btn-toggle-mode').click()"
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
                        self.assertGreaterEqual(page.locator("#dec-route-host .g-reason").count(), 1)
                        panel = page.locator(".dec-panel")
                        panel.scroll_into_view_if_needed()
                        spec_name = f"reader-specialist-{theme}-{width}.png"
                        panel.screenshot(path=str(SHOT_DIR / spec_name))
                        shots.append(spec_name)

                        page.locator("#act-show-evidence").click()
                        page.wait_for_timeout(200)
                        evid_spec = page.locator(".cite-evidence").count()
                        self.assertEqual(
                            evid_spec,
                            0,
                            "missing evidence id must not highlight anything",
                        )

                        if first:
                            first = False
                            items = page.locator(".q-it")
                            self.assertGreaterEqual(items.count(), 3)
                            items.nth(1).click()
                            page.wait_for_selector("#dec-route-host .g-reason.is-legacy")
                            legacy_host = page.locator("#dec-route-host")
                            self.assertIn(LABEL_WAIT, legacy_host.inner_text())
                            self.assertIn(LABEL_LEGACY, legacy_host.inner_text())
                            self.assertNotIn(LABEL_UNKNOWN, legacy_host.inner_text())
                            notes = page.locator("#dec-notes-body")
                            self.assertIn(XSS_RATIONALE, notes.inner_text())
                            self.assertEqual(page.locator("#dec-notes-body img").count(), 0)

                            items.nth(2).click()
                            page.wait_for_selector("#dec-route-host .g-reason.is-unknown")
                            unk_host = page.locator("#dec-route-host")
                            self.assertIn(LABEL_WAIT, unk_host.inner_text())
                            self.assertIn(LABEL_UNKNOWN, unk_host.inner_text())
                            self.assertIn(UNKNOWN_CODE, unk_host.inner_text())
                            self.assertNotIn(LABEL_LEGACY, unk_host.inner_text())
                            unk_line = page.locator("#dec-route-host .g-reason.is-unknown").inner_text()
                            self.assertEqual(unk_line, LABEL_UNKNOWN + UNKNOWN_CODE)

                            page.locator(".q-it").first.click()
                            page.wait_for_selector("#dec-route-host .g-reason")

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

    def test_fahras_drawer_legacy_escape_and_highlight(self) -> None:
        ok, why = _playwright_available()
        if not ok:
            self.skipTest(why)
        from playwright.sync_api import sync_playwright

        fixture_html = _patch_html(BUILT_FAHRAS)
        fixture_path = WEB / "_grounding_fahras_fixture.html"
        fixture_path.write_text(fixture_html, encoding="utf-8")
        meaning = REASON_CODES["EVIDENCE_EMPTY"]
        server, port = _start_web_server()
        url = f"http://127.0.0.1:{port}/_grounding_fahras_fixture.html"
        try:
            with sync_playwright() as p:
                try:
                    browser = p.chromium.launch()
                except Exception as exc:
                    self.skipTest(f"chromium unavailable: {exc}")
                    return
                context = browser.new_context()
                page = context.new_page()
                page.add_init_script("try { localStorage.clear(); } catch (e) {}")
                page.set_viewport_size({"width": 1440, "height": 900})
                page.goto(url, wait_until="domcontentloaded")
                page.wait_for_selector('[data-hid="ai-2_255-g-spec"]')

                def open_hid(hid: str) -> None:
                    # Drawer backdrop covers the tafsir; dispatch click on the mark.
                    page.locator(f'[data-hid="{hid}"]').first.evaluate(
                        "el => el.click()"
                    )

                open_hid("ai-2_255-g-spec")
                page.wait_for_selector("#g-route-host .g-route")
                spec_host = page.locator("#g-route-host")
                self.assertIn(LABEL_WAIT, spec_host.inner_text())
                self.assertIn(meaning, spec_host.inner_text())
                self.assertGreaterEqual(page.locator("#g-route-host .g-reason").count(), 1)
                page.locator("#flash-evidence").click()
                page.wait_for_timeout(200)
                self.assertEqual(
                    page.locator(".cite-evidence").count(),
                    0,
                    "missing evidence id must not highlight anything",
                )

                open_hid("ai-2_255-g-legacy")
                page.wait_for_selector("#g-route-host .g-reason.is-legacy")
                legacy_host = page.locator("#g-route-host")
                self.assertIn(LABEL_WAIT, legacy_host.inner_text())
                self.assertIn(LABEL_LEGACY, legacy_host.inner_text())
                self.assertNotIn(LABEL_UNKNOWN, legacy_host.inner_text())
                notes = page.locator("#g-notes-body")
                self.assertIn(XSS_RATIONALE, notes.inner_text())
                self.assertEqual(page.locator("#g-notes-body img").count(), 0)
                self.assertEqual(page.locator("#drawer img").count(), 0)

                open_hid("ai-2_255-g-unknown")
                page.wait_for_selector("#g-route-host .g-reason.is-unknown")
                unk_host = page.locator("#g-route-host")
                self.assertIn(LABEL_WAIT, unk_host.inner_text())
                self.assertIn(LABEL_UNKNOWN, unk_host.inner_text())
                self.assertIn(UNKNOWN_CODE, unk_host.inner_text())
                self.assertNotIn(LABEL_LEGACY, unk_host.inner_text())
                unk_line = page.locator("#g-route-host .g-reason.is-unknown").inner_text()
                self.assertEqual(unk_line, LABEL_UNKNOWN + UNKNOWN_CODE)

                open_hid("ai-2_255-g-auto")
                page.wait_for_selector("#g-route-host .g-route.is-auto")
                auto_host = page.locator("#g-route-host")
                self.assertIn(LABEL_CANDIDATE, auto_host.inner_text())
                page.locator("#flash-evidence").click()
                page.wait_for_timeout(200)
                styles = page.evaluate(
                    """() => {
                      const e = document.querySelector('.cite-evidence');
                      const v = document.querySelector('.cite-verdict');
                      if (!e || !v) return { evid: !!e, verd: !!v };
                      const es = getComputedStyle(e);
                      const vs = getComputedStyle(v);
                      return {
                        evid: true,
                        verd: true,
                        eShadow: es.boxShadow,
                        vShadow: vs.boxShadow,
                        eBg: es.backgroundImage,
                        vBg: vs.backgroundImage
                      };
                    }"""
                )
                self.assertTrue(styles.get("evid"))
                self.assertTrue(styles.get("verd"))
                self.assertNotEqual(styles.get("eShadow"), styles.get("vShadow"))
                context.close()
                browser.close()
        finally:
            server.shutdown()
            try:
                fixture_path.unlink()
            except OSError:
                pass


if __name__ == "__main__":
    unittest.main()
