"""Build the public site (site/index.html) from the reader template and the published snapshot.

The public page is the reader (src/fahras_v2_template.html) with one change of substance:
it shows only what a human specialist approved and a super admin published from the
committee console. The text itself comes from the pinned source files in data/ (letter
for letter, the same fidelity checks as build_fahras.py); the approved units come from
the published snapshot (``/public/v1/published.json``). Nothing here approves, nothing
here writes under data/.

    python src/build_site.py                        # snapshot from the console
    python src/build_site.py --snapshot path.json   # a saved snapshot (tests, offline)
    python src/build_site.py --snapshot URL

Review mode, the export button and every working state are removed from the page.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from build_fahras import check_html, embed  # noqa: E402
from textcore import read_exact as _read_exact, read_json as _read_json  # noqa: E402

TEMPLATE = ROOT / "src" / "fahras_v2_template.html"
OUT = ROOT / "site" / "index.html"
DATA_MARKER = "__METHODS_DATA_JSON__"
DEFAULT_SNAPSHOT = "https://console.mirqah.app/public/v1/published.json"

TAFSIR_ORDER = ("al_tabari", "ibn_kathir", "al_baghawi", "al_saadi")
TAFSIR_META = {
    "al_tabari": ("تفسير الطبري", "الطبري", "محمد بن جرير الطبري"),
    "ibn_kathir": ("تفسير ابن كثير", "ابن كثير", "إسماعيل بن عمر بن كثير"),
    "al_baghawi": ("تفسير البغوي", "البغوي", "الحسين بن مسعود البغوي"),
    "al_saadi": ("تفسير السعدي", "السعدي", "عبد الرحمن بن ناصر السعدي"),
}
SURAH_AR = {2: "البقرة", 8: "الأنفال", 17: "الإسراء", 24: "النور"}
DATA_ROOTS = {24: ROOT / "data" / "nur"}
AR_DIGITS = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")
MONTHS_AR = ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس",
             "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"]


def ar(n: int | str) -> str:
    return str(n).translate(AR_DIGITS)


def load_snapshot(src: str) -> dict:
    if src.startswith("http://") or src.startswith("https://"):
        # Cloudflare's bot check answers 403 to Python's default User-Agent
        req = urllib.request.Request(src, headers={"Accept": "application/json",
                                                   "User-Agent": "Mozilla/5.0 (mirqah-site-builder)"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 (our own console)
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise SystemExit("nothing is published yet: publish a version from the console"
                                 " (النشر → انشر الإصدار) and run this again") from e
            if e.code == 403:
                raise SystemExit(f"{src}: 403 from the edge. Download it with a browser or"
                                 " `curl -fsSL <url> -o published.json` and run with"
                                 " --snapshot published.json") from e
            raise
    return _read_json(Path(src))


def _parts(base: Path, n: int) -> list[Path]:
    d = base / "windows"
    out = [p for p in d.glob(f"24_{n}.json")] + sorted(d.glob(f"24_{n}_p*.json"))
    return [p for p in out if re.match(rf"^24_{n}(_p\d+)?$", p.stem)]


def ayah_window(base: Path, surah: int, n: int) -> tuple[dict, str, str]:
    """One window for the whole commentary of an ayah: the source slice from the first
    part to the last, with every span and apparatus entry (offsets are absolute)."""
    parts = [_read_json(p) for p in _parts(base, n)]
    if not parts:
        raise SystemExit(f"{base.name}: no window for {surah}:{n}")
    parts.sort(key=lambda w: int(w["window_start"]))
    first, last = parts[0], parts[-1]
    raw_path = ROOT / first["source_file"]
    full = _read_exact(raw_path)
    sha = hashlib.sha256(raw_path.read_bytes()).hexdigest()
    start, end = int(first["window_start"]), int(last["window_end"])
    text = full[start:end]
    spans: list[dict] = []
    apparatus: list[dict] = []
    for w in parts:
        if full[w["window_start"]:w["window_end"]] != w["window_text"]:
            raise SystemExit(f"{base.name}/{w['window_id']}: window_text != source slice")
        for sp in w.get("spans") or []:
            if full[sp["start"]:sp["end"]] != sp["text"]:
                raise SystemExit(f"{base.name}/{w['window_id']} span {sp['id']} != source")
            spans.append(sp)
        apparatus.extend(w.get("apparatus") or [])
    seen = set()
    for sp in spans:
        if sp["id"] in seen:
            raise SystemExit(f"{base.name}/{surah}:{n}: duplicate span id {sp['id']}")
        seen.add(sp["id"])
    key = f"{surah}_{n}"
    window = {
        "window_id": key, "verse_key": key, "ayah": f"{surah}:{n}", "surah": surah,
        "ayah_number": n, "source_file": first["source_file"], "source_sha256": sha,
        "window_start": start, "window_end": end, "window_text": text, "spans": spans,
        "apparatus": apparatus, "selection": {"parts": len(parts)}, "span_count": len(spans),
    }
    return window, text, sha


def collect(snapshot: dict) -> dict:
    units = snapshot.get("units") or []
    swin = {(w["tafsir"], w["window"]): w for w in snapshot.get("windows") or []}
    by_t_ayah: dict[tuple[str, int, int], list[dict]] = {}
    for u in units:
        s, n = (int(x) for x in str(u["ayah"]).split(":"))
        by_t_ayah.setdefault((u["tafsir"], s, n), []).append(u)
    tafsirs: dict = {}
    labels: dict[str, str] = {}
    verses: dict[str, str] = {}
    order: set[str] = set()
    skipped: list[str] = []
    for tid in TAFSIR_ORDER:
        name, short, author = TAFSIR_META[tid]
        windows: dict = {}
        raw: dict = {}
        verified: dict = {}
        for (t, s, n), us in sorted(by_t_ayah.items(), key=lambda kv: (kv[0][1], kv[0][2])):
            if t != tid or s not in DATA_ROOTS:
                continue
            base = DATA_ROOTS[s] / tid
            w, text, sha = ayah_window(base, s, n)
            pinned = {u["source_sha256"] for u in us}
            if pinned != {sha}:
                skipped.append(f"{tid}/{s}:{n} (source changed since publication)")
                continue
            moves = []
            for u in sorted(us, key=lambda u: int(u["start"])):
                a, b = int(u["start"]), int(u["end"])
                by_id = {sp["id"]: sp for sp in w["spans"]}
                joined = "".join(by_id[i]["text"] for i in u.get("span_ids") or [] if i in by_id)
                if not (w["window_start"] <= a < b <= w["window_end"]) or not joined or joined != u["text"] \
                        or any(i not in by_id for i in u.get("span_ids") or []):
                    skipped.append(f"{u['id']} (text differs from the pinned source)")
                    continue
                moves.append({
                    "move_id": u["move"], "id": u["id"], "span_ids": u.get("span_ids") or [],
                    "start": a, "end": b, "text": u["text"], "primary": u.get("primary"),
                    "secondary": u.get("secondary") or [], "content_tags": u.get("content_tags") or [],
                    "certainty": u.get("certainty"), "evidence_span_ids": u.get("evidence_span_ids") or [],
                    "references": u.get("references") or {}, "flags": [],
                    "review_status": "approved", "origin": "approved",
                    "approved_at": u.get("approved_at"),
                })
            if not moves:
                continue
            key = w["verse_key"]
            windows[key] = w
            raw[key] = {"text": text, "source_sha256": sha, "source_file": w["source_file"],
                        "window_start": w["window_start"], "window_end": w["window_end"]}
            verified[key] = {"approved": {"annotator": "approved", "moves": moves,
                                          "summary": {"move_count": len(moves)}}}
            order.add(key)
            labels[key] = f"{SURAH_AR.get(s, 'سورة ' + ar(s))} {ar(n)}"
            sw = swin.get((tid, key)) or next((x for (tt, _k), x in swin.items() if tt == tid and x.get("ayah") == f"{s}:{n}"), None)
            if sw and sw.get("ayah_text") and key not in verses:
                verses[key] = sw["ayah_text"]
        if windows:
            tafsirs[tid] = {"id": tid, "name": name, "short": short, "author": author,
                            "windows": windows, "markers": {k: {"family_counts": {}, "spans": [],
                                                                "editor_footnote_evidence": [], "isnad_ranges": []}
                                                            for k in windows},
                            "layers": {}, "verified": verified, "raw": raw,
                            "annotators": ["approved"], "classifier_ran": True,
                            "run1_totals": {"auto": 0, "specialist": 0}}
    for key in order:
        if key not in verses:   # the verse from any tafsir of the snapshot, else from the data
            s, n = (int(x) for x in key.split("_"))
            for w in snapshot.get("windows") or []:
                if w.get("ayah") == f"{s}:{n}" and w.get("ayah_text"):
                    verses[key] = w["ayah_text"]
                    break
    window_order = sorted(order, key=lambda k: tuple(int(x) for x in k.split("_")))
    tafsir_order = [t for t in TAFSIR_ORDER if t in tafsirs]
    first = tafsir_order[0] if tafsir_order else "al_tabari"
    first_w = next((k for k in window_order if k in tafsirs.get(first, {}).get("windows", {})), window_order[0] if window_order else "")
    n_units = sum(len(v["approved"]["moves"]) for t in tafsirs.values() for v in t["verified"].values())
    pub_at = snapshot.get("published_at")
    date_ar = ""
    if pub_at:
        d = datetime.fromtimestamp(float(pub_at), tz=timezone.utc)
        date_ar = f"{ar(d.day)} {MONTHS_AR[d.month - 1]} {ar(d.year)}"
    seed = tafsirs.get(first) or {"windows": {}, "markers": {}, "verified": {}, "layers": {}, "raw": {},
                                   "classifier_ran": False, "annotators": [], "id": first,
                                   "name": TAFSIR_META[first][0]}
    payload = {
        "tafsirs": tafsirs, "tafsir_order": tafsir_order,
        "tafsir_labels": {t: TAFSIR_META[t][1] for t in tafsir_order},
        "default_tafsir": first, "default_window": first_w,
        "window_order": window_order, "window_labels": labels, "window_verses": verses,
        "windows": seed["windows"], "markers": seed["markers"], "verified": seed["verified"],
        "layers": seed["layers"], "raw": seed["raw"], "classifier_ran": seed["classifier_ran"],
        "tafsir": {"id": seed["id"], "name": seed["name"]}, "annotators": seed["annotators"],
        "sources": {}, "coverage": {"moves": n_units, "ayahs": len(window_order), "tafsirs": len(tafsir_order),
                                    "label": f"{ar(n_units)} موضعاً معتمداً في {ar(len(window_order))} آيات عبر {ar(len(tafsir_order))} تفاسير"},
        "integrity_rule": "لم يُغيَّر حرف من النص",
        "published": {"version": snapshot.get("version"), "published_at": pub_at, "date_ar": date_ar,
                      "units": n_units, "notice_ar": snapshot.get("notice_ar") or ""},
        "skipped": skipped,
    }
    core = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    payload["data_version"] = hashlib.sha256(core.encode("utf-8")).hexdigest()[:12]
    payload["build_date"] = date_ar
    return payload


# ---- the template, made public: reader only, no working states, a version line ----
PATCHES: list[tuple[str, str]] = [
    # review mode is never entered
    ('if (REVIEW_OPEN && params.get("mode") === "review") {', 'if (false) {'),
    # the verse list and prev/next follow the active tafsir (not every tafsir covers every ayah)
    ('    (DATA.window_order || []).forEach(function (wid) {\n      var opt = document.createElement("option");\n      opt.value = wid;',
     '    availableWindows().forEach(function (wid) {\n      var opt = document.createElement("option");\n      opt.value = wid;'),
    ('    var order = DATA.window_order || [];\n    var idx = order.indexOf(state.windowId);',
     '    var order = availableWindows();\n    var idx = order.indexOf(state.windowId);'),
    ('    tafsirSel.addEventListener("change", function () {\n      state.tafsirId = tafsirSel.value;',
     '    tafsirSel.addEventListener("change", function () {\n      state.tafsirId = tafsirSel.value;\n      if (availableWindows().indexOf(state.windowId) < 0) state.windowId = availableWindows()[0] || state.windowId;\n      fillVerseSelect();'),
    ('  function navigateVerse(delta) {',
     '  function availableWindows() {\n    var T = activeTafsir();\n    return (DATA.window_order || []).filter(function (wid) { return T && T.windows && T.windows[wid]; });\n  }\n  function fillVerseSelect() {\n    var verseSel = document.getElementById("verse-sel");\n    if (!verseSel) return;\n    verseSel.textContent = "";\n    availableWindows().forEach(function (wid) {\n      var opt = document.createElement("option");\n      opt.value = wid;\n      opt.textContent = (DATA.window_labels && DATA.window_labels[wid]) || wid;\n      if (wid === state.windowId) opt.selected = true;\n      verseSel.appendChild(opt);\n    });\n  }\n  function navigateVerse(delta) {'),
    # header: no review toggle, no export, no classic page; the brand goes home
    ('<button type="button" class="btn" id="btn-export-decisions" hidden', '<button type="button" class="btn" id="btn-export-decisions" hidden style="display:none!important"'),
    ('<button type="button" class="btn btn-primary" id="btn-toggle-mode" hidden>', '<button type="button" class="btn btn-primary" id="btn-toggle-mode" hidden style="display:none!important">'),
    ('<a href="fahras.html" class="btn btn-ghost" title="الرجوع إلى الواجهة الكلاسيكية">', '<a href="/" class="btn btn-ghost" hidden style="display:none!important" title="">'),
    ('<span class="mode-badge" id="header-mode-badge" hidden>وضع المراجعة</span>',
     '<span class="mode-badge pub-badge" id="header-mode-badge" hidden>وضع المراجعة</span><span class="pub-badge" id="pub-badge"></span>'),
    # the source line carries the published version
    ('اقرأ في المصدر: مركز تفسير — CC BY 4.0 ·', '<span id="pub-line"></span>اقرأ في المصدر: مركز تفسير — CC BY 4.0 ·'),
    ('<div class="ayah-ref" id="reader-ayah-ref">سورة البقرة · الآية ٢٥٥</div>', '<div class="ayah-ref" id="reader-ayah-ref"></div>'),
    # one block per window on the public page: the approved units
    ('    var pref = ["codex", "deepseek", "mimo"];', '    var pref = ["approved"];'),
    ('(T.annotators && T.annotators[0]) || "codex";', '(T.annotators && T.annotators[0]) || "approved";'),
    ('// Re-run strict fidelity verification on replay (Codex DELTA 3):', '// Re-run strict fidelity verification on replay:'),
    # a browser-stored log from an earlier pilot has no place on the public page
    ('<button type="button" class="btn" id="btn-export-log" hidden', '<button type="button" class="btn" id="btn-export-log" hidden style="display:none!important"'),
]

EXTRA_CSS = """
<style>
.pub-badge { display: inline-flex; align-items: center; gap: 6px; margin-inline-start: 10px; padding: 4px 10px; border-radius: 999px;
  font-size: .78rem; background: color-mix(in srgb, var(--accent) 12%, transparent); color: var(--accent); border: 1px solid color-mix(in srgb, var(--accent) 35%, transparent); white-space: nowrap; }
