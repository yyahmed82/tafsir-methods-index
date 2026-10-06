"""Read-only view of the repo pipeline: windows, moves, verified files, progress.

Nothing here writes under ``data/``. Writing happens only in ``runner.py`` and
only by calling ``src/run_window.py`` (the pinned pipeline).
"""

from __future__ import annotations

import datetime as dt
import json
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from . import config, db, settings

if str(config.REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(config.REPO_ROOT / "src"))

try:  # the strict verse extractor is shared with the site builder (src/textcore.py)
    from textcore import verse_at_head  # type: ignore  # noqa: E402
except Exception:  # pragma: no cover - no verse header is safer than a wrong one
    def verse_at_head(text: str, n: int) -> str | None:  # type: ignore[misc]
        return None

try:  # single source of truth for annotator folder names
    from classify_api import model_slug  # type: ignore  # noqa: E402
except Exception:  # pragma: no cover - fallback keeps the console usable
    def model_slug(model: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9]+", "_", (model or "model").strip()).strip("_").lower()
        return slug or "model"

try:  # arm B (methodology profiles) naming — one source of truth in src/v2_profiles.py
    from v2_profiles import VARIANTS, variant_annotator, variant_dir  # type: ignore  # noqa: E402
except Exception:  # pragma: no cover - fallback keeps the console usable
    VARIANTS = ("profile",)

    def variant_annotator(slug: str, variant: str | None) -> str:
        return f"{slug}__{variant}" if variant and not slug.endswith(f"__{variant}") else slug

    def variant_dir(base: Path, name: str, variant: str | None) -> Path:
        return Path(base) / (f"{name}_{variant}" if variant else name)

# Blind A/B review: arm A = baseline (variant None), arm B = "profile". Reviewers see
# X / Y per window; which one is the profile arm is hidden (see arm_codes()).
ARM_VARIANTS = (None, "profile")

WINDOW_RE = re.compile(r"^\d{1,3}_\d{1,3}(?:_p\d{2})?$")
_CACHE: dict[str, tuple[float, Any]] = {}
_CACHE_LOCK = threading.Lock()


def data_root() -> Path:
    return (config.work_root() / settings.get("general")["data_root"]).resolve()


def _demo():
    """console.demo when the current request runs in demo mode, else None."""
    if db.mode() == "demo":
        from . import demo
        return demo
    return None


def gates(as_of: float | None = None) -> dict:
    d = _demo()
    return d.gates(as_of) if d else settings.get("gates")


def base_dir(tafsir: str) -> Path:
    if tafsir not in config.TAFSIRS:
        raise ValueError(f"unknown tafsir {tafsir!r}")
    return data_root() / tafsir


def _read_json(path: Path) -> Any:
    return json.loads(path.read_bytes().decode("utf-8"))


def windows(tafsir: str) -> list[dict]:
    """[{window, ayah, ayah_number, span_count}] sorted by ayah then part."""
    d = base_dir(tafsir) / "windows"
    if not d.is_dir():
        return []
    key = f"win:{d}"
    mtime = d.stat().st_mtime
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
        if hit and hit[0] == mtime:
            return hit[1]
    out = []
    for p in d.glob("*.json"):
        if not WINDOW_RE.match(p.stem):
            continue
        w = _read_json(p)
        out.append({
            "window": p.stem,
            "ayah": w.get("ayah"),
            "ayah_number": int(w.get("ayah_number") or p.stem.split("_")[1]),
            "span_count": int(w.get("span_count") or len(w.get("spans") or [])),
            "chars": max(0, int(w.get("window_end") or 0) - int(w.get("window_start") or 0)),
        })
    out.sort(key=lambda x: (x["ayah_number"], x["window"]))
    with _CACHE_LOCK:
        _CACHE[key] = (mtime, out)
    return out


def window_ids(tafsir: str) -> set[str]:
    return {w["window"] for w in windows(tafsir)}


SURAH_NAMES_AR = {2: "البقرة", 8: "الأنفال", 17: "الإسراء", 24: "النور"}


def _verse_from(text: str, n: int) -> str | None:
    """The verse quoted at the head of a commentary — the strict shared extractor
    (src/textcore.verse_at_head): the quotation right before «(n)», never the heading,
    the edition's separators, the mufassir's introduction or half a verse."""
    return verse_at_head(text or "", int(n))


