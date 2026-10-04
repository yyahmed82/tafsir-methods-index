"""Playwright visual/contrast/scroll audit for مِرْقاة UI polish."""
from __future__ import annotations

import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parent
PAGES = ("index.html", "reader.html", "fahras.html")
VIEWPORTS = (("mobile", 375, 812), ("desktop", 1440, 900))
THEMES = ("light", "dark")


def rel_luminance(rgb: tuple[float, float, float]) -> float:
    def chan(c: float) -> float:
        c = c / 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (chan(x) for x in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    l1, l2 = rel_luminance(a), rel_luminance(b)
    lighter, darker = max(l1, l2), min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def parse_rgb(value: str) -> tuple[float, float, float] | None:
    if not value:
        return None
    if value.startswith("rgb"):
        nums = value[value.find("(") + 1 : value.find(")")].split(",")
        return tuple(float(n.strip()) for n in nums[:3])  # type: ignore[return-value]
    return None


def launch_browser(p):
    try:
        return p.chromium.launch(channel="chrome", headless=True)
    except Exception:
        return p.chromium.launch(headless=True)


def wait_for_origin(origin: str, timeout_s: float = 8.0) -> None:
    deadline = time.time() + timeout_s
    last = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(origin + "/index.html", timeout=1) as resp:
                if resp.status == 200:
                    return
        except Exception as exc:
            last = exc
            time.sleep(0.15)
    raise RuntimeError(f"local audit server did not start: {last}")


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright unavailable")
        return 2

    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    with sync_playwright() as p:
        browser = launch_browser(p)
        from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
        import threading

        class Handler(SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(ROOT / "web"), **kwargs)

            def log_message(self, fmt, *args):
                return

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        origin = f"http://127.0.0.1:{httpd.server_address[1]}"
        print(f"audit server {origin} root={ROOT / 'web'}")
        wait_for_origin(origin)
        for page_name in PAGES:
            for vp_name, w, h in VIEWPORTS:
                for theme in THEMES:
                    page = browser.new_page(viewport={"width": w, "height": h})
                    url = origin + "/" + page_name
                    page.goto(url, wait_until="load")
                    page.evaluate(
                        """(theme) => {
                          document.documentElement.setAttribute('data-theme', theme);
                          try { localStorage.setItem('tafsir-fahras-v1-theme', theme); } catch (e) {}
                        }""",
                        theme,
                    )
                    page.wait_for_timeout(250)
                    if page_name in ("reader.html", "fahras.html"):
                        page.wait_for_function(
                            """() => {
                              const links = Array.from(document.querySelectorAll('.js-quranpedia-link'));
                              return links.some(a => !a.hidden && a.getAttribute('href'));
                            }""",
                            timeout=8000,
                        )
                    metrics = page.evaluate(
                        """() => {
                          const cs = getComputedStyle(document.body);
                          const hs = getComputedStyle(document.documentElement);
                          function opaque(c) {
                            return c && !c.startsWith('rgba(0, 0, 0, 0)') && c !== 'transparent';
                          }
                          const brand = document.querySelector('.brand-lockup, .mirqat-wordmark');
                          const links = Array.from(document.querySelectorAll('.js-quranpedia-link'));
                          const link = links.find(a => !a.hidden && a.getClientRects().length) || links[0];
                          const header = document.querySelector('.app-header, .hero, .site-header');
                          let overlap = false;
                          if (brand && header) {
                            const br = brand.getBoundingClientRect();
                            const hr = header.getBoundingClientRect();
                            overlap = br.top < hr.top - 2;
                          }
                          const linkText = (link && (link.textContent || '').trim()) || '';
                          const rule = document.querySelector('.brand-rule');
                          const visible = !!(link && !link.hidden && link.getClientRects().length && linkText.includes('قرآنبيديا'));
                          return {
                            innerWidth: window.innerWidth,
                            scrollWidth: document.documentElement.scrollWidth,
                            color: cs.color,
                            background: opaque(cs.backgroundColor) ? cs.backgroundColor : hs.backgroundColor,
                            wordmark: !!(document.body.innerText || '').includes('مِرْقاة'),
                            mark: !!document.querySelector('.mirqat-mark'),
                            divider: !!(rule && rule.getClientRects().length),
                            linkVisible: visible,
                            linkHref: (link && link.getAttribute('href')) || '',
                            brandOverlap: overlap
                          };
                        }"""
                    )
                    shot = OUT / f"{page_name.replace('.html','')}_{vp_name}_{theme}.png"
                    page.screenshot(path=str(shot), full_page=True)
                    header = page.query_selector(".app-header, .hero, .site-header, .brand-lockup")
                    if header:
                        header.screenshot(
                            path=str(OUT / f"header_{page_name.replace('.html','')}_{vp_name}_{theme}.png")
                        )
                    page.close()
                    fg = parse_rgb(metrics["color"])
                    bg = parse_rgb(metrics["background"])
                    ratio = contrast_ratio(fg, bg) if fg and bg else 0.0
                    scroll_ok = metrics["scrollWidth"] <= metrics["innerWidth"] + 1
                    contrast_ok = ratio >= 4.5
                    rows.append(
                        {
                            "page": page_name,
                            "viewport": f"{w}x{h}",
                            "theme": theme,
                            "scroll_ok": scroll_ok,
                            "contrast_ok": contrast_ok,
                            "ratio": round(ratio, 2),
                            "scrollWidth": metrics["scrollWidth"],
                            "innerWidth": metrics["innerWidth"],
                            "wordmark": metrics["wordmark"],
                            "mark": metrics["mark"],
                            "divider": metrics["divider"],
                            "link_visible": metrics["linkVisible"],
                            "brand_overlap": metrics["brandOverlap"],
                            "shot": shot.name,
                        }
                    )

        def tab_to(page, predicate, limit=40):
            for _ in range(limit):
                page.keyboard.press("Tab")
                if page.evaluate(predicate):
                    return True
            return False

        def focus_ring_ok(page) -> bool:
            return page.evaluate(
                """() => {
                  const el = document.activeElement;
                  if (!el || el === document.body) return false;
                  const cs = getComputedStyle(el);
                  const ow = parseFloat(cs.outlineWidth) || 0;
                  const style = (cs.outlineStyle || '').toLowerCase();
                  const shadow = cs.boxShadow || '';
                  return (style !== 'none' && ow >= 2) || /rgb|rgba|#/.test(shadow);
                }"""
            )

        focus_rows = []
        fp = browser.new_page(viewport={"width": 1440, "height": 900})
        fp.goto(origin + "/reader.html", wait_until="load")
        fp.wait_for_function(
            """() => Array.from(document.querySelectorAll('.js-quranpedia-link')).some(a => !a.hidden && a.getAttribute('href'))""",
            timeout=8000,
        )
        brand_ok = tab_to(
            fp,
            """() => {
              const el = document.activeElement;
              return !!(el && el.id === 'brand-logo' && el.tagName === 'BUTTON');
            }""",
        )
        brand_ring = focus_ring_ok(fp) if brand_ok else False
        fp.screenshot(path=str(OUT / "focus_reader_brand.png"))
        src_ok = tab_to(
            fp,
            """() => {
              const el = document.activeElement;
              if (!el || el.tagName !== 'A') return false;
              return !!(el.closest('.source-row, .src-box') && el.getClientRects().length);
            }""",
            60,
        )
        src_ring = focus_ring_ok(fp) if src_ok else False
        fp.screenshot(path=str(OUT / "focus_reader_source.png"))
        fp.close()
        focus_rows.append(("reader brand", brand_ok and brand_ring))
        focus_rows.append(("reader source", src_ok and src_ring))

        fp = browser.new_page(viewport={"width": 1440, "height": 900})
        fp.goto(origin + "/fahras.html", wait_until="load")
        fp.wait_for_function(
            """() => Array.from(document.querySelectorAll('.js-quranpedia-link')).some(a => !a.hidden && a.getAttribute('href'))""",
            timeout=8000,
        )
        fahras_ok = tab_to(
            fp,
            """() => {
              const el = document.activeElement;
              if (!el || el.tagName !== 'A') return false;
              return !!(el.closest('.source-row') && el.getClientRects().length);
            }""",
            80,
        )
        fahras_ring = focus_ring_ok(fp) if fahras_ok else False
        fp.screenshot(path=str(OUT / "focus_fahras_source.png"))
        fp.close()
        focus_rows.append(("fahras source", fahras_ok and fahras_ring))

        browser.close()
        httpd.shutdown()

    print("page\tviewport\ttheme\tscrollWidth ok?\tcontrast ok?\tratio\tlink\tbrand overlap")
    failed = 0
    for row in rows:
        print(
            f"{row['page']}\t{row['viewport']}\t{row['theme']}\t"
            f"{'yes' if row['scroll_ok'] else 'NO ' + str(row['scrollWidth']) + '>' + str(row['innerWidth'])}\t"
            f"{'yes' if row['contrast_ok'] else 'NO ' + str(row['ratio'])}\t"
            f"{row['ratio']}\t{'yes' if row['link_visible'] else 'no'}\t"
            f"{'yes' if row['brand_overlap'] else 'no'}"
        )
        if not row["scroll_ok"] or not row["contrast_ok"] or row["brand_overlap"]:
            failed += 1
        if page_name_has_link(row) and not row["link_visible"]:
            failed += 1
        if not row["wordmark"] or not row["mark"] or not row.get("divider", True):
            failed += 1
    print("focus\ttarget\tok")
    for name, ok in focus_rows:
        print(f"focus\t{name}\t{'yes' if ok else 'NO'}")
        if not ok:
            failed += 1
    print(f"shots in {OUT}")
    return 1 if failed else 0


def page_name_has_link(row: dict) -> bool:
    return row["page"] in ("reader.html", "fahras.html")


if __name__ == "__main__":
    sys.exit(main())
