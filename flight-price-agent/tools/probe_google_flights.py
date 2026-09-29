"""Sonda temporal: abre Google Flights y vuelca lo que encuentra (para desarrollar el parser)."""
import sys
import urllib.parse

from playwright.sync_api import sync_playwright

QUERIES = [
    "Flights to FLN from BUE on 2027-01-02 through 2027-01-14",
    "Flights to FLN from EZE on 2027-01-02 through 2027-01-14",
    "Flights to SSA from AEP on 2027-01-03 through 2027-01-16",
]

with sync_playwright() as p:
    browser = p.chromium.launch()
    ctx = browser.new_context(locale="en-US", viewport={"width": 1366, "height": 900})
    page = ctx.new_page()
    for q in QUERIES:
        url = "https://www.google.com/travel/flights?" + urllib.parse.urlencode(
            {"q": q, "curr": "USD", "hl": "en", "gl": "us"}
        )
        print("=" * 100)
        print("QUERY:", q)
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        try:
            page.wait_for_selector('[aria-label^="From "]', timeout=30000)
        except Exception as e:
            print("NO RESULTS SELECTOR:", e)
        page.wait_for_timeout(3000)
        print("FINAL URL:", page.url)
        print("TITLE:", page.title())
        labels = page.eval_on_selector_all(
            "[aria-label]", "els => els.map(e => e.tagName + ' | ' + e.getAttribute('aria-label'))"
        )
        froms = [l for l in labels if "dollar" in l.lower() or l.split(" | ", 1)[1].startswith("From ")]
        print(f"ARIA LABELS: {len(labels)} total, {len(froms)} with price")
        for l in froms[:25]:
            print("  ", l[:400])
        print("--- BODY TEXT ---")
        print(page.inner_text("body")[:2500])
        page.screenshot(path=f"probe_{QUERIES.index(q)}.png", full_page=True)
    browser.close()
