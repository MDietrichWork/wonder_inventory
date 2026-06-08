#!/usr/bin/env python3
"""Drive each prototype headlessly: click through nav screens, screenshot, capture JS errors."""
import pathlib, re, sys
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path("/Users/mikedietrich/Eliassen Clients/Wonder Group/prototypes")
OUT = pathlib.Path("/tmp/wonder-shots")
VARIANTS = ["variant-a-dense-workbench", "variant-b-guided-triage", "variant-c-dashboard-led"]
NAV_SEL = ("[data-view],[data-screen],[data-target],[data-tab],[role=tab],"
           "nav a,nav button,aside a,aside button,.nav a,.nav button,.nav-item,"
           ".sidebar a,.sidebar button,.menu a,.menu button")

def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", (s or "").strip().lower())[:32] or "item"

def run():
    results = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for v in VARIANTS:
            errors, console = [], []
            page = browser.new_context(viewport={"width": 1440, "height": 900}).new_page()
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda m: console.append((m.type, m.text)) if m.type in ("error", "warning") else None)
            uri = (ROOT / v / "index.html").as_uri()
            page.goto(uri, wait_until="networkidle")
            page.wait_for_timeout(600)
            outdir = OUT / v
            outdir.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(outdir / "00-initial.png"), full_page=True)
            # enumerate nav candidates by visible text
            handles = page.query_selector_all(NAV_SEL)
            seen, labels = set(), []
            for h in handles:
                try:
                    if not h.is_visible():
                        continue
                    t = (h.inner_text() or "").strip()
                except Exception:
                    continue
                key = t.lower()
                if t and 1 <= len(t) <= 40 and key not in seen:
                    seen.add(key)
                    labels.append(t)
            shots = ["00-initial.png"]
            for i, label in enumerate(labels[:8], 1):
                try:
                    el = page.query_selector_all(NAV_SEL)
                    target = next((h for h in el if (h.inner_text() or "").strip() == label and h.is_visible()), None)
                    if not target:
                        continue
                    target.click(timeout=2000)
                    page.wait_for_timeout(500)
                    name = f"{i:02d}-{slug(label)}.png"
                    page.screenshot(path=str(outdir / name), full_page=True)
                    shots.append(name)
                except Exception as e:
                    errors.append(f"click '{label}': {e}")
            results[v] = {"nav": labels, "shots": shots, "pageerrors": errors, "console": console}
            page.context.close()
        browser.close()
    # report
    for v, r in results.items():
        print(f"\n=== {v} ===")
        print(f"  nav screens found ({len(r['nav'])}): {r['nav']}")
        print(f"  screenshots: {len(r['shots'])} -> /tmp/wonder-shots/{v}/")
        print(f"  pageerrors: {len(r['pageerrors'])}")
        for e in r["pageerrors"][:10]:
            print(f"     ! {e}")
        ce = r["console"]
        print(f"  console errors/warnings: {len(ce)}")
        for typ, txt in ce[:10]:
            print(f"     [{typ}] {txt[:160]}")

if __name__ == "__main__":
    run()