QURANPEDIA_BOOKS = {"al_tabari": 4, "ibn_kathir": 136, "al_baghawi": 2, "al_saadi": 3}
# quranpedia.net: /surah/1/{surah}/book/{book}#verse-{n}; 1 is the Hafs mushaf and n the
# ayah's running number in it (24:1 = 2792). Book ids verified in the rendered page (2026-10-06):
# 4 الطبري, 136 ابن كثير (ط. دار طيبة), 2 البغوي (ط. دار طيبة), 3 السعدي.
SURAH_AYAT = (7, 286, 200, 176, 120, 165, 206, 75, 129, 109, 123, 111, 43, 52, 99, 128, 111, 110, 98,
              135, 112, 78, 118, 64, 77, 227, 93, 88, 69, 60, 34, 30, 73, 54, 45, 83, 182, 88, 75, 85,
              54, 53, 89, 59, 37, 35, 38, 29, 18, 45, 60, 49, 62, 55, 78, 96, 29, 22, 24, 13, 14, 11,
              11, 18, 12, 12, 30, 52, 52, 44, 28, 28, 20, 56, 40, 31, 50, 40, 46, 42, 29, 19, 36, 25,
              22, 17, 19, 26, 30, 20, 15, 21, 11, 8, 8, 19, 5, 8, 8, 11, 11, 8, 3, 9, 5, 4, 7, 3, 6, 3,
              5, 4, 5, 6)


def verse_number(surah: int, ayah: int) -> int:
    """The ayah's running number in the mushaf (1..6236), 0 when out of range."""
    if not (1 <= surah <= 114) or not (1 <= ayah <= SURAH_AYAT[surah - 1]):
        return 0
    return sum(SURAH_AYAT[:surah - 1]) + ayah


def source_url(tafsir: str, surah: int | None, ayah: int | None) -> str | None:
    """Where a reader can read the same commentary in a public mushaf site."""
    book = QURANPEDIA_BOOKS.get(tafsir)
    if not book or not surah or not ayah:
        return None
    n = verse_number(int(surah), int(ayah))
    if not n:
        return None
    return f"https://quranpedia.net/surah/1/{int(surah)}/book/{book}#verse-{n}"


def surah_name(surah: int | None) -> str:
    return SURAH_NAMES_AR.get(int(surah or 0), f"سورة {surah}" if surah else "")


def load_window(tafsir: str, window: str) -> dict | None:
    """The pinned window file (text, offsets, spans) or None."""
    if tafsir not in config.TAFSIRS or not WINDOW_RE.match(window):
        return None
    p = base_dir(tafsir) / "windows" / f"{window}.json"
    return _read_json(p) if p.is_file() else None


def span_text_ok(source: str, window: dict | None, span_ids: list, expected: str | None) -> bool:
    """A move's text is the join of its spans' texts, each of which must read back
    letter for letter from the pinned source at the span's offsets. The contiguous
    slice start:end is wider when the editor's apparatus sits between two spans, so
    the slice is never the thing compared."""
    by_id = {s.get("id"): s for s in (window or {}).get("spans") or []}
    parts = []
    for sid in span_ids or []:
        sp = by_id.get(sid)
        if sp is None:
            return False
        try:
            a, b = int(sp["start"]), int(sp["end"])
        except (KeyError, TypeError, ValueError):
            return False
        if not 0 <= a < b <= len(source) or source[a:b] != sp.get("text"):
            return False
        parts.append(sp["text"])
    if not parts:
        return False
    return expected is None or "".join(parts) == expected


def window_parts(tafsir: str, ayah_number: int) -> list[str]:
    """Window ids of one ayah in reading order (24_11, or 24_11_p01, 24_11_p02 …)."""
    return [w["window"] for w in windows(tafsir) if w["ayah_number"] == int(ayah_number)]


def ayah_text(tafsir: str, ayah_number: int) -> str | None:
    """The verse as this mufassir quotes it at the head of the ayah's first window, or
    None. Never another tafsir's quotation: see ayah_quote() for the labelled fallback."""
    q = ayah_quote(tafsir, ayah_number)
    return q["text"] if q and q.get("tafsir") == tafsir else None


