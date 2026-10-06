"""The public site (site/): the reader built from the published snapshot, nothing else.

Built by src/build_site.py from src/fahras_v2_template.html. It shows the whole surah
(every ayah of every tafsir, the pinned source text letter for letter) and marks only
units a specialist approved and a super admin published; no review mode, no export, no
working states, no model or vendor names. The page fetches the live snapshot on load.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import build_site  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "published_sample.json"
SITE = ROOT / "site"
VENDOR_WORDS = ["deepseek", "qwen", "gemma", "codex", "claude", "gpt", "ollama", "mimo", "grok", "anthropic", "openai"]


@pytest.fixture(scope="module")
def built(tmp_path_factory) -> tuple[str, dict]:
    out = tmp_path_factory.mktemp("site") / "index.html"
    build_site.build(str(FIXTURE), out)
    html = out.read_text(encoding="utf-8")
    m = re.search(r'<script type="application/json" id="methods-data">(.*?)</script>', html, re.S)
    assert m, "embedded data missing"
    return html, json.loads(m.group(1).replace("\\u003c", "<"))


def test_whole_surah_with_only_the_published_units_marked(built):
    html, data = built
    snap = json.loads(FIXTURE.read_text(encoding="utf-8"))
    want = {(u["tafsir"], u["id"]) for u in snap["units"]}
    got = set()
    for tid, t in data["tafsirs"].items():
        assert len(t["windows"]) == 64 and set(t["windows"]) == set(data["window_order"])
        for wid, block in t["verified"].items():
            assert block == {} or list(block) == ["approved"]
            for mv in (block.get("approved") or {}).get("moves") or []:
                assert mv["review_status"] == "approved"
                got.add((tid, mv["id"]))
    assert got == want
    assert data["tafsir_order"] == ["al_tabari", "ibn_kathir", "al_baghawi", "al_saadi"]
    assert data["window_order"] == [f"24_{n}" for n in range(1, 65)]
    assert data["window_labels"]["24_11"] == "النور ١١" and data["window_labels"]["24_64"] == "النور ٦٤"
    assert "جَاءُوا بِالْإِفْكِ" in data["window_verses"]["24_11"]
    assert set(data["window_verses"]) == set(data["window_order"])   # the verse of every ayah
    assert data["default_tafsir"] == "ibn_kathir" and data["default_window"] == "24_11"
    assert data["surah"] == {"number": 24, "name_ar": "النور", "name_en": "An-Nur", "ayat": 64}
    assert len(data["surahs"]) == 114 and sum(x["ayat"] for x in data["surahs"]) == 6236
    assert [x["n"] for x in data["surahs"] if x["available"]] == [24]
    # the page's labels in every language the console ships, the console's languages endpoint to follow
    assert set(data["i18n"]) >= {"ar", "en", "ur", "zh"} and data["i18n"]["en"]["site.ayah"] == "Ayah"
    assert all(set(data["i18n"][c]) == set(data["i18n"]["en"]) for c in data["i18n"])
    assert data["live_languages_url"].endswith("/public/v1/languages.json")
    assert data["published"]["version"] == 1 and data["published"]["units"] == len(want)
    assert data["coverage"]["ayahs"] == 1 and data["coverage"]["tafsirs"] == 2
    assert data["live_snapshot_url"].startswith("https://console.mirqah.app/public/v1/")


def test_text_is_the_pinned_source_letter_for_letter(built):
    _html, data = built
    for tid, t in data["tafsirs"].items():
        for wid, w in t["windows"].items():
            raw = (ROOT / w["source_file"]).read_bytes()
            assert hashlib.sha256(raw).hexdigest() == w["source_sha256"]
            full = raw.decode("utf-8")
            assert full[w["window_start"]:w["window_end"]] == w["window_text"]
            assert t["raw"][wid]["source_sha256"] == w["source_sha256"] and "text" not in t["raw"][wid]
            base = w["window_start"]
            for sp in w["spans"]:   # offsets only: the span's text is the window's text
                assert set(sp) == {"id", "start", "end"} and base <= sp["start"] < sp["end"] <= w["window_end"]
            for ap in w["apparatus"]:
                assert "text" not in ap and "start" in ap and "end" in ap
            by_id = {sp["id"]: sp for sp in w["spans"]}
            for mv in (t["verified"][wid].get("approved") or {}).get("moves") or []:
                # a move's text is its spans joined (the editor's apparatus between them is
                # not the mufassir's text); every span reads back from the source
                assert "".join(w["window_text"][by_id[i]["start"] - base:by_id[i]["end"] - base] for i in mv["span_ids"]) == mv["text"]
                assert w["window_start"] <= mv["start"] < mv["end"] <= w["window_end"]


def test_a_unit_whose_source_changed_is_left_out(tmp_path):
    snap = json.loads(FIXTURE.read_text(encoding="utf-8"))
    for u in snap["units"]:
        if u["tafsir"] == "al_saadi":
            u["source_sha256"] = "0" * 64
    p = tmp_path / "snap.json"
    p.write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "index.html"
    build_site.build(str(p), out)
    html = out.read_text(encoding="utf-8")
    data = json.loads(re.search(r'id="methods-data">(.*?)</script>', html, re.S).group(1).replace("\\u003c", "<"))
    saadi = data["tafsirs"]["al_saadi"]
    assert len(saadi["windows"]) == 64 and not any(saadi["verified"].values())   # the text stays, no unit
    assert any(data["tafsirs"]["ibn_kathir"]["verified"].values())
    assert any("source changed" in s for s in data["skipped"])


def test_review_mode_and_old_pages_are_gone(built):
    html, _ = built
    assert 'if (params.get("mode") === "review")' not in html
    assert 'id="btn-toggle-mode" hidden' in html and 'id="btn-export-decisions" hidden' in html
    assert 'href="fahras.html"' not in html and "mirqah-wordmark.svg" in html
    assert 'id="btn-export-log" hidden style="display:none!important"' in html
    assert 'id="pub-line"' in html and '"pub-badge"' in html
    assert "availableWindows()" in html and "function goTo(" in html and "fahras:render" in html
    assert "nav-strip" in html and "live_snapshot_url" in html
    assert "surah-pop" in html and "lang-pop" in html and "mq-lang" in html
    assert html.count("<style>") == 1 and html.count("</style>") == 1   # one style block, the brand tokens inside it
    assert "--gold:" in html and html.index("--gold:") > html.index("--m-ray:")
    low = html.lower()
    for word in VENDOR_WORDS:
        assert word not in low, word


def test_committed_site_folder_is_the_built_reader():
    html = (SITE / "index.html").read_text(encoding="utf-8")
    assert html.startswith('<meta charset="utf-8">') and 'id="methods-data"' in html
    assert 'id="btn-toggle-mode" hidden' in html
    for name in ("reader.html", "fahras.html", "methods.html", "app.html"):
        assert "url=/" in (SITE / name).read_text(encoding="utf-8")
    for name in ("reconcile.html", "index_data.json", "reconcile_data.json", "published.json"):
        assert not (SITE / name).exists()
    headers = (SITE / "_headers").read_text(encoding="utf-8")
    assert "Content-Security-Policy" in headers
    for asset in ("mirqah-wordmark.svg", "mirqah-wordmark-on-dark.svg", "quranpedia-books.js"):
        assert (SITE / "assets" / "brand" / asset).is_file()
