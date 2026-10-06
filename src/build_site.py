"""Build the public site (site/index.html) from the reader template and the published snapshot.

The public page is the reader (src/fahras_v2_template.html) over the whole surah: every
ayah of every tafsir under data/ (letter for letter, the same fidelity checks as
build_fahras.py), with the units a human specialist approved and a super admin published
from the committee console marked on the text. The approved units come from the
published snapshot (``/public/v1/published.json``): the build embeds the snapshot it was
given, and the page fetches the live one on load, so a newer publication shows on the
next reload without a rebuild. Nothing here approves, nothing here writes under data/.

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
                print("  note: nothing is published yet; the page shows the surah without approved"
                      " units until a version is published (النشر → انشر الإصدار)")
                return {"kind": "mirqah-published", "units": [], "windows": []}
            if e.code == 403:
                raise SystemExit(f"{src}: 403 from the edge. Download it with a browser or"
                                 " `curl -fsSL <url> -o published.json` and run with"
                                 " --snapshot published.json") from e
            raise
    return _read_json(Path(src))


def verse_from(text: str, n: int) -> str | None:
    """The verse quoted at the head of a commentary (the console's pipeline._verse_from):
    the text before «(n)», without the editor's apparatus, the formula and the braces."""
    t = re.sub(r"¬[^¥]*¥", "", (text or "")[:3000])
    m = re.search(rf"\({n}\)", t)
    if not m:
        return None
    head = t[:m.start()]
    i = head.find("{")
    if 0 <= i <= 80:
        head = head[i + 1:]
    head = head.strip().strip("{}").strip()
    return head if 8 <= len(head) <= 1500 else None


def ayat_of(surah: int) -> list[int]:
    """Every ayah number that has a window in any tafsir of the surah."""
    nums: set[int] = set()
    for tid in TAFSIR_ORDER:
        d = DATA_ROOTS[surah] / tid / "windows"
        for p in d.glob(f"{surah}_*.json"):
            m = re.match(rf"^{surah}_(\d+)(_p\d+)?$", p.stem)
            if m:
                nums.add(int(m.group(1)))
    return sorted(nums)


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


def _slim(w: dict) -> dict:
    """The window as the page needs it: the text once, spans and apparatus as offsets
    (their text reads back from the window text, so it is not embedded twice)."""
    out = dict(w)
    out["spans"] = [{"id": sp["id"], "start": sp["start"], "end": sp["end"]} for sp in w["spans"]]
    out["apparatus"] = [{k: v for k, v in ap.items() if k != "text"} for ap in w.get("apparatus") or []]
    return out


def approved_moves(w: dict, us: list[dict], skipped: list[str]) -> list[dict]:
    """The published units of one window as reader moves; a unit whose text does not
    read back from the pinned source is left out (and said so)."""
    moves = []
    by_id = {sp["id"]: sp for sp in w["spans"]}
    for u in sorted(us, key=lambda u: int(u["start"])):
        a, b = int(u["start"]), int(u["end"])
        ids = u.get("span_ids") or []
        joined = "".join(by_id[i]["text"] for i in ids if i in by_id)
        if not (w["window_start"] <= a < b <= w["window_end"]) or not joined or joined != u["text"] \
                or any(i not in by_id for i in ids):
            skipped.append(f"{u['id']} (text differs from the pinned source)")
            continue
        moves.append({
            "move_id": u["move"], "id": u["id"], "span_ids": ids,
            "start": a, "end": b, "text": u["text"], "primary": u.get("primary"),
            "secondary": u.get("secondary") or [], "content_tags": u.get("content_tags") or [],
            "certainty": u.get("certainty"), "evidence_span_ids": u.get("evidence_span_ids") or [],
            "references": u.get("references") or {}, "flags": [],
            "review_status": "approved", "origin": "approved",
            "approved_at": u.get("approved_at"),
        })
    return moves


def collect(snapshot: dict, surah: int = 24) -> dict:
    units = snapshot.get("units") or []
    by_t_ayah: dict[tuple[str, int], list[dict]] = {}
    for u in units:
        s, n = (int(x) for x in str(u["ayah"]).split(":"))
        if s == surah:
            by_t_ayah.setdefault((u["tafsir"], n), []).append(u)
    tafsirs: dict = {}
    labels: dict[str, str] = {}
    verses: dict[str, str] = {}
    skipped: list[str] = []
    approved_keys: dict[str, list[str]] = {}
    nums = ayat_of(surah)
    for tid in TAFSIR_ORDER:
        name, short, author = TAFSIR_META[tid]
        base = DATA_ROOTS[surah] / tid
        windows: dict = {}
        raw: dict = {}
        verified: dict = {}
        for n in nums:
            if not _parts(base, n):
                continue
            w, text, sha = ayah_window(base, surah, n)
            key = w["verse_key"]
            us = by_t_ayah.get((tid, n)) or []
            if us and {u["source_sha256"] for u in us} != {sha}:
                skipped.append(f"{tid}/{surah}:{n} (source changed since publication)")
                us = []
            moves = approved_moves(w, us, skipped) if us else []
            windows[key] = _slim(w)
            raw[key] = {"source_sha256": sha, "source_file": w["source_file"],
                        "window_start": w["window_start"], "window_end": w["window_end"]}
            verified[key] = {"approved": {"annotator": "approved", "moves": moves,
                                          "summary": {"move_count": len(moves)}}} if moves else {}
            if moves:
                approved_keys.setdefault(tid, []).append(key)
            labels[key] = f"{SURAH_AR.get(surah, 'سورة ' + ar(surah))} {ar(n)}"
            if key not in verses:
                v = verse_from(text, n)
                if v:
                    verses[key] = v
        tafsirs[tid] = {"id": tid, "name": name, "short": short, "author": author,
                        "windows": windows, "markers": {k: {"family_counts": {}, "spans": [],
                                                            "editor_footnote_evidence": [], "isnad_ranges": []}
                                                        for k in windows},
                        "layers": {}, "verified": verified, "raw": raw,
                        "annotators": ["approved"], "classifier_ran": True,
                        "run1_totals": {"auto": 0, "specialist": 0}}
    for w in snapshot.get("windows") or []:   # the verse from the snapshot when the data has none
        key = f"{surah}_{w.get('ayah_number')}"
        if key in labels and key not in verses and w.get("ayah_text"):
            verses[key] = w["ayah_text"]
    window_order = [f"{surah}_{n}" for n in nums]
    tafsir_order = list(TAFSIR_ORDER)
    first = next((t for t in TAFSIR_ORDER if approved_keys.get(t)), TAFSIR_ORDER[0])
    first_w = (approved_keys.get(first) or window_order)[0]
    n_units = sum(len(v["approved"]["moves"]) for t in tafsirs.values() for v in t["verified"].values() if v)
    n_ayat = len({k for ks in approved_keys.values() for k in ks})
    n_taf = len(approved_keys)
    pub_at = snapshot.get("published_at")
    date_ar = ""
    if pub_at:
        d = datetime.fromtimestamp(float(pub_at), tz=timezone.utc)
        date_ar = f"{ar(d.day)} {MONTHS_AR[d.month - 1]} {ar(d.year)}"
    seed = tafsirs[first]
    payload = {
        "tafsirs": tafsirs, "tafsir_order": tafsir_order,
        "tafsir_labels": {t: TAFSIR_META[t][1] for t in tafsir_order},
        "default_tafsir": first, "default_window": first_w,
        "window_order": window_order, "window_labels": labels, "window_verses": verses,
        "surah": {"number": surah, "name_ar": SURAH_AR.get(surah, ""), "ayat": len(window_order)},
        "windows": seed["windows"], "markers": seed["markers"], "verified": seed["verified"],
        "layers": seed["layers"], "raw": seed["raw"], "classifier_ran": seed["classifier_ran"],
        "tafsir": {"id": seed["id"], "name": seed["name"]}, "annotators": seed["annotators"],
        "sources": {}, "coverage": {"moves": n_units, "ayahs": n_ayat, "tafsirs": n_taf,
                                    "label": f"{ar(n_units)} موضعاً معتمداً في {ar(n_ayat)} آيات عبر {ar(n_taf)} تفاسير"},
        "integrity_rule": "لم يُغيَّر حرف من النص",
        "published": {"version": snapshot.get("version"), "published_at": pub_at, "date_ar": date_ar,
                      "units": n_units, "notice_ar": snapshot.get("notice_ar") or ""},
        "live_snapshot_url": DEFAULT_SNAPSHOT,
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
     '  function goTo(tid, wid) {\n    if (tid && DATA.tafsirs && DATA.tafsirs[tid]) state.tafsirId = tid;\n    if (wid && availableWindows().indexOf(wid) >= 0) state.windowId = wid;\n    if (availableWindows().indexOf(state.windowId) < 0) state.windowId = availableWindows()[0] || state.windowId;\n    var ts = document.getElementById("tafsir-sel"); if (ts) ts.value = state.tafsirId;\n    fillVerseSelect();\n    resolveAnnotator();\n    replayMoves();\n    state.selectedId = null;\n    renderAll();\n  }\n  function availableWindows() {\n    var T = activeTafsir();\n    return (DATA.window_order || []).filter(function (wid) { return T && T.windows && T.windows[wid]; });\n  }\n  function fillVerseSelect() {\n    var verseSel = document.getElementById("verse-sel");\n    if (!verseSel) return;\n    verseSel.textContent = "";\n    availableWindows().forEach(function (wid) {\n      var opt = document.createElement("option");\n      opt.value = wid;\n      opt.textContent = (DATA.window_labels && DATA.window_labels[wid]) || wid;\n      if (wid === state.windowId) opt.selected = true;\n      verseSel.appendChild(opt);\n    });\n  }\n  function navigateVerse(delta) {'),
    # header: no review toggle, no export, no classic page; the brand goes home
    ('<button type="button" class="btn" id="btn-export-decisions" hidden', '<button type="button" class="btn" id="btn-export-decisions" hidden style="display:none!important"'),
    ('<button type="button" class="btn btn-primary" id="btn-toggle-mode" hidden>', '<button type="button" class="btn btn-primary" id="btn-toggle-mode" hidden style="display:none!important">'),
    ('<a href="fahras.html" class="btn btn-ghost" title="الرجوع إلى الواجهة الكلاسيكية">', '<a href="/" class="btn btn-ghost" hidden style="display:none!important" title="">'),
    # the source line carries the published version
    ('اقرأ في المصدر: مركز تفسير — CC BY 4.0 ·', '<span id="pub-line"></span>اقرأ في المصدر: مركز تفسير — CC BY 4.0 ·'),
    ('<div class="ayah-ref" id="reader-ayah-ref">سورة البقرة · الآية ٢٥٥</div>', '<div class="ayah-ref" id="reader-ayah-ref"></div>'),
    # one block per window on the public page: the approved units
    ('    var pref = ["codex", "deepseek", "mimo"];', '    var pref = ["approved"];'),
    ('(T.annotators && T.annotators[0]) || "codex";', '(T.annotators && T.annotators[0]) || "approved";'),
    ('// Re-run strict fidelity verification on replay (Codex DELTA 3):', '// Re-run strict fidelity verification on replay:'),
    # a browser-stored log from an earlier pilot has no place on the public page
    ('<button type="button" class="btn" id="btn-export-log" hidden', '<button type="button" class="btn" id="btn-export-log" hidden style="display:none!important"'),
    # the page tells the navigation strip it rendered, and keeps the address shareable
    ('    var refEl = document.getElementById("reader-ayah-ref");\n    if (refEl) refEl.textContent = label;',
     '    var refEl = document.getElementById("reader-ayah-ref");\n    if (refEl) refEl.textContent = label;\n    try { var _u = new URL(window.location.href); _u.searchParams.set("t", state.tafsirId); _u.searchParams.set("w", state.windowId); window.history.replaceState({}, "", _u.toString()); } catch (e0) { /* ignore */ }\n    try { document.dispatchEvent(new CustomEvent("fahras:render")); } catch (e1) { /* ignore */ }'),
    # the live overlay and the navigation strip reach the page through this API
    ('    state: state,\n    getSelectedMove: getSelectedMove,',
     '    state: state,\n    DATA: DATA,\n    goTo: goTo,\n    navigateVerse: navigateVerse,\n    availableWindows: availableWindows,\n    getSelectedMove: getSelectedMove,'),
]