def ayah_quote(tafsir: str, ayah_number: int) -> dict | None:
    """{"text", "tafsir"}: the verse quoted at the head of the ayah, from this tafsir
    when it can be isolated there, else from the first other tafsir that quotes it
    cleanly — with the tafsir it was taken from, so the interface can say so."""
    key = f"ayah:{data_root()}:{tafsir}:{ayah_number}"
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
    if hit:
        return hit[1]
    out = None
    for t in [tafsir] + [x for x in config.TAFSIRS if x != tafsir]:
        parts = window_parts(t, ayah_number)
        w = load_window(t, parts[0]) if parts else None
        text = _verse_from((w or {}).get("window_text") or "", int(ayah_number))
        if text:
            out = {"text": text, "tafsir": t}
            break
    if out:
        with _CACHE_LOCK:
            _CACHE[key] = (0.0, out)
    return out


def verified_path(tafsir: str, annotator: str, window: str) -> Path:
    return base_dir(tafsir) / "verified" / annotator / f"{window}.json"


def moves_path(tafsir: str, annotator: str, window: str) -> Path:
    return base_dir(tafsir) / "moves" / annotator / f"{window}.json"


_PART_RE = re.compile(r"^(?P<stem>\d+_\d+)_p(?P<n>\d+)$")
CONTEXT_EDGE = 400   # characters of the neighbouring part shown before / after a window


def window_context(tafsir: str, window: str) -> dict | None:
    """The window's whole pinned text, so the reviewer reads each move in place.

    Returns the exact source slice (window_text), each span's offsets relative to it,
    and the edge of the previous / next part of the same ayah. Text only comes from
    the pinned window file written by the extraction step; nothing is generated."""
    base = base_dir(tafsir)
    p = base / "windows" / f"{window}.json"
    if not p.is_file():
        return None
    w = _read_json(p)
    text = w.get("window_text") or ""
    ws = int(w.get("window_start") or 0)
    spans = {}
    for s in w.get("spans") or []:
        try:
            a, b = int(s["start"]) - ws, int(s["end"]) - ws
        except (KeyError, TypeError, ValueError):
            continue
        if 0 <= a <= b <= len(text):
            spans[s["id"]] = [a, b]
    out = {"text": text, "spans": spans, "prev": None, "next": None}
    m = _PART_RE.match(window)
    if m:
        n = int(m.group("n"))
        for key, k, edge in (("prev", n - 1, "tail"), ("next", n + 1, "head")):
            q = base / "windows" / f"{m.group('stem')}_p{k:02d}.json"
            if k >= 1 and q.is_file():
                t = _read_json(q).get("window_text") or ""
                out[key] = {"window": q.stem,
                            "text": t[-CONTEXT_EDGE:] if edge == "tail" else t[:CONTEXT_EDGE]}
    return out


def load_verified(tafsir: str, annotator: str, window: str) -> dict | None:
    p = verified_path(tafsir, annotator, window)
    return _read_json(p) if p.is_file() else None


def committee_path(tafsir: str, window: str, variant: str | None = None) -> Path:
    """Chair decision written by src/committee_chair.py (committee_profile/ for arm B)."""
    return variant_dir(base_dir(tafsir), "committee", variant) / f"{window}.json"


def load_committee(tafsir: str, window: str, variant: str | None = None) -> dict | None:
    p = committee_path(tafsir, window, variant)
    return _read_json(p) if p.is_file() else None


def committee_is_current(tafsir: str, window: str, variant: str | None = None) -> bool:
    """True when the committee file is newer than both agents' verified files."""
    m = models()
    c = committee_path(tafsir, window, variant)
    paths = [verified_path(tafsir, variant_annotator(m["classifier_slug"], variant), window),
             verified_path(tafsir, variant_annotator(m["verifier_slug"], variant), window)]
    if not c.is_file() or not all(p.is_file() for p in paths):
        return False
    return c.stat().st_mtime >= max(p.stat().st_mtime for p in paths)


def specialist_is_current(tafsir: str, window: str, variant: str | None) -> bool:
    """The method specialists' file exists and is newer than the arm's classifier output."""
    if not variant:
        return False
    sp = variant_dir(base_dir(tafsir), "specialist", variant) / f"{window}.json"
    cv = verified_path(tafsir, variant_annotator(models()["classifier_slug"], variant), window)
    return sp.is_file() and cv.is_file() and sp.stat().st_mtime >= cv.stat().st_mtime


