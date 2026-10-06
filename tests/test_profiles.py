"""Arm B (methodology profiles) and the teaching-examples loop.

Covers:
- the four profiles load and validate;
- baseline parity: rebuilding a baseline packet from windows + markers gives the
  stored packet byte-for-byte (arm A is untouched by this layer);
- deterministic lexicon effects on synthetic spans (heading quote, isnad words,
  «قلت» in a report vs the author's own «قلت:», added verdict formulas, readers);
- prompt sections appear only in profile packets;
- full chain on a temp base: variant packet → classify (annotator __profile) →
  verify against markers_profile → committee_profile;
- teaching examples: same-ayah exclusion, corrections first, text from source.
"""

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
import gold_bank  # noqa: E402
import run_window  # noqa: E402
import v2_packets  # noqa: E402
import v2_profiles  # noqa: E402
import v2_verify  # noqa: E402
from textcore import read_json  # noqa: E402

TAFSIRS = {"al_tabari": "الطبري", "ibn_kathir": "ابن كثير",
           "al_baghawi": "البغوي", "al_saadi": "السعدي"}
NUR = ROOT / "data" / "nur"


def _window(spans: list[str], window_id: str = "24_9") -> dict:
    out, pos = [], 0
    for i, t in enumerate(spans, 1):
        out.append({"id": f"s{i:03d}", "start": pos, "end": pos + len(t), "text": t})
        pos += len(t)
    return {"window_id": window_id, "ayah": "24:9", "source_file": "x", "spans": out,
            "window_start": 0, "window_end": pos}


def _markers(window: dict, hits: dict[str, list[dict]]) -> dict:
    spans = []
    for s in window["spans"]:
        hs = []
        for h in hits.get(s["id"], []):
            idx = s["text"].find(h["find"])
            assert idx >= 0, h
            hs.append({"family": h["family"], "marker": h["marker"],
                       "start": s["start"] + idx, "end": s["start"] + idx + len(h["find"]),
                       "span_id": s["id"]})
        spans.append({"span_id": s["id"], "markers": hs})
    return {"window_id": window["window_id"], "spans": spans, "family_counts": {}}


class TestProfilesLoad(unittest.TestCase):
    def test_four_profiles_validate(self) -> None:
        for key, name in TAFSIRS.items():
            p = v2_profiles.load_profile(key)
            self.assertEqual(p["name_ar"], name)
            self.assertEqual(len(p["golden_rules_ar"]), 8, key)
            self.assertEqual(set(p["families"]),
                             {"QURAN", "SUNNAH", "ATTRIBUTION", "LUGHA_QIRAAT", "AKHBAR", "RAY"})
            self.assertIn("ملف المنهج", v2_profiles.card_text_ar(p))

    def test_variant_names(self) -> None:
        self.assertEqual(v2_profiles.variant_annotator("qwen2_5_14b", None), "qwen2_5_14b")
        self.assertEqual(v2_profiles.variant_annotator("qwen2_5_14b", "profile"),
                         "qwen2_5_14b__profile")
        self.assertEqual(v2_profiles.variant_annotator("x__profile", "profile"), "x__profile")
        self.assertEqual(v2_profiles.split_annotator("gemma3_12b__profile"),
                         ("gemma3_12b", "profile"))
        self.assertEqual(v2_profiles.variant_dir(Path("b"), "packets", "profile"),
                         Path("b/packets_profile"))
        with self.assertRaises(ValueError):
            v2_profiles.variant_dir(Path("b"), "packets", "other")
        # family detection still works on suffixed names (chair refuses same family)
        self.assertEqual(committee_chair.extract_family("qwen2_5_14b__profile"), "qwen")


@unittest.skipUnless((NUR / "al_tabari" / "packets").is_dir(), "no al-Nur data")
class TestBaselineParity(unittest.TestCase):
    def test_baseline_packets_unchanged(self) -> None:
        for key, name in TAFSIRS.items():
            base = NUR / key
            for wp in sorted((base / "windows").glob("*.json"))[:3]:
                rebuilt = v2_packets.build_packet(read_json(wp), read_json(base / "markers" / wp.name),
                                                  tafsir_name=name)
                self.assertEqual(rebuilt, read_json(base / "packets" / wp.name), f"{key}/{wp.name}")


