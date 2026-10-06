"""Method specialists (arm B): strict context, closed replies, block-only power."""

from __future__ import annotations

import io
import json
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

import classify_api  # noqa: E402
import committee_chair  # noqa: E402
import run_window  # noqa: E402
import specialist  # noqa: E402
import v2_profiles  # noqa: E402
import v2_verify  # noqa: E402
from textcore import read_json  # noqa: E402

V2 = ROOT / "data" / "v2"


def _reply(obj) -> callable:
    calls = []

    def post(url: str, headers: dict, body: bytes) -> bytes:
        calls.append(json.loads(body))
        content = obj(len(calls)) if callable(obj) else obj
        return json.dumps({"choices": [{"message": {"content": json.dumps(content, ensure_ascii=False)}}]}).encode()
    post.calls = calls
    return post


class TestPrompt(unittest.TestCase):
    def test_only_its_family_and_move(self) -> None:
        prof = v2_profiles.load_profile("al_tabari")
        window = {"window_id": "24_9", "spans": [
            {"id": "s001", "start": 0, "end": 5, "text": "أول."},
            {"id": "s002", "start": 5, "end": 30, "text": " وأولى الأقوال في ذلك بالصواب"},
            {"id": "s003", "start": 30, "end": 40, "text": " نص آخر."}]}
        pm = {"spans": [{"span_id": "s002", "markers": [], "profile_signals": ["AUTHOR_VERDICT"]}]}
        move = {"move_id": "m01", "span_ids": ["s002"], "primary": "M_RAY", "certainty": "strong",
                "evidence_span_ids": ["s002"]}
        msgs, shown = specialist.build_prompt(family="RAY", profile=prof, move=move, window=window,
                                              profile_markers=pm, examples=[])
        user = msgs[1]["content"]
        self.assertEqual(shown, ["s001", "s002"])        # previous span for context, not s003
        self.assertIn("s002: [profile:AUTHOR_VERDICT]", user)
        self.assertNotIn("s003", user)
        self.assertIn("الرأي والاستنباط", user)
        for r in prof["families"]["RAY"]["rules_ar"]:
            self.assertIn(r, user)
        for r in prof["families"]["QURAN"]["rules_ar"]:
            self.assertNotIn(r, user)                       # no other family's rules
        self.assertNotIn('"M_QURAN"', user)                 # no other method definitions
        self.assertEqual(specialist.family_for("M_TABIIN"), "ATTRIBUTION")
        self.assertIsNone(specialist.family_for(None))


class TestReplies(unittest.TestCase):
    def setUp(self) -> None:
        self.prof = v2_profiles.load_profile("ibn_kathir")
        self.window = {"window_id": "24_9", "spans": [{"id": "s001", "start": 0, "end": 4, "text": "نص."}]}
        self.move = {"move_id": "m01", "span_ids": ["s001"], "primary": "M_QURAN",
                     "certainty": "explicit", "evidence_span_ids": ["s001"]}

    def _check(self, post):
        return specialist.check_move(family="QURAN", profile=self.prof, move=self.move,
                                     window=self.window, profile_markers={"spans": []}, examples=[],
                                     model="qwen2.5:14b", base_url="http://x/v1", api_key="k",
                                     http_post=post)

    def test_valid_confirm(self) -> None:
        post = _reply({"move_id": "m01", "verdict": "confirm", "primary": "M_QURAN",
                       "certainty": "strong", "evidence_span_ids": ["s001"], "reason_code": "ok",
                       "note_ar": "آية أخرى تبين المعنى"})
        v = self._check(post)
        self.assertEqual((v["verdict"], v["primary"], v["reason_code"]), ("confirm", "M_QURAN", "ok"))
        self.assertEqual(post.calls[0]["temperature"], 0)

    def test_out_of_family_retried_then_invalid(self) -> None:
        post = _reply({"move_id": "m01", "verdict": "reframe", "primary": "M_SUNNAH",
                       "evidence_span_ids": ["s001"], "reason_code": "verse_in_report"})
        v = self._check(post)
        self.assertEqual(v["verdict"], "invalid")
        self.assertEqual(len(post.calls), 2)
        self.assertIn("تصحيح مطلوب", post.calls[1]["messages"][-1]["content"])

    def test_engine_down_fails_the_step(self) -> None:
        def down(url, headers, body):
            raise classify_api.ClassifyError("network error: refused")
        with self.assertRaises(classify_api.ClassifyError):
            self._check(down)

    def test_unknown_span_refused(self) -> None:
        v = self._check(_reply({"move_id": "m01", "verdict": "reject", "primary": None,
                                "evidence_span_ids": ["s999"], "reason_code": "target_verse"}))
        self.assertEqual(v["verdict"], "invalid")


