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
SURAHS: list[tuple[int, str, str, int]] = [
    (1, "الفاتحة", "Al-Fatihah", 7), (2, "البقرة", "Al-Baqarah", 286), (3, "آل عمران", "Al 'Imran", 200),
    (4, "النساء", "An-Nisa'", 176), (5, "المائدة", "Al-Ma'idah", 120), (6, "الأنعام", "Al-An'am", 165),
    (7, "الأعراف", "Al-A'raf", 206), (8, "الأنفال", "Al-Anfal", 75), (9, "التوبة", "At-Tawbah", 129),
    (10, "يونس", "Yunus", 109), (11, "هود", "Hud", 123), (12, "يوسف", "Yusuf", 111), (13, "الرعد", "Ar-Ra'd", 43),
    (14, "إبراهيم", "Ibrahim", 52), (15, "الحجر", "Al-Hijr", 99), (16, "النحل", "An-Nahl", 128),
    (17, "الإسراء", "Al-Isra'", 111), (18, "الكهف", "Al-Kahf", 110), (19, "مريم", "Maryam", 98), (20, "طه", "Ta-Ha", 135),
    (21, "الأنبياء", "Al-Anbiya'", 112), (22, "الحج", "Al-Hajj", 78), (23, "المؤمنون", "Al-Mu'minun", 118),
    (24, "النور", "An-Nur", 64), (25, "الفرقان", "Al-Furqan", 77), (26, "الشعراء", "Ash-Shu'ara'", 227),
    (27, "النمل", "An-Naml", 93), (28, "القصص", "Al-Qasas", 88), (29, "العنكبوت", "Al-'Ankabut", 69),
    (30, "الروم", "Ar-Rum", 60), (31, "لقمان", "Luqman", 34), (32, "السجدة", "As-Sajdah", 30), (33, "الأحزاب", "Al-Ahzab", 73),
    (34, "سبأ", "Saba'", 54), (35, "فاطر", "Fatir", 45), (36, "يس", "Ya-Sin", 83), (37, "الصافات", "As-Saffat", 182),
    (38, "ص", "Sad", 88), (39, "الزمر", "Az-Zumar", 75), (40, "غافر", "Ghafir", 85), (41, "فصلت", "Fussilat", 54),
    (42, "الشورى", "Ash-Shura", 53), (43, "الزخرف", "Az-Zukhruf", 89), (44, "الدخان", "Ad-Dukhan", 59),
    (45, "الجاثية", "Al-Jathiyah", 37), (46, "الأحقاف", "Al-Ahqaf", 35), (47, "محمد", "Muhammad", 38),
    (48, "الفتح", "Al-Fath", 29), (49, "الحجرات", "Al-Hujurat", 18), (50, "ق", "Qaf", 45), (51, "الذاريات", "Adh-Dhariyat", 60),
    (52, "الطور", "At-Tur", 49), (53, "النجم", "An-Najm", 62), (54, "القمر", "Al-Qamar", 55), (55, "الرحمن", "Ar-Rahman", 78),
    (56, "الواقعة", "Al-Waqi'ah", 96), (57, "الحديد", "Al-Hadid", 29), (58, "المجادلة", "Al-Mujadilah", 22),
    (59, "الحشر", "Al-Hashr", 24), (60, "الممتحنة", "Al-Mumtahanah", 13), (61, "الصف", "As-Saff", 14),
    (62, "الجمعة", "Al-Jumu'ah", 11), (63, "المنافقون", "Al-Munafiqun", 11), (64, "التغابن", "At-Taghabun", 18),
    (65, "الطلاق", "At-Talaq", 12), (66, "التحريم", "At-Tahrim", 12), (67, "الملك", "Al-Mulk", 30), (68, "القلم", "Al-Qalam", 52),
    (69, "الحاقة", "Al-Haqqah", 52), (70, "المعارج", "Al-Ma'arij", 44), (71, "نوح", "Nuh", 28), (72, "الجن", "Al-Jinn", 28),
    (73, "المزمل", "Al-Muzzammil", 20), (74, "المدثر", "Al-Muddaththir", 56), (75, "القيامة", "Al-Qiyamah", 40),
    (76, "الإنسان", "Al-Insan", 31), (77, "المرسلات", "Al-Mursalat", 50), (78, "النبأ", "An-Naba'", 40),
    (79, "النازعات", "An-Nazi'at", 46), (80, "عبس", "'Abasa", 42), (81, "التكوير", "At-Takwir", 29),
    (82, "الانفطار", "Al-Infitar", 19), (83, "المطففين", "Al-Mutaffifin", 36), (84, "الانشقاق", "Al-Inshiqaq", 25),
    (85, "البروج", "Al-Buruj", 22), (86, "الطارق", "At-Tariq", 17), (87, "الأعلى", "Al-A'la", 19), (88, "الغاشية", "Al-Ghashiyah", 26),
    (89, "الفجر", "Al-Fajr", 30), (90, "البلد", "Al-Balad", 20), (91, "الشمس", "Ash-Shams", 15), (92, "الليل", "Al-Layl", 21),
    (93, "الضحى", "Ad-Duha", 11), (94, "الشرح", "Ash-Sharh", 8), (95, "التين", "At-Tin", 8), (96, "العلق", "Al-'Alaq", 19),
    (97, "القدر", "Al-Qadr", 5), (98, "البينة", "Al-Bayyinah", 8), (99, "الزلزلة", "Az-Zalzalah", 8), (100, "العاديات", "Al-'Adiyat", 11),
    (101, "القارعة", "Al-Qari'ah", 11), (102, "التكاثر", "At-Takathur", 8), (103, "العصر", "Al-'Asr", 3), (104, "الهمزة", "Al-Humazah", 9),
    (105, "الفيل", "Al-Fil", 5), (106, "قريش", "Quraysh", 4), (107, "الماعون", "Al-Ma'un", 7), (108, "الكوثر", "Al-Kawthar", 3),
    (109, "الكافرون", "Al-Kafirun", 6), (110, "النصر", "An-Nasr", 3), (111, "المسد", "Al-Masad", 5), (112, "الإخلاص", "Al-Ikhlas", 4),
    (113, "الفلق", "Al-Falaq", 5), (114, "الناس", "An-Nas", 6),
]
assert len(SURAHS) == 114 and sum(x[3] for x in SURAHS) == 6236
SURAH_AR = {n: name for n, name, _e, _c in SURAHS}
SURAH_EN = {n: en for n, _a, en, _c in SURAHS}
I18N_DIR = ROOT / "console" / "static" / "i18n"
SITE_LANGS = [("ar", "العربية", "Arabic", "rtl"), ("en", "English", "English", "ltr")]