class TestLexicon(unittest.TestCase):
    def test_tabari_heading_isnad_and_report_qultu(self) -> None:
        w = _window([
            "القول في تأويل قوله تعالى:",
            " {وَالْخَامِسَةُ أَنَّ غَضَبَ اللَّهِ عَلَيْهَا}",
            "حدثنا ابن بشار، قال: ثنا عبد الرحمن، قال:",
            " قلت لعطاء: أواجب ذلك؟",
            " وأولى الأقوال في ذلك بالصواب قول من قال",
        ])
        m = _markers(w, {
            "s001": [{"family": "QURAN", "marker": "قوله تعالى", "find": "قوله تعالى"}],
            "s002": [{"family": "QURAN", "marker": "{…}", "find": "{وَالْخَامِسَةُ أَنَّ غَضَبَ اللَّهِ عَلَيْهَا}"}],
            "s003": [{"family": "HADITH", "marker": "حدثنا", "find": "حدثنا"}],
            "s004": [{"family": "RAY", "marker": "قلت", "find": "قلت"}],
        })
        pm = v2_profiles.apply_profile(w, m, v2_profiles.load_profile("al_tabari"))
        by = {b["span_id"]: b for b in pm["spans"]}
        self.assertEqual(by["s002"]["markers"], [])
        self.assertIn("TARGET_VERSE_HEADING", by["s002"]["profile_signals"])
        self.assertEqual(by["s003"]["markers"], [])
        self.assertIn("ISNAD_WORDS_ONLY", by["s003"]["profile_signals"])
        self.assertEqual(by["s004"]["markers"], [])
        self.assertIn("QULTU_IN_REPORT", by["s004"]["profile_signals"])
        ray = [h for h in by["s005"]["markers"] if h["family"] == "RAY"]
        self.assertEqual(len(ray), 1)
        self.assertEqual(ray[0]["via"], "profile")
        self.assertEqual(w["spans"][4]["text"][ray[0]["start"] - w["spans"][4]["start"]:
                                             ray[0]["end"] - w["spans"][4]["start"]],
                         "وأولى الأقوال")
        self.assertEqual(pm["family_counts"], {"RAY": 1})
        # the source markers document is not mutated
        self.assertEqual(len(m["spans"][1]["markers"]), 1)

    def test_cross_reference_with_verse_ref_is_kept(self) -> None:
        w = _window(["وقوله:", " {إِنَّ اللَّهَ غَفُورٌ}"])
        m = _markers(w, {"s002": [{"family": "QURAN", "marker": "{…}", "find": "{إِنَّ اللَّهَ غَفُورٌ}"}]})
        m["spans"][1]["markers"].append({"family": "QURAN", "marker": "verse_ref", "start": 30,
                                         "end": 40, "span_id": "s002"})
        pm = v2_profiles.apply_profile(w, m, v2_profiles.load_profile("ibn_kathir"))
        self.assertEqual(len(pm["spans"][1]["markers"]), 2)

    def test_prophet_keeps_hadith(self) -> None:
        w = _window(["حدثنا أبو كريب عن رسول الله صلى الله عليه وسلم قال:"])
        m = _markers(w, {"s001": [{"family": "HADITH", "marker": "حدثنا", "find": "حدثنا"}]})
        pm = v2_profiles.apply_profile(w, m, v2_profiles.load_profile("al_tabari"))
        self.assertEqual(len(pm["spans"][0]["markers"]), 1)

    def test_ibn_kathir_author_qultu_kept_dialogue_dropped(self) -> None:
        w = _window([
            " وحديثه أولى بالصواب.",
            "\nقلت: وهو ابن أبي المخارق ضعيف الحديث.",
            " فقال: أتحب أن تطيع الله؟",
            " قلت: نعم.",
        ])
        m = _markers(w, {"s002": [{"family": "RAY", "marker": "قلت", "find": "قلت"}],
                         "s004": [{"family": "RAY", "marker": "قلت", "find": "قلت"}]})
        pm = v2_profiles.apply_profile(w, m, v2_profiles.load_profile("ibn_kathir"))
        self.assertEqual(len(pm["spans"][1]["markers"]), 1)
        self.assertEqual(pm["spans"][3]["markers"], [])

    def test_baghawi_readers_but_not_person_named_asim(self) -> None:
        w = _window(["قرأ حمزة والكسائي وحفص: أربع بالرفع.",
                     " فقال عاصم بن عدي: يا رسول الله، أرأيت رجلا"])
        pm = v2_profiles.apply_profile(w, _markers(w, {}), v2_profiles.load_profile("al_baghawi"))
        self.assertEqual(pm["spans"][0]["markers"][0]["family"], "QIRAAT")
        self.assertIn("حمزة", pm["spans"][0]["markers"][0]["marker"])
        self.assertEqual(pm["spans"][1]["markers"], [])

    def test_saadi_istinbat_added(self) -> None:
        w = _window([" وفيها: دليل على جواز المشاركة في الطعام.", " لما أريد بها ومنها."])
        pm = v2_profiles.apply_profile(w, _markers(w, {}), v2_profiles.load_profile("al_saadi"))
        self.assertTrue(any(h["family"] == "RAY" for h in pm["spans"][0]["markers"]))
        self.assertEqual(pm["spans"][1]["markers"], [])  # «ومنها» without colon is not a list


