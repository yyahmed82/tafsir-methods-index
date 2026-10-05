"""Static checks for the public site in site/ (served at mirqah.app). No network."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
INDEX = SITE / "index.html"

DATA_URL = "https://console.mirqah.app/public/v1/published.json"

# The public page must not leak review-workflow vocabulary or tool/vendor names.
FORBIDDEN = [
    "ai_proposed",
    "under_review",
    "needs_edit",
    "rejected",
    "export",
    "deepseek",
    "qwen",
    "gemma",
    "codex",
    "claude",
    "gpt",
    "ollama",
]

REDIRECT_PAGES = ["reader.html", "fahras.html", "methods.html", "app.html"]
MUST_NOT_EXIST = ["reconcile.html", "index_data.json", "reconcile_data.json", "published.json"]


@pytest.fixture(scope="module")
def index_html() -> str:
    assert INDEX.is_file(), "site/index.html missing"
    return INDEX.read_text(encoding="utf-8")


def test_index_exists_and_is_rtl_arabic(index_html: str) -> None:
    assert INDEX.stat().st_size > 10_000
    assert 'dir="rtl"' in index_html
    assert 'lang="ar"' in index_html
    assert "فهرس مناهج التفسير" in index_html


def test_index_contains_data_url(index_html: str) -> None:
    assert DATA_URL in index_html
    assert "cache: 'no-cache'" in index_html or 'cache: "no-cache"' in index_html


@pytest.mark.parametrize("word", FORBIDDEN)
def test_index_has_no_forbidden_strings(index_html: str, word: str) -> None:
    assert word not in index_html.lower(), f"forbidden string {word!r} found in site/index.html"


def test_index_has_no_review_controls(index_html: str) -> None:
    low = index_html.lower()
    for word in ("reject", "decision", "reviewer", "model"):
        assert word not in low, f"review vocabulary {word!r} found in public page"


def test_index_wires_required_ui(index_html: str) -> None:
    for el in ("sel-surah", "sel-ayah", "sel-tafsir", "btn-prev", "btn-next", "btn-theme", "legend", "ucard"):
        assert f'id="{el}"' in index_html, f"missing #{el}"
    assert "لم يُنشر بعد أي إصدار معتمد" in index_html
    assert "تعذّر الاتصال" in index_html
    assert "https://console.mirqah.app" in index_html
    assert "https://github.com/yyahmed82/tafsir-methods-index" in index_html
    assert "assets/brand/quranpedia-books.js" in index_html
    assert "localStorage" in index_html  # manual dark-mode toggle (allowed)
    assert "prefers-color-scheme: dark" in index_html


def test_method_colours_defined(index_html: str) -> None:
    for code in (
        "M_QURAN", "M_SUNNAH", "M_SAHABA", "M_TABIIN", "M_LUGHA",
        "M_QIRAAT", "M_NUZUL", "M_SIRA", "M_ISRAILIYYAT", "M_RAY",
    ):
        assert f"--m-{code}:" in index_html, f"missing colour token for {code}"


@pytest.mark.parametrize("page", REDIRECT_PAGES)
def test_redirect_pages_point_home(page: str) -> None:
    p = SITE / page
    assert p.is_file(), f"site/{page} missing"
    html = p.read_text(encoding="utf-8")
    assert "url=/" in html
    assert re.search(r'http-equiv="refresh"', html)
    assert 'href="/"' in html
    assert p.stat().st_size < 4_000


def test_headers_csp_allows_console() -> None:
    headers = (SITE / "_headers").read_text(encoding="utf-8")
    assert "connect-src 'self' https://console.mirqah.app" in headers
    assert "Content-Security-Policy:" in headers
    assert "frame-ancestors 'none'" in headers
    assert "Strict-Transport-Security" in headers


@pytest.mark.parametrize("name", MUST_NOT_EXIST)
def test_no_stale_or_data_files(name: str) -> None:
    assert not (SITE / name).exists(), f"site/{name} must not be deployed"


def test_brand_assets_present() -> None:
    brand = SITE / "assets" / "brand"
    for name in ("mirqah-logo.svg", "mirqah-logo-on-dark.svg", "mirqah-mark.svg", "mirqah-icon.svg", "quranpedia-books.js"):
        assert (brand / name).is_file(), f"missing assets/brand/{name}"
    js = (brand / "quranpedia-books.js").read_text(encoding="utf-8")
    assert "quranpediaSourceUrl" in js


def test_readme_present() -> None:
    readme = (SITE / "README.md").read_text(encoding="utf-8")
    assert "wrangler" in readme
    assert DATA_URL in readme
