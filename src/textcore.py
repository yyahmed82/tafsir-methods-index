"""Shared text/path helpers for the pinned pipeline.

One authoritative copy of the helpers that were previously duplicated across
src/*.py (see docs/AUDIT_2026-10-02.md §3 / phase 2.1). Callers import from here;
do not re-define these functions elsewhere.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class IntegrityError(ValueError):
    """Raised when text/span integrity checks fail (tiling, coverage, …)."""


def read_exact(path: Path) -> str:
    """Read a pinned text file as UTF-8 without newline translation."""
    return path.read_bytes().decode("utf-8")


def read_json(path: Path) -> dict:
    """Load a UTF-8 JSON object from disk (bytes → decode → json.loads)."""
    return json.loads(path.read_bytes().decode("utf-8"))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def assert_tiling(ranges: list[dict], n: int) -> None:
    """Strict tiling check: sorted, abutting, non-empty, covering [0, n).

    Combines the strongest checks from the former copies in layers.py,
    multi_layers.py, and check_phase1b.py. Uses explicit exceptions so
    ``python -O`` cannot strip the guard.
    """
    if ranges != sorted(ranges, key=lambda r: r["start"]):
        raise IntegrityError("ranges not sorted by start")
    if n == 0:
        if ranges:
            raise IntegrityError("expected no ranges for empty text")
        return
    if not ranges:
        raise IntegrityError("ranges empty but text length > 0")
    if ranges[0]["start"] != 0:
        raise IntegrityError("ranges do not start at 0")
    if ranges[-1]["end"] != n:
        raise IntegrityError("ranges do not end at len(text)")
    prev_end = 0
    for r in ranges:
        start = r["start"]
        end = r["end"]
        if start != prev_end:
            raise IntegrityError(f"gap/overlap at {prev_end} vs {start}")
        if end <= start:
            raise IntegrityError(f"empty range at {start}")
        prev_end = end
    if prev_end != n:
        raise IntegrityError(f"ranges end at {prev_end}, expected {n}")


def resolve_base(base: str | Path, root: Path | None = None) -> Path:
    """Resolve a ``--base`` path relative to the repo root (or ``root``)."""
    p = Path(base)
    if not p.is_absolute():
        p = (root or ROOT) / p
    return p.resolve()


# ---------------------------------------------------------------------------
# The verse at the head of a commentary window — strict.
#
# The reader and the console show the ayah above a window. There is no mushaf text in
# this repository, so the ayah is taken from the window itself: the quotation the
# mufassir puts right before the edition's «(n)» marker. The old heuristic cut
# everything before the marker and only dropped a brace found in the first 80
# characters, so it also showed the surah heading and the edition's «****»
# separator (Ibn Kathir 24:1), the mufassir's own introductory sentence (al-Saadi
# 24:6, 24:36, 24:51) and commentary between two halves of a verse (al-Tabari 24:21)
# inside the Quranic brackets. This version isolates the quotation or returns None.

_VERSE_MARKER_WINDOW = 3000
# anything that is never inside a verse quotation in these editions
_VERSE_FORBIDDEN = re.compile(r"[*¬¥<>{}\[\]\d\r\n:؛«»]")
# a few formulas of the commentary itself; a verse never contains them
_VERSE_FORMULAS = ("القول في تأويل", "القولُ في تأويلِ", "قوله تعالى", "قولِه تعالى", "قوله عز وجل",
                   "يقول تعالى", "قال أبو جعفر", "وهي مدنية", "وهي مكية", "وهي مدينة", "تفسير سورة",
                   "تفسيرُ سورةِ", "فقال", "ثم قال", "بسم الله", "بِسْمِ اللَّهِ")


def _verse_clean(s: str) -> str | None:
    s = s.strip().strip("{}").strip()
    s = s.strip(" .،؟!﴾﴿‏‎﻿\t")
    if not 8 <= len(s) <= 1500:
        return None
    if _VERSE_FORBIDDEN.search(s):
        return None
    if any(f in s for f in _VERSE_FORMULAS):
        return None
    return s


def verse_at_head(text: str, n: int) -> str | None:
    """The ayah ``n`` as the mufassir quotes it before the edition's «(n)» marker, or
    None when it cannot be isolated with certainty.

    - the editor's apparatus ``¬…¥`` is removed first;
    - with braces, the quotation is the text after the **last** ``{`` before the marker
      (the mufassir's introduction stays outside); if that ``{`` is preceded by another
      brace segment with only connective text between them, the two are one verse
      quoted in consecutive braces and are joined; a verse quoted in two halves with
      commentary between them is not isolable and gives None;
    - without braces (Ibn Kathir's edition), the quotation is the last line before the
      marker (the heading and the «****» separator sit on earlier lines);
    - the result must contain no apparatus marker, separator, bracket, digit, line
      break, colon or commentary formula; otherwise None.
    """
    t = re.sub(r"¬[^¥]*¥", "", (text or "")[:_VERSE_MARKER_WINDOW])
    m = re.search(rf"\({int(n)}\)", t)
    if not m:
        return None
    head = t[:m.start()]
    if "{" in head:
        i = head.rfind("{")
        verse = head[i + 1:]
        before = head[:i]
        # consecutive quotations: «{…} {…}» or «{…}، {…}» — join them
        while before.rstrip().endswith("}"):
            j = before.rfind("{")
            if j < 0:
                break
            gap = before[before.rfind("}") + 1:]
            if gap.strip(" ،.‏") != "":
                break
            verse = before[j + 1:before.rfind("}")] + " " + verse
            before = before[:j]
        if "{" in before:
            # an earlier quotation with commentary after it: the verse may be quoted in
            # halves (al-Tabari 24:21) — half a verse is never shown as the ayah
            return None
        return _verse_clean(verse)
    lines = [ln for ln in re.split(r"\r?\n", head) if ln.strip()]
    if not lines:
        return None
    return _verse_clean(lines[-1])
