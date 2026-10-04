/* Verified quranpedia.app tafsir-by-ayah mapping (Playwright, 2026-10-04).
   Pattern: https://quranpedia.app/tafseer/{book}/sura{surah}-aya{ayah}.html
   Book slugs verified at surah 24 ayah 35:
     tabary (الطبري), katheer (ابن كثير), baghawy (البغوي), saadi (السعدي)
   Do not add a book that has not been verified in the rendered page. */
(function (global) {
  "use strict";
  var BOOK_IDS = {
    al_tabari: "tabary",
    ibn_kathir: "katheer",
    al_baghawi: "baghawy",
    al_saadi: "saadi"
  };
  function sourceUrl(tafsirId, surah, ayah) {
    var book = BOOK_IDS[tafsirId];
    var s = Number(surah);
    var a = Number(ayah);
    if (!book || !s || !a) return "";
    return "https://quranpedia.app/tafseer/" + book + "/sura" + s + "-aya" + a + ".html";
  }
  global.QURANPEDIA_BOOK_IDS = BOOK_IDS;
  global.quranpediaSourceUrl = sourceUrl;
})(typeof window !== "undefined" ? window : this);
