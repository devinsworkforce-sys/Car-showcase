#!/usr/bin/env python3
"""
fetch_vehicle_photos.py

Given a vehicle detail page (VDP) URL, downloads whatever photos the listing
has and sorts them into exterior/ and interior/ subfolders for use with
make_showcase_video.py.

Usage:
    python3 fetch_vehicle_photos.py --vdp-url "https://www.metronissanmontclair.com/inventory/Used-2024-Nissan-Kicks-SV-VIN/" --vin VIN --out-dir photos

Honesty about limitations:
- These are still-photo galleries, not real 360-degree spins. Quality and
  photo count vary a lot by listing -- some have ~15-19 angles, some
  (freshly-added "In Transit" cars in particular) only have a single
  generic placeholder image. The script skips obvious placeholder images
  automatically where it can detect them by filename hash, but you should
  glance at what gets downloaded before generating a video for a brand-new
  listing -- if there's only 1-2 real photos, a "showcase" video isn't
  going to look great no matter how it's assembled, and it's worth waiting
  until the dealer uploads more photos (often happens within a day or two).
- There's no true semantic "this photo is the dashboard" tag in the public
  feed, so exterior/interior sorting is a position-based heuristic (first
  ~60% of photos = exterior, rest = interior). It's right most of the time
  for standard dealer photo sets but not guaranteed -- spot check it.
"""

import argparse
import os
import re
import sys

import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; InventoryWatcher/1.0; +personal social-media tool)"
}

IMG_URL_RE = re.compile(
    r'https://content\.homenetiol\.com/[^\s"\'<>]+?\.(?:jpg|jpeg|png|webp)',
    re.IGNORECASE,
)

# This dealer's photo CDN serves the same photo at multiple sizes via a
# /WIDTHxHEIGHT/ path segment (e.g. /640x480/hash.jpg vs /1600x1200/hash.jpg
# for the identical photo). Whatever size happens to be linked in the page
# is often a small thumbnail -- rewriting to the larger size noticeably
# improves video quality since it's no longer being stretched up from a
# tiny source image.
_SIZE_SEGMENT_RE = re.compile(r"/\d{2,4}x\d{2,4}/")
PREFERRED_SIZE = "/1600x1200/"


def upsize_photo_url(url):
    if _SIZE_SEGMENT_RE.search(url):
        return _SIZE_SEGMENT_RE.sub(PREFERRED_SIZE, url, count=1)
    return url

# Filename hash that showed up repeatedly as a generic "no photo available"
# placeholder on this dealer's site as of June 2026. New placeholder hashes
# may appear over time -- if downloaded images all look identical/wrong,
# add the hash here.
KNOWN_PLACEHOLDER_HASHES = {
    "d2c4dae1f55142c885cc8aab98d7cea7",
}


def fetch_html(url):
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    return resp.text


def extract_photo_urls(html):
    urls = IMG_URL_RE.findall(html)
    urls = [upsize_photo_url(u) for u in urls]
    # de-dupe while preserving order (two thumbnail sizes of the same photo
    # become identical URLs after upsizing, so this also removes those dupes)
    seen, ordered = set(), []
    for u in urls:
        if u not in seen:
            seen.add(u)
            ordered.append(u)
    # drop known placeholders
    real = [u for u in ordered if not any(h in u for h in KNOWN_PLACEHOLDER_HASHES)]
    return real


def download(url, path):
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    with open(path, "wb") as f:
        f.write(resp.content)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vdp-url", required=True)
    ap.add_argument("--vin", required=True)
    ap.add_argument("--out-dir", default="photos")
    ap.add_argument("--exterior-ratio", type=float, default=0.6,
                     help="Fraction of photos (in listing order) treated as exterior")
    args = ap.parse_args()

    print(f"Fetching {args.vdp_url}")
    html = fetch_html(args.vdp_url)
    photo_urls = extract_photo_urls(html)

    if not photo_urls:
        print("No real photos found (only placeholder, or page format changed).")
        sys.exit(1)

    print(f"Found {len(photo_urls)} usable photos.")

    vin_dir = os.path.join(args.out_dir, args.vin)
    ext_dir = os.path.join(vin_dir, "exterior")
    int_dir = os.path.join(vin_dir, "interior")
    os.makedirs(ext_dir, exist_ok=True)
    os.makedirs(int_dir, exist_ok=True)

    split_idx = max(1, int(len(photo_urls) * args.exterior_ratio))

    for i, url in enumerate(photo_urls):
        target_dir = ext_dir if i < split_idx else int_dir
        ext = os.path.splitext(url)[1] or ".jpg"
        out_path = os.path.join(target_dir, f"{i:02d}{ext}")
        try:
            download(url, out_path)
        except requests.RequestException as e:
            print(f"  failed on {url}: {e}")

    print(f"Saved {split_idx} exterior + {len(photo_urls) - split_idx} interior photos to {vin_dir}")
    print("Spot-check the split before generating the video -- move any "
          "miscategorized photos between the two folders if needed.")


if __name__ == "__main__":
    main()