EXTRA_CSS = """
<style>
.pub-badge { display: inline-flex; align-items: center; gap: 6px; margin-inline-start: 10px; padding: 4px 10px; border-radius: 999px;
  font-size: .78rem; background: color-mix(in srgb, var(--accent) 12%, transparent); color: var(--accent); border: 1px solid color-mix(in srgb, var(--accent) 35%, transparent); white-space: nowrap; }
.pub-badge:empty { display: none; }
#pub-line { display: block; margin-bottom: 6px; color: var(--ink, inherit); }
#pub-line b { color: var(--accent); }
/* the text is the source, letter for letter: no added glyphs, the apparatus markers hidden */
.hl-status { display: none !important; }
/* working states and model notes have no place on the published page (every unit here is approved) */
#ec-route-host, #ec-notes, .g-route-host, .g-notes, .g-disclaimer { display: none !important; }
#ec-status-line[hidden] { display: block !important; }
.app-glyph { display: none; }
.chips-bar.is-empty { display: none; }
/* navigation: the surah's ayat in a strip, the tafsirs as tabs (the reading below is unchanged) */
.nav-strip { background: var(--surface); border: 1px solid var(--line); border-radius: 14px; padding: 10px 12px; margin-bottom: 14px; }
.nav-strip .nav-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.nav-strip .nav-row + .nav-row { margin-top: 10px; }
.nav-strip .nav-lbl { font-size: .8rem; color: var(--muted); margin-inline-end: 2px; }
.nav-taf { display: inline-flex; align-items: center; gap: 6px; border: 1px solid var(--line); background: var(--surface); color: var(--sub, var(--ink));
  border-radius: 999px; padding: 6px 13px; font-size: .86rem; font-weight: 600; cursor: pointer; transition: all .15s ease; }
.nav-taf:hover { background: var(--surface-2, var(--accent-bg)); }
.nav-taf.is-cur { border-color: var(--accent); background: var(--accent-bg); color: var(--accent); }
.nav-taf small { font-size: .74rem; font-weight: 500; color: var(--ok); }
.nav-taf.is-cur small { color: var(--accent); }
.nav-ayat { display: flex; gap: 6px; overflow-x: auto; padding: 4px 2px 6px; scroll-snap-type: x proximity; -webkit-overflow-scrolling: touch; scrollbar-width: thin; }
.nav-ayah { flex: 0 0 auto; min-width: 38px; height: 38px; padding: 0 8px; border-radius: 999px; border: 1px solid var(--line); background: var(--surface);
  color: var(--sub, var(--ink)); font-size: .92rem; font-weight: 600; cursor: pointer; position: relative; scroll-snap-align: center; transition: all .15s ease; font-variant-numeric: tabular-nums; }
.nav-ayah:hover { background: var(--surface-2, var(--accent-bg)); }
.nav-ayah.has-ok { border-color: var(--ok); color: var(--ok); }
.nav-ayah.has-ok::after { content: ""; position: absolute; bottom: 3px; left: 50%; transform: translateX(-50%); width: 5px; height: 5px; border-radius: 50%; background: var(--ok); }
.nav-ayah.has-any:not(.has-ok) { border-style: dashed; }
.nav-ayah.is-cur { background: var(--accent); border-color: var(--accent); color: #fff; }
.nav-ayah.is-cur::after { background: #fff; }
.nav-ayah.is-dim { display: none; }
.nav-jump { margin-inline-start: auto; display: inline-flex; align-items: center; gap: 6px; }
.nav-jump .ib-btn { width: 34px; height: 34px; }
.nav-only { display: inline-flex; align-items: center; gap: 6px; font-size: .8rem; color: var(--muted); cursor: pointer; user-select: none; }
.nav-only input { accent-color: var(--accent); }
.nav-note { font-size: .8rem; color: var(--muted); margin: 4px 2px 0; }
.nav-live { font-size: .74rem; color: var(--muted); }
.nav-live.is-on { color: var(--ok); }
@media (max-width: 640px) { .pub-badge { display: none; } .nav-taf { padding: 5px 10px; font-size: .8rem; } .nav-ayah { min-width: 34px; height: 34px; font-size: .86rem; } }
</style>
"""

