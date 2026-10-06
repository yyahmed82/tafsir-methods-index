"""The public site (site/): the reader built from the published snapshot, nothing else.

Built by src/build_site.py from src/fahras_v2_template.html. It shows only units a
specialist approved and a super admin published, inside the pinned source text; no
review mode, no export, no working states, no model or vendor names.
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


def test_only_published_units_and_only_their_ayat(built):
    html, data = built
    snap = json.loads(FIXTURE.read_text(encoding="utf-8"))
    want = {(u["tafsir"], u["id"]) for u in snap["units"]}
    got = set()
    for tid, t in data["tafsirs"].items():
        for wid, block in t["verified"].items():
            assert list(block) == ["approved"]
            for mv in block["approved"]["moves"]:
                assert mv["review_status"] == "approved"
                got.add((tid, mv["id"]))
    assert got == want
    assert data["tafsir_order"] == ["ibn_kathir", "al_saadi"]
    assert data["window_order"] == ["24_11"]
    assert data["window_labels"]["24_11"] == "النور ١١"
    assert "جَاءُوا بِالْإِفْكِ" in data["window_verses"]["24_11"]
    assert data["published"]["version"] == 1 and data["published"]["units"] == len(want)


def test_text_is_the_pinned_source_letter_for_letter(built):
    _html, data = built
    for tid, t in data["tafsirs"].items():
        for wid, w in t["windows"].items():
            raw = (ROOT / w["source_file"]).read_bytes()
            assert hashlib.sha256(raw).hexdigest() == w["source_sha256"]
            full = raw.decode("utf-8")
            assert full[w["window_start"]:w["window_end"]] == w["window_text"] == t["raw"][wid]["text"]
            for sp in w["spans"]:
                assert full[sp["start"]:sp["end"]] == sp["text"]
            by_id = {sp["id"]: sp for sp in w["spans"]}
            for mv in t["verified"][wid]["approved"]["moves"]:
                # a move's text is its spans joined (the editor's apparatus between them is
                # not the mufassir's text); every span reads back from the source
                assert "".join(by_id[i]["text"] for i in mv["span_ids"]) == mv["text"]
                assert all(full[by_id[i]["start"]:by_id[i]["end"]] == by_id[i]["text"] for i in mv["span_ids"])
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
    assert "al_saadi" not in data["tafsirs"] and "ibn_kathir" in data["tafsirs"]
    assert any("source changed" in s for s in data["skipped"])


def test_review_mode_and_old_pages_are_gone(built):
    html, _ = built
    assert 'if (params.get("mode") === "review")' not in html
    assert 'id="btn-toggle-mode" hidden' in html and 'id="btn-export-decisions" hidden' in html
    assert 'href="fahras.html"' not in html and "mirqah-wordmark.svg" in html
    assert 'id="pub-badge"' in html and 'id="pub-line"' in html
    assert "availableWindows()" in html
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