def site_strings() -> dict[str, dict[str, str]]:
    """The public page's strings (site.*) of every language file the console ships: the
    page's fallback when the console cannot be reached."""
    out: dict[str, dict[str, str]] = {}
    for p in sorted(I18N_DIR.glob("*.json")):
        d = _read_json(p)
        out[p.stem] = {k: v for k, v in d.items() if k.startswith("site.")}
    return out
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
        "surah": {"number": surah, "name_ar": SURAH_AR.get(surah, ""), "name_en": SURAH_EN.get(surah, ""), "ayat": len(window_order)},
        "surahs": [{"n": n, "ar": a, "en": e, "ayat": c, "available": n in DATA_ROOTS} for n, a, e, c in SURAHS],
        "i18n": site_strings(),
        "languages": [{"code": c, "name_native": nn, "name_en": ne, "dir": d, "is_default": c == "ar"} for c, nn, ne, d in SITE_LANGS],
        "live_languages_url": DEFAULT_SNAPSHOT.rsplit("/", 1)[0] + "/languages.json",
        "live_i18n_url": DEFAULT_SNAPSHOT.rsplit("/", 1)[0] + "/i18n/{code}.json",
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
/* ---- the brand of the logo: the deep green of its ink (#0a4a3e → #12735c) as the accent, its gold
   (#bc903f → #ecdcb2) for what a specialist approved; the same two in the dark mode, lifted for contrast */
:root, :root[data-theme="light"] {
  --base: #F4F7F5; --surface: #FFFFFF; --surface-2: #E8F0EC; --line: #D9E4DE;
  --ink: #122420; --sub: #3B554C; --muted: #6B847B;
  --accent: #0F6B55; --accent-bg: #E1F1EA; --accent-hover: #0A4A3E; --on-accent: #FFFFFF;
  --gold: #A6792C; --gold-bg: #FAF2DF; --gold-line: #DCBD6C;
  --ok: #946D22; --ok-bg: #FAF2DF; --teal: #0F6B55; --teal-bg: rgba(15, 107, 85, .1);
  --mirqat-brand: var(--accent); --mirqat-rule: var(--gold-line);
}
:root[data-theme="dark"] {
  --base: #0E1917; --surface: #152420; --surface-2: #1C2F2A; --line: #28403A;
  --ink: #EEF4F1; --sub: #C3D2CB; --muted: #8DA69C;
  --accent: #4FD1B0; --accent-bg: #163B32; --accent-hover: #7FE3C9; --on-accent: #0E1917;
  --gold: #E2CF9C; --gold-bg: rgba(226, 207, 156, .14); --gold-line: #BC903F;
  --ok: #E2CF9C; --ok-bg: rgba(226, 207, 156, .14); --teal: #4FD1B0; --teal-bg: rgba(79, 209, 176, .14);
  --mirqat-brand: var(--accent); --mirqat-rule: var(--gold-line);
}
body { background: var(--base); color: var(--ink); }
/* the product name in the calligraphic family next to the wordmark, a gold rule between them */
.brand-title { font-family: var(--font-quran); font-weight: 700; font-size: 1.45rem; color: var(--accent); letter-spacing: 0; }
.brand-rule { width: 2px; height: 26px; border-radius: 2px; background: linear-gradient(180deg, var(--gold-line), var(--gold)); }
@media (max-width: 640px) { .brand-title { font-size: 1.1rem; } }
/* the accent fills read in both modes */
.btn-primary, .toc-list li.is-cur::before { color: var(--on-accent); }
.ib-btn:hover, .ib-btn:focus-visible { border-color: var(--accent); color: var(--accent); }
.switch-wrap input:checked + .sw-track { background: var(--accent); }
.pub-badge { display: inline-flex; align-items: center; gap: 6px; margin-inline-start: 10px; padding: 4px 10px; border-radius: 999px;
  font-size: .78rem; background: var(--gold-bg); color: var(--gold); border: 1px solid var(--gold-line); white-space: nowrap; font-weight: 600; }
.pub-badge:empty { display: none; }
#pub-line { display: block; margin-bottom: 6px; color: var(--ink, inherit); }
#pub-line b { color: var(--gold); }
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
.nav-ayah.is-cur { background: var(--accent); border-color: var(--accent); color: var(--on-accent); }
.nav-ayah.is-cur::after { background: var(--on-accent); }
.nav-ayah.is-dim { display: none; }
.nav-jump { margin-inline-start: auto; display: inline-flex; align-items: center; gap: 6px; }
.nav-jump .ib-btn { height: 34px; }
.nav-only { display: inline-flex; align-items: center; gap: 6px; font-size: .8rem; color: var(--muted); cursor: pointer; user-select: none; }
.nav-only input { accent-color: var(--accent); }
.nav-note { font-size: .8rem; color: var(--muted); margin: 4px 2px 0; }
.nav-live { font-size: .74rem; color: var(--muted); }
.nav-live.is-on { color: var(--ok); }
/* previous/next for an Arabic reader (as on tafsir.app): the previous ayah is to the right and says so with an arrow pointing
   right, the next to the left pointing left; the chevrons are bidi-mirrored glyphs, so the icon-only buttons are LTR boxes */
.nav-btns, .nav-jump { direction: rtl; }
.nav-word { width: auto; min-width: 34px; padding: 0 12px; white-space: nowrap; font-size: .84rem; font-weight: 600; direction: rtl; unicode-bidi: isolate; gap: 6px; display: inline-flex; align-items: center; }
.nav-word .arr { font-size: 1rem; line-height: 1; }
/* the ayah number box in the header: type the number, −/+, Enter — instead of a 64-line native list */
.sel-box.has-picker { position: relative; }
.sel-box.has-picker select#verse-sel { position: absolute; width: 1px; height: 1px; opacity: 0; pointer-events: none; }
.ayah-box { display: inline-flex; align-items: center; gap: 4px; }
.ayah-box input { width: 3.4em; border: 1px solid var(--line); border-radius: 7px; padding: 3px 6px; background: var(--bg, var(--surface-2)); color: var(--ink);
  font: inherit; font-weight: 700; text-align: center; outline: none; font-variant-numeric: tabular-nums; -moz-appearance: textfield; }