def _committee_summaries(tafsir: str, variant: str | None = None) -> dict[str, dict]:
    d = variant_dir(base_dir(tafsir), "committee", variant)
    out: dict[str, dict] = {}
    if d.is_dir():
        for p in d.glob("*.json"):
            try:
                out[p.stem] = _read_json(p).get("summary") or {}
            except (OSError, ValueError):
                out[p.stem] = {"error": "unreadable"}
    return out


def unit_key(committee_move: dict | None, index: int) -> str:
    """Stable key for one committee row: P-<proposer move> or R-<reviewer-only move>.

    verified/committee/<window>.json can hold two rows with the same move_id
    (a proposer m01 and a reviewer-only m01), so move_id alone is not unique.
    """
    if committee_move:
        if committee_move.get("proposer_move_id"):
            return f"P-{committee_move['proposer_move_id']}"
        if committee_move.get("reviewer_move_id"):
            return f"R-{committee_move['reviewer_move_id']}"
    return f"X-{index}"


def unit_rows(v: dict, com: dict | None) -> list[tuple[str, dict, dict | None]]:
    """(unit key, verified move, committee row) for every move a reviewer can decide."""
    rows = (com or {}).get("moves") or []
    out = []
    for i, mv in enumerate(v.get("moves") or []):
        c = rows[i] if i < len(rows) else None
        key = unit_key(c, i) if com is not None else str(mv.get("move_id"))
        out.append((key, mv, c))
    return out


def models() -> dict[str, str]:
    llm = settings.get("llm")
    return {
        "classifier": llm["classifier_model"],
        "verifier": llm["verifier_model"],
        "classifier_slug": model_slug(llm["classifier_model"]),
        "verifier_slug": model_slug(llm["verifier_model"]),
    }


def _summaries(tafsir: str, annotator: str) -> dict[str, dict]:
    d = base_dir(tafsir) / "verified" / annotator
    out: dict[str, dict] = {}
    if d.is_dir():
        for p in d.glob("*.json"):
            try:
                out[p.stem] = _read_json(p).get("summary") or {}
            except (OSError, ValueError):
                out[p.stem] = {"error": "unreadable"}
    return out


def progress(as_of: float | None = None) -> dict:
    """Coverage per tafsir for the configured classifier / verifier models."""
    d = _demo()
    if d:
        return d.progress(as_of)
    m = models()
    per_tafsir = []
    totals = {"windows": 0, "classifier": 0, "verifier": 0, "both": 0,
              "auto_candidate": 0, "specialist": 0, "moves": 0, "flags": 0,
              "committee": 0, "committee_candidates": 0, "committee_specialist": 0}
    for t in config.TAFSIRS:
        wins = windows(t)
        ids = {w["window"] for w in wins}
        c = {k: v for k, v in _summaries(t, m["classifier_slug"]).items() if k in ids}
        v = {k: v for k, v in _summaries(t, m["verifier_slug"]).items() if k in ids}
        auto = sum(int(s.get("auto_candidate") or 0) for s in c.values())
        spec = sum(int(s.get("specialist") or 0) for s in c.values())
        mv = sum(int(s.get("move_count") or 0) for s in c.values())
        fl = sum(int(s.get("flag_count") or 0) for s in c.values())
        cm = {k: v for k, v in _committee_summaries(t).items() if k in ids}
        row = {
            "tafsir": t, "name_ar": config.TAFSIR_NAMES_AR[t], "windows": len(ids),
            "ayat": len({w["ayah"] for w in wins}),
            "classifier": len(c), "verifier": len(v), "both": len(set(c) & set(v)),
            "auto_candidate": auto, "specialist": spec, "moves": mv, "flags": fl,
            "committee": len(cm),
            "committee_candidates": sum(int(s.get("auto_candidate") or 0) for s in cm.values()),
            "committee_specialist": sum(int(s.get("specialist") or 0) for s in cm.values()),
        }
        per_tafsir.append(row)
        for k in totals:
            totals[k] += row[k]
    return {"models": m, "tafsirs": per_tafsir, "totals": totals,
            "caption_ar": "أعداد توجيه وليست دقة"}


