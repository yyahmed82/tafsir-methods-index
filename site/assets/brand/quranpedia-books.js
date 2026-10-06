/* Verified quranpedia.net tafsir-by-ayah mapping (rendered page, 2026-10-06).
   Pattern: https://quranpedia.net/surah/1/{surah}/book/{book}#verse-{n}
   where 1 is the Hafs mushaf and n is the ayah's running number in the mushaf
   (24:1 = 2792). Book ids verified at surah 24:
     4 (الطبري، جامع البيان), 136 (ابن كثير، تفسير القرآن العظيم، ط. دار طيبة),
     2 (البغوي، معالم التنزيل، ط. دار طيبة), 3 (السعدي، تيسير الكريم الرحمن)
   Do not add a book that has not been verified in the rendered page. */
(function (global) {
  "use strict";
  var BOOK_IDS = {
    al_tabari: 4,
    ibn_kathir: 136,
    al_baghawi: 2,
    al_saadi: 3
  };
  var AYAT = [7, 286, 200, 176, 120, 165, 206, 75, 129, 109, 123, 111, 43, 52, 99, 128, 111, 110, 98, 135,
    112, 78, 118, 64, 77, 227, 93, 88, 69, 60, 34, 30, 73, 54, 45, 83, 182, 88, 75, 85, 54, 53, 89, 59, 37,
    35, 38, 29, 18, 45, 60, 49, 62, 55, 78, 96, 29, 22, 24, 13, 14, 11, 11, 18, 12, 12, 30, 52, 52, 44, 28,
    28, 20, 56, 40, 31, 50, 40, 46, 42, 29, 19, 36, 25, 22, 17, 19, 26, 30, 20, 15, 21, 11, 8, 8, 19, 5, 8,
    8, 11, 11, 8, 3, 9, 5, 4, 7, 3, 6, 3, 5, 4, 5, 6];
  function verseNumber(surah, ayah) {
    var s = Number(surah);
    var a = Number(ayah);
    if (!(s >= 1 && s <= 114) || !(a >= 1 && a <= AYAT[s - 1])) return 0;
    var n = 0;
    for (var i = 0; i < s - 1; i++) n += AYAT[i];
    return n + a;
  }
  function sourceUrl(tafsirId, surah, ayah) {
    var book = BOOK_IDS[tafsirId];
    var s = Number(surah);
    var a = Number(ayah);
    if (!book || !s || !a) return "";
    var n = verseNumber(s, a);
    if (!n) return "";
    return "https://quranpedia.net/surah/1/" + s + "/book/" + book + "#verse-" + n;
  }
  global.QURANPEDIA_BOOK_IDS = BOOK_IDS;
  global.quranpediaVerseNumber = verseNumber;
  global.quranpediaSourceUrl = sourceUrl;
})(typeof window !== "undefined" ? window : this);