.ayah-box input::-webkit-outer-spin-button, .ayah-box input::-webkit-inner-spin-button { -webkit-appearance: none; margin: 0; }
.ayah-box input:focus { border-color: var(--accent); box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 18%, transparent); }
.ayah-box input.is-bad { border-color: var(--bad, #c0392b); animation: ayah-shake .25s ease; }
@keyframes ayah-shake { 25% { transform: translateX(3px); } 75% { transform: translateX(-3px); } }
.ayah-box .of { color: var(--muted); font-size: .8rem; white-space: nowrap; }
.ayah-box .st { width: 24px; height: 24px; border: 1px solid var(--line); border-radius: 6px; background: var(--surface); color: var(--sub, var(--ink)); font: inherit; font-size: .95rem; line-height: 1; cursor: pointer; display: inline-grid; place-items: center; }
.ayah-box .st:hover { background: var(--surface-2, var(--accent-bg)); color: var(--accent); border-color: var(--accent); }
/* the surah navigator: the 114 surahs, the ones with data open */
.ayah-pick { border: none; background: transparent; color: var(--ink); font: inherit; font-weight: 600; cursor: pointer; padding: 0; display: inline-flex; align-items: center; gap: 6px; }
.ayah-pick .caret { font-size: .7rem; color: var(--muted); }
.surah-pop { position: absolute; top: calc(100% + 8px); inset-inline-start: 0; z-index: 60; width: 320px; max-width: calc(100vw - 24px); background: var(--surface); border: 1px solid var(--line);
  border-radius: 14px; box-shadow: 0 14px 40px rgba(20, 24, 60, .18); padding: 10px; }
.surah-pop[hidden] { display: none; }
.surah-pop input { width: 100%; border: 1px solid var(--line); border-radius: 8px; padding: 7px 10px; background: var(--bg, var(--surface-2)); color: var(--ink); font: inherit; font-size: .88rem; outline: none; margin-bottom: 8px; }
.surah-pop input:focus { border-color: var(--accent); box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 18%, transparent); }
.surah-list { max-height: 50vh; overflow-y: auto; display: flex; flex-direction: column; gap: 2px; scrollbar-width: thin; }
.surah-item { display: grid; grid-template-columns: 2.4em 1fr auto; align-items: center; gap: 8px; width: 100%; text-align: start; border: 1px solid transparent; border-radius: 9px; padding: 7px 9px;
  background: transparent; color: var(--ink); font: inherit; font-size: .9rem; cursor: pointer; }
.surah-item .sn { color: var(--muted); font-variant-numeric: tabular-nums; }
.surah-item .nm { font-weight: 600; }
.surah-item .ct { font-size: .74rem; color: var(--ok); white-space: nowrap; }
.surah-item:hover:not(:disabled) { background: var(--surface-2, var(--accent-bg)); border-color: var(--line); }
.surah-item.is-cur { background: var(--accent-bg); border-color: var(--accent); color: var(--accent); }
.surah-item.is-cur .sn, .surah-item.is-cur .ct { color: var(--accent); }
.surah-item.is-off { cursor: default; opacity: .55; }
.surah-item.is-off .ct { color: var(--muted); }
/* the language switcher: the languages enabled in the console, the same saved choice */
.lang-wrap { position: relative; display: inline-flex; }
.lang-btn { width: auto; min-width: 34px; padding: 0 9px; font-size: .78rem; letter-spacing: .04em; }
.lang-pop { position: absolute; top: calc(100% + 8px); inset-inline-end: 0; z-index: 60; min-width: 160px; background: var(--surface); border: 1px solid var(--line); border-radius: 12px;
  box-shadow: 0 14px 40px rgba(20, 24, 60, .18); padding: 6px; }
.lang-pop[hidden] { display: none; }
.lang-pop .mh { font-size: .74rem; color: var(--muted); padding: 6px 10px 4px; }
.lang-pop .mi { display: block; width: 100%; text-align: start; border: none; background: transparent; color: var(--ink); font: inherit; font-size: .9rem; padding: 8px 10px; border-radius: 8px; cursor: pointer; }
.lang-pop .mi:hover { background: var(--surface-2, var(--accent-bg)); }
.lang-pop .mi.on { background: var(--accent-bg); color: var(--accent); font-weight: 600; }
/* a left-to-right interface keeps the mufassirs' texts, the verse and their headings right-to-left */
html[dir="ltr"] .ayah-card, html[dir="ltr"] .reading-article, html[dir="ltr"] .toc-list, html[dir="ltr"] #ec-rationale, html[dir="ltr"] #ec-method-name,
html[dir="ltr"] .surah-item .nm[lang="ar"], html[dir="ltr"] #reader-ayah-text { direction: rtl; text-align: right; }
html[dir="ltr"] body, html[dir="ltr"] .shell { direction: ltr; text-align: left; }
html[dir="ltr"] .nav-btns, html[dir="ltr"] .nav-jump { direction: ltr; }
html[dir="ltr"] .ayah-text { direction: rtl; }
html[dir="ltr"] .reading-article .src-run, html[dir="ltr"] .reading-article .fn { unicode-bidi: isolate; }
@media (max-width: 1200px) { .nav-btns { display: none; } }
@media (max-width: 640px) {
  .pub-badge { display: none; }
  .surah-pop { position: fixed; top: auto; bottom: 0; inset-inline: 0; width: auto; max-width: none; border-radius: 16px 16px 0 0; padding: 14px 14px calc(14px + env(safe-area-inset-bottom)); box-shadow: 0 -10px 40px rgba(20, 24, 60, .25); }
  .surah-list { max-height: 60vh; } .nav-taf { padding: 5px 10px; font-size: .8rem; } .nav-ayah { min-width: 34px; height: 34px; font-size: .86rem; }
  .nav-btns { display: none; }   /* the strip below carries previous/next on a phone */
  .nav-word { width: 34px; padding: 0; } .nav-word .txt { display: none; }
}
</style>
"""

EXTRA_JS = """
<script>
(function () {
  // the address as the visitor opened it (before the reader writes t= and w= into it)
  var OPENED_WITH_W = false;
  try { OPENED_WITH_W = new URLSearchParams(window.location.search).has("w"); } catch (e) { /* ignore */ }
  var MONTHS_AR = ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"];
  var MONTHS_EN = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
  function api() { return window.__fahras_v2 || null; }
  function D() { var a = api(); return a && a.DATA; }

  // ---- language: the same choice as the console (localStorage mq-lang), the same enabled list
  var L = { code: "ar", dir: "rtl", strings: {}, langs: [] };
  function store(k, v) { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (e) { return null; } }
  function T(key, vars) {
    var d = D(); var s = L.strings[key];
    if (s == null && d && d.i18n) s = (d.i18n[L.code] || {})[key];
    if (s == null && d && d.i18n) s = (d.i18n.ar || {})[key];
    if (s == null) s = key;
    return String(s).replace(/\\{(\\w+)\\}/g, function (_, k) { return vars && vars[k] != null ? vars[k] : ""; });
  }
  function arabicDigits() { return L.code === "ar" || L.code === "ur"; }
  function num(n) { var t = String(n == null ? "" : n); return arabicDigits() ? t.replace(/\\d/g, function (d) { return "٠١٢٣٤٥٦٧٨٩"[d]; }) : t; }
  function dateStr(ts) { if (!ts) return ""; var d = new Date(ts * 1000); return arabicDigits() ? num(d.getUTCDate()) + " " + MONTHS_AR[d.getUTCMonth()] + " " + num(d.getUTCFullYear()) : MONTHS_EN[d.getUTCMonth()] + " " + d.getUTCDate() + ", " + d.getUTCFullYear(); }
  function surahName(x) { return (L.dir === "rtl") ? x.ar : x.en; }
  function tafsirName(tid) { var d = D(); var k = "site.tafsir." + tid; var v = T(k); return v === k ? ((d.tafsir_labels || {})[tid] || tid) : v; }
  function methodName(id) { var k = "site.method." + id; var v = T(k); return v === k ? id : v; }
  function ayahLabel(k) { var d = D(); var n = String(k).split("_")[1] || k; var sn = d.surah ? surahName({ ar: d.surah.name_ar, en: d.surah.name_en }) : ""; return sn + " " + num(n); }

  // ---- the published version in the header and the source box
  var LIVE = false;
  function paintVersion() {
    var d = D(); var P = (d && d.published) || {};
    var badge = document.getElementById("pub-badge");
    if (!badge) { var wrap = document.querySelector(".brand-wrap"); if (wrap) { badge = document.createElement("span"); badge.className = "pub-badge"; badge.id = "pub-badge"; wrap.appendChild(badge); } }
    if (badge) badge.textContent = P.version ? T("site.badge", { v: num(P.version) }) : "";
    var pl = document.getElementById("pub-line");
    if (pl) {
      pl.textContent = "";
      var b = document.createElement("b");
      b.textContent = P.version
        ? T("site.pub_line", { v: num(P.version) }) + (P.published_at ? " · " + T("site.pub_date", { d: dateStr(P.published_at) }) : "") + " · " + (L.code === "ar" && P.notice_ar ? P.notice_ar : T("site.notice"))
        : T("site.pub_none");
      pl.appendChild(b);
    }
    var lv = document.getElementById("nav-live");
    if (lv) { lv.textContent = LIVE ? T("site.live") : T("site.build"); lv.classList.toggle("is-on", LIVE); }
  }

  // ---- the approved units of each tafsir per ayah (for the strip's marks)
  function approvedMap() {
    var d = D(); var out = {};
    if (!d) return out;
    Object.keys(d.tafsirs || {}).forEach(function (tid) {
      var Tt = d.tafsirs[tid]; out[tid] = {};
      Object.keys(Tt.verified || {}).forEach(function (k) {
        var blk = Tt.verified[k] || {}; var n = 0;
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
    var box = document.createElement("nav"); box.className = "nav-strip"; box.id = "nav-strip";
    var r1 = document.createElement("div"); r1.className = "nav-row"; r1.id = "nav-tafsirs";
    var r2 = document.createElement("div"); r2.className = "nav-row";
    var lbl = document.createElement("span"); lbl.className = "nav-lbl"; lbl.id = "nav-surah-lbl";
    r2.appendChild(lbl);
    var only = document.createElement("label"); only.className = "nav-only";
    var cb = document.createElement("input"); cb.type = "checkbox"; cb.id = "nav-only-approved";
    cb.addEventListener("change", function () { onlyApproved = cb.checked; paintStrip(); });
    only.appendChild(cb); var onlyTxt = document.createElement("span"); onlyTxt.id = "nav-only-txt"; only.appendChild(onlyTxt);
    r2.appendChild(only);
    var jump = document.createElement("span"); jump.className = "nav-jump";
    var live = document.createElement("span"); live.className = "nav-live"; live.id = "nav-live"; jump.appendChild(live);
    var prev = document.createElement("button"); prev.type = "button"; prev.className = "ib-btn"; prev.id = "nav-prev";
    var next = document.createElement("button"); next.type = "button"; next.className = "ib-btn"; next.id = "nav-next";
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
    var sl = document.getElementById("nav-surah-lbl"); if (sl) sl.textContent = T("site.surah_ayat", { s: d.surah ? surahName({ ar: d.surah.name_ar, en: d.surah.name_en }) : "" });
    var ot = document.getElementById("nav-only-txt"); if (ot) ot.textContent = T("site.only_approved");
    r1.textContent = "";
    var l = document.createElement("span"); l.className = "nav-lbl"; l.textContent = T("site.tafsir"); r1.appendChild(l);
    (d.tafsir_order || []).forEach(function (tid) {
      var b = document.createElement("button"); b.type = "button"; b.className = "nav-taf" + (tid === st.tafsirId ? " is-cur" : "");
      b.textContent = tafsirName(tid);
      var n = Object.keys(ap[tid] || {}).length;
      if (n) { var sm = document.createElement("small"); sm.textContent = T("site.n_ayat", { n: num(n) }); b.appendChild(document.createTextNode(" ")); b.appendChild(sm); }
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
      b.textContent = num(n);
      if (mine[k]) { b.classList.add("has-ok"); b.title = T("site.approved_in", { n: num(mine[k]), t: tafsirName(st.tafsirId) }); }
      else if (any) { b.classList.add("has-any"); b.title = T("site.approved_other"); }
      else b.title = T("site.ayah_n", { n: num(n) });
      if (k === st.windowId) { b.classList.add("is-cur"); b.setAttribute("aria-current", "true"); cur = b; }
      if (onlyApproved && !mine[k] && k !== st.windowId) b.classList.add("is-dim");
      b.addEventListener("click", function () { a.goTo(null, k); });
      r3.appendChild(b);
    });
    if (cur && cur.scrollIntoView) { try { cur.scrollIntoView({ block: "nearest", inline: "center", behavior: "smooth" }); } catch (e) { /* ignore */ } }
    var chips = document.getElementById("reader-chips-bar");
    if (chips) chips.classList.toggle("is-empty", !(st.reviewMoves || []).length);
  }

  // ---- the header's ayah box (as on tafsir.app): a number to type, −/+, Enter — instead of a 64-line list
  var box = null, inp = null;
  function toLatin(v) { return String(v || "").replace(/[٠-٩]/g, function (d) { return "٠١٢٣٤٥٦٧٨٩".indexOf(d); }).replace(/\\D/g, ""); }
  function jumpTo(n) {
    var a = api(); var d = D(); if (!a || !d) return false;
    var k = (d.surah && d.surah.number) + "_" + n;
    if (n && (d.window_order || []).indexOf(k) >= 0) { if (k !== a.state.windowId) a.goTo(null, k); return true; }
    return false;
  }
  function buildPicker() {
    var sel = document.getElementById("verse-sel"); var sb = sel && sel.parentNode; if (!sel || !sb || box) return;
    sb.classList.add("has-picker");
    var lbl = sb.querySelector("label"); if (lbl) { lbl.setAttribute("for", "ayah-num"); lbl.id = "ayah-lbl"; }
    box = document.createElement("span"); box.className = "ayah-box";
    var minus = document.createElement("button"); minus.type = "button"; minus.className = "st"; minus.id = "ayah-minus"; minus.textContent = "−";
    var plus = document.createElement("button"); plus.type = "button"; plus.className = "st"; plus.id = "ayah-plus"; plus.textContent = "+";
    inp = document.createElement("input"); inp.type = "text"; inp.inputMode = "numeric"; inp.id = "ayah-num"; inp.autocomplete = "off";
    var of = document.createElement("span"); of.className = "of"; of.id = "ayah-of";
    // right to left: + (next) sits to the left of the number, − (previous) to its right
    box.appendChild(minus); box.appendChild(inp); box.appendChild(of); box.appendChild(plus);
    sb.appendChild(box);
    minus.addEventListener("click", function () { step(-1); });
    plus.addEventListener("click", function () { step(1); });
    function commit() {
      var n = parseInt(toLatin(inp.value), 10) || 0;
      if (!jumpTo(n)) { inp.classList.remove("is-bad"); void inp.offsetWidth; inp.classList.add("is-bad"); paintPicker(); setTimeout(function () { inp.classList.remove("is-bad"); }, 600); }
    }
    inp.addEventListener("focus", function () { inp.select(); });
    inp.addEventListener("keydown", function (e) {
      if (e.key === "Enter") { commit(); inp.blur(); e.preventDefault(); }
      else if (e.key === "ArrowUp") { step(1); e.preventDefault(); }
      else if (e.key === "ArrowDown") { step(-1); e.preventDefault(); }
      else if (e.key === "Escape") { paintPicker(); inp.blur(); }
    });
    inp.addEventListener("change", commit);
  }
  function paintPicker() {
    var a = api(); var d = D(); if (!a || !d || !inp) return;
    var n = String(a.state.windowId).split("_")[1] || ""; var total = (d.surah && d.surah.ayat) || (d.window_order || []).length;
    inp.value = num(n); inp.setAttribute("aria-label", T("site.ayah")); inp.title = T("site.ayah");
    var of = document.getElementById("ayah-of"); if (of) of.textContent = T("site.of", { n: num(total) });
    var mi = document.getElementById("ayah-minus"); if (mi) { mi.title = T("site.prev_ayah"); mi.setAttribute("aria-label", mi.title); }
    var pl = document.getElementById("ayah-plus"); if (pl) { pl.title = T("site.next_ayah"); pl.setAttribute("aria-label", pl.title); }
  }
  // previous/next that say what they do, with the arrow (tafsir.app style); icons only on a phone
  function wordButton(btn, prev) {
    if (!btn) return;
    btn.textContent = ""; btn.classList.add("nav-word");
    var rtl = L.dir === "rtl";
    var arr = document.createElement("span"); arr.className = "arr"; arr.textContent = (prev === rtl) ? "\\u2192" : "\\u2190";
    var txt = document.createElement("span"); txt.className = "txt"; txt.textContent = prev ? T("site.prev_ayah") : T("site.next_ayah");
    if (prev) { btn.appendChild(arr); btn.appendChild(txt); } else { btn.appendChild(txt); btn.appendChild(arr); }
    btn.title = txt.textContent; btn.setAttribute("aria-label", btn.title);
  }
  function paintButtons() {
    wordButton(document.getElementById("btn-prev-verse"), true);
    wordButton(document.getElementById("btn-next-verse"), false);
    wordButton(document.getElementById("nav-prev"), true);
    wordButton(document.getElementById("nav-next"), false);
  }

  // ---- the surah navigator: the 114 surahs, the ones with data open; a search by number or name
  var sPick = null, sPop = null;
  function buildSurah() {
    var d = D(); var sb = document.getElementById("verse-sel") && document.getElementById("verse-sel").parentNode; if (!d || !sb || sPick) return;
    var wrap = document.createElement("div"); wrap.className = "sel-box has-picker surah-box";
    var lbl = document.createElement("label"); lbl.id = "surah-lbl"; lbl.setAttribute("for", "surah-pick"); wrap.appendChild(lbl);
    sPick = document.createElement("button"); sPick.type = "button"; sPick.className = "ayah-pick"; sPick.id = "surah-pick"; sPick.setAttribute("aria-haspopup", "listbox"); sPick.setAttribute("aria-expanded", "false");
    wrap.appendChild(sPick);
    sPop = document.createElement("div"); sPop.className = "surah-pop"; sPop.id = "surah-pop"; sPop.hidden = true; sPop.setAttribute("role", "dialog");
    var si = document.createElement("input"); si.type = "search"; si.id = "surah-q"; si.autocomplete = "off";
    var list = document.createElement("div"); list.className = "surah-list"; list.id = "surah-list"; list.setAttribute("role", "listbox");
    sPop.appendChild(si); sPop.appendChild(list);
    wrap.appendChild(sPop);
    sb.parentNode.insertBefore(wrap, sb);
    sPick.addEventListener("click", function (e) { e.stopPropagation(); if (sPop.hidden) openSurah(); else closeSurah(); });
    sPop.addEventListener("click", function (e) { e.stopPropagation(); });
    document.addEventListener("click", closeSurah);
    document.addEventListener("keydown", function (e) { if (e.key === "Escape" && !sPop.hidden) { closeSurah(); sPick.focus(); } });
    si.addEventListener("input", function () { paintSurahList(si.value); });
    si.addEventListener("keydown", function (e) { if (e.key === "Enter") { var first = list.querySelector(".surah-item:not(.is-off)"); if (first) first.click(); e.preventDefault(); } });
  }
  function openSurah() { paintSurahList(""); var si = document.getElementById("surah-q"); if (si) si.value = ""; sPop.hidden = false; sPick.setAttribute("aria-expanded", "true"); var c = sPop.querySelector(".is-cur"); if (c && c.scrollIntoView) { try { c.scrollIntoView({ block: "center" }); } catch (e) { /* ignore */ } } if (si && window.matchMedia && !window.matchMedia("(max-width: 640px)").matches) si.focus(); }
  function closeSurah() { if (!sPop || sPop.hidden) return; sPop.hidden = true; sPick.setAttribute("aria-expanded", "false"); }
  function paintSurah() {
    var d = D(); if (!d || !sPick) return;
    var lbl = document.getElementById("surah-lbl"); if (lbl) lbl.textContent = T("site.surah");
    sPick.textContent = ""; sPick.appendChild(document.createTextNode(num(d.surah.number) + " · " + surahName({ ar: d.surah.name_ar, en: d.surah.name_en }) + " "));
    var car = document.createElement("span"); car.className = "caret"; car.textContent = "▼"; sPick.appendChild(car);
    sPick.title = T("site.surah");
    var si = document.getElementById("surah-q"); if (si) { si.placeholder = T("site.surah_search"); si.setAttribute("aria-label", si.placeholder); }
  }
  function paintSurahList(q) {
    var d = D(); var list = document.getElementById("surah-list"); if (!d || !list) return;
    var ql = toLatin(q); var qs = String(q || "").trim().replace(/^سورة\\s+/, "").replace(/^(al|an|ar|as|ash|at|ad|az|adh|ath)[-\\s]/i, "").toLowerCase();
    list.textContent = "";
    (d.surahs || []).forEach(function (x) {
      if (ql && String(x.n).indexOf(ql) !== 0) return;
      if (!ql && qs && x.ar.indexOf(qs) < 0 && x.en.toLowerCase().replace(/^(al|an|ar|as|ash|at|ad|az|adh|ath)[-\\s]/, "").indexOf(qs) < 0 && x.en.toLowerCase().indexOf(qs) < 0) return;
      var b = document.createElement("button"); b.type = "button"; b.className = "surah-item" + (x.available ? "" : " is-off") + (x.n === d.surah.number ? " is-cur" : "");
      b.setAttribute("role", "option"); if (!x.available) b.disabled = true;
      var nn = document.createElement("span"); nn.className = "sn"; nn.textContent = num(x.n);
      var nm = document.createElement("span"); nm.className = "nm"; nm.textContent = surahName(x);
      var ct = document.createElement("span"); ct.className = "ct"; ct.textContent = x.available ? T("site.n_ayat", { n: num(x.ayat) }) : T("site.not_available");
      b.appendChild(nn); b.appendChild(nm); b.appendChild(ct);
      if (x.available) b.addEventListener("click", function () { closeSurah(); if (x.n !== d.surah.number) { try { window.location.search = "?s=" + x.n; } catch (e) { /* ignore */ } } });
      list.appendChild(b);
    });
  }

  // ---- the language switcher (globe, as in the console) and the page's labels in the chosen language
  var gPop = null;
  function buildLang() {
    var acts = document.querySelector(".header-actions"); if (!acts || document.getElementById("lang-btn")) return;
    var wrap = document.createElement("span"); wrap.className = "lang-wrap";
    var btn = document.createElement("button"); btn.type = "button"; btn.className = "ib-btn lang-btn"; btn.id = "lang-btn"; btn.setAttribute("aria-haspopup", "menu"); btn.setAttribute("aria-expanded", "false");
    gPop = document.createElement("div"); gPop.className = "lang-pop"; gPop.id = "lang-pop"; gPop.hidden = true; gPop.setAttribute("role", "menu");
    wrap.appendChild(btn); wrap.appendChild(gPop);
    acts.insertBefore(wrap, acts.firstChild);
    btn.addEventListener("click", function (e) { e.stopPropagation(); gPop.hidden = !gPop.hidden; btn.setAttribute("aria-expanded", gPop.hidden ? "false" : "true"); });
    gPop.addEventListener("click", function (e) { e.stopPropagation(); });
    document.addEventListener("click", function () { if (gPop) { gPop.hidden = true; btn.setAttribute("aria-expanded", "false"); } });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape" && gPop && !gPop.hidden) { gPop.hidden = true; btn.setAttribute("aria-expanded", "false"); } });
  }
  function paintLang() {
    var btn = document.getElementById("lang-btn"); if (!btn || !gPop) return;
    var cur = L.langs.filter(function (l) { return l.code === L.code; })[0];
    btn.textContent = cur ? cur.code.toUpperCase() : "AR"; btn.title = T("site.lang_switch"); btn.setAttribute("aria-label", btn.title);
    gPop.textContent = "";
    var h = document.createElement("div"); h.className = "mh"; h.textContent = T("site.lang_switch"); gPop.appendChild(h);
    L.langs.forEach(function (l) {
      var b = document.createElement("button"); b.type = "button"; b.className = "mi" + (l.code === L.code ? " on" : ""); b.setAttribute("role", "menuitem");
      b.textContent = l.name_native; b.lang = l.code; b.dir = l.dir;
      b.addEventListener("click", function () { gPop.hidden = true; setLang(l.code, true); });
      gPop.appendChild(b);
    });
    var wrap = btn.parentNode; if (wrap) wrap.style.display = L.langs.length > 1 ? "" : "none";
  }
  function setLang(code, persist) {
    var d = D(); var l = L.langs.filter(function (x) { return x.code === code; })[0];
    if (!l) return;
    L.code = l.code; L.dir = l.dir || "ltr";
    if (persist) store("mq-lang", l.code);
    L.strings = (d && d.i18n && d.i18n[l.code]) || {};
    document.documentElement.lang = l.code;
    document.documentElement.dir = L.dir;
    var shell = document.querySelector(".shell"); if (shell) shell.setAttribute("dir", L.dir);
    document.body.classList.toggle("lang-ltr", L.dir === "ltr");
    var done = function () { paintAll(); };
    var url = d && d.live_i18n_url;
    if (url && window.fetch) {
      fetch(url.replace("{code}", l.code), { headers: { "Accept": "application/json" } }).then(function (r) { return r.ok ? r.json() : null; }).then(function (b) {
        if (b && b.strings && L.code === l.code) { L.strings = b.strings; paintAll(); }
      }).catch(function () { /* the embedded strings stay */ });
    }
    done();
  }
  function loadLanguages() {
    var d = D(); if (!d) return;
    L.langs = (d.languages || []).slice();
    var want = store("mq-lang") || (L.langs.filter(function (x) { return x.is_default; })[0] || L.langs[0] || {}).code;
    setLang(L.langs.some(function (x) { return x.code === want; }) ? want : "ar", false);
    var url = d.live_languages_url; if (!url || !window.fetch) return;
    fetch(url, { headers: { "Accept": "application/json" } }).then(function (r) { return r.ok ? r.json() : null; }).then(function (b) {
      if (!b || !b.languages || !b.languages.length) return;
      L.langs = b.languages;
      var w2 = store("mq-lang") || b["default"] || L.code;
      if (!L.langs.some(function (x) { return x.code === w2; })) w2 = b["default"] || L.langs[0].code;
      setLang(w2, false);
    }).catch(function () { /* the built-in list stays */ });
  }

  // ---- the template's own labels in the chosen language (the texts of the mufassirs stay as they are)
  function setText(sel, text) { var el = typeof sel === "string" ? document.querySelector(sel) : sel; if (el && el.textContent !== text) el.textContent = text; }
  function translateStatic() {
    var d = D(); var a = api(); if (!d || !a) return;
    setText('label[for="tafsir-sel"]', T("site.tafsir"));
    setText("#ayah-lbl", T("site.ayah"));
    setText(".brand-title", T("site.brand"));
    var chipsLbl = document.querySelector(".chips-bar .lbl"); if (chipsLbl) setText(chipsLbl, T("site.color_by"));
    setText("#chip-none", T("site.no_color"));
    var h4s = document.querySelectorAll(".reader-aside .aside-card h4");
    if (h4s[1]) setText(h4s[1], T("site.toc"));
    var tg = document.querySelectorAll(".reader-aside .tg-row > span:first-child");
    if (tg[0]) setText(tg[0], T("site.footnotes"));
    if (tg[1]) setText(tg[1], T("site.font_size"));
    var src = document.getElementById("reader-source-box");
    if (src) { var tn = src.firstChild; if (tn && tn.nodeType === 3 && tn.nodeValue.trim() !== T("site.read_source")) tn.nodeValue = T("site.read_source") + " "; }
    setText("#reader-dorar-link", T("site.dorar"));
    setText("#reader-quranpedia-link", T("site.quranpedia"));
    setText("#ec-copy-btn", T("site.copy_cite"));
    setText("#ec-source-link", T("site.read_in_source"));
    // tafsir names in the header's select
    var ts = document.getElementById("tafsir-sel");
    if (ts) Array.prototype.forEach.call(ts.options, function (o) { var nm = tafsirName(o.value); if (o.textContent !== nm) o.textContent = nm; });
  }
  function translateDynamic() {
    var d = D(); var a = api(); if (!d || !a) return;
    var st = a.state; var tn = tafsirName(st.tafsirId);
    setText("#reader-ayah-ref", ayahLabel(st.windowId));
    setText("#dist-title", T("site.methods_in", { t: tn }));
    // the method chips and the legend
    var cnt = {}; (st.reviewMoves || []).forEach(function (m) { if (m.primary) cnt[m.primary] = (cnt[m.primary] || 0) + 1; });
    document.querySelectorAll("#reader-dynamic-chips .chip").forEach(function (c, i) {
      var ids = Object.keys(cnt); var order = ["M_QURAN", "M_SUNNAH", "M_SAHABA", "M_TABIIN", "M_LUGHA", "M_QIRAAT", "M_NUZUL", "M_SIRA", "M_ISRAILIYYAT", "M_RAY"].filter(function (k) { return cnt[k]; });
      var id = order[i]; if (!id) return;
      var txt = Array.prototype.filter.call(c.childNodes, function (n) { return n.nodeType === 3; })[0];
      if (txt && txt.nodeValue !== methodName(id) + " ") txt.nodeValue = methodName(id) + " ";
      var sm = c.querySelector("small.cnt"); if (sm) sm.textContent = num(cnt[id]);
    });
    var AR_NAMES = {}; ["M_QURAN", "M_SUNNAH", "M_SAHABA", "M_TABIIN", "M_LUGHA", "M_QIRAAT", "M_NUZUL", "M_SIRA", "M_ISRAILIYYAT", "M_RAY"].forEach(function (k) { AR_NAMES[(d.i18n.ar || {})["site.method." + k]] = k; });
    document.querySelectorAll("#dist-legend .leg-item").forEach(function (li) {
      var spans = li.querySelectorAll("span");
      var lbl = spans[0], cnt = li.querySelector(".leg-cnt");
      if (lbl) { var id = AR_NAMES[lbl.textContent.trim()] || lbl.getAttribute("data-m"); if (id) { lbl.setAttribute("data-m", id); if (lbl.textContent !== methodName(id)) lbl.textContent = methodName(id); } }
      if (cnt) { var v = toLatin(cnt.textContent); if (v && cnt.textContent !== num(v)) cnt.textContent = num(v); }
    });
    var un = document.getElementById("chip-unused-note");
    if (un && !un.hidden) { var m = toLatin(un.textContent); if (m) setText(un, T("site.unused", { n: num(m) })); }
    var ban = document.getElementById("reader-info-banner");
    if (ban && !ban.classList.contains("is-mismatch")) {
      var sha = (ban.textContent.match(/sha256\\s+([0-9a-f]+)/) || [])[1] || "";
      var nAp = (st.reviewMoves || []).filter(function (m) { return m.review_status === "approved"; }).length;
      var want = "ⓘ " + (nAp ? T("site.banner_approved", { n: num(nAp) }) + " " + T("site.banner_approved_tail", { sha: sha }) : T("site.banner_none") + " · " + T("site.banner_none_tail", { sha: sha }));
      if (ban.textContent !== want) { ban.textContent = ""; ban.appendChild(document.createTextNode("ⓘ ")); var b = document.createElement("b"); b.textContent = nAp ? T("site.banner_approved", { n: num(nAp) }) : T("site.banner_none"); ban.appendChild(b); ban.appendChild(document.createTextNode(nAp ? " " + T("site.banner_approved_tail", { sha: sha }) : " · " + T("site.banner_none_tail", { sha: sha }))); }
    }
  }
  function paintAll() { translateStatic(); paintButtons(); paintStrip(); paintPicker(); paintSurah(); paintLang(); paintVersion(); translateDynamic(); }

  // ---- the live snapshot: what the console published since this page was built
  function overlay(snap) {
    var d = D(); if (!d || !snap || snap.kind !== "mirqah-published") return false;
    var units = snap.units || [];
    var fresh = {};
    Object.keys(d.tafsirs || {}).forEach(function (tid) { fresh[tid] = {}; });
    var n_units = 0;
    units.forEach(function (u) {
      var Tt = d.tafsirs && d.tafsirs[u.tafsir]; if (!Tt) return;
      var parts = String(u.ayah || "").split(":"); var key = parts[0] + "_" + parts[1];
      var w = Tt.windows && Tt.windows[key]; if (!w || w.source_sha256 !== u.source_sha256) return;
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
      var Tt = d.tafsirs[tid]; Tt.verified = {};
      Object.keys(fresh[tid]).forEach(function (k) {
        var mv = fresh[tid][k].sort(function (x, y) { return x.start - y.start; });
        Tt.verified[k] = { approved: { annotator: "approved", moves: mv, summary: { move_count: mv.length } } };
      });
    });
    d.published = { version: snap.version, published_at: snap.published_at, units: n_units, notice_ar: snap.notice_ar || "" };
    return true;
  }
  function loadLive() {
    var d = D(); var url = d && d.live_snapshot_url;
    try { url = new URLSearchParams(window.location.search).get("data") || url; } catch (e) { /* ignore */ }
    if (!url || !window.fetch) return;
    fetch(url, { headers: { "Accept": "application/json" }, cache: "no-cache" }).then(function (r) { return r.ok ? r.json() : null; }).then(function (snap) {
      if (!overlay(snap)) return;
      LIVE = true;
      var a = api(); var st = a.state;
      var ap = approvedMap();
      var mine = ap[st.tafsirId] || {};
      // no address given: open the first ayah with an approved unit
      if (!OPENED_WITH_W && !mine[st.windowId]) {
        var t0 = (d.tafsir_order || []).filter(function (t) { return Object.keys(ap[t] || {}).length; })[0];
        if (t0) { var k0 = (d.window_order || []).filter(function (k) { return ap[t0][k]; })[0]; a.goTo(t0, k0); paintAll(); return; }
      }
      a.goTo(null, null); paintAll();
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
      buildStrip();
      buildPicker();
      buildSurah();
      buildLang();
      loadLanguages();          // paints everything in the chosen language
      document.addEventListener("fahras:render", function () { paintStrip(); paintPicker(); translateDynamic(); });
      var ban = document.getElementById("reader-info-banner");
      if (ban && window.MutationObserver) { var bb = false; new MutationObserver(function () { if (bb) return; bb = true; try { translateDynamic(); } finally { bb = false; } }).observe(ban, { childList: true }); }
      var art = document.getElementById("reading-article");
      if (art && window.MutationObserver) { new MutationObserver(function () { if (!busy) wrapGlyphs(art); }).observe(art, { childList: true, subtree: true }); wrapGlyphs(art); }
      window.addEventListener("keydown", function (e) {
        var t = e.target && e.target.tagName; if (t === "INPUT" || t === "SELECT" || t === "TEXTAREA" || e.altKey || e.ctrlKey || e.metaKey) return;
        var fwd = (L.dir === "rtl") ? "ArrowLeft" : "ArrowRight", back = (L.dir === "rtl") ? "ArrowRight" : "ArrowLeft";
        if (e.key === fwd) { step(1); e.preventDefault(); } else if (e.key === back) { step(-1); e.preventDefault(); }
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
    # the extra rules join the template's style block (a nested <style> tag would swallow the first rule)
    css = EXTRA_CSS.strip()
    css = css[len("<style>"):] if css.startswith("<style>") else css
    css = css[:-len("</style>")] if css.endswith("</style>") else css
    html = html.replace("</style>", css.strip() + "\n</style>", 1) if "</style>" in html else html
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