def ayah_matrix() -> dict:
    """Status per ayah × tafsir: none | partial | classifier | both."""
    d = _demo()
    if d:
        return d.ayah_matrix()
    m = models()
    cols = []
    ayat: dict[int, dict] = {}
    for t in config.TAFSIRS:
        cols.append({"tafsir": t, "name_ar": config.TAFSIR_NAMES_AR[t]})
        c = set(_summaries(t, m["classifier_slug"]))
        v = set(_summaries(t, m["verifier_slug"]))
        cm = set(_committee_summaries(t))
        groups: dict[int, list[str]] = {}
        for w in windows(t):
            groups.setdefault(w["ayah_number"], []).append(w["window"])
        for n, ws in groups.items():
            nc = sum(1 for w in ws if w in c)
            nb = sum(1 for w in ws if w in c and w in v)
            ncm = sum(1 for w in ws if w in cm)
            if ncm == len(ws):
                st = "committee"
            elif nb == len(ws):
                st = "both"
            elif nc == len(ws):
                st = "classifier"
            elif nc or nb:
                st = "partial"
            else:
                st = "none"
            ayat.setdefault(n, {"ayah_number": n, "cells": {}})["cells"][t] = {
                "status": st, "windows": len(ws), "classified": nc, "both": nb, "committee": ncm}
    return {"columns": cols, "rows": [ayat[k] for k in sorted(ayat)]}


def resolve_scope(scope: str, ayat: str, tafsirs: list[str]) -> list[tuple[str, str]]:
    """Return [(tafsir, window)] for a scope: sample | ayat | surah."""
    gen = settings.get("general")
    tafsirs = [t for t in tafsirs if t in config.TAFSIRS] or list(config.TAFSIRS)
    wanted: set[int] | None
    if scope == "sample":
        wanted = {int(gen["sample_ayah"].split(":")[1])}
    elif scope == "ayat":
        wanted = parse_ayat(ayat)
        if not wanted:
            raise ValueError("ayat_empty")
    elif scope == "surah":
        wanted = None
    else:
        raise ValueError("scope_unknown")
    out = []
    for t in tafsirs:
        for w in windows(t):
            if wanted is None or w["ayah_number"] in wanted:
                out.append((t, w["window"]))
    return out


def parse_ayat(text: str) -> set[int]:
    """'1-5, 35, 40' → {1,2,3,4,5,35,40}; ignores anything else."""
    out: set[int] = set()
    for part in re.split(r"[,\s،]+", text or ""):
        if not part:
            continue
        m = re.fullmatch(r"(\d{1,3})\s*[-–]\s*(\d{1,3})", part)
        if m:
            a, b = sorted((int(m.group(1)), int(m.group(2))))
            if b - a <= 300:
                out.update(range(a, b + 1))
        elif part.isdigit():
            out.add(int(part))
    return {n for n in out if 1 <= n <= 300}


# ------------------------------------------------------------ chair preview

def _overlap(a: list[str], b: list[str]) -> bool:
    return bool(set(a or []) & set(b or []))


def chair_preview(tafsir: str, window: str, variant: str | None = None) -> dict | None:
    """Read-only committee decision per classifier move (docs/COMMITTEE_PLAN.md §ج).

    Candidate only if: both routes auto_candidate, same primary, overlapping
    spans, classifier score ≥ 85, no flags on either side. Otherwise one
    reason code, first that applies. Writes nothing.
    """
    m = models()
    cv = load_verified(tafsir, variant_annotator(m["classifier_slug"], variant), window)
    vv = load_verified(tafsir, variant_annotator(m["verifier_slug"], variant), window)
    if cv is None:
        return None
    out = []
    for mv in cv.get("moves") or []:
        match = None
        if vv:
            for other in vv.get("moves") or []:
                if _overlap(mv.get("span_ids"), other.get("span_ids")):
                    match = other
                    break
        score = int((mv.get("score") or {}).get("total") or 0)
        reason = None
        if mv.get("certainty") == "insufficient" or not mv.get("primary"):
            reason = "written_abstain"
        elif mv.get("primary") in config.FORCE_SPECIALIST:
            reason = "force_specialist"
        elif vv is None:
            reason = "agent_missing"
        elif match is None:
            reason = "unclear_bounds"
        elif match.get("primary") != mv.get("primary"):
            reason = "agent_disagree"
        elif (mv.get("route") != "auto_candidate" or match.get("route") != "auto_candidate"
              or score < config.COMMITTEE_THRESHOLD or mv.get("flags") or match.get("flags")):
            reason = "weak_evidence"
        out.append({
            "move_id": mv.get("move_id"),
            "reviewer_move_id": match.get("move_id") if match else None,
            "primary": mv.get("primary"),
            "primary_reviewer": match.get("primary") if match else None,
            "score": score,
            "route_classifier": mv.get("route"),
            "route_reviewer": match.get("route") if match else None,
            "committee_route": "auto_candidate" if reason is None else "specialist",
            "reason": reason,
        })
    return {
        "tafsir": tafsir, "window": window, "has_reviewer": vv is not None,
        "moves": out,
        "candidates": sum(1 for x in out if x["committee_route"] == "auto_candidate"),
        "specialist": sum(1 for x in out if x["committee_route"] == "specialist"),
        "note_ar": "معاينة للقراءة فقط — لا تكتب ملفات ولا تعني اعتماداً",
    }


