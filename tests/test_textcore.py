"""Unit tests for src/textcore.py (audit phase 2.1)."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from textcore import (  # noqa: E402
    IntegrityError,
    assert_tiling,
    read_exact,
    read_json,
    resolve_base,
    sha256_bytes,
    sha256_file,
)


class TestReadExact(unittest.TestCase):
    def test_reads_utf8_bytes_without_newline_translation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.txt"
            path.write_bytes("أ\r\nب".encode("utf-8"))
            self.assertEqual(read_exact(path), "أ\r\nب")


class TestReadJson(unittest.TestCase):
    def test_loads_object(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.json"
            path.write_bytes(json.dumps({"a": 1, "ب": [2]}, ensure_ascii=False).encode("utf-8"))
            self.assertEqual(read_json(path), {"a": 1, "ب": [2]})


class TestSha256(unittest.TestCase):
    def test_sha256_bytes(self) -> None:
        self.assertEqual(
            sha256_bytes(b"abc"),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
        )

    def test_sha256_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.bin"
            path.write_bytes(b"abc")
            self.assertEqual(sha256_file(path), sha256_bytes(b"abc"))


class TestAssertTiling(unittest.TestCase):
    def test_ok_full_cover(self) -> None:
        assert_tiling(
            [{"start": 0, "end": 3}, {"start": 3, "end": 5}],
            5,
        )

    def test_ok_empty_text(self) -> None:
        assert_tiling([], 0)

    def test_rejects_unsorted(self) -> None:
        with self.assertRaises(IntegrityError):
            assert_tiling([{"start": 2, "end": 4}, {"start": 0, "end": 2}], 4)

    def test_rejects_gap(self) -> None:
        with self.assertRaises(IntegrityError):
            assert_tiling([{"start": 0, "end": 2}, {"start": 3, "end": 5}], 5)

    def test_rejects_empty_range(self) -> None:
        with self.assertRaises(IntegrityError):
            assert_tiling([{"start": 0, "end": 0}, {"start": 0, "end": 3}], 3)

    def test_rejects_short_cover(self) -> None:
        with self.assertRaises(IntegrityError):
            assert_tiling([{"start": 0, "end": 2}], 5)

    def test_rejects_nonempty_ranges_for_empty_text(self) -> None:
        with self.assertRaises(IntegrityError):
            assert_tiling([{"start": 0, "end": 1}], 0)


class TestResolveBase(unittest.TestCase):
    def test_relative_to_repo_root(self) -> None:
        got = resolve_base("data/v2")
        self.assertEqual(got, (ROOT / "data" / "v2").resolve())

    def test_absolute_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            abs_path = Path(tmp).resolve()
            self.assertEqual(resolve_base(abs_path), abs_path)

    def test_custom_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "base").mkdir()
            self.assertEqual(resolve_base("base", root=root), (root / "base").resolve())


if __name__ == "__main__":
    unittest.main()


# ---- the verse at the head of a window: strict (the «****» / heading incident, 6 Oct 2026)

from textcore import verse_at_head  # noqa: E402

VERSE_1 = "سُورَةٌ أَنْزَلْنَاهَا وَفَرَضْنَاهَا وَأَنْزَلْنَا فِيهَا آيَاتٍ بَيِّنَاتٍ لَعَلَّكُمْ تَذَكَّرُونَ"


def test_verse_header_drops_heading_and_separator_lines():
    # Ibn Kathir's edition: surah title, "وهي مدنية", a «****» separator, then the verse, then (1)
    text = f"سُوْرَةُ النُّوْرِ\r\nوهي مدنية\r\n****\r\n{VERSE_1} (1)\r\nيقول تعالى: هذه سورة"
    assert verse_at_head(text, 1) == VERSE_1


def test_verse_header_keeps_only_the_quotation_after_the_last_brace():
    # al-Saadi's edition: an introductory sentence, then {verse} (6)
    verse = "وَالَّذِينَ يَرْمُونَ أَزْوَاجَهُمْ وَلَمْ يَكُنْ لَهُمْ شُهَدَاءُ إِلَّا أَنْفُسُهُمْ"
    text = ("وإنَّما يُجْلَدُ القاذف إذا لم يأت بأربعة شهداء إذا لم يكن زوجاً؛ فإنْ كان زوجاً؛ فقد ذُكِرَ بقوله:\n"
            f"{{{verse} (6)}}.\n{{6}} أي: ...")
    assert verse_at_head(text, 6) == verse


def test_verse_header_never_shows_half_a_verse():
    # al-Tabari 24:21: the verse quoted in two halves with commentary between them
    text = ("القولُ في تأويلِ قولِه تعالى: {يَاأَيُّهَا الَّذِينَ آمَنُوا لَا تَتَّبِعُوا خُطُوَاتِ الشَّيْطَانِ}."
            "يقولُ تعالى ذِكرُه للمؤمنين به: يا أيُّها الذين صدَّقوا اللهَ ورسولَه لا تتبعوا ... في هذا الموضعِ ."
            "القولُ في تأويلِ قولِه تعالى: {وَلَوْلَا فَضْلُ اللَّهِ عَلَيْكُمْ وَرَحْمَتُهُ (21)}.يقولُ تعالى ذكرُه")
    assert verse_at_head(text, 21) is None


def test_verse_header_joins_consecutive_quotations_only():
    text = "القول في تأويل قوله تعالى: {إِنَّ الَّذِينَ جَاءُوا بِالْإِفْكِ عُصْبَةٌ مِنْكُمْ} {لَا تَحْسَبُوهُ شَرًّا لَكُمْ (11)}."
    assert verse_at_head(text, 11) == "إِنَّ الَّذِينَ جَاءُوا بِالْإِفْكِ عُصْبَةٌ مِنْكُمْ لَا تَحْسَبُوهُ شَرًّا لَكُمْ"


def test_verse_header_strips_apparatus_and_refuses_what_is_not_a_verse():
    assert verse_at_head(f"{{{VERSE_1}¬حاشية المحقق¥ (1)}}", 1) == VERSE_1
    assert verse_at_head("القولُ في تأويلِ قولِه تعالى: {سُورَةٌ أَنْزَلْنَاهَا}", 1) is None   # no (1) marker
    assert verse_at_head("تفسير سورة النور **** (1)", 1) is None                                # separator, no verse
    assert verse_at_head("فقال: {كذا وكذا: قال (2)}", 2) is None                              # commentary colon
    assert verse_at_head("{قصير (3)}", 3) is None                                              # too short to be a verse


def test_every_an_nur_window_header_is_a_clean_quotation_or_none():
    """On the real corpus: no header may contain separators, brackets, digits, line breaks
    or the commentary's own formulas — and 24:1 reads the verse, not the surah title."""
    import json
    import re
    nur = ROOT / "data" / "nur"
    if not nur.exists():
        return
    bad = re.compile(r"[*¬¥<>{}\[\]\d\r\n:؛]")
    seen = 0
    for tafsir in ("al_tabari", "ibn_kathir", "al_baghawi", "al_saadi"):
        for n in range(1, 65):
            for name in (f"24_{n}.json", f"24_{n}_p01.json"):
                p = nur / tafsir / "windows" / name
                if p.exists():
                    break
            else:
                continue
            w = json.loads(p.read_text(encoding="utf-8"))
            v = verse_at_head(w["window_text"], n)
            if v is None:
                continue
            seen += 1
            assert not bad.search(v), (tafsir, n, v[:80])
            assert "وهي مدنية" not in v and "القول في تأويل" not in v, (tafsir, n)
            if n == 1:
                assert v.startswith("سُورَةٌ أَنْزَلْنَاهَا"), (tafsir, v[:60])
    assert seen >= 200
