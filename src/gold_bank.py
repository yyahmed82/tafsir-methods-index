"""Teaching examples from specialist reviews (the agents' learning loop).

The console writes ``<base>/gold/examples.json`` from decisions a reviewer marked
«علّم الوكلاء بهذا». Each example stores references only (window id, span ids,
labels, a closed error type) — never text. Text is read back from the pinned
window when a profile packet is built, so examples cannot drift from the source.

Nothing here approves anything: an example records a human decision that
already exists in the console.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from textcore import read_json

BANK_NAME = "examples.json"
MAX_EXAMPLES = 4
MAX_PER_FAMILY = 2
MAX_EXAMPLE_CHARS = 700

METHODS = ("M_QURAN", "M_SUNNAH", "M_SAHABA", "M_TABIIN", "M_LUGHA", "M_QIRAAT",
           "M_NUZUL", "M_SIRA", "M_ISRAILIYYAT", "M_RAY")

# Closed list shown to reviewers; the Arabic label is what agents read.
ERROR_TYPES_AR = {
    "verse_in_report": "آية داخل حديث أو أثر — ليست قرآنًا بالقرآن",
    "target_verse": "الآية المفسَّرة نفسها — ليست قرآنًا بالقرآن",
    "narrator_not_speaker": "الاسم ناقل في الإسناد لا قائل",
    "isnad_not_sunnah": "إسناد بلا متن نبوي — ليس سنة",
    "takhrij_not_method": "تخريج أو عزو أو حكم حديثي — لا منهج",
    "editor_note": "حاشية المحقق ليست كلام المفسر",
    "quoted_not_author": "رأي منقول عن غيره — ليس رأي المفسر",
    "report_not_author": "كلام داخل رواية (مثل «قلت») — ليس رأي المفسر",
    "not_nuzul": "خلفية تاريخية — ليست سبب نزول",
    "israiliyyat_wrong": "إسرائيليات: الوسم خطأ أو فات",
    "recitation_not_qiraat": "تلاوة أو اختلاف نسخة — ليست قراءة",
    "paraphrase_not_lugha": "شرح إجمالي — ليس منهجًا لغويًا",
    "wrong_method": "المنهج خطأ (غير ما سبق)",
    "wrong_bounds": "حدود الحركة خاطئة",
    "weak_evidence": "الشاهد لا يدعم الوسم",
    "other": "سبب آخر",
}

METHOD_FAMILY = {
    "M_QURAN": "QURAN", "M_SUNNAH": "SUNNAH", "M_SAHABA": "ATTRIBUTION",
    "M_TABIIN": "ATTRIBUTION", "M_LUGHA": "LUGHA_QIRAAT", "M_QIRAAT": "LUGHA_QIRAAT",
    "M_NUZUL": "AKHBAR", "M_SIRA": "AKHBAR", "M_ISRAILIYYAT": "AKHBAR", "M_RAY": "RAY",
}
MARKER_FAMILY = {
    "QURAN": ("QURAN",), "HADITH": ("SUNNAH", "ATTRIBUTION"), "ISNAD": ("ATTRIBUTION", "SUNNAH"),
    "SAHABA": ("ATTRIBUTION",), "TABIIN": ("ATTRIBUTION",), "LUGHA": ("LUGHA_QIRAAT",),
    "QIRAAT": ("LUGHA_QIRAAT",), "NUZUL": ("AKHBAR",), "SIRA": ("AKHBAR",),
    "ISRAILIYYAT": ("AKHBAR",), "RAY": ("RAY",),
}


def family_of(primary: str | None) -> str:
    return METHOD_FAMILY.get(primary or "", "NONE")


def bank_path(base: Path) -> Path:
    return Path(base) / "gold" / BANK_NAME


def load_bank(base: Path) -> list[dict]:
    p = bank_path(base)
    if not p.is_file():
        return []
    data = read_json(p)
    return [e for e in data.get("examples") or [] if isinstance(e, dict)]


def make_example(*, window: str, ayah: str, span_ids: list[str], decision: str,
                 proposed_primary: str | None, correct_primary: str | None,
                 error_type: str | None, decided_at: float, decision_id: int) -> dict:
    if decision not in ("approve", "needs_edit", "reject"):
        raise ValueError(f"bad decision {decision!r}")
    if error_type and error_type not in ERROR_TYPES_AR:
        raise ValueError(f"bad error_type {error_type!r}")
    for m in (proposed_primary, correct_primary):
        if m and m not in METHODS:
            raise ValueError(f"bad method {m!r}")
    if decision == "approve":
        correct_primary = proposed_primary
        error_type = None
    return {
        "id": decision_id, "window": window, "ayah": ayah, "span_ids": list(span_ids),
        "decision": decision, "proposed_primary": proposed_primary,
        "correct_primary": correct_primary, "error_type": error_type,
        "family": family_of(correct_primary or proposed_primary), "decided_at": decided_at,
    }


def write_bank(base: Path, tafsir: str, examples: list[dict]) -> Path:
    p = bank_path(base)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {"kind": "mirqah-teaching-examples", "tafsir": tafsir,
               "updated_at": time.time(), "count": len(examples),
               "note_ar": "مراجع فقط (نافذة، أجزاء، وسوم، سبب مغلق) — النص يُقرأ من المصدر المثبّت",
               "examples": sorted(examples, key=lambda e: e["id"])}
    p.write_bytes(json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8") + b"\n")
    return p


def _ayah_of(window_id: str) -> str:
    parts = window_id.split("_")
    return "_".join(parts[:2])


def _example_text(base: Path, ex: dict) -> str | None:
    wp = Path(base) / "windows" / f"{ex['window']}.json"
    if not wp.is_file():
        return None
    spans = {s["id"]: s["text"] for s in read_json(wp).get("spans") or []}
    if not ex["span_ids"] or any(sid not in spans for sid in ex["span_ids"]):
        return None
    text = "".join(spans[sid] for sid in ex["span_ids"]).strip()
    if not text or len(text) > MAX_EXAMPLE_CHARS:
        return None
    return text


def examples_for_window(base: Path, window: dict, markers: dict,
                        max_n: int = MAX_EXAMPLES) -> list[dict]:
    """Reviewed examples relevant to this window's marker families.

    Never uses the same ayah (no leakage into the window being classified).
    Corrections come before approvals; at most MAX_PER_FAMILY per family.
    """
    bank = load_bank(base)
    if not bank:
        return []
    wanted: list[str] = []
    for fam, n in sorted((markers.get("family_counts") or {}).items(), key=lambda kv: -kv[1]):
        for f in MARKER_FAMILY.get(fam, ()):
            if n and f not in wanted:
                wanted.append(f)
    this_ayah = _ayah_of(window["window_id"])
    pool = [e for e in bank if _ayah_of(e["window"]) != this_ayah]
    pool.sort(key=lambda e: (e["decision"] == "approve", -e.get("decided_at", 0)))
    picked: list[dict] = []
    per_family: dict[str, int] = {}
    for fam in wanted + ["NONE"]:
        for e in pool:
            if len(picked) >= max_n:
                break
            if e["family"] != fam or per_family.get(fam, 0) >= MAX_PER_FAMILY:
                continue
            text = _example_text(base, e)
            if text is None:
                continue
            per_family[fam] = per_family.get(fam, 0) + 1
            picked.append({
                "ref": f"{e['window']}:{','.join(e['span_ids'])}",
                "decision": e["decision"], "family": e["family"],
                "proposed_primary": e["proposed_primary"],
                "correct_primary": e["correct_primary"],
                "error_ar": ERROR_TYPES_AR.get(e.get("error_type") or "", None),
                "text": text,
            })
    return picked


def examples_prompt_ar(examples: list[dict]) -> list[str]:
    lines = ["## أمثلة راجعها المختص في هذا التفسير (للفهم فقط — لا تُعِد معرّفاتها ولا نصها)"]
    for i, e in enumerate(examples, 1):
        if e["decision"] == "approve":
            verdict = f"اعتمده المختص: {e['correct_primary'] or 'بلا منهج'}"
        else:
            verdict = (f"اقترح الوكيل {e['proposed_primary'] or 'بلا منهج'}؛ "
                       f"صوّبه المختص إلى {e['correct_primary'] or 'بلا منهج'}")
            if e.get("error_ar"):
                verdict += f" — السبب: {e['error_ar']}"
        lines.append(f"مثال {i}: «{e['text']}» ← {verdict}")
    return lines
