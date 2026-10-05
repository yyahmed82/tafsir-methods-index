"""UX-1..6 and UX-8 checks on built index / fahras / reader (UX-7 out of scope)."""

from __future__ import annotations

import io
import json
import re
import sys
import threading
import unittest
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
INDEX = WEB / "index.html"
FAHRAS = WEB / "fahras.html"
READER = WEB / "reader.html"
TPL_INDEX = ROOT / "src" / "index_template.html"
TPL_FAHRAS = ROOT / "src" / "fahras_template.html"
TPL_READER = ROOT / "src" / "fahras_v2_template.html"

CLAIM_STRINGS = (
    "فهرس تفسير ابن كثير — نموذج تجريبي",
    "٩٠٫٩٪",
    "٩٠.٩٪",
    "١٠٠٪ سلامة",
    "٦٩٫٢٪",
    "٦٩.٢٪",
    "٩٤٫٩٪",
    "٩٤.٩٪",
    "اتفاق وسوم المصدر بين الفاحصين",
    "اتفاق وسوم المحتوى بين الفاحصين",
    "سلامة النص حرفاً بحرف",
    "ماذا أثبتت التجربة؟",
    "نتائج تجربة أولى صغيرة",
)

CTA_READ = "افتح وضع القراءة"
CTA_COMMITTEE = "لوحة اللجنة (للمتخصص)"
CONSOLE_HREF = "https://console.mirqah.app"
TRUST = "الوسوم مقترحة آلياً ولم يعتمدها متخصص بعد · النص مطابق للمصدر حرفاً بحرف"
COUNTS_CAPTION = "أعداد توجيه وليست دقة"
NO_APPROVAL = "لا اعتماد إلا من المتخصص"
STEP_STRIP = (
    "نص مثبّت",
    "اقتراح آلي بمعرّفات الأجزاء",
    "فحص حتمي",
    "قرار المختص",
)
GROUNDING_KEEP = (
    "ملاحظة النموذج — غير مُسنَدة، ليست دليلاً",
    "وجود الشاهد لا يثبت صحة الاستنتاج؛ الاعتماد للمتخصص بعد فحص الدلالة",
    "بانتظار المتخصص",
)


def _chrome(html: str) -> str:
    html = re.sub(r"<style\b[\s\S]*?</style>", " ", html, flags=re.I)
    html = re.sub(
        r'<script\b[^>]*type="application/json"[\s\S]*?</script>',
        " ",
        html,
        flags=re.I,
    )
    html = re.sub(r"<script\b[\s\S]*?</script>", " ", html, flags=re.I)
    html = re.sub(r"\sstyle=\"[^\"]*\"", " ", html)
    html = re.sub(r"\sstyle='[^']*'", " ", html)
    return html


def _playwright_available() -> tuple[bool, str]:
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except ImportError:
        return False, "playwright Python package not importable"
    return True, ""


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


def _boxes_overlap(a: dict, b: dict) -> bool:
    return not (
        a["x"] + a["width"] <= b["x"]
        or b["x"] + b["width"] <= a["x"]
        or a["y"] + a["height"] <= b["y"]
        or b["y"] + b["height"] <= a["y"]
    )


