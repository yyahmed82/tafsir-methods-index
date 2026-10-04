"""Method specialists with strict context (arm B): one narrow check per move.

After the classifier of the profile arm has proposed and the deterministic checker
has verified its moves, each move whose primary method belongs to one of six
families goes to that family's specialist. The specialist sees ONLY:

  - its own methods (closed list) and their operational definitions;
  - this mufassir's rules and traps for that family (method/profiles/<tafsir>.json);
  - up to three reviewed examples of that family from the teaching bank;
  - the move's spans, the span just before it, and their deterministic signals.

It never sees other methods' rules, another tafsir's profile, other moves, or the
verifier's output. It answers confirm / reject / reframe / abstain with span ids
and a closed reason code. Its power is one-sided: the committee chair may only
move a candidate to the specialist queue because of it — never approve.

Writes <base>/specialist_<variant>/<window>.json. Never edits source text.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

import classify_api  # noqa: E402
import gold_bank  # noqa: E402
import v2_packets  # noqa: E402
import v2_profiles  # noqa: E402
from textcore import read_json  # noqa: E402

FAMILIES = {
    "QURAN": ("M_QURAN",),
    "SUNNAH": ("M_SUNNAH",),
    "ATTRIBUTION": ("M_SAHABA", "M_TABIIN"),
    "LUGHA_QIRAAT": ("M_LUGHA", "M_QIRAAT"),
    "AKHBAR": ("M_NUZUL", "M_SIRA", "M_ISRAILIYYAT"),
    "RAY": ("M_RAY",),
}
FAMILY_AR = {
    "QURAN": "القرآن بالقرآن", "SUNNAH": "السنة والتخريج", "ATTRIBUTION": "الإسناد والأقوال",
    "LUGHA_QIRAAT": "اللغة والقراءات", "AKHBAR": "الأخبار (النزول والسيرة والإسرائيليات)",
    "RAY": "الرأي والاستنباط",
}
QUESTION_AR = {
    "QURAN": "هل الآية الأخرى تبيّن معنى الآية المفسَّرة فعلًا، أم هي الآية المفسَّرة نفسها أو آية داخل خبر؟",
    "SUNNAH": "هل في الأجزاء متن نبوي يبيّن الآية، أم هو إسناد أو عزو أو حكم حديثي فقط؟",
    "ATTRIBUTION": "من القائل الذي يفسّر، ومن مجرد ناقل في الإسناد؟ وهل القائل صحابي أم تابعي؟",
    "LUGHA_QIRAAT": "هل هذا شرح لفظ أو استعمال عربي أو قراءة تؤثر في المعنى، أم شرح إجمالي أو تلاوة؟",
    "AKHBAR": "هل يربط الخبر حدثًا بنزول الآية، أو يشرحها بواقعة من السيرة، أو يعزو لأهل الكتاب؟",
    "RAY": "هل هذا كلام المفسر نفسه وحكمه أو ترجيحه أو استنباطه، أم نقل لكلام غيره أو كلام داخل رواية؟",
}
VERDICTS = ("confirm", "reject", "reframe", "abstain")
REASONS = ("ok",) + tuple(gold_bank.ERROR_TYPES_AR)
MAX_EXAMPLES = 3
ANNOTATOR = "method_specialist"


def family_for(primary: str | None) -> str | None:
    for fam, methods in FAMILIES.items():
        if primary in methods:
            return fam
    return None


def _span_lines(window: dict, ids: list[str], signals: dict[str, list[str]]) -> tuple[list[str], list[str]]:
    order = [s["id"] for s in window.get("spans") or []]
    text = {s["id"]: s["text"] for s in window.get("spans") or []}
    wanted = [sid for sid in ids if sid in text]
    if wanted:
        first = order.index(wanted[0])
        if first > 0 and order[first - 1] not in wanted:
            wanted = [order[first - 1]] + wanted
    shown = sorted(set(wanted), key=order.index)
    lines = []
    for sid in shown:
        sig = signals.get(sid) or []
        note = f" [profile:{','.join(sig)}]" if sig else ""
        lines.append(f"{sid}:{note} {text[sid]}")
    return shown, lines


def build_prompt(*, family: str, profile: dict, move: dict, window: dict,
                 profile_markers: dict, examples: list[dict]) -> tuple[list[dict], list[str]]:
    """Messages for one move, and the span ids the specialist may cite."""
    allowed = FAMILIES[family]
    defs = [d for d in v2_packets._definitions_ar(profile["name_ar"]) if d["id"] in allowed]
    fam_prof = profile["families"].get(family) or {}
    signals = {b["span_id"]: b.get("profile_signals") or []
               for b in profile_markers.get("spans") or []}
    ids = list(dict.fromkeys((move.get("span_ids") or []) + (move.get("evidence_span_ids") or [])))
    shown, span_lines = _span_lines(window, ids, signals)
    lines = [
        f"أنت أخصائي «{FAMILY_AR[family]}» في تفسير {profile['name_ar']} فقط.",
        f"سؤالك الوحيد: {QUESTION_AR[family]}",
        f"الوسوم المسموحة لك: {', '.join(allowed)}. إن لم يكن الصواب منها فأجب abstain مع "
        "primary = null ولا تقترح منهجًا من خارج قائمتك.",
        "لا تعتمد شيئًا: حكمك يُحال إلى المختص البشري.",
        "",
        "## تعريف مناهجك",
        json.dumps(defs, ensure_ascii=False, indent=1),
        "",
        f"## قواعد {profile['name_ar']} في مناهجك (من ملف المنهج {profile['version']})",
    ]
    lines += [f"- {r}" for r in fam_prof.get("rules_ar") or []]
    if fam_prof.get("traps_ar"):
        lines.append("فخاخ معروفة: " + "؛ ".join(fam_prof["traps_ar"]))
    if examples:
        lines.append("")
        lines.extend(gold_bank.examples_prompt_ar(examples))
    lines += [
        "",
        "## الحركة المعروضة عليك",
        f"move_id: {move.get('move_id')} · اقتراح المصنّف: {move.get('primary')} · "
        f"اليقين: {move.get('certainty')} · الشاهد: {', '.join(move.get('evidence_span_ids') or [])}",
        "الأجزاء (أولها الجزء السابق للسياق):",
        *span_lines,
        "",
        "## أعد JSON فقط",
        json.dumps({"move_id": move.get("move_id"), "verdict": "confirm|reject|reframe|abstain",
                    "primary": "|".join(allowed) + "|null", "certainty":
                    "explicit|strong|weak|insufficient", "evidence_span_ids": [shown[0] if shown else "s001"],
                    "reason_code": "|".join(REASONS[:6]) + "|…", "note_ar": "≤ 25 كلمة، بلا اقتباس طويل"},
                   ensure_ascii=False),
        f"reason_code من القائمة المغلقة: {', '.join(REASONS)}. confirm يعني reason_code=ok.",
        "reframe = المنهج صحيح العائلة لكن غير المقترح (مثل M_SAHABA بدل M_TABIIN) أو الشاهد غير المذكور.",
    ]
    system = ("You are a narrow tafsir-method specialist. Reply with one JSON object only. "
              "Cite only span ids shown to you; never quote long source text.")
    return ([{"role": "system", "content": system}, {"role": "user", "content": "\n".join(lines)}],
            shown)


def validate_reply(payload: dict, *, move_id: str, family: str, shown: list[str]) -> list[str]:
    errors = []
    if payload.get("verdict") not in VERDICTS:
        errors.append(f"verdict must be one of {VERDICTS}")
    prim = payload.get("primary")
    if prim not in FAMILIES[family] and prim is not None:
        errors.append(f"primary must be one of {FAMILIES[family]} or null")
    if payload.get("reason_code") not in REASONS:
        errors.append("reason_code must come from the closed list")
    ev = payload.get("evidence_span_ids") or []
    if not isinstance(ev, list) or any(sid not in shown for sid in ev):
        errors.append(f"evidence_span_ids must be among {shown}")
    if payload.get("verdict") == "confirm" and prim is None:
        errors.append("confirm needs a primary")
    return errors


def _clean(payload: dict, move_id: str, family: str) -> dict:
    note = str(payload.get("note_ar") or "")
    words = note.split()
    return {"move_id": move_id, "family": family, "verdict": payload["verdict"],
            "primary": payload.get("primary"),
            "certainty": payload.get("certainty") if payload.get("certainty") in (
                "explicit", "strong", "weak", "insufficient") else None,
            "evidence_span_ids": list(payload.get("evidence_span_ids") or []),
            "reason_code": payload["reason_code"],
            "note_ar": " ".join(words[:25])}


def check_move(*, family: str, profile: dict, move: dict, window: dict, profile_markers: dict,
               examples: list[dict], model: str, base_url: str, api_key: str,
               http_post=None) -> dict:
    messages, shown = build_prompt(family=family, profile=profile, move=move, window=window,
                                   profile_markers=profile_markers, examples=examples)
    error = None
    transport_failures = 0
    for attempt in range(2):
        if error:
            messages = messages + [{"role": "user", "content": "تصحيح مطلوب: " + error +
                                    "\nأعد JSON صالحًا فقط."}]
        try:
            content = classify_api.call_chat(base_url=base_url, api_key=api_key, model=model,
                                             messages=messages, http_post=http_post)
        except (classify_api.ClassifyError, OSError) as e:
            # no reply at all (engine down, timeout): fail the step so it can be retried
            transport_failures += 1
            error = str(e)
            if transport_failures == 2:
                raise
            continue
        try:
            payload = classify_api.extract_json_object(content)
        except classify_api.ClassifyError as e:
            error = str(e)
            continue
        errs = validate_reply(payload, move_id=move.get("move_id"), family=family, shown=shown)
        if not errs:
            return _clean(payload, move.get("move_id"), family)
        error = "; ".join(errs)
    # a reply we cannot trust never confirms anything
    return {"move_id": move.get("move_id"), "family": family, "verdict": "invalid",
            "primary": None, "certainty": None, "evidence_span_ids": [],
            "reason_code": None, "note_ar": "", "error": (error or "")[:300]}


def run_window(base: Path, window_id: str, *, tafsir: str | None, classifier: str,
               variant: str, model: str, base_url: str, api_key: str, http_post=None) -> dict:
    base = Path(base)
    profile = v2_profiles.load_profile(v2_profiles.profile_key_for(base, tafsir))
    proposer = v2_profiles.variant_annotator(classifier, variant)
    verified = read_json(base / "verified" / proposer / f"{window_id}.json")
    window = read_json(base / "windows" / f"{window_id}.json")
    markers = read_json(base / "markers" / f"{window_id}.json")
    pm = v2_profiles.apply_profile(window, markers, profile)
    bank = gold_bank.examples_for_window(base, window, markers, max_n=12)
    verdicts = []
    for mv in verified.get("moves") or []:
        fam = family_for(mv.get("primary"))
        if fam is None:
            continue
        ex = [e for e in bank if e["family"] == fam][:MAX_EXAMPLES]
        verdicts.append(check_move(family=fam, profile=profile, move=mv, window=window,
                                   profile_markers=pm, examples=ex, model=model,
                                   base_url=base_url, api_key=api_key, http_post=http_post))
    summary = {v: sum(1 for x in verdicts if x["verdict"] == v) for v in VERDICTS + ("invalid",)}
    out = {"window_id": window_id, "tafsir": profile["tafsir"], "variant": variant,
           "annotator": v2_profiles.variant_annotator(ANNOTATOR, variant), "model": model,
           "proposer": proposer, "packet_sha256": verified.get("packet_sha256"),
           "profile_version": profile["version"], "verdicts": verdicts,
           "summary": {"moves": len(verdicts), **summary},
           "note_ar": "حكم الأخصائي الآلي يمنع ولا يعتمد؛ القرار للمختص البشري."}
    path = v2_profiles.variant_dir(base, "specialist", variant) / f"{window_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps(out, ensure_ascii=False, indent=2).encode("utf-8") + b"\n")
    return out


def load_for(base: Path, window_id: str, variant: str | None) -> dict | None:
    if not variant:
        return None
    p = v2_profiles.variant_dir(Path(base), "specialist", variant) / f"{window_id}.json"
    return read_json(p) if p.is_file() else None


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Method specialists (strict context) for one window.")
    p.add_argument("--base", required=True)
    p.add_argument("--tafsir", default=None)
    p.add_argument("--window", required=True)
    p.add_argument("--classifier", required=True, help="classifier annotator slug, e.g. qwen2_5_14b")
    p.add_argument("--variant", default=v2_profiles.VARIANT, choices=v2_profiles.VARIANTS)
    p.add_argument("--model", default=None)
    p.add_argument("--base-url", default=None)
    args = p.parse_args(argv)
    model, base_url = classify_api.resolve_env(model=args.model, base_url=args.base_url)
    if not model or not base_url:
        print("set --model/--base-url or LLM_MODEL/LLM_BASE_URL", file=sys.stderr)
        return 2
    base = Path(args.base)
    if not base.is_absolute():
        base = (ROOT / base).resolve() if (ROOT / base).exists() else base.resolve()
    try:
        out = run_window(base, args.window, tafsir=args.tafsir, classifier=args.classifier,
                         variant=args.variant, model=model, base_url=base_url,
                         api_key=os.environ.get("LLM_API_KEY", ""))
    except (OSError, ValueError, KeyError, classify_api.ClassifyError) as e:
        print(json.dumps({"status": "failed", "reason_code": "RUN_FAILURE", "error": str(e)},
                         ensure_ascii=False))
        return 1
    s = out["summary"]
    print(f"specialist: moves={s['moves']} confirm={s['confirm']} reject={s['reject']} "
          f"reframe={s['reframe']} abstain={s['abstain']} invalid={s['invalid']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