class TestPrompt(unittest.TestCase):
    def test_profile_sections_only_in_profile_packets(self) -> None:
        w = _window(["القول في تأويل قوله تعالى:", " {وَالْخَامِسَةُ}"])
        m = _markers(w, {"s002": [{"family": "QURAN", "marker": "{…}", "find": "{وَالْخَامِسَةُ}"}]})
        base_pkt = v2_packets.build_packet(w, m, tafsir_name="الطبري")
        base_prompt = classify_api.build_user_prompt(base_pkt)
        self.assertNotIn("بطاقة منهج المفسر", base_prompt)
        self.assertNotIn("[profile:", base_prompt)
        ex = [{"ref": "24_2:s004", "decision": "needs_edit", "family": "SUNNAH",
               "proposed_primary": "M_QURAN", "correct_primary": "M_SUNNAH",
               "error_ar": gold_bank.ERROR_TYPES_AR["verse_in_report"], "text": "نص المثال"}]
        _, pkt = v2_profiles.build_variant_packet(w, m, v2_profiles.load_profile("al_tabari"), ex)
        prompt = classify_api.build_user_prompt(pkt)
        self.assertIn("بطاقة منهج المفسر", prompt)
        self.assertIn("القواعد الذهبية", prompt)
        self.assertIn("s002: [profile:TARGET_VERSE_HEADING]", prompt)
        self.assertIn("صوّبه المختص إلى M_SUNNAH", prompt)
        self.assertIn("آية داخل حديث", prompt)


@unittest.skipUnless((ROOT / "data" / "v2" / "packets" / "17_105.json").is_file(), "no v2 fixture")
class TestVariantChain(unittest.TestCase):
    def test_classify_verify_chair_profile_arm(self) -> None:
        src = ROOT / "data" / "v2"
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "ibn_kathir"
            for d in ("windows", "markers", "packets"):
                (base / d).mkdir(parents=True)
                shutil.copy(src / d / "17_105.json", base / d / "17_105.json")
            pkt_path = v2_profiles.ensure_variant_packet(base, "17_105", "ibn_kathir")
            self.assertEqual(pkt_path, base / "packets_profile" / "17_105.json")
            self.assertTrue((base / "markers_profile" / "17_105.json").is_file())
            # deterministic: rebuilding gives the same bytes
            before = pkt_path.read_bytes()
            v2_profiles.ensure_variant_packet(base, "17_105", "ibn_kathir")
            self.assertEqual(before, pkt_path.read_bytes())
            # baseline packet untouched
            self.assertEqual((base / "packets" / "17_105.json").read_bytes(),
                             (src / "packets" / "17_105.json").read_bytes())

            moves = {"window": "17_105", "moves": [{
                "move_id": "m01", "span_ids": ["s002", "s003", "s004"], "primary": "M_QURAN",
                "secondary": [], "content_tags": ["C_TAFSIR"], "certainty": "explicit",
                "evidence_span_ids": ["s002", "s003"], "author_verdict_span_ids": [],
                "references": {"verses": [], "hadith": [], "persons": []},
                "alternatives": [], "rationale_ar": "اختبار"}]}

            def fake(url: str, headers: dict, body: bytes) -> bytes:
                return json.dumps({"choices": [{"message": {
                    "content": json.dumps(moves, ensure_ascii=False)}}]}).encode("utf-8")

            anns = []
            for model in ("qwen2.5:14b", "gemma3:12b"):
                ann = v2_profiles.variant_annotator(classify_api.model_slug(model), "profile")
                res = classify_api.classify(pkt_path, model, "http://x/v1", base / "moves",
                                            api_key="ollama", http_post=fake, annotator=ann)
                self.assertEqual(res["path"].parent.name, ann)
                with redirect_stdout(io.StringIO()):
                    run_window.run_verifier(base, ann, "17_105", res["payload"], variant="profile")
                anns.append(ann)
            try:
                v_out = read_json(base / "verified" / anns[0] / "17_105.json")
            finally:
                v2_verify.configure(v2_verify.DEFAULT_BASE)
            self.assertIsNone(next(
                (m for m in v_out["moves"] if "PACKET_HASH_MISMATCH" in json.dumps(m)), None))
            c_pay, v_pay = committee_chair.evaluate_window(
                base=base, proposer=anns[0], reviewer=anns[1], window_id="17_105",
                variant="profile")
            self.assertTrue((base / "committee_profile" / "17_105.json").is_file())
            self.assertTrue((base / "verified" / "committee__profile" / "17_105.json").is_file())
            self.assertFalse((base / "committee").exists())
            self.assertEqual(v_pay["annotator"], "committee__profile")

    def test_verify_all_skips_the_other_arm(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "moves" / "qwen2_5_14b__profile").mkdir(parents=True)
            (base / "moves" / "qwen2_5_14b__profile" / "17_105.json").write_text("{}", "utf-8")
            try:
                v2_verify.configure(base)
                with redirect_stdout(io.StringIO()):
                    v2_verify.verify_all()  # would fail reading windows if it did not skip
            finally:
                v2_verify.configure(v2_verify.DEFAULT_BASE)
            self.assertFalse((base / "verified" / "qwen2_5_14b__profile").exists())