.pub-badge:empty { display: none; }
#pub-line { display: block; margin-bottom: 6px; color: var(--ink, inherit); }
#pub-line b { color: var(--accent); }
.site-empty { max-width: 640px; margin: 10vh auto; padding: 28px 24px; border: 1px solid var(--line); border-radius: 16px; text-align: center; }
.site-empty h2 { margin: 0 0 8px; }
/* the text is the source, letter for letter: no added glyphs, the apparatus markers hidden */
.hl-status { display: none !important; }
.app-glyph { display: none; }
@media (max-width: 640px) { .pub-badge { display: none; } }
</style>
"""

EXTRA_JS = """
<script>
(function () {
  try {
    var D = JSON.parse(document.getElementById("methods-data").textContent);
    var P = D.published || {};
    var line = "الإصدار المنشور v" + String(P.version || "").replace(/\\d/g, function (d) { return "٠١٢٣٤٥٦٧٨٩"[d]; })
      + (P.date_ar ? " · نُشر " + P.date_ar : "") + " · " + (P.notice_ar || "وحدات اعتمدها متخصص بشري وروجعت مقابل النص المثبّت.");
    var badge = document.getElementById("pub-badge");
    if (badge && P.version) badge.textContent = "الإصدار v" + String(P.version).replace(/\\d/g, function (d) { return "٠١٢٣٤٥٦٧٨٩"[d]; }) + " · معتمد";
    var pl = document.getElementById("pub-line");
    if (pl) { var b = document.createElement("b"); b.textContent = line; pl.appendChild(b); }
    // hide the ¬ and ¥ marker glyphs of the editor's apparatus (they stay in the DOM text,
    // so the fidelity check and copy-paste still see the pinned source, letter for letter)
    var art = document.getElementById("reading-article");
    var busy = false;
    function wrapGlyphs() {
      if (!art || busy) return;
      busy = true;
      try {
        var walker = document.createTreeWalker(art, NodeFilter.SHOW_TEXT, null);
        var nodes = [];
        while (walker.nextNode()) {
          var n = walker.currentNode;
          if (n.parentNode && n.parentNode.classList && n.parentNode.classList.contains("app-glyph")) continue;
          if (n.nodeValue.indexOf("\u00ac") >= 0 || n.nodeValue.indexOf("\u00a5") >= 0) nodes.push(n);
        }
        nodes.forEach(function (n) {
          var frag = document.createDocumentFragment();
          n.nodeValue.split(/([\u00ac\u00a5])/).forEach(function (part) {
            if (!part) return;
            if (part === "\u00ac" || part === "\u00a5") {
              var g = document.createElement("span"); g.className = "app-glyph"; g.textContent = part; frag.appendChild(g);
            } else frag.appendChild(document.createTextNode(part));
          });
          n.parentNode.replaceChild(frag, n);
        });
      } finally { busy = false; }
    }
    if (art && window.MutationObserver) {
      new MutationObserver(function () { if (!busy) wrapGlyphs(); }).observe(art, { childList: true, subtree: true });
      wrapGlyphs();
    }
    if (!(D.tafsir_order || []).length) {
      var main = document.getElementById("reader-view");
      if (main) {
        main.innerHTML = '<div class="site-empty"><h2>لم يُنشر بعد أي إصدار معتمد</h2><p>يظهر هنا ما اعتمده متخصص بشري ونشره المشرف العام من لوحة اللجنة.</p><p><a class="btn" id="site-console-link">لوحة اللجنة</a></p></div>';
        var a = document.getElementById("site-console-link"); if (a) a.href = "https:" + "//console.mirqah.app";
      }
    }
  } catch (e) { /* ignore */ }
})();
</script>
"""


# wording that differs between template versions: applied when present, skipped otherwise
OPTIONAL_PATCHES: list[tuple[str, str]] = [
    # every unit on the page is approved: no "the rest is proposed" remainder
    ('" بواسطة متخصص · باقي الوسوم (" + toArabicDigits(proposedCount) + ") مقترحة آلياً · النص مطابق',
     '" بواسطة متخصص بشري" + (proposedCount ? " · باقي الوسوم (" + toArabicDigits(proposedCount) + ") مقترحة آلياً" : "") + " · النص مطابق'),
    ('" بواسطة متخصص · باقي الوسوم (" + toArabicDigits(proposedCount) + ") اقتراح آلي · غير معتمد بعد · النص مطابق',
     '" بواسطة متخصص بشري" + (proposedCount ? " · باقي الوسوم (" + toArabicDigits(proposedCount) + ") اقتراح آلي · غير معتمد بعد" : "") + " · النص مطابق'),
]


def render(payload: dict) -> str:
    html = TEMPLATE.read_text(encoding="utf-8")
    for old, new in PATCHES:
        if old not in html:
            raise SystemExit(f"template changed; patch anchor not found: {old[:70]!r}")
        html = html.replace(old, new, 1)
    for old, new in OPTIONAL_PATCHES:
        html = html.replace(old, new, 1)
    html = html.replace("</style>", EXTRA_CSS.strip() + "\n</style>", 1) if "</style>" in html else html
    html = html.replace(DATA_MARKER, embed(payload))
    html = html.rstrip("\n") + "\n" + EXTRA_JS.strip() + "\n"
    # no path to the old pages or to the review mode is left behind
    html = html.replace('href="fahras.html"', 'href="/"')
    return html


def build(snapshot_src: str = DEFAULT_SNAPSHOT, out: Path = OUT) -> Path:
    snapshot = load_snapshot(snapshot_src)
    if snapshot.get("kind") not in (None, "mirqah-published"):
        raise SystemExit(f"not a published snapshot: {snapshot.get('kind')!r}")
    payload = collect(snapshot)
    html = render(payload)
    check_html(html)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    pub = payload["published"]
    shown = out.relative_to(ROOT) if out.is_relative_to(ROOT) else out
    print(f"site: v{pub['version']} · {pub['units']} approved units · {len(payload['window_order'])} ayat"
          f" · {len(payload['tafsir_order'])} tafsirs → {shown}")
    for s in payload["skipped"]:
        print(f"  skipped: {s}")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--snapshot", default=DEFAULT_SNAPSHOT, help="published.json (URL or file)")
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args(argv)
    build(a.snapshot, Path(a.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
