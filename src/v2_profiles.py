"""Per-mufassir methodology profiles: arm B ("profile") of the A/B test.

The baseline pipeline (arm A) is untouched. A profile run reads the same pinned
windows and deterministic markers, then:

1. applies the mufassir's lexicon from ``method/profiles/<tafsir>.json``
   (suppress known false markers, add the mufassir's own formulas) and writes
   ``<base>/markers_profile/<window>.json``;
2. builds a packet with the profile card, per-span profile signals and, when
   reviewed examples exist, teaching examples, and writes
   ``<base>/packets_profile/<window>.json``.

Moves and verified outputs of a profile run use the annotator name
``<model_slug>__profile``; the committee writes ``<base>/committee_profile/``.
Nothing here edits windows, spans, layers or raw text, and nothing approves.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from textcore import read_json, resolve_base  # noqa: E402
from v2_markers import _find_phrases, _strip_map  # noqa: E402
import v2_packets  # noqa: E402

PROFILES_DIR = ROOT / "method" / "profiles"
VARIANT = "profile"
VARIANTS = (VARIANT,)
ANNOTATOR_SEP = "__"

ISNAD_WORDS = frozenset({"حدثنا", "أخبرنا", "اخبرنا"})
_PROPHET_RX = re.compile(r"رسول الله|النبي|صلى الله عليه وسلم|ﷺ")
_QUOTE_RX = re.compile(r"\{[^{}]+\}|﴿[^﴾]+﴾")
_LEX_KEYS = ("ray_add", "qultu", "heading_phrases", "paraphrase_phrases",
             "opinion_list_phrases", "isnad_words_only", "readers")

SIGNALS_AR = {
    "TARGET_VERSE_HEADING": "عنوان يقتبس الآية المفسَّرة نفسها — ليس قرآنًا بالقرآن",
    "ISNAD_WORDS_ONLY": "ألفاظ إسناد فقط — لا تعني سنة؛ المنهج لآخر قائل",
    "QULTU_IN_REPORT": "«قلت» داخل رواية أو آية — ليست رأي المفسر",
    "AUTHOR_VERDICT": "صيغة حكم أو ترجيح أو استنباط من كلام المفسر",
    "AUTHOR_PARAPHRASE": "بيان إجمالي من المفسر للآية",
    "OPINION_EVIDENCE_LIST": "بداية روايات تشهد لقول سبق",
    "READER_NAMES": "أسماء قرّاء بعد «قرأ» — قراءات لا أعلام تفسير",
}


# ------------------------------------------------------------------ variants

def check_variant(variant: str | None) -> str | None:
    """None/'' → baseline; otherwise the variant name, validated."""
    if not variant:
        return None
    if variant not in VARIANTS:
        raise ValueError(f"unknown variant {variant!r}; expected one of {VARIANTS}")
    return variant


def variant_dir(base: Path, name: str, variant: str | None) -> Path:
    """<base>/<name> for the baseline, <base>/<name>_<variant> for a variant."""
    variant = check_variant(variant)
    return Path(base) / (name if not variant else f"{name}_{variant}")


def variant_annotator(slug: str, variant: str | None) -> str:
    variant = check_variant(variant)
    if not variant or slug.endswith(ANNOTATOR_SEP + variant):
        return slug
    return f"{slug}{ANNOTATOR_SEP}{variant}"


def split_annotator(name: str) -> tuple[str, str | None]:
    """'qwen2_5_14b__profile' → ('qwen2_5_14b', 'profile')."""
    for v in VARIANTS:
        suffix = ANNOTATOR_SEP + v
        if name.endswith(suffix):
            return name[: -len(suffix)], v
    return name, None


# ------------------------------------------------------------------ profiles

def profile_path(key: str) -> Path:
    if not re.fullmatch(r"[a-z_]+", key or ""):
        raise ValueError(f"bad profile key {key!r}")
    return PROFILES_DIR / f"{key}.json"


def load_profile(key: str) -> dict:
    path = profile_path(key)
    if not path.is_file():
        raise FileNotFoundError(f"no methodology profile for {key!r}: {path}")
    prof = read_json(path)
    missing = [k for k in ("tafsir", "name_ar", "version", "card_ar", "golden_rules_ar",
                           "families", "lexicon") if k not in prof]
    if missing:
        raise ValueError(f"profile {key} missing keys: {missing}")
    lex_missing = [k for k in _LEX_KEYS if k not in prof["lexicon"]]
    if lex_missing:
        raise ValueError(f"profile {key} lexicon missing keys: {lex_missing}")
    if prof["lexicon"]["qultu"] not in ("never", "author_voice"):
        raise ValueError(f"profile {key}: qultu must be never|author_voice")
    if prof["tafsir"] != key:
        raise ValueError(f"profile {key}: tafsir field is {prof['tafsir']!r}")
    return prof


def profile_key_for(base: Path, tafsir: str | None = None) -> str:
    """The profile key is the tafsir id, else the base directory name."""
    return tafsir or Path(base).resolve().name


def card_text_ar(profile: dict) -> str:
    lines = [f"المفسر: {profile['name_ar']} — ملف المنهج {profile['version']} "
             f"({profile.get('status_ar') or profile.get('status')})"]
    lines.append("نمط العرض:")
    lines += [f"- {x}" for x in profile["card_ar"]]
    lines.append("القواعد الذهبية لهذا المفسر:")
    lines += [f"{i}. {x}" for i, x in enumerate(profile["golden_rules_ar"], 1)]
    lines.append("علامات [profile:…] بجانب الأجزاء إشارات حتمية من الملف، لا أحكام نهائية.")
    return "\n".join(lines)


# ------------------------------------------------------------------ lexicon

def _heading_rx(phrases: list[str]) -> re.Pattern | None:
    if not phrases:
        return None
    alts = "|".join(re.escape(p) for p in sorted(set(phrases), key=len, reverse=True))
    return re.compile(
        rf"(?:^|[.\n\r،؛:]\s*)(?:{alts})(?:\s+تعالى|\s+عز وجل|\s+جل ذكره)?\s*:?\s*$"
    )


def _heading_quote_end(text: str, prev_text: str, rx: re.Pattern | None) -> int | None:
    """End offset (in original span text) of a heading quote of the target verse.

    The quote is the first {…}/﴿…﴾ in the span; the text right before it — in this
    span, or at the end of the previous span when the quote opens the span — must
    be a heading formula such as «القول في تأويل قوله تعالى» or «وقوله:».
    """
    if rx is None:
        return None
    m = _QUOTE_RX.search(text)
    if not m:
        return None
    before, _ = _strip_map(text[: m.start()])
    if not before.strip():
        before = _strip_map(prev_text)[0]
    if rx.search(before.rstrip()):
        return m.end()
    return None


def _trailing_heading_start(text: str, next_text: str, rx: re.Pattern | None) -> int | None:
    """Offset where a heading formula closing this span begins, when the next span
    opens with the quoted target verse («القول في تأويل قوله تعالى:» + «{…}»)."""
    if rx is None or not re.match(r"^\s*[{\ufd3f]", next_text or ""):
        return None
    stripped, mapping = _strip_map(text)
    m = rx.search(stripped.rstrip())
    if not m:
        return None
    return mapping[m.start()] if m.start() < len(mapping) else None


def _author_qultu(text: str, rel_start: int, prev_text: str) -> bool:
    """«قلت:» opening the span, not inside a quoted narration."""
    head, _ = _strip_map(text[:rel_start])
    if head.strip(" \t\r\n.،؛-–—"):
        return False
    tail, _ = _strip_map(text[rel_start:rel_start + 8])
    if not re.match(r"^قلت\s*:", tail):
        return False
    prev, _ = _strip_map(prev_text)
    # a question or a speech verb just before means «قلت» answers inside a dialogue
    return not re.search(r"(?:قال|قالت|فقال|فقالت|يقول)\s*:?\s*$|[؟?]\s*$", prev.rstrip())


def apply_profile(window: dict, markers: dict, profile: dict) -> dict:
    """Return a new markers document with the profile lexicon applied."""
    lex = profile["lexicon"]
    out = copy.deepcopy(markers)
    blocks = {b["span_id"]: b for b in out.get("spans") or []}
    spans = window.get("spans") or []
    head_rx = _heading_rx(lex["heading_phrases"])
    readers = sorted(set(lex["readers"]), key=len, reverse=True)
    reader_rx = (re.compile(r"(?<!\w)(?:" + "|".join(re.escape(r) for r in readers) + r")(?!\w)")
                 if readers else None)
    totals = {"suppressed": 0, "added": 0}

    for i, span in enumerate(spans):
        sid = span["id"]
        block = blocks.get(sid)
        if block is None:
            block = {"span_id": sid, "markers": []}
            out.setdefault("spans", []).append(block)
            blocks[sid] = block
        text = span["text"]
        prev_text = spans[i - 1]["text"] if i else ""
        stripped, mapping = _strip_map(text)
        keep: list[dict] = []
        suppressed: list[dict] = []
        signals: list[str] = []

        def suppress(hit: dict, reason: str) -> None:
            suppressed.append({**hit, "suppressed_by": reason})
            if reason not in signals:
                signals.append(reason)

        next_text = spans[i + 1]["text"] if i + 1 < len(spans) else ""
        trailing_head = _trailing_heading_start(text, next_text, head_rx)
        heading_end = _heading_quote_end(text, prev_text, head_rx)
        has_verse_ref = any(h.get("marker") == "verse_ref" for h in block.get("markers") or [])
        if heading_end is not None and has_verse_ref:
            heading_end = None  # a cited reference [سورة: n] means a cross-reference
        for h in block.get("markers") or []:
            rel = h["start"] - span["start"]
            if h["family"] == "RAY" and h.get("marker") == "قلت":
                if lex["qultu"] == "never" or not _author_qultu(text, rel, prev_text):
                    suppress(h, "QULTU_IN_REPORT")
                    continue
            if (h["family"] == "QURAN" and heading_end is not None
                    and h.get("marker") != "verse_ref" and rel < heading_end):
                suppress(h, "TARGET_VERSE_HEADING")
                continue
            if (h["family"] == "QURAN" and trailing_head is not None
                    and h.get("marker") != "verse_ref" and rel >= trailing_head):
                suppress(h, "TARGET_VERSE_HEADING")
                continue
            keep.append(h)

        if lex["isnad_words_only"]:
            hadith = [h for h in keep if h["family"] == "HADITH"]
            if (hadith and all(h.get("marker") in ISNAD_WORDS for h in hadith)
                    and not _PROPHET_RX.search(stripped)):
                for h in hadith:
                    suppress(h, "ISNAD_WORDS_ONLY")
                keep = [h for h in keep if h["family"] != "HADITH"]

        added: list[dict] = []
        for h in _find_phrases(stripped, mapping, len(text), list(lex["ray_add"]), "RAY"):
            added.append({**h, "start": h["start"] + span["start"], "end": h["end"] + span["start"],
                          "span_id": sid, "via": "profile"})
        if added:
            signals.append("AUTHOR_VERDICT")
        if reader_rx:
            # a reader name counts only shortly after «قرأ/قراءة», and never as «X بن …»
            cues = [m.end() for m in re.finditer(r"قرأ|قراءة", stripped)]
            found = [m for m in reader_rx.finditer(stripped)
                     if not re.match(r"\s+بن\b", stripped[m.end():])
                     and any(0 <= m.start() - c <= 80 for c in cues)]
            names = []
            for m in found:
                if m.group() not in names:
                    names.append(m.group())
            if names:
                first = found[0]
                oa = mapping[first.start()] + span["start"]
                ob = mapping[first.end() - 1] + 1 + span["start"]
                added.append({"family": "QIRAAT", "marker": "قرّاء: " + "، ".join(names),
                              "start": oa, "end": ob, "span_id": sid, "via": "profile"})
                signals.append("READER_NAMES")
        if any(p in stripped for p in lex["paraphrase_phrases"]):
            signals.append("AUTHOR_PARAPHRASE")
        if any(p in stripped for p in lex["opinion_list_phrases"]):
            signals.append("OPINION_EVIDENCE_LIST")

        seen = {(h["family"], h["start"], h["end"], h.get("marker")) for h in keep}
        for h in added:
            key = (h["family"], h["start"], h["end"], h.get("marker"))
            if key not in seen:
                keep.append(h)
                seen.add(key)
                totals["added"] += 1
        totals["suppressed"] += len(suppressed)
        block["markers"] = keep
        if suppressed:
            block["suppressed"] = suppressed
        if signals:
            block["profile_signals"] = signals

    counts: dict[str, int] = {}
    for b in out.get("spans") or []:
        for h in b.get("markers") or []:
            counts[h["family"]] = counts.get(h["family"], 0) + 1
    out["family_counts"] = counts
    out["profile"] = {"tafsir": profile["tafsir"], "version": profile["version"],
                      "status": profile.get("status"), **totals}
    return out


# ------------------------------------------------------------------ packets

def build_variant_packet(window: dict, markers: dict, profile: dict,
                         examples: list[dict] | None = None) -> tuple[dict, dict]:
    """(profile markers, profile packet) for one window; pure, no I/O."""
    pm = apply_profile(window, markers, profile)
    packet = v2_packets.build_packet(window, pm, tafsir_name=profile["name_ar"])
    signals = {b["span_id"]: b.get("profile_signals") or [] for b in pm.get("spans") or []}
    for s in packet["spans"]:
        if signals.get(s["id"]):
            s["profile_signals"] = signals[s["id"]]
    packet["variant"] = VARIANT
    packet["profile"] = {"tafsir": profile["tafsir"], "version": profile["version"],
                         "status": profile.get("status")}
    packet["profile_card_ar"] = card_text_ar(profile)
    packet["profile_signals_ar"] = SIGNALS_AR
    if examples:
        packet["teaching_examples"] = examples
    return pm, packet


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    if path.is_file() and path.read_bytes() == data:
        return  # unchanged: keep mtime so freshness checks stay stable
    path.write_bytes(data)


def ensure_variant_packet(base: Path, window_id: str, tafsir: str | None = None,
                          variant: str = VARIANT) -> Path:
    """Build (or refresh) <base>/packets_<variant>/<window>.json deterministically."""
    check_variant(variant)
    base = Path(base)
    profile = load_profile(profile_key_for(base, tafsir))
    window = read_json(base / "windows" / f"{window_id}.json")
    markers = read_json(base / "markers" / f"{window_id}.json")
    import gold_bank  # local import: gold bank depends on this module's helpers
    examples = gold_bank.examples_for_window(base, window, markers)
    pm, packet = build_variant_packet(window, markers, profile, examples)
    _write_json(variant_dir(base, "markers", variant) / f"{window_id}.json", pm)
    out = variant_dir(base, "packets", variant) / f"{window_id}.json"
    _write_json(out, packet)
    return out


def build_all(base: Path, tafsir: str | None = None) -> dict:
    base = Path(base)
    summary = {"windows": 0, "suppressed": 0, "added": 0}
    for path in sorted((base / "windows").glob("*.json")):
        out = ensure_variant_packet(base, path.stem, tafsir)
        pm = read_json(variant_dir(base, "markers", VARIANT) / out.name)
        summary["windows"] += 1
        summary["suppressed"] += pm["profile"]["suppressed"]
        summary["added"] += pm["profile"]["added"]
    return summary


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build profile-variant markers and packets (arm B).")
    p.add_argument("--base", required=True, help="e.g. data/nur/al_tabari")
    p.add_argument("--tafsir", default=None, help="profile key (default: base dir name)")
    p.add_argument("--window", default=None, help="one window id (default: all)")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    base = resolve_base(args.base)
    if args.window:
        out = ensure_variant_packet(base, args.window, args.tafsir)
        print(f"wrote {out}")
        return 0
    s = build_all(base, args.tafsir)
    print(f"profile variant: windows={s['windows']} suppressed={s['suppressed']} added={s['added']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