def _ab_salt() -> bytes:
    """Per-server secret that decides which arm is X and which is Y (blind review)."""
    import secrets

    p = config.VAR_DIR / "ab_blind.salt"
    try:
        return p.read_bytes()
    except OSError:
        p.parent.mkdir(parents=True, exist_ok=True)
        salt = secrets.token_hex(16).encode("ascii")
        p.write_bytes(salt)
        return salt


def arm_codes(tafsir: str, window: str) -> dict[str | None, str]:
    """{None: 'X'|'Y', 'profile': 'Y'|'X'} — stable per window, hidden from reviewers."""
    import hashlib

    h = hashlib.sha256(_ab_salt() + f"{tafsir}/{window}".encode("utf-8")).digest()
    return {None: "X", "profile": "Y"} if h[0] % 2 == 0 else {None: "Y", "profile": "X"}


def variant_for_arm(tafsir: str, window: str, arm: str | None) -> str | None:
    if not arm:
        return None
    for v, code in arm_codes(tafsir, window).items():
        if code == arm:
            return v
    raise ValueError("bad_arm")


def review_source(tafsir: str, window: str,
                  variant: str | None = None) -> tuple[str, dict | None, dict | None]:
    """(annotator, verified payload, committee payload) for one arm of one window."""
    m = models()
    com_name = variant_annotator("committee", variant)
    com_v = load_verified(tafsir, com_name, window)
    if com_v is not None:
        return com_name, com_v, load_committee(tafsir, window, variant)
    slug = variant_annotator(m["classifier_slug"], variant)
    return slug, load_verified(tafsir, slug, window), None


def move_routes(tafsir: str, window: str, annotator: str) -> dict[str, str]:
    """Unit key → the route the agents gave it (auto_candidate = suggested by the chair,
    else referred to the specialist), for the file a reviewer decided on."""
    d = _demo()
    if d:
        u = db.row("SELECT span_count FROM demo_units WHERE tafsir=? AND window=?",
                   (tafsir, window))
        return {m["key"]: m["route"] for m in d.unit_moves(tafsir, window, u["span_count"])} \
            if u else {}
    variant = "profile" if annotator.endswith("__profile") else None
    ann, v, com = review_source(tafsir, window, variant)
    if v is None or ann != annotator:
        return {}
    return {key: str(mv.get("route") or "") for key, mv, _c in unit_rows(v, com)}


def review_units(tafsir: str | None = None) -> list[dict]:
    """Units ready for review: per window and arm, the chair's decision when it
    exists, else agent 1. Windows with an arm B run get one unit per arm, labelled
    X / Y (blind); the variant and annotator fields are for operators only."""
    d = _demo()
    if d:
        return d.review_units(tafsir)
    m = models()
    out = []
    for t in config.TAFSIRS:
        if tafsir and t != tafsir:
            continue
        meta = {w["window"]: w for w in windows(t)}
        arms = {}
        for v in ARM_VARIANTS:
            arms[v] = (_summaries(t, variant_annotator(m["classifier_slug"], v)),
                       _committee_summaries(t, v))
        b_windows = set(arms["profile"][0]) | set(arms["profile"][1])
        for v, (sums, com) in arms.items():
            for wid in sorted(set(sums) | set(com)):
                if wid not in meta:
                    continue
                is_com = wid in com
                s = com[wid] if is_com else sums[wid]
                arm = arm_codes(t, wid)[v] if wid in b_windows else None
                out.append({"tafsir": t, "name_ar": config.TAFSIR_NAMES_AR[t], "window": wid,
                            "ayah": meta[wid]["ayah"], "ayah_number": meta[wid]["ayah_number"],
                            "moves": int(s.get("move_count") or 0),
                            "auto_candidate": int(s.get("auto_candidate") or 0),
                            "specialist": int(s.get("specialist") or 0),
                            "flags": int(s.get("flag_count") or 0) if not is_com else None,
                            "reasons": s.get("by_abstention_reason") if is_com else None,
                            "committee": is_com, "arm": arm, "variant": v,
                            "annotator": variant_annotator(
                                "committee" if is_com else m["classifier_slug"], v)})
    out.sort(key=lambda x: (x["ayah_number"], x["tafsir"], x["window"], x["arm"] or ""))
    return out


