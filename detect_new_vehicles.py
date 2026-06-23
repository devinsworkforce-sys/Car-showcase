#!/usr/bin/env python3
"""
detect_new_vehicles.py

Checks the dealer's public USED inventory listing pages and flags any VINs
that weren't seen on the previous run. Designed to be run on a schedule
(cron, Task Scheduler, or a GitHub Actions workflow) since there's no
backend/CMS access to hook into directly.

State is kept in known_vins.json (created automatically on first run).
On the first run, every vehicle currently in inventory will be reported as
"new" -- that's expected, since there's no prior state to compare against.
After that, only genuinely new listings will show up.

Usage:
    python3 detect_new_vehicles.py --base-url https://www.metronissanmontclair.com/inventory/used/

Outputs:
    new_vehicles.json   -- list of {vin, url, year, make, model, trim} added this run
    known_vins.json      -- running state file (don't delete between runs)

Notes / honesty about limitations:
- This relies on the public listing pages being readable HTML (no login wall),
  which they are. It does light, infrequent polling (intended: every 30-60+
  minutes) -- please don't drop the interval to seconds; that's unnecessary
  and discourteous to the dealer's hosting.
- It parses VIN + year/make/model out of the vehicle detail page URL slug,
  which has been consistent (e.g. /inventory/Used-2024-Nissan-Kicks-SV-VIN/).
  If the dealer changes their URL scheme this will need a quick update.
"""

import argparse
import json
import os
import re
import sys
import time
from urllib.parse import urljoin

import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; InventoryWatcher/1.0; +personal social-media tool)"
}

# Match a vehicle-detail-page slug wherever it appears, in any link form:
#   https://www.metronissanmontclair.com/inventory/Used-...-VIN/
#   /inventory/Used-...-VIN/
#   [/inventory/Used-...-VIN/](https://.../inventory/Used-...-VIN/)
# The reliable anchor is the "/inventory/Used-<stuff>-<17-char VIN>/" slug
# itself, so we key on that and rebuild the absolute URL from the base
# domain. This is far more robust than requiring an absolute href, which
# broke because the site also uses relative links.
VDP_RE = re.compile(
    r'/inventory/(Used-[^"/\s\)\]]+-([A-HJ-NPR-Z0-9]{17}))/'
)


def _domain_root(base_url):
    m = re.match(r'(https?://[^/]+)', base_url)
    return m.group(1) if m else base_url.rstrip("/")


def fetch(url):
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    return resp.text


def parse_slug(slug, vin):
    """Best-effort parse of /Used-YEAR-MAKE-MODEL-TRIM-VIN/ into fields."""
    parts = slug.split("-")
    # parts[0] == 'Used', parts[-1] == VIN
    try:
        year = parts[1]
        make = parts[2].replace("_", " ")
        trim = parts[-2].replace("_", " ") if len(parts) > 4 else ""
        model = " ".join(p.replace("_", " ") for p in parts[3:-2]) or (
            parts[3].replace("_", " ") if len(parts) > 3 else ""
        )
    except IndexError:
        year, make, model, trim = "", "", "", ""
    return year, make, model, trim


def collect_listings(base_url, max_pages=10, delay_seconds=1.0):
    """Walk paginated inventory pages, return dict {vin: info}."""
    found = {}
    root = _domain_root(base_url)
    base_no_slash = base_url.rstrip("/")

    for page_num in range(1, max_pages + 1):
        # The real site paginates as .../inventory/used-page-2/ etc.
        url = base_no_slash + "/" if page_num == 1 else base_no_slash + f"-page-{page_num}/"
        try:
            html = fetch(url)
        except requests.RequestException as e:
            print(f"  (stopped paging at page {page_num}: {e})")
            break

        matches = VDP_RE.findall(html)
        if not matches:
            break

        new_on_page = 0
        for slug, vin in matches:
            if vin not in found:
                year, make, model, trim = parse_slug(slug, vin)
                found[vin] = {
                    "vin": vin,
                    "url": f"{root}/inventory/{slug}/",
                    "year": year,
                    "make": make,
                    "model": model,
                    "trim": trim,
                }
                new_on_page += 1

        print(f"  page {page_num}: {len(matches)} slug matches ({new_on_page} new VINs)")
        time.sleep(delay_seconds)

    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True,
                     help="e.g. https://www.metronissanmontclair.com/inventory/used/")
    ap.add_argument("--state-file", default="known_vins.json")
    ap.add_argument("--out-file", default="new_vehicles.json")
    ap.add_argument("--max-pages", type=int, default=10)
    args = ap.parse_args()

    print(f"Checking inventory at {args.base_url} ...")
    current = collect_listings(args.base_url, max_pages=args.max_pages)
    print(f"Total listings found: {len(current)}")

    known = {}
    first_run = not os.path.exists(args.state_file)
    if not first_run:
        known = json.load(open(args.state_file))

    new_vins = [v for v in current if v not in known]
    new_listings = [current[v] for v in new_vins]

    json.dump(current, open(args.state_file, "w"), indent=2)
    json.dump(new_listings, open(args.out_file, "w"), indent=2)

    if first_run:
        print(f"First run -- saved baseline of {len(current)} VINs. "
              f"No videos will be triggered this time.")
        json.dump([], open(args.out_file, "w"), indent=2)
    else:
        print(f"New vehicles since last check: {len(new_listings)}")
        for v in new_listings:
            print(f"  + {v['year']} {v['make']} {v['model']} {v['trim']} -- {v['vin']}")


if __name__ == "__main__":
    main()
