import os
import glob
from html.parser import HTMLParser

with open("web/reader.html", "r", encoding="utf-8") as f:
    r_html = f.read()
with open("web/fahras.html", "r", encoding="utf-8") as f:
    f_html = f.read()

def norm(s):
    return " ".join(s.split())

corpus = norm(r_html) + " " + norm(f_html)

mockup_files = sorted(glob.glob("docs/design/ux-proposals-2026-10-04/mockups/*.html"))

print("=" * 65)
print("GATE CHECK: Verifying All Arabic Tafsir/Quran Runs Appear Verbatim")
print("=" * 65)

total_checked = 0
failures = []

class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_script_or_style = False
        self.texts = []
        self.tag_stack = []

    def handle_starttag(self, tag, attrs):
        self.tag_stack.append((tag, dict(attrs)))
        if tag in ["script", "style"]:
            self.in_script_or_style = True

    def handle_endtag(self, tag):
        if self.tag_stack:
            self.tag_stack.pop()
        if tag in ["script", "style"]:
            self.in_script_or_style = False

    def handle_data(self, data):
        if not self.in_script_or_style:
            d = data.strip()
            if d:
                classes = " ".join([attr_dict.get("class", "") for t, attr_dict in self.tag_stack])
                self.texts.append((classes, d))

for mf in mockup_files:
    with open(mf, "r", encoding="utf-8") as f:
        content = f.read()
    
    parser = TextExtractor()
    parser.feed(content)
    
    for classes, t in parser.texts:
        is_tafsir = any(c in classes for c in ["tafsir", "quran", "article", "passage", "ev-", "inset-text"])
        has_kw = any(kw in t for kw in ["{", "قال", "تأويل"])
        if is_tafsir or has_kw:
            words = t.split()
            if len(words) >= 6 and any("\u0600" <= ch <= "\u06FF" for ch in t):
                clean_t = norm(t)
                total_checked += 1
                if clean_t in corpus:
                    print(f"PASS [{os.path.basename(mf):<24}]: {clean_t[:45]}... ({len(words)} words)")
                else:
                    print(f"FAIL [{os.path.basename(mf):<24}]: {clean_t} ({len(words)} words)")
                    failures.append((mf, clean_t))

print("=" * 65)
print(f"Total checked: {total_checked}, Failures: {len(failures)}")
assert len(failures) == 0, f"{len(failures)} runs failed verbatim check!"
print("GATE CHECK STATUS: PASSED WITH ZERO MISSES (100% VERBATIM)")
print("=" * 65)