class TestUxApplyStatic(unittest.TestCase):
    def test_no_percent_or_removed_claims_in_built_pages(self) -> None:
        for path in (INDEX, FAHRAS, READER):
            html = path.read_text(encoding="utf-8")
            self.assertNotIn("٪", html, path.name)
            for claim in CLAIM_STRINGS:
                self.assertNotIn(claim, html, f"{path.name}: {claim}")
            chrome = _chrome(html)
            self.assertNotIn("%", chrome, path.name)
            self.assertNotIn("٪", chrome, path.name)

    def test_index_ctas_and_copy(self) -> None:
        html = INDEX.read_text(encoding="utf-8")
        self.assertIn("<h1>فهرس مناهج التفسير</h1>", html)
        self.assertIn(
            "منهج المفسّر ظاهراً على نصّه — أربعة تفاسير على سورة النور",
            html,
        )
        self.assertRegex(
            html,
            r'<a\b[^>]*href="reader\.html"[^>]*>\s*' + re.escape(CTA_READ),
        )
        self.assertRegex(
            html,
            r'<a\b[^>]*href="https://console\.mirqah\.app"[^>]*>\s*'
            + re.escape(CTA_COMMITTEE),
        )
        self.assertNotIn("reader.html?mode=review", html)
        self.assertNotIn("افتح وضع المختص", html)
        self.assertIn(TRUST, html)
        self.assertIn(COUNTS_CAPTION, html)
        self.assertIn(NO_APPROVAL, html)
        self.assertIn("٦٤", html)
        self.assertIn("٢٩٦", html)
        for step in STEP_STRIP:
            self.assertIn(step, html)
        pos_read = html.find(CTA_READ)
        pos_h2 = html.find('id="how-title"')
        self.assertGreater(pos_h2, pos_read)

    def test_index_template_matches_built(self) -> None:
        tpl = TPL_INDEX.read_text(encoding="utf-8")
        self.assertIn(CTA_READ, tpl)
        self.assertIn(f'href="{CONSOLE_HREF}"', tpl)
        self.assertIn(CTA_COMMITTEE, tpl)
        self.assertNotIn('href="reader.html?mode=review"', tpl)
        self.assertNotIn("فهرس تفسير ابن كثير — نموذج تجريبي", tpl)

    def test_footnote_switch_markup(self) -> None:
        for path in (TPL_READER, READER):
            html = path.read_text(encoding="utf-8")
            self.assertIn('id="toggle-footnotes"', html)
            self.assertIn('role="switch"', html)
            self.assertIn("aria-checked", html)
            self.assertIn("إظهار حواشي المحقق", html)
            self.assertIn("if (!state.footnotesVisible) continue;", html)
            self.assertIn(".hide-footnotes .fn { display: none !important; }", html)

    def test_queue_heading_above_tabs(self) -> None:
        html = TPL_READER.read_text(encoding="utf-8")
        h = html.find('id="queue-heading"')
        tabs = html.find('id="queue-tabs"')
        self.assertGreater(h, 0)
        self.assertGreater(tabs, h)
        self.assertIn("flex-direction: column", html)
        chunk = html[h : tabs + 80]
        self.assertIn("طابور المواضع", chunk)

    def test_only_pass_frame_is_the_frame_class(self) -> None:
        html = TPL_READER.read_text(encoding="utf-8")
        self.assertIn("pass-frame", html)
        self.assertIn('className = "cur-move pass-frame"', html)
        cite_css = html.split(".src-run.cite-evidence, .cite-evidence")[1].split(
            ".src-run.cite-verdict"
        )[0]
        self.assertIn("text-decoration-thickness: 2px", cite_css)
        self.assertIn("outline: none", cite_css)
        frame_css = html.split(".cur-move.pass-frame")[1].split(".sid")[0]
        self.assertIn("outline: 2px solid", frame_css)

    def test_classic_fahras_banner(self) -> None:
        html = FAHRAS.read_text(encoding="utf-8")
        self.assertIn("الواجهة الكلاسيكية — للمقارنة", html)
        self.assertIn("جرّب الواجهة الجديدة", html)
        self.assertIn('href="reader.html"', html)
        self.assertNotIn("حكّام", html)
        self.assertNotIn("المحكّم", html)
        self.assertNotIn("القضاة", html)

    def test_grounding_labels_kept(self) -> None:
        for path in (TPL_READER, TPL_FAHRAS, READER, FAHRAS):
            html = path.read_text(encoding="utf-8")
            for label in GROUNDING_KEEP:
                self.assertIn(label, html, path.name)

    def test_sbs_toggle_markup(self) -> None:
        for path in (TPL_READER, READER):
            html = path.read_text(encoding="utf-8")
            self.assertIn('id="toggle-sbs"', html, path.name)
            self.assertRegex(
                html,
                r'<button\b[^>]*\bid="toggle-sbs"[^>]*\brole="switch"',
                path.name,
            )
            self.assertIn("اعرض الأصل بجانبه", html, path.name)
            self.assertIn("النص الملوّن بالمناهج", html, path.name)
            self.assertIn("النص الأصلي كما في المصدر", html, path.name)
            self.assertIn('id="orig-article"', html, path.name)
            self.assertIn("function concatSpanText", html, path.name)
            self.assertIn("function renderOrigColumn", html, path.name)
            self.assertIn("SBS_KEY", html, path.name)

    def test_public_review_closed_export_kept(self) -> None:
        for path in (TPL_READER, READER):
            html = path.read_text(encoding="utf-8")
            self.assertIn("var REVIEW_OPEN = false;", html, path.name)
            self.assertIn(
                'if (REVIEW_OPEN && params.get("mode") === "review")',
                html,
                path.name,
            )
            self.assertIn('id="btn-export-log"', html, path.name)
            self.assertIn("صدّر قراراتك المحفوظة", html, path.name)
            self.assertIn("mirqah-reader-decisions.json", html, path.name)
            self.assertRegex(
                html,
                r'<button\b[^>]*\bid="btn-toggle-mode"[^>]*\bhidden\b',
                path.name,
            )
            self.assertNotRegex(
                html,
                r'<button\b(?![^>]*\bhidden\b)[^>]*\bid="btn-toggle-mode"',
                path.name,
            )


