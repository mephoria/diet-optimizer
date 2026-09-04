"""
Crawl a No Frills / PC Express category listing page, open every product,
grab the rendered product-page HTML, and parse it with parse_nutrition.py
into a single aggregate JSON file (merged by category).

Requires:
    pip install playwright beautifulsoup4
    playwright install chromium

Usage:
    python scrape_nofrills_category.py \
        "https://www.nofrills.ca/en/food/fruits-vegetables/fresh-vegetables/c/28195?navid=flyout-L2-fruits-vegetables&page=1" \
        --category fresh_vegetables \
        --out data.json \
        --max-pages 5 \
        --headful

Notes / etiquette:
    - This makes real requests to nofrills.ca. Keep volume low, add delays
      (already built in), and re-check the site's Terms of Use / robots.txt
      before running this at any scale. Treat this as a personal research
      tool, not a basis for a scraping service or resale of data.
    - The site is a JS-rendered React/Angular app, so plain requests+BS4
      won't see product tiles or the nutrition panel -- Playwright renders
      the page first, then we hand the *rendered* HTML to parse_nutrition.py.
    - Selectors below are a best-effort based on typical PC Express markup.
      If the site changes, edit the SELECTORS block; the rest of the script
      is layout-agnostic.
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qs, urlencode, urlunparse

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

sys.path.insert(0, str(Path(__file__).resolve().parent))
from parse_nutrition import build_product_json, merge_into_category_file  # noqa: E402


# ---------------------------------------------------------------------------
# Selector configuration -- adjust here if the site markup changes.
# Each list is tried in order on the LISTING page to find product tiles/links.
# ---------------------------------------------------------------------------
PRODUCT_LINK_SELECTORS = [
    "a[data-testid='product-tile-title-link']",
    "a[data-testid*='product-tile']",
    "div[data-testid='product-tile'] a[href*='/p/']",
    "a[href*='/en/'][href*='/p/']",
    "a[href*='/p/']",
]

# "Next page" control on the listing page.
NEXT_PAGE_SELECTORS = [
    "a[aria-label='Next page']",
    "button[aria-label='Next page']",
    "a[rel='next']",
    "li.pagination__item--next a",
    "[data-testid='pagination-next']",
]

COOKIE_BANNER_SELECTORS = [
    "#onetrust-accept-btn-handler",
    "button#truste-consent-button",
    "button[aria-label='Accept all cookies']",
]

# A CSS selector we expect to see once a *product detail* page has rendered
# (used to know when it's safe to grab page.content()).
PRODUCT_PAGE_READY_SELECTORS = [
    "h1.product-name__item--name",
    ".product-name__item--name",
    "h1",
]


def dismiss_cookie_banner(page):
    for sel in COOKIE_BANNER_SELECTORS:
        try:
            btn = page.locator(sel)
            if btn.count() > 0 and btn.first.is_visible():
                btn.first.click(timeout=2000)
                page.wait_for_timeout(300)
                return
        except Exception:
            pass


def wait_for_any(page, selectors, timeout=15000):
    """Wait until any selector in the list matches at least one element."""
    deadline = time.time() + timeout / 1000
    while time.time() < deadline:
        for sel in selectors:
            try:
                if page.locator(sel).count() > 0:
                    return sel
            except Exception:
                pass
        page.wait_for_timeout(250)
    return None


def collect_product_links(page, base_url):
    """Return a de-duplicated, absolute list of product detail URLs on the current listing page."""
    links = []
    seen = set()
    for sel in PRODUCT_LINK_SELECTORS:
        try:
            handles = page.locator(sel).all()
        except Exception:
            handles = []
        if not handles:
            continue
        for h in handles:
            href = h.get_attribute("href")
            if not href:
                continue
            abs_url = urljoin(base_url, href)
            if abs_url not in seen:
                seen.add(abs_url)
                links.append(abs_url)
        if links:
            break  # first selector that yields results wins
    return links


def set_page_param(url: str, page_num: int) -> str:
    """Return `url` with its `page` query param set to `page_num`."""
    parsed = urlparse(url)
    q = parse_qs(parsed.query)
    q["page"] = [str(page_num)]
    new_query = urlencode(q, doseq=True)
    return urlunparse(parsed._replace(query=new_query))


def scrape_category(start_url, category, out_path, max_pages, headful, delay, max_items):
    total_scraped = 0
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headful)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
            locale="en-CA",
        )
        listing_page = context.new_page()
        detail_page = context.new_page()

        page_num = 1
        current_url = start_url

        while page_num <= max_pages:
            print(f"[listing] page {page_num}: {current_url}")
            listing_page.goto(current_url, wait_until="domcontentloaded", timeout=45000)
            dismiss_cookie_banner(listing_page)

            found_sel = wait_for_any(listing_page, PRODUCT_LINK_SELECTORS, timeout=20000)
            if not found_sel:
                print("  no product tiles found on this page -- stopping pagination.")
                break

            listing_page.wait_for_timeout(500)  # let lazy content settle
            product_urls = collect_product_links(listing_page, current_url)
            print(f"  found {len(product_urls)} product link(s)")

            for i, purl in enumerate(product_urls, 1):
                if max_items and total_scraped >= max_items:
                    print("  reached --max-items limit, stopping.")
                    browser.close()
                    return total_scraped

                print(f"  [{i}/{len(product_urls)}] {purl}")
                try:
                    detail_page.goto(purl, wait_until="domcontentloaded", timeout=30000)
                    dismiss_cookie_banner(detail_page)
                    ready_sel = wait_for_any(detail_page, PRODUCT_PAGE_READY_SELECTORS, timeout=15000)
                    if not ready_sel:
                        print("    product name selector never appeared, skipping.")
                        continue
                    detail_page.wait_for_timeout(400)  # let nutrition panel hydrate
                    html = detail_page.content()

                    result = build_product_json(html)
                    result["source_url"] = purl
                    count = merge_into_category_file(result, out_path, category)
                    total_scraped += 1
                    print(f"    parsed '{result.get('name')}' -> {out_path} "
                          f"[{category}] ({count} item(s) so far)")
                except PWTimeout:
                    print("    timed out loading product page, skipping.")
                except Exception as e:
                    print(f"    error parsing product page: {e}")

                time.sleep(delay)  # be polite between product hits

            # --- pagination ---
            next_url = None
            for sel in NEXT_PAGE_SELECTORS:
                try:
                    loc = listing_page.locator(sel)
                    if loc.count() > 0:
                        href = loc.first.get_attribute("href")
                        if href:
                            next_url = urljoin(current_url, href)
                        break
                except Exception:
                    pass

            page_num += 1
            if next_url:
                current_url = next_url
            else:
                # fall back to manually bumping the `page` query param
                current_url = set_page_param(start_url, page_num)

            time.sleep(delay)

        browser.close()
    return total_scraped


def main():
    ap = argparse.ArgumentParser(description="Scrape a No Frills category page into structured JSON.")
    ap.add_argument("url", help="Category listing page URL (include ?page=1).")
    ap.add_argument("--category", default="uncategorized", help="Category key in the output JSON.")
    ap.add_argument("--out", default="data.json", help="Output aggregate JSON file.")
    ap.add_argument("--max-pages", type=int, default=10, help="Max listing pages to paginate through.")
    ap.add_argument("--max-items", type=int, default=0, help="Stop after N products total (0 = no limit).")
    ap.add_argument("--delay", type=float, default=1.5, help="Seconds to wait between product page hits.")
    ap.add_argument("--headful", action="store_true", help="Show the browser window (default: headless).")
    args = ap.parse_args()

    total = scrape_category(
        start_url=args.url,
        category=args.category,
        out_path=args.out,
        max_pages=args.max_pages,
        headful=args.headful,
        delay=args.delay,
        max_items=args.max_items,
    )
    print(f"\nDone. Scraped {total} product(s) into '{args.out}' under category '{args.category}'.")


if __name__ == "__main__":
    main()
