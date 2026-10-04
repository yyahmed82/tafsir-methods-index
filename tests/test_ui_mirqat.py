"""Static UI checks for team مِرْقاة (no browser)."""

from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAPPING = ROOT / "web" / "assets" / "brand" / "quranpedia-books.js"
MARK_SVG = ROOT / "web" / "assets" / "brand" / "mirqat-mark.svg"
LOGO_LIGHT = ROOT / "web" / "assets" / "brand" / "mirqah-wordmark.svg"
LOGO_DARK = ROOT / "web" / "assets" / "brand" / "mirqah-wordmark-on-dark.svg"
ICON = ROOT / "web" / "assets" / "brand" / "mirqah-icon.svg"
WORDMARK = "مِرْقاة"
SOURCE_AREA = "اقرأ في المصدر"
SOURCE_LABEL = "قرآنبيديا"
COMPETING_LABEL = ">اقرأ المصدر<"
HREF_RE = re.compile(
    r"^https://quranpedia\.app/tafseer/[a-z]+/sura\d+-aya\d+\.html$"
)
VERIFIED_IDS = {
    "al_tabari": "tabary",
    "ibn_kathir": "katheer",
    "al_baghawi": "baghawy",
    "al_saadi": "saadi",
}
PERSON_NAME_NEEDLES = (
    "Khaled",
    "Khale",
    "Claude",
    "Codex",
    "Cursor",
)
OWNED_PATHS = (
    MAPPING,
    MARK_SVG,
)
HTML_PAGES = (
    ROOT / "web" / "index.html",
    ROOT / "web" / "reader.html",
    ROOT / "web" / "fahras.html",
    ROOT / "web" / "methods.html",
    ROOT / "web" / "reconcile.html",
)
SOURCE_PAGES = (
    ROOT / "web" / "reader.html",
    ROOT / "web" / "fahras.html",
)
SOURCE_TEMPLATES = (
    ROOT / "src" / "fahras_template.html",
    ROOT / "src" / "fahras_v2_template.html",
)


def _parse_js_object(src: str, name: str) -> dict:
    pattern = r"var " + re.escape(name) + r" = (\{.*?\});"
    match = re.search(pattern, src, re.S)
    if not match:
        raise AssertionError(f"missing JS object {name}")
    literal = match.group(1)
    literal = re.sub(r"(\w+)\s*:", r'"\1":', literal)
    raw = ast.literal_eval(literal)
    out = {}
    for key, value in raw.items():
        out[int(key) if str(key).isdigit() else key] = value
    return out


def _source_url(book_ids: dict, tafsir_id: str, surah: int, ayah: int) -> str:
    book = book_ids[tafsir_id]
    return f"https://quranpedia.app/tafseer/{book}/sura{surah}-aya{ayah}.html"