EXTRA_JS = """
<script>
(function () {
  // the address as the visitor opened it (before the reader writes t= and w= into it)
  var OPENED_WITH_W = false;
  try { OPENED_WITH_W = new URLSearchParams(window.location.search).has("w"); } catch (e) { /* ignore */ }
  var AR = function (n) { return String(n == null ? "" : n).replace(/\\d/g, function (d) { return "٠١٢٣٤٥٦٧٨٩"[d]; }); };
  var MONTHS = ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"];
  function api() { return window.__fahras_v2 || null; }
  function D() { var a = api(); return a && a.DATA; }
  function dateAr(ts) { if (!ts) return ""; var d = new Date(ts * 1000); return AR(d.getUTCDate()) + " " + MONTHS[d.getUTCMonth()] + " " + AR(d.getUTCFullYear()); }

  // ---- the published version in the header and the source box
  function paintVersion(P, live) {
    var badge = document.getElementById("pub-badge");
    if (!badge) { var wrap = document.querySelector(".brand-wrap"); if (wrap) { badge = document.createElement("span"); badge.className = "pub-badge"; badge.id = "pub-badge"; wrap.appendChild(badge); } }
    if (badge) badge.textContent = P.version ? "الإصدار v" + AR(P.version) + " · معتمد" : "";
    var pl = document.getElementById("pub-line");
    if (pl) {
      pl.textContent = "";
      var b = document.createElement("b");
      b.textContent = P.version
        ? "الإصدار المنشور v" + AR(P.version) + (P.date_ar ? " · نُشر " + P.date_ar : "") + " · " + (P.notice_ar || "وحدات اعتمدها متخصص بشري وروجعت مقابل النص المثبّت.")
        : "لم يُنشر بعد أي إصدار معتمد · النص معروض كاملاً من المصدر المثبّت.";
      pl.appendChild(b);
    }
    var lv = document.getElementById("nav-live");
    if (lv) { lv.textContent = live ? "مُحدَّث من لوحة اللجنة" : "نسخة وقت البناء"; lv.classList.toggle("is-on", !!live); }
  }

  // ---- the approved units of each tafsir per ayah (for the strip's marks)
  function approvedMap() {
    var d = D(); var out = {};
    if (!d) return out;
    Object.keys(d.tafsirs || {}).forEach(function (tid) {
      var T = d.tafsirs[tid]; out[tid] = {};
      Object.keys(T.verified || {}).forEach(function (k) {
        var blk = T.verified[k] || {}; var n = 0;
        Object.keys(blk).forEach(function (a) { n += ((blk[a] && blk[a].moves) || []).length; });
        if (n) out[tid][k] = n;
      });
    });
    return out;
  }

  // ---- the navigation strip: tafsir tabs, the surah's ayat, approved-only switch
  var onlyApproved = false;
  function buildStrip() {
    var d = D(); var col = document.querySelector(".reader-col"); var card = document.querySelector(".ayah-card");
    if (!d || !col || !card || document.getElementById("nav-strip")) return;
    var box = document.createElement("nav"); box.className = "nav-strip"; box.id = "nav-strip"; box.setAttribute("aria-label", "التنقل بين التفاسير والآيات");
    var r1 = document.createElement("div"); r1.className = "nav-row"; r1.id = "nav-tafsirs";
    var r2 = document.createElement("div"); r2.className = "nav-row";
    var lbl = document.createElement("span"); lbl.className = "nav-lbl"; lbl.textContent = "سورة " + ((d.surah && d.surah.name_ar) || "") + " · الآيات";
    r2.appendChild(lbl);
    var only = document.createElement("label"); only.className = "nav-only";
    var cb = document.createElement("input"); cb.type = "checkbox"; cb.id = "nav-only-approved";
    cb.addEventListener("change", function () { onlyApproved = cb.checked; paintStrip(); });
    only.appendChild(cb); only.appendChild(document.createTextNode("الآيات ذات المواضع المعتمدة فقط"));
    r2.appendChild(only);
    var jump = document.createElement("span"); jump.className = "nav-jump";
    var live = document.createElement("span"); live.className = "nav-live"; live.id = "nav-live"; jump.appendChild(live);
    var prev = document.createElement("button"); prev.type = "button"; prev.className = "ib-btn"; prev.title = "الآية السابقة"; prev.textContent = "›";
    var next = document.createElement("button"); next.type = "button"; next.className = "ib-btn"; next.title = "الآية التالية"; next.textContent = "‹";
    prev.addEventListener("click", function () { step(-1); }); next.addEventListener("click", function () { step(1); });
    jump.appendChild(prev); jump.appendChild(next); r2.appendChild(jump);
    var r3 = document.createElement("div"); r3.className = "nav-ayat"; r3.id = "nav-ayat";
    box.appendChild(r1); box.appendChild(r2); box.appendChild(r3);
    col.insertBefore(box, card);
  }
  function visibleOrder() {
    var a = api(); if (!a) return [];
    var order = a.availableWindows ? a.availableWindows() : (a.DATA.window_order || []);
    if (!onlyApproved) return order;
    var m = approvedMap()[a.state.tafsirId] || {};
    return order.filter(function (k) { return m[k]; });
  }
  function step(delta) {
    var a = api(); if (!a) return;
    var order = visibleOrder(); var i = order.indexOf(a.state.windowId);
    var j = i < 0 ? 0 : i + delta;
    if (j >= 0 && j < order.length) a.goTo(null, order[j]);
  }
  function paintStrip() {
    var a = api(); var d = D(); if (!a || !d) return;
    var st = a.state; var ap = approvedMap();
    var r1 = document.getElementById("nav-tafsirs"); var r3 = document.getElementById("nav-ayat");
    if (!r1 || !r3) return;
    r1.textContent = "";
    var l = document.createElement("span"); l.className = "nav-lbl"; l.textContent = "التفسير"; r1.appendChild(l);
    (d.tafsir_order || []).forEach(function (tid) {
      var b = document.createElement("button"); b.type = "button"; b.className = "nav-taf" + (tid === st.tafsirId ? " is-cur" : "");
      b.textContent = (d.tafsir_labels && d.tafsir_labels[tid]) || tid;
      var n = Object.keys(ap[tid] || {}).length;
      if (n) { var s = document.createElement("small"); s.textContent = AR(n) + " آية"; s.title = "آيات فيها مواضع معتمدة"; b.appendChild(document.createTextNode(" ")); b.appendChild(s); }
      b.addEventListener("click", function () { a.goTo(tid, null); });
      r1.appendChild(b);
    });
    r3.textContent = "";
    var mine = ap[st.tafsirId] || {};
    var cur = null;
    (d.window_order || []).forEach(function (k) {
      var any = Object.keys(ap).some(function (t) { return ap[t][k]; });
      var b = document.createElement("button"); b.type = "button"; b.className = "nav-ayah";
      var n = String(k).split("_")[1] || k;
      b.textContent = AR(n);
      if (mine[k]) { b.classList.add("has-ok"); b.title = AR(mine[k]) + " موضع معتمد في " + ((d.tafsir_labels && d.tafsir_labels[st.tafsirId]) || ""); }
      else if (any) { b.classList.add("has-any"); b.title = "مواضع معتمدة في تفسير آخر"; }
      else b.title = "الآية " + AR(n);
      if (k === st.windowId) { b.classList.add("is-cur"); b.setAttribute("aria-current", "true"); cur = b; }
      if (onlyApproved && !mine[k] && k !== st.windowId) b.classList.add("is-dim");
      b.addEventListener("click", function () { a.goTo(null, k); });
      r3.appendChild(b);
    });
    if (cur && cur.scrollIntoView) { try { cur.scrollIntoView({ block: "nearest", inline: "center", behavior: "smooth" }); } catch (e) { /* ignore */ } }
    var chips = document.getElementById("reader-chips-bar");
    if (chips) chips.classList.toggle("is-empty", !(st.reviewMoves || []).length);
  }

  // ---- the live snapshot: what the console published since this page was built
  function overlay(snap) {
    var d = D(); if (!d || !snap || snap.kind !== "mirqah-published") return false;
    var units = snap.units || [];
    var fresh = {};
    Object.keys(d.tafsirs || {}).forEach(function (tid) { fresh[tid] = {}; });
    var n_units = 0;
    units.forEach(function (u) {
      var T = d.tafsirs && d.tafsirs[u.tafsir]; if (!T) return;
      var parts = String(u.ayah || "").split(":"); var key = parts[0] + "_" + parts[1];
      var w = T.windows && T.windows[key]; if (!w || w.source_sha256 !== u.source_sha256) return;
      var base = w.window_start; var byId = {};
      (w.spans || []).forEach(function (sp) { byId[sp.id] = sp; });
      var ids = u.span_ids || [];
      if (!ids.length || ids.some(function (i) { return !byId[i]; })) return;
      var joined = ids.map(function (i) { return w.window_text.slice(byId[i].start - base, byId[i].end - base); }).join("");
      var a = +u.start, b = +u.end;
      if (joined !== u.text || !(w.window_start <= a && a < b && b <= w.window_end)) return;
      (fresh[u.tafsir][key] = fresh[u.tafsir][key] || []).push({
        move_id: u.move, id: u.id, span_ids: ids, start: a, end: b, text: u.text, primary: u.primary,
        secondary: u.secondary || [], content_tags: u.content_tags || [], certainty: u.certainty,
        evidence_span_ids: u.evidence_span_ids || [], references: u.references || {}, flags: [],
        review_status: "approved", origin: "approved", approved_at: u.approved_at });
      n_units++;
    });
    Object.keys(fresh).forEach(function (tid) {
      var T = d.tafsirs[tid]; T.verified = {};
      Object.keys(fresh[tid]).forEach(function (k) {
        var mv = fresh[tid][k].sort(function (x, y) { return x.start - y.start; });
        T.verified[k] = { approved: { annotator: "approved", moves: mv, summary: { move_count: mv.length } } };
      });
    });
    d.published = { version: snap.version, published_at: snap.published_at, date_ar: dateAr(snap.published_at), units: n_units, notice_ar: snap.notice_ar || "" };
    return true;
  }
  function loadLive() {
    var d = D(); var url = d && d.live_snapshot_url;
    try { url = new URLSearchParams(window.location.search).get("data") || url; } catch (e) { /* ignore */ }
    if (!url || !window.fetch) return;
    fetch(url, { headers: { "Accept": "application/json" }, cache: "no-cache" }).then(function (r) { return r.ok ? r.json() : null; }).then(function (snap) {
      if (!overlay(snap)) return;
      var a = api(); var st = a.state;
      paintVersion(d.published, true);
      var ap = approvedMap();
      // no address given: open the first ayah with an approved unit
      var mine = ap[st.tafsirId] || {};
      if (!OPENED_WITH_W && !mine[st.windowId]) {
        var t0 = (d.tafsir_order || []).filter(function (t) { return Object.keys(ap[t] || {}).length; })[0];
        if (t0) { var k0 = (d.window_order || []).filter(function (k) { return ap[t0][k]; })[0]; a.goTo(t0, k0); return; }
      }
      a.goTo(null, null);
    }).catch(function () { /* the build-time snapshot stays */ });
  }

  // ---- hide the ¬ and ¥ marker glyphs of the editor's apparatus (they stay in the DOM text,
  // so the fidelity check and copy-paste still see the pinned source, letter for letter)
  var busy = false;
  function wrapGlyphs(art) {
    if (!art || busy) return;
    busy = true;
    try {
      var walker = document.createTreeWalker(art, NodeFilter.SHOW_TEXT, null);
      var nodes = [];
      while (walker.nextNode()) {
        var n = walker.currentNode;
        if (n.parentNode && n.parentNode.classList && n.parentNode.classList.contains("app-glyph")) continue;
        if (n.nodeValue.indexOf("\\u00ac") >= 0 || n.nodeValue.indexOf("\\u00a5") >= 0) nodes.push(n);
      }
      nodes.forEach(function (n) {
        var frag = document.createDocumentFragment();
        n.nodeValue.split(/([\\u00ac\\u00a5])/).forEach(function (part) {
          if (!part) return;
          if (part === "\\u00ac" || part === "\\u00a5") {
            var g = document.createElement("span"); g.className = "app-glyph"; g.textContent = part; frag.appendChild(g);
          } else frag.appendChild(document.createTextNode(part));
        });
        n.parentNode.replaceChild(frag, n);
      });
    } finally { busy = false; }
  }

  function start() {
    try {
      var d = D(); if (!d) return;
      paintVersion(d.published || {}, false);
      buildStrip();
      paintStrip();
      document.addEventListener("fahras:render", paintStrip);
      var art = document.getElementById("reading-article");
      if (art && window.MutationObserver) { new MutationObserver(function () { if (!busy) wrapGlyphs(art); }).observe(art, { childList: true, subtree: true }); wrapGlyphs(art); }
      window.addEventListener("keydown", function (e) {
        var t = e.target && e.target.tagName; if (t === "INPUT" || t === "SELECT" || t === "TEXTAREA" || e.altKey || e.ctrlKey || e.metaKey) return;
        if (e.key === "ArrowLeft") { step(1); e.preventDefault(); } else if (e.key === "ArrowRight") { step(-1); e.preventDefault(); }
      });
      loadLive();
    } catch (e) { /* ignore */ }
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", function () { setTimeout(start, 0); }); else setTimeout(start, 0);
})();
</script>
"""


