"""قلم التمييز — units a specialist marks by hand in the pinned text.

A pen unit is a contiguous slice [start, end) of the pinned source file, read back
letter for letter at the moment it is saved and again at every publication (the
file's sha256 must still be the pinned one). It carries the method the specialist
chose, optional content tags and a note. It may replace a machine move (parent_key):
the parent then takes a «needs_edit» decision so only the specialist's unit is
published. Keys are h01, h02 … per window. Deleting keeps the row (deleted_at) for
the audit trail.
"""
from __future__ import annotations

import re

from . import db, pipeline, publish

CONTENT_TAGS = ("C_NUZUL", "C_FIQH", "C_BALAGHA", "C_SHIR", "C_ISRAILIYYAT", "C_FADAIL",
                "C_TAKHRIJ", "C_TAFSIR")
KEY_RE = re.compile(r"^h\d{2,3}$")
_WORD = re.compile(r"\S")


def _row(r: dict) -> dict:
    out = dict(r)
    out["content_tags"] = db.loads(r.get("content_tags"), []) or []
    out["primary"] = out.pop("primary_method")
    out["key"] = out["key"]
    return out


def units(tafsir: str, window: str, include_deleted: bool = False) -> list[dict]:
    q = ("SELECT p.*, u.name AS user_name FROM pen_units p JOIN users u ON u.id=p.user_id"
         " WHERE tafsir=? AND window=?" + ("" if include_deleted else " AND deleted_at IS NULL")
         + " ORDER BY start, id")
    return [_row(r) for r in db.rows(q, (tafsir, window))]


def all_active() -> list[dict]:
    return [_row(r) for r in db.rows(
        "SELECT * FROM pen_units WHERE deleted_at IS NULL ORDER BY tafsir, window, start, id")]


def get(pen_id: int) -> dict | None:
    r = db.row("SELECT * FROM pen_units WHERE id=?", (pen_id,))
    return _row(r) if r else None


def next_key(tafsir: str, window: str) -> str:
    n = 0
    for r in db.rows("SELECT key FROM pen_units WHERE tafsir=? AND window=?", (tafsir, window)):
        m = re.match(r"^h(\d+)$", r["key"])
        if m:
            n = max(n, int(m.group(1)))
    return f"h{n + 1:02d}"


def snap(text: str, start: int, end: int, lo: int, hi: int) -> tuple[int, int]:
    """Trim whitespace at both ends, then widen to whole words, inside [lo, hi)."""
    start, end = max(lo, start), min(hi, end)
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    while start > lo and not text[start - 1].isspace() and _WORD.match(text[start - 1] or " "):
        start -= 1
    while end < hi and not text[end].isspace() and _WORD.match(text[end]):
        end += 1
    return start, end


def _source_of(tafsir: str, window: str, w: dict) -> tuple[str | None, str | None, str | None]:
    """(text, sha, rel) of the pinned file: named by the window file, else by the verified
    payload the reviewer decides on."""
    rel = w.get("source_file")
    if not rel:
        _ann, v, _com = pipeline.review_source(tafsir, window)
        rel = (v or {}).get("source_file")
    text, sha = publish._source(tafsir, rel)
    return text, sha, rel


def check(tafsir: str, window: str, start: int, end: int) -> tuple[dict | None, str | None, str]:
    """(window, error key, text) — the slice read back from the pinned file, letter for
    letter, after snapping to whole words. Errors: unit_not_found, source_missing,
    source_changed, bad_bounds, empty."""
    w = pipeline.load_window(tafsir, window)
    if w is None:
        return None, "unit_not_found", ""
    text, sha, _rel = _source_of(tafsir, window, w)
    if text is None:
        return w, "source_missing", ""
    if sha != w.get("source_sha256", sha):
        return w, "source_changed", ""
    lo, hi = int(w.get("window_start") or 0), int(w.get("window_end") or 0)
    if not (isinstance(start, int) and isinstance(end, int) and lo <= start < end <= hi):
        return w, "bad_bounds", ""
    a, b = snap(text, start, end, lo, hi)
    if a >= b:
        return w, "empty", ""
    w["_start"], w["_end"] = a, b
    return w, None, text[a:b]


def verify(unit: dict) -> tuple[bool, str | None, str | None]:
    """At publication: (ok, reason, sha) — the slice still reads back from the file."""
    w = pipeline.load_window(unit["tafsir"], unit["window"])
    if w is None:
        return False, "unit_missing", None
    text, sha, _rel = _source_of(unit["tafsir"], unit["window"], w)
    if text is None:
        return False, "source_missing", sha
    if sha != w.get("source_sha256", sha) or sha != unit.get("source_sha256"):
        return False, "source_changed", sha
    a, b = int(unit["start"]), int(unit["end"])
    if not 0 <= a < b <= len(text) or text[a:b] != unit["text"]:
        return False, "text_mismatch", sha
    return True, None, sha


def save(tafsir: str, window: str, user_id: int, start: int, end: int, primary: str,
         content_tags: list[str], note: str, pen_id: int | None = None,
         parent_key: str = "", parent_annotator: str = "") -> dict:
    w, err, text = check(tafsir, window, start, end)
    if err:
        raise ValueError(err)
    a, b = w["_start"], w["_end"]
    now = db.now()
    tags = db.dumps([t for t in content_tags if t in CONTENT_TAGS])
    if pen_id:
        db.execute("UPDATE pen_units SET start=?, end=?, text=?, primary_method=?, content_tags=?,"
                   " note=?, updated_at=?, user_id=? WHERE id=? AND deleted_at IS NULL",
                   (a, b, text, primary, tags, note, now, user_id, pen_id))
        return get(pen_id)
    key = next_key(tafsir, window)
    db.execute("INSERT INTO pen_units(tafsir, window, key, parent_key, parent_annotator, start, end,"
               " text, primary_method, content_tags, note, source_sha256, user_id, created_at,"
               " updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
               (tafsir, window, key, parent_key or "", parent_annotator or "", a, b, text, primary,
                tags, note, w.get("source_sha256") or _source_of(tafsir, window, w)[1] or "",
                user_id, now, now))
    r = db.row("SELECT id FROM pen_units WHERE tafsir=? AND window=? AND key=?", (tafsir, window, key))
    return get(r["id"])


def delete(pen_id: int, user_id: int) -> dict | None:
    u = get(pen_id)
    if u is None or u.get("deleted_at"):
        return None
    db.execute("UPDATE pen_units SET deleted_at=?, user_id=? WHERE id=?", (db.now(), user_id, pen_id))
    return get(pen_id)