class TestTeachingExamples(unittest.TestCase):
    def _base(self, tmp: Path) -> Path:
        base = tmp / "al_tabari"
        (base / "windows").mkdir(parents=True)
        for wid, texts in {"24_2": ["نص أول.", " نص ثان."], "24_6": ["نص ثالث."],
                           "24_9": ["نص النافذة."], "24_4": ["ط" * 800]}.items():
            (base / "windows" / f"{wid}.json").write_text(
                json.dumps(_window(texts, wid), ensure_ascii=False), "utf-8")
        return base

    def test_selection_and_text_from_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = self._base(Path(tmp))
            ex = [
                gold_bank.make_example(window="24_2", ayah="24:2", span_ids=["s001", "s002"],
                                       decision="approve", proposed_primary="M_SUNNAH",
                                       correct_primary=None, error_type=None,
                                       decided_at=10, decision_id=1),
                gold_bank.make_example(window="24_6", ayah="24:6", span_ids=["s001"],
                                       decision="needs_edit", proposed_primary="M_QURAN",
                                       correct_primary="M_SUNNAH", error_type="verse_in_report",
                                       decided_at=5, decision_id=2),
                gold_bank.make_example(window="24_9", ayah="24:9", span_ids=["s001"],
                                       decision="approve", proposed_primary="M_SUNNAH",
                                       correct_primary=None, error_type=None,
                                       decided_at=20, decision_id=3),
                gold_bank.make_example(window="24_4", ayah="24:4", span_ids=["s001"],
                                       decision="approve", proposed_primary="M_SUNNAH",
                                       correct_primary=None, error_type=None,
                                       decided_at=30, decision_id=4),
            ]
            gold_bank.write_bank(base, "al_tabari", ex)
            w = _window(["نص"], "24_9")
            got = gold_bank.examples_for_window(base, w, {"family_counts": {"HADITH": 3}})
            self.assertEqual([g["ref"] for g in got], ["24_6:s001", "24_2:s001,s002"])
            self.assertEqual(got[0]["correct_primary"], "M_SUNNAH")
            self.assertEqual(got[1]["text"], "نص أول. نص ثان.")
            self.assertEqual(got[1]["correct_primary"], "M_SUNNAH")  # approve keeps proposal

    def test_bad_values_refused(self) -> None:
        with self.assertRaises(ValueError):
            gold_bank.make_example(window="24_2", ayah="24:2", span_ids=["s001"], decision="approve",
                                   proposed_primary="M_X", correct_primary=None, error_type=None,
                                   decided_at=0, decision_id=1)
        with self.assertRaises(ValueError):
            gold_bank.make_example(window="24_2", ayah="24:2", span_ids=["s001"],
                                   decision="reject", proposed_primary="M_RAY",
                                   correct_primary=None, error_type="nope",
                                   decided_at=0, decision_id=1)


if __name__ == "__main__":
    unittest.main()