# wording that differs between template versions: applied when present, skipped otherwise
OPTIONAL_PATCHES: list[tuple[str, str]] = [
    # an ayah with no approved unit yet: say so (nothing here is "proposed")
    ('      b.textContent = "الوسوم مقترحة آلياً";\n      infoEl.appendChild(b);\n      infoEl.appendChild(document.createTextNode(" ولم يعتمدها متخصص بعد · النص نفسه مطابق للمصدر حرفاً بحرف (sha256 " + res.sha + ")"));',
     '      b.textContent = moves.length ? "الوسوم مقترحة آلياً" : "لا مواضع معتمدة بعد في هذه الآية";\n      infoEl.appendChild(b);\n      infoEl.appendChild(document.createTextNode((moves.length ? " ولم يعتمدها متخصص بعد · النص نفسه" : " · النص") + " مطابق للمصدر حرفاً بحرف (sha256 " + res.sha + ")"));'),
    ('      if (unusedCount > 0) {\n        unusedNote.hidden = false;', '      if (unusedCount > 0 && presentMethods.length) {\n        unusedNote.hidden = false;'),
    # every unit on the page is approved: no "the rest is proposed" remainder
    ('" بواسطة متخصص · باقي الوسوم (" + toArabicDigits(proposedCount) + ") مقترحة آلياً · النص مطابق',
     '" بواسطة متخصص بشري" + (proposedCount ? " · باقي الوسوم (" + toArabicDigits(proposedCount) + ") مقترحة آلياً" : "") + " · النص مطابق'),
    ('" بواسطة متخصص · باقي الوسوم (" + toArabicDigits(proposedCount) + ") اقتراح آلي · غير معتمد بعد · النص مطابق',
     '" بواسطة متخصص بشري" + (proposedCount ? " · باقي الوسوم (" + toArabicDigits(proposedCount) + ") اقتراح آلي · غير معتمد بعد" : "") + " · النص مطابق'),
]


def render(payload: dict) -> str:
    html = TEMPLATE.read_text(encoding="utf-8")
    skipped = []
    for old, new in PATCHES:
        if old not in html:
            skipped.append(old[:60])
            continue
        html = html.replace(old, new, 1)
    for old, new in OPTIONAL_PATCHES:
        html = html.replace(old, new, 1)
    for anchor in skipped:   # the template moved on: say so, the page still builds
        print(f"  note: template patch not applied (anchor not found): {anchor!r}")
    if "availableWindows()" not in html:
        raise SystemExit("template changed: the per-tafsir verse list could not be patched in")
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
    cov = payload["coverage"]
    print(f"site: v{pub['version']} · {pub['units']} approved units in {cov['ayahs']} ayat"
          f" · whole surah {payload['surah']['number']} ({payload['surah']['ayat']} ayat × {len(payload['tafsir_order'])} tafsirs) → {shown}")
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