@unittest.skipUnless((V2 / "packets" / "17_105.json").is_file(), "no v2 fixture")
class TestChairBlockOnly(unittest.TestCase):
    def _arm_b(self, base: Path) -> list[str]:
        for d in ("windows", "markers", "packets"):
            (base / d).mkdir(parents=True)
            shutil.copy(V2 / d / "17_105.json", base / d / "17_105.json")
        pkt = v2_profiles.ensure_variant_packet(base, "17_105", "ibn_kathir")
        moves = {"window": "17_105", "moves": [{
            "move_id": "m01", "span_ids": ["s002", "s003", "s004"], "primary": "M_QURAN",
            "secondary": [], "content_tags": ["C_TAFSIR"], "certainty": "explicit",
            "evidence_span_ids": ["s002", "s003"], "author_verdict_span_ids": [],
            "references": {"verses": [], "hadith": [], "persons": []},
            "alternatives": [], "rationale_ar": "اختبار"}]}
        anns = []
        for model in ("qwen2.5:14b", "gemma3:12b"):
            ann = v2_profiles.variant_annotator(classify_api.model_slug(model), "profile")
            res = classify_api.classify(pkt, model, "http://x/v1", base / "moves", api_key="k",
                                        http_post=_reply(moves), annotator=ann)
            with redirect_stdout(io.StringIO()):
                run_window.run_verifier(base, ann, "17_105", res["payload"], variant="profile")
            anns.append(ann)
        v2_verify.configure(v2_verify.DEFAULT_BASE)
        return anns

    def _run(self, verdict: dict, stale: bool = False, missing: bool = False) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "ibn_kathir"
            anns = self._arm_b(base)
            out = specialist.run_window(base, "17_105", tafsir="ibn_kathir", classifier="qwen2_5_14b",
                                        variant="profile", model="qwen2.5:14b",
                                        base_url="http://x/v1", api_key="k",
                                        http_post=_reply({"move_id": "m01", **verdict}))
            self.assertTrue((base / "specialist_profile" / "17_105.json").is_file())
            self.assertEqual(out["summary"]["moves"], 1)
            if missing:
                (base / "specialist_profile" / "17_105.json").unlink()
            if stale:
                p = base / "specialist_profile" / "17_105.json"
                d = read_json(p)
                d["packet_sha256"] = "0" * 64
                p.write_text(json.dumps(d), encoding="utf-8")
            c_pay, v_pay = committee_chair.evaluate_window(base=base, proposer=anns[0],
                                                           reviewer=anns[1], window_id="17_105",
                                                           variant="profile")
            return c_pay["moves"][0], v_pay["moves"][0]

    def test_confirm_keeps_candidate(self) -> None:
        c, v = self._run({"verdict": "confirm", "primary": "M_QURAN", "evidence_span_ids": ["s002"],
                          "reason_code": "ok"})
        self.assertEqual(c["committee_route"], "auto_candidate")
        self.assertEqual(v["method_specialist"]["verdict"], "confirm")

    def test_reject_blocks_candidate(self) -> None:
        c, v = self._run({"verdict": "reject", "primary": None, "evidence_span_ids": ["s002"],
                          "reason_code": "target_verse", "note_ar": "الآية المفسرة نفسها"})
        self.assertEqual(c["committee_route"], "specialist")
        self.assertEqual(c["abstention_reasons"], ["specialist_block"])
        self.assertEqual(v["route"], "specialist")
        self.assertEqual(v["committee_reason_code"], "specialist_block")

    def test_stale_specialist_file_blocks_candidate(self) -> None:
        # audit C-01: a verdict made for another packet is not a verdict; no auto candidate
        c, v = self._run({"verdict": "confirm", "primary": "M_QURAN", "evidence_span_ids": ["s002"],
                          "reason_code": "ok"}, stale=True)
        self.assertEqual(c["committee_route"], "specialist")
        self.assertEqual(c["abstention_reasons"], ["specialist_missing"])
        self.assertEqual(v["committee_reason_code"], "specialist_missing")
        self.assertNotIn("method_specialist", c)

    def test_missing_specialist_file_blocks_candidate(self) -> None:
        # the specialist step failed or never ran: arm B must not leave a candidate
        c, v = self._run({"verdict": "confirm", "primary": "M_QURAN", "evidence_span_ids": ["s002"],
                          "reason_code": "ok"}, missing=True)
        self.assertEqual(c["committee_route"], "specialist")
        self.assertEqual(c["abstention_reasons"], ["specialist_missing"])
        self.assertEqual(v["route"], "specialist")


if __name__ == "__main__":
    unittest.main()