def _public_review_stays_closed(page) -> None:
    """?mode=review must not open the browser review UI on the public reader."""
    page.wait_for_function(
        """() => {
          var review = document.getElementById('review-view');
          var reader = document.getElementById('reader-view');
          var toggle = document.getElementById('btn-toggle-mode');
          return review && review.hidden && reader && !reader.hidden
            && toggle && toggle.hidden;
        }"""
    )


def _open_dormant_review_for_layout(page) -> None:
    """Measure markup that remains in the page after the public entry was closed."""
    _public_review_stays_closed(page)
    page.evaluate("() => document.getElementById('btn-toggle-mode').click()")
    page.wait_for_function(
        """() => {
          var v = document.getElementById('review-view');
          return v && !v.hidden;
        }"""
    )


class TestUxApplyPlaywright(unittest.TestCase):
    def test_footnote_switch_hides_chips(self) -> None:
        ok, why = _playwright_available()
        if not ok:
            self.skipTest(why)
        from playwright.sync_api import sync_playwright

        server, port = _start_web_server()
        url = f"http://127.0.0.1:{port}/reader.html"
        try:
            with sync_playwright() as p:
                try:
                    browser = p.chromium.launch()
                except Exception as exc:
                    self.skipTest(f"chromium unavailable: {exc}")
                    return
                page = browser.new_page()
                page.goto(url, wait_until="domcontentloaded")
                page.wait_for_selector("#toggle-footnotes")
                sw = page.locator("#toggle-footnotes")
                self.assertEqual(sw.get_attribute("role"), "switch")
                self.assertEqual(sw.get_attribute("aria-checked"), "true")
                page.wait_for_selector("#reading-article")
                page.evaluate(
                    """() => {
                      var art = document.getElementById('reading-article');
                      if (art && !art.querySelector('.fn')) {
                        var chip = document.createElement('span');
                        chip.className = 'fn';
                        chip.textContent = 'حاشية';
                        art.appendChild(chip);
                      }
                    }"""
                )
                self.assertGreater(page.locator("#reading-article .fn").count(), 0)
                sw.click()
                self.assertEqual(sw.get_attribute("aria-checked"), "false")
                page.wait_for_timeout(80)
                visible = page.evaluate(
                    """() => {
                      var nodes = document.querySelectorAll('#reading-article .fn');
                      var shown = 0;
                      nodes.forEach(function (n) {
                        var s = getComputedStyle(n);
                        if (s.display !== 'none' && s.visibility !== 'hidden') shown++;
                      });
                      return shown;
                    }"""
                )
                self.assertEqual(visible, 0)
                browser.close()
        finally:
            server.shutdown()

    def test_queue_heading_and_tabs_do_not_overlap(self) -> None:
        ok, why = _playwright_available()
        if not ok:
            self.skipTest(why)
        from playwright.sync_api import sync_playwright

        server, port = _start_web_server()
        url = f"http://127.0.0.1:{port}/reader.html?mode=review"
        try:
            with sync_playwright() as p:
                try:
                    browser = p.chromium.launch()
                except Exception as exc:
                    self.skipTest(f"chromium unavailable: {exc}")
                    return
                page = browser.new_page()
                for width, height in ((1440, 900), (375, 812)):
                    page.set_viewport_size({"width": width, "height": height})
                    page.goto(url, wait_until="domcontentloaded")
                    _open_dormant_review_for_layout(page)
                    if width == 375:
                        toggle = page.locator("#btn-toggle-mobile-queue")
                        if toggle.is_visible():
                            toggle.click()
                    page.wait_for_selector("#queue-heading", state="visible")
                    page.wait_for_selector("#queue-tabs", state="visible")
                    head = page.locator("#queue-heading").bounding_box()
                    tabs = page.locator("#queue-tabs").bounding_box()
                    self.assertIsNotNone(head)
                    self.assertIsNotNone(tabs)
                    self.assertFalse(
                        _boxes_overlap(head, tabs),
                        f"queue heading overlaps tabs at {width}",
                    )
                    self.assertGreaterEqual(tabs["y"], head["y"] + head["height"] - 1)
                browser.close()
        finally:
            server.shutdown()

    def test_only_active_passage_has_frame_class(self) -> None:
        ok, why = _playwright_available()
        if not ok:
            self.skipTest(why)
        from playwright.sync_api import sync_playwright

        server, port = _start_web_server()
        url = f"http://127.0.0.1:{port}/reader.html?mode=review"
        try:
            with sync_playwright() as p:
                try:
                    browser = p.chromium.launch()
                except Exception as exc:
                    self.skipTest(f"chromium unavailable: {exc}")
                    return
                page = browser.new_page()
                page.set_viewport_size({"width": 1440, "height": 900})
                page.goto(url, wait_until="domcontentloaded")
                _open_dormant_review_for_layout(page)
                page.wait_for_selector("#review-paper")
                page.wait_for_timeout(200)
                counts = page.evaluate(
                    """() => ({
                      frames: document.querySelectorAll('.pass-frame').length,
                      citeOnFrame: document.querySelectorAll('.cite-evidence.pass-frame').length,
                      curWithoutFrame: document.querySelectorAll('.cur-move:not(.pass-frame)').length
                    })"""
                )
                self.assertLessEqual(counts["frames"], 1)
                self.assertEqual(counts["citeOnFrame"], 0)
                self.assertEqual(counts["curWithoutFrame"], 0)
                browser.close()
        finally:
            server.shutdown()

    def test_side_by_side_columns_and_plain_source(self) -> None:
        ok, why = _playwright_available()
        if not ok:
            self.skipTest(why)
        from playwright.sync_api import sync_playwright

        server, port = _start_web_server()
        url = f"http://127.0.0.1:{port}/reader.html"
        try:
            with sync_playwright() as p:
                try:
                    browser = p.chromium.launch()
                except Exception as exc:
                    self.skipTest(f"chromium unavailable: {exc}")
                    return
                page = browser.new_page()
                page.add_init_script("try { localStorage.clear(); } catch (e) {}")
                page.set_viewport_size({"width": 1440, "height": 900})
                page.goto(url, wait_until="domcontentloaded")
                page.wait_for_selector("#toggle-sbs")
                sw = page.locator("#toggle-sbs")
                self.assertEqual(sw.get_attribute("role"), "switch")
                if sw.get_attribute("aria-checked") != "true":
                    sw.click()
                page.wait_for_selector("#orig-pane", state="visible")
                page.wait_for_selector("#orig-article .src-run")
                tagged = page.locator("#tagged-pane").bounding_box()
                orig = page.locator("#orig-pane").bounding_box()
                self.assertIsNotNone(tagged)
                self.assertIsNotNone(orig)
                self.assertLess(orig["x"], tagged["x"])
                self.assertLess(abs(orig["y"] - tagged["y"]), 80)

                info = page.evaluate(
                    """() => {
                      var art = document.getElementById('orig-article');
                      var w = window.__fahras_v2;
                      var T = (window.DATA) ? null : null;
                      var plain = art ? (art.textContent || '') : '';
                      var spans = w.concatSpanText(w.state && null);
                      try {
                        spans = w.concatSpanText(
                          (function () {
                            var data = JSON.parse(document.getElementById('methods-data').textContent);
                            var tid = w.state.tafsirId;
                            var wid = w.state.windowId;
                            return data.tafsirs[tid].windows[wid];
                          })()
                        );
                      } catch (e) { spans = ''; }
                      return {
                        plain: plain,
                        spans: spans,
                        hl: art.querySelectorAll('.hl').length,
                        fn: art.querySelectorAll('.fn').length,
                        chip: art.querySelectorAll('.chip').length
                      };
                    }"""
                )
                self.assertEqual(info["hl"], 0)
                self.assertEqual(info["fn"], 0)
                self.assertEqual(info["chip"], 0)
                self.assertGreater(len(info["plain"]), 0)
                self.assertEqual(info["plain"], info["spans"])

                displays = page.evaluate(
                    """() => {
                      var nodes = document.querySelectorAll('#reading-article .hl');
                      var out = [];
                      nodes.forEach(function (n) { out.push(getComputedStyle(n).display); });
                      return out;
                    }"""
                )
                for disp in displays:
                    self.assertTrue(
                        str(disp).startswith("inline"),
                        f"highlight display is {disp!r}, expected inline",
                    )

                page.set_viewport_size({"width": 375, "height": 812})
                page.wait_for_timeout(120)
                if page.locator("#orig-pane").is_hidden():
                    sw.click()
                    page.wait_for_selector("#orig-pane", state="visible")
                tagged = page.locator("#tagged-pane").bounding_box()
                orig = page.locator("#orig-pane").bounding_box()
                self.assertIsNotNone(tagged)
                self.assertIsNotNone(orig)
                self.assertLessEqual(tagged["y"], orig["y"] + 2)
                browser.close()
        finally:
            server.shutdown()


