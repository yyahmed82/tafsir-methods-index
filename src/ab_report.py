"""A/B counts: baseline (arm A) vs methodology profile (arm B) on the same windows.

Reads committee outputs only (never writes). A "trap hit" is a move whose primary
method rests only on markers that the mufassir's profile identifies as known false
signals: the target verse quoted as a heading (M_QURAN), chain words without a
Prophetic text (M_SUNNAH), or «قلت» inside a report (M_RAY). It is measured the same
way for both arms, from the profile lexicon applied to the shared markers.

All numbers are routing counts, not accuracy («أعداد توجيه وليست دقة»).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

import v2_profiles  # noqa: E402
from textcore import read_json  # noqa: E402

CAPTION_AR = "أعداد توجيه وليست دقة"
# trap signal → (method it falsely supports, marker family that would support it)
TRAPS = {
    "TARGET_VERSE_HEADING": ("M_QURAN", "QURAN"),
    "ISNAD_WORDS_ONLY": ("M_SUNNAH", "HADITH"),
    "QULTU_IN_REPORT": ("M_RAY", "RAY"),
}


def trap_hits(moves: list[dict], profile_markers: dict) -> list[dict]:
    """Moves whose primary is supported only by spans the profile marks as traps."""
    blocks = {b["span_id"]: b for b in profile_markers.get("spans") or []}
    hits = []
    for mv in moves:
        primary = mv.get("primary")
        ev = mv.get("evidence_span_ids") or mv.get("span_ids") or []
        for code, (method, family) in TRAPS.items():
            if primary != method:
                continue
            flagged = [sid for sid in ev if code in (blocks.get(sid, {}).get("profile_signals") or [])]
            if not flagged:
                continue
            supported = any(h.get("family") == family
                            for sid in ev for h in blocks.get(sid, {}).get("markers") or [])
            if not supported:
                hits.append({"move_id": mv.get("move_id"), "trap": code, "spans": flagged,
                             "route": mv.get("committee_route") or mv.get("route")})
    return hits


def _committee_moves(base: Path, window: str, variant: str | None) -> list[dict] | None:
    """Verified-committee moves for one arm (primary, spans, route), or None."""
    name = v2_profiles.variant_annotator("committee", variant)
    p = Path(base) / "verified" / name / f"{window}.json"
    if not p.is_file():
        return None
    out = []
    for m in read_json(p).get("moves") or []:
        out.append({"move_id": m.get("move_id"), "primary": m.get("primary"),
                    "span_ids": m.get("span_ids") or [],
                    "evidence_span_ids": m.get("evidence_span_ids") or [],
                    "route": m.get("route"), "reason": m.get("committee_reason_code")
                    or m.get("reason_code")})
    return out


def compare_base(base: Path, tafsir: str | None = None) -> dict:
    """Paired counts over windows where both arms have a committee result."""
    base = Path(base)
    profile = v2_profiles.load_profile(v2_profiles.profile_key_for(base, tafsir))
    arms = {"A": None, "B": v2_profiles.VARIANT}
    result = {a: {"windows": 0, "moves": 0, "auto_candidate": 0, "specialist": 0,
                  "by_primary": {}, "by_reason": {}, "trap_hits": 0,
                  "trap_hits_candidates": 0, "by_trap": {}} for a in arms}
    paired = []
    for wp in sorted((base / "windows").glob("*.json")):
        wid = wp.stem
        moves = {a: _committee_moves(base, wid, v) for a, v in arms.items()}
        if any(m is None for m in moves.values()):
            continue
        paired.append(wid)
        pm = v2_profiles.apply_profile(read_json(wp), read_json(base / "markers" / wp.name), profile)
        for a, mv in moves.items():
            r = result[a]
            r["windows"] += 1
            r["moves"] += len(mv)
            for m in mv:
                key = "auto_candidate" if m["route"] == "auto_candidate" else "specialist"
                r[key] += 1
                p = str(m["primary"])
                r["by_primary"][p] = r["by_primary"].get(p, 0) + 1
                if m["reason"]:
                    r["by_reason"][m["reason"]] = r["by_reason"].get(m["reason"], 0) + 1
            for h in trap_hits(mv, pm):
                r["trap_hits"] += 1
                r["by_trap"][h["trap"]] = r["by_trap"].get(h["trap"], 0) + 1
                if h["route"] == "auto_candidate":
                    r["trap_hits_candidates"] += 1
    return {"tafsir": profile["tafsir"], "name_ar": profile["name_ar"],
            "profile_version": profile["version"], "paired_windows": paired,
            "arms": result, "caption_ar": CAPTION_AR}