# ------------------------------------------------------------------ ollama

def _get_json(url: str, timeout: float = 4.0) -> Any:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (configured URL)
        return json.loads(r.read().decode("utf-8"))


def probe_llm() -> dict:
    d = _demo()
    if d:
        return d.probe()
    llm = settings.get("llm")
    base = llm["base_url"].rstrip("/")
    out: dict[str, Any] = {"base_url": base, "runtime": llm["runtime"], "reachable": False,
                           "models": [], "version": None, "error": None,
                           "classifier_model": llm["classifier_model"],
                           "verifier_model": llm["verifier_model"]}
    if llm["runtime"] != "ollama-local":
        out["error"] = "hosted_runtime_not_probed"
        return out
    try:
        tags = _get_json(f"{base}/api/tags")
        out["reachable"] = True
        out["models"] = sorted(
            [{"name": x.get("name"), "size": x.get("size"),
              "family": (x.get("details") or {}).get("family"),
              "parameter_size": (x.get("details") or {}).get("parameter_size"),
              "quantization": (x.get("details") or {}).get("quantization_level")}
             for x in tags.get("models") or []],
            key=lambda x: x["name"] or "")
        try:
            out["version"] = _get_json(f"{base}/api/version").get("version")
        except (urllib.error.URLError, OSError, ValueError):
            pass
    except (urllib.error.URLError, OSError, ValueError) as e:
        out["error"] = f"{type(e).__name__}: {getattr(e, 'reason', e)}"[:200]
    names = {x["name"] for x in out["models"]}
    out["classifier_installed"] = llm["classifier_model"] in names
    out["verifier_installed"] = llm["verifier_model"] in names
    return out


_PS_CACHE: dict[str, Any] = {"at": 0.0, "value": None}


def _epoch(iso: str | None) -> float | None:
    """Ollama's RFC 3339 time (nanoseconds allowed) → epoch seconds; None for "forever"."""
    if not iso:
        return None
    s = re.sub(r"(\.\d{6})\d+", r"\1", str(iso)).replace("Z", "+00:00")
    try:
        ts = dt.datetime.fromisoformat(s).timestamp()
    except ValueError:
        return None
    return ts if 0 < ts < 4e9 else None  # year 1 / far future = kept loaded


def ollama_ps(max_age: float = 4.0) -> dict:
    """Models the model server holds in memory now (GET /api/ps), cached a few seconds."""
    d = _demo()
    if d:
        return d.ollama_ps()
    now = time.time()
    if _PS_CACHE["value"] is not None and now - _PS_CACHE["at"] < max_age:
        return _PS_CACHE["value"]
    llm = settings.get("llm")
    out: dict[str, Any] = {"available": False, "error": None, "models": [], "at": now}
    if llm["runtime"] != "ollama-local":
        out["error"] = "hosted_runtime_not_probed"
    else:
        try:
            ps = _get_json(llm["base_url"].rstrip("/") + "/api/ps", timeout=3.0)
            out["available"] = True
            for x in ps.get("models") or []:
                det = x.get("details") or {}
                out["models"].append({
                    "name": x.get("name") or x.get("model"), "size": x.get("size"),
                    "size_vram": x.get("size_vram"), "context_length": x.get("context_length"),
                    "expires_at": _epoch(x.get("expires_at")),
                    "parameter_size": det.get("parameter_size"),
                    "quantization": det.get("quantization_level")})
        except (urllib.error.URLError, OSError, ValueError) as e:
            out["error"] = f"{type(e).__name__}: {getattr(e, 'reason', e)}"[:200]
    _PS_CACHE.update(at=now, value=out)
    return out