class TestUiMirqat(unittest.TestCase):
    def test_mapping_only_verified_tafsirs(self) -> None:
        src = MAPPING.read_text(encoding="utf-8")
        self.assertNotIn("quranpedia.net", src)
        self.assertNotIn("SURAH_SLUGS", src)
        book_ids = _parse_js_object(src, "BOOK_IDS")
        self.assertEqual(book_ids, VERIFIED_IDS)
        self.assertEqual(set(book_ids), {"al_tabari", "ibn_kathir", "al_baghawi", "al_saadi"})
        self.assertIn("function sourceUrl", src)
        self.assertIn('if (!book || !s || !a) return "";', src)
        for tid, surah, ayah in (
            ("al_tabari", 24, 35),
            ("ibn_kathir", 24, 35),
            ("al_baghawi", 24, 35),
            ("al_saadi", 24, 35),
            ("al_tabari", 2, 255),
        ):
            url = _source_url(book_ids, tid, surah, ayah)
            self.assertRegex(url, HREF_RE)
        self.assertEqual(
            _source_url(book_ids, "al_tabari", 24, 35),
            "https://quranpedia.app/tafseer/tabary/sura24-aya35.html",
        )
        self.assertEqual(
            _source_url(book_ids, "ibn_kathir", 24, 35),
            "https://quranpedia.app/tafseer/katheer/sura24-aya35.html",
        )
        self.assertEqual(
            _source_url(book_ids, "al_baghawi", 24, 35),
            "https://quranpedia.app/tafseer/baghawy/sura24-aya35.html",
        )
        self.assertEqual(
            _source_url(book_ids, "al_saadi", 24, 35),
            "https://quranpedia.app/tafseer/saadi/sura24-aya35.html",
        )
        self.assertNotIn("al_qurtubi", book_ids)
        self.assertNotIn("al_shawkani", book_ids)

    def test_logo_in_built_html(self) -> None:
        for svg in (LOGO_LIGHT, LOGO_DARK, ICON):
            self.assertTrue(svg.is_file(), svg.name)
            text = svg.read_text(encoding="utf-8")
            self.assertIn("<svg", text, svg.name)
            self.assertIn(f"<title>{WORDMARK}</title>", text, svg.name)
            self.assertNotIn("<script", text, svg.name)
            self.assertNotIn("href=", text, svg.name)  # self-contained, no external refs
        for path in HTML_PAGES:
            html = path.read_text(encoding="utf-8")
            self.assertIn(WORDMARK, html, path.name)
            self.assertIn('src="assets/brand/mirqah-wordmark.svg"', html, path.name)
            self.assertIn('src="assets/brand/mirqah-wordmark-on-dark.svg"', html, path.name)
            self.assertEqual(html.count(f'alt="{WORDMARK}"'), 2, path.name)
            self.assertIn('rel="icon" href="assets/brand/mirqah-icon.svg"', html, path.name)

    def test_source_links_match_verified_pattern(self) -> None:
        mapping = MAPPING.read_text(encoding="utf-8")
        book_ids = _parse_js_object(mapping, "BOOK_IDS")
        allowed_books = set(book_ids.values())
        for path in SOURCE_PAGES + SOURCE_TEMPLATES:
            html = path.read_text(encoding="utf-8")
            self.assertNotIn("quranpedia.net", html, path.name)
            self.assertNotIn(COMPETING_LABEL, html, path.name)
            self.assertIn(SOURCE_AREA, html, path.name)
            self.assertIn(SOURCE_LABEL, html, path.name)
            anchors = re.findall(
                r"<a\b([^>]*class=\"[^\"]*js-quranpedia-link[^\"]*\"[^>]*)>",
                html,
            )
            self.assertTrue(anchors, f"no قرآنبيديا anchors in {path.name}")
            for attrs in anchors:
                href = re.search(r'href="([^"]+)"', attrs)
                self.assertIsNone(
                    href,
                    f"static quranpedia href must be omitted (JS sets it): {attrs}",
                )
                self.assertIn("قرآنبيديا", html)
                target = re.search(r'target="([^"]+)"', attrs)
                rel = re.search(r'rel="([^"]+)"', attrs)
                self.assertEqual(target.group(1), "_blank")
                rel_tokens = set(rel.group(1).split())
                self.assertIn("noopener", rel_tokens)
                self.assertIn("noreferrer", rel_tokens)
            self.assertNotIn('href="https://quranpedia.app', html, path.name)
            if path in SOURCE_PAGES:
                self.assertIn("quranpediaSourceUrl", html, path.name)
                self.assertIn('target = "_blank"', html, path.name)
                self.assertIn('rel = "noopener noreferrer"', html, path.name)
        for book in allowed_books:
            self.assertRegex(
                f"https://quranpedia.app/tafseer/{book}/sura24-aya35.html",
                HREF_RE,
            )

    def test_no_person_names_added(self) -> None:
        blobs = [p.read_text(encoding="utf-8") for p in OWNED_PATHS if p.is_file()]
        joined = "\n".join(blobs)
        for needle in PERSON_NAME_NEEDLES:
            self.assertNotIn(needle, joined, f"person-name token {needle!r} found")

    def test_brand_control_is_button(self) -> None:
        reader = (ROOT / "web" / "reader.html").read_text(encoding="utf-8")
        tpl = (ROOT / "src" / "fahras_v2_template.html").read_text(encoding="utf-8")
        for html, name in ((reader, "reader.html"), (tpl, "fahras_v2_template.html")):
            self.assertRegex(
                html,
                r'<button\b[^>]*\bclass="brand-lockup"[^>]*\baria-label="العودة إلى وضع القراءة"',
                name,
            )
            self.assertNotRegex(html, r'<div\b[^>]*\bid="brand-logo"', name)

    def test_source_row_min_height_and_no_opacity(self) -> None:
        for path in SOURCE_TEMPLATES:
            css_html = path.read_text(encoding="utf-8")
            self.assertIn("min-height: 24px", css_html, path.name)
            self.assertIn("padding-block: 2px", css_html, path.name)
            self.assertIn("display: flex", css_html, path.name)
            self.assertIn("flex-wrap: wrap", css_html, path.name)
            self.assertNotIn("opacity: 0.82", css_html, path.name)
            self.assertNotRegex(
                css_html,
                r"\.js-quranpedia-link\s*\{[^}]*opacity",
                path.name,
            )

    def test_quran_com_label_isolated_ltr(self) -> None:
        for path in SOURCE_PAGES + SOURCE_TEMPLATES:
            html = path.read_text(encoding="utf-8")
            self.assertIn('dir="ltr"', html, path.name)
            self.assertIn('translate="no"', html, path.name)
            self.assertRegex(
                html,
                r'<bdi dir="ltr" translate="no">quran\.com</bdi>',
                path.name,
            )

    def test_theme_toggle_exposes_aria_pressed(self) -> None:
        cases = (
            (ROOT / "web" / "index.html", 'id="theme-btn"'),
            (ROOT / "web" / "fahras.html", 'id="theme-btn"'),
            (ROOT / "web" / "reader.html", 'id="btn-theme-toggle"'),
            (ROOT / "web" / "methods.html", 'id="theme-btn"'),
        )
        for path, needle in cases:
            html = path.read_text(encoding="utf-8")
            self.assertIn(needle, html, path.name)
            self.assertRegex(
                html,
                r"<button\b[^>]*" + re.escape(needle) + r"[^>]*\baria-pressed=",
                path.name,
            )
            self.assertIn('setAttribute("aria-pressed"', html, path.name)

    def test_brand_mark_tokens_identical(self) -> None:
        templates = (
            ROOT / "src" / "index_template.html",
            ROOT / "src" / "fahras_template.html",
            ROOT / "src" / "fahras_v2_template.html",
            ROOT / "src" / "methods_template.html",
            ROOT / "src" / "reconcile_template.html",
        )
        logo = []
        for path in templates:
            html = path.read_text(encoding="utf-8")
            m = re.search(r"\.mq-logo\s*\{([^}]+)\}", html)
            g = re.search(r"\.brand-lockup\s*\{([^}]+)\}", html)
            self.assertIsNotNone(m, path.name)
            self.assertIsNotNone(g, path.name)
            logo.append(("height: 46px" in m.group(1), "width: auto" in m.group(1)))
            self.assertIn(".mq-logo--light { display: var(--mq-logo-light, inline-block); }", html, path.name)
            self.assertIn(".mq-logo--dark { display: var(--mq-logo-dark, none); }", html, path.name)
            # every theme block that sets the brand colour also picks the logo variant
            n = html.count("--mirqat-brand:")
            self.assertEqual(html.count("--mq-logo-light:"), n, path.name)
            self.assertEqual(html.count("--mq-logo-dark:"), n, path.name)
            self.assertIn("gap: 8px", g.group(1), path.name)
            self.assertTrue(all(logo[-1]), path.name + " logo tokens")
        self.assertEqual(len(set(logo)), 1)

    def test_header_divider_in_built_pages(self) -> None:
        for path in HTML_PAGES:
            html = path.read_text(encoding="utf-8")
            self.assertIn('class="brand-team"', html, path.name)
            self.assertIn('class="brand-heading"', html, path.name)
            self.assertRegex(
                html,
                r'<span class="brand-rule" aria-hidden="true"></span>',
                path.name,
            )
            self.assertIn("فهرس مناهج التفسير", html, path.name)
            self.assertIn("height: 18px", html, path.name)
            self.assertIn("margin-inline: 12px", html, path.name)
            self.assertIn("background: var(--mirqat-rule)", html, path.name)


if __name__ == "__main__":
    unittest.main()