def _import_build_index():
    src = str(ROOT / "src")
    if src not in sys.path:
        sys.path.insert(0, src)
    import build_index

    return build_index


class TestBuildIndexNoSilentFallback(unittest.TestCase):
    def test_without_flag_forced_failure_exits_nonzero(self) -> None:
        bi = _import_build_index()
        with mock.patch.object(
            bi, "build_index_data", side_effect=FileNotFoundError("missing 17_105.txt")
        ):
            with mock.patch.object(bi, "write_outputs") as write:
                with self.assertRaises(FileNotFoundError):
                    bi.main([])
                write.assert_not_called()

    def test_with_flag_uses_cached_json(self) -> None:
        bi = _import_build_index()
        cached = json.loads((ROOT / "web" / "index_data.json").read_text(encoding="utf-8"))
        captured: dict = {}

        def fake_write(data):
            captured["data"] = data
            return ROOT / "web" / "index_data.json", ROOT / "web" / "index.html"

        err = io.StringIO()
        with mock.patch.object(
            bi, "build_index_data", side_effect=AssertionError("must not rebuild from raw")
        ):
            with mock.patch.object(bi, "write_outputs", side_effect=fake_write):
                with mock.patch.object(sys, "stderr", err):
                    rc = bi.main(["--from-cached-json"])
        self.assertEqual(rc, 0)
        warning = err.getvalue()
        self.assertIn("WARNING", warning)
        self.assertIn("--from-cached-json", warning)
        self.assertEqual(captured["data"]["ayat"], cached["ayat"])
        self.assertEqual(captured["data"]["title_ar"], "فهرس مناهج التفسير")


if __name__ == "__main__":
    unittest.main()
