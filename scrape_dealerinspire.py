#!/usr/bin/env python3
"""
scrape_dealerinspire.py

Inventory detector for Dealer Inspire-powered dealer sites (like
markchristopher.com). Unlike Metro Nissan's FoxDealer site, Dealer Inspire
loads vehicle listings with JavaScript after the page opens -- a plain
HTTP fetch of the page returns an empty shell. This uses a real (headless)
browser via Playwright to load the page the way an actual visitor's browser
would, waits for the vehicle cards to appear, then reads them out.

Returns the same shape as detect_new_vehicles.collect_listings() so it's a
drop-in replacement: {vin: {vin, url, year, make, model, trim}}

This was built without the ability to test against the live site (network
restrictions in the build environment), so the CSS selectors below are
based on Dealer Inspire's common patterns -- expect this may need one
round of adjustment once it's run for real. If it comes back with 0
vehicles, that's the signal: the selectors need updating for this specific
site's HTML, and the fix is usually a quick one once we see the actual
error/output from a real run.
"""

import json
import re
import time

VIN_RE = re.compile(r'\b([A-HJ-NPR-Z0-9]{17})\b')


def fetch_pages(urls, delay_seconds=0.5):
    """Fetch multiple detail pages using ONE shared headless browser session
    (much faster than launching a new browser per page). Returns {url: html}.
    Used for Dealer Inspire vehicle detail pages, which -- like the
    inventory listing page -- render via JavaScript and return an empty/
    unusable shell to a plain HTTP request."""
    from playwright.sync_api import sync_playwright

    results = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        for url in urls:
            try:
                page.goto(url, wait_until="networkidle", timeout=30000)
                page.wait_for_timeout(int(delay_seconds * 1000))
                results[url] = page.content()
            except Exception as e:
                print(f"    (failed to load {url}: {e})")
        browser.close()
    return results


def collect_listings(base_url, max_pages=10, delay_seconds=1.5):
    """Load the inventory pages with a real headless browser using direct
    page-number navigation (confirmed pattern: ?_p=2, ?_p=3, ...), extract
    VIN + basic info from each page."""
    from playwright.sync_api import sync_playwright

    found = {}
    sep = "&" if "?" in base_url else "?"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )

        for page_num in range(1, max_pages + 1):
            url = base_url if page_num == 1 else f"{base_url}{sep}_p={page_num}"
            print(f"  loading page {page_num}: {url}")
            try:
                page.goto(url, wait_until="networkidle", timeout=45000)
            except Exception as e:
                print(f"  (stopped paging at page {page_num}: {e})")
                break

            # Give any lazy-loaded widgets a moment to finish rendering.
            page.wait_for_timeout(int(delay_seconds * 1000))
            html = page.content()

            vins_before = len(found)
            _extract_vehicles_from_html(html, base_url, found)
            new_on_page = len(found) - vins_before
            print(f"  page {page_num}: {new_on_page} new vehicle(s) found "
                  f"({len(found)} total so far)")

            if new_on_page == 0 and page_num > 1:
                break  # no new vehicles on this page -- we've reached the end

        browser.close()

    print(f"  found {len(found)} vehicle(s) total across all pages")
    return found


def _extract_vehicles_from_html(html, base_url, found):
    """Extract VIN + detail-page info from one page's HTML, adding new
    entries into the shared `found` dict in place."""
    vin_matches = set(VIN_RE.findall(html))

    for vin in vin_matches:
        if vin in found:
            continue
        url_pattern = re.compile(
            rf'href="([^"]*{re.escape(vin)}[^"]*)"', re.IGNORECASE)
        url_match = url_pattern.search(html)
        if not url_match:
            continue
        detail_url = url_match.group(1)
        if detail_url.startswith("/"):
            root_match = re.match(r'(https?://[^/]+)', base_url)
            root = root_match.group(1) if root_match else base_url.rstrip("/")
            detail_url = root + detail_url

        slug = detail_url.split("?")[0].rstrip("/").split("/")[-1]
        parts = [p for p in slug.replace(vin, "").split("-") if p]
        year = next((p for p in parts if p.isdigit() and len(p) == 4), "")
        make, model, trim = "", "", ""
        if year and year in parts:
            idx = parts.index(year)
            rest = parts[idx + 1:]
            if rest:
                make = rest[0].capitalize()
            if len(rest) > 1:
                model = " ".join(w.capitalize() for w in rest[1:-1]) or rest[1].capitalize()
            if len(rest) > 2:
                trim = rest[-1].upper()

        found[vin] = {
            "vin": vin,
            "url": detail_url,
            "year": year,
            "make": make,
            "model": model,
            "trim": trim,
        }
