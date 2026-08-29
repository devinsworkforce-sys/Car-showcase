#!/usr/bin/env python3
"""
fetch_vehicle_photos.py

Downloads and filters vehicle photos from a dealer's vehicle detail page
(VDP). Supports two photo-hosting patterns seen so far:
  - content.homenetiol.com  (FoxDealer sites, e.g. Metro Nissan of Montclair)
  - vehicle-images.carscommerce.inc  (Dealer Inspire sites, e.g. Mark
    Christopher Auto Center -- URLs here embed the VIN directly:
    https://vehicle-images.carscommerce.inc/<dealer-id>/<VIN>/<hash>.jpg)

Filters out two kinds of non-real photos before a video gets built from them:
  1. Known/reused placeholder graphics (a real photo is unique to one car;
     a placeholder graphic gets reused across many cars)
  2. Manufacturer studio/press photos (car on a near-pure-white background,
     not an actual lot photo)
"""

import os
import re

import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; InventoryWatcher/1.0; +personal social-media tool)"
}

# Matches photo URLs from either known hosting pattern.
IMG_URL_RE = re.compile(
    r'https://content\.homenetiol\.com/[^\s"\'<>]+?\.(?:jpg|jpeg|png|webp)'
    r'|https://vehicle-images\.carscommerce\.inc/[^\s"\'<>]+?\.(?:jpg|jpeg|png|webp)',
    re.IGNORECASE,
)

# homenetiol.com serves the same photo at multiple sizes via a
# /WIDTHxHEIGHT/ path segment -- rewrite to the larger size for quality.
_SIZE_SEGMENT_RE = re.compile(r"/\d{2,4}x\d{2,4}/")
PREFERRED_SIZE = "/1600x1200/"


def upsize_photo_url(url):
    if _SIZE_SEGMENT_RE.search(url):
        return _SIZE_SEGMENT_RE.sub(PREFERRED_SIZE, url, count=1)
    return url


# Known generic "no photo available" placeholder image hashes seen on
# FoxDealer sites. New placeholder hashes may appear over time -- reused
# images are ALSO auto-detected dynamically via find_placeholder_hashes(),
# so this list is a backstop, not the only line of defense.
KNOWN_PLACEHOLDER_HASHES = {
    "d2c4dae1f55142c885cc8aab98d7cea7",
}

_HASH_RE = re.compile(r"/([0-9a-f]{16,40})\.(?:jpg|jpeg|png|webp)", re.IGNORECASE)


def image_hash(url):
    m = _HASH_RE.search(url)
    return m.group(1).lower() if m else url


def find_placeholder_hashes(vin_to_urls, reuse_threshold=2):
    """Given {vin: [photo_urls]}, return image hashes that appear across
    reuse_threshold or more DIFFERENT vehicles -- almost certainly stock/
    placeholder images, since a real photo is unique to one car."""
    hash_vins = {}
    for vin, urls in vin_to_urls.items():
        for h in {image_hash(u) for u in urls}:
            hash_vins.setdefault(h, set()).add(vin)
    return {h for h, vins in hash_vins.items() if len(vins) >= reuse_threshold}


def fetch_html(url):
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    return resp.text


def extract_photo_urls(html, extra_placeholder_hashes=None):
    urls = IMG_URL_RE.findall(html)
    # findall with an alternation containing no groups returns whole matches
    # as strings directly (no groups used above), so urls is already a
    # flat list of full URL strings.
    urls = [upsize_photo_url(u) for u in urls]

    seen, ordered = set(), []
    for u in urls:
        if u not in seen:
            seen.add(u)
            ordered.append(u)

    block = set(KNOWN_PLACEHOLDER_HASHES)
    if extra_placeholder_hashes:
        block |= set(extra_placeholder_hashes)
    real = [u for u in ordered if image_hash(u) not in block
            and not any(h in u for h in KNOWN_PLACEHOLDER_HASHES)]
    return real


def download(url, path):
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    with open(path, "wb") as f:
        f.write(resp.content)


def looks_like_studio_photo(image_path, white_thresh=238, frac_needed=0.80):
    """Return True if the image looks like a manufacturer studio/press photo
    (car on a near-pure-white seamless background) rather than a real photo
    taken on the lot (asphalt, sky, buildings in the background)."""
    try:
        from PIL import Image
        img = Image.open(image_path).convert("RGB")
    except Exception:
        return False

    W, H = img.size
    if W < 50 or H < 50:
        return False
    px = img.load()
    border = max(2, int(min(W, H) * 0.04))

    white = 0
    total = 0
    for y in range(0, H, 2):
        for x in range(0, W, 2):
            on_edge = (x < border or x >= W - border or
                       y < border or y >= H - border)
            if not on_edge:
                continue
            r, g, b = px[x, y]
            total += 1
            if r >= white_thresh and g >= white_thresh and b >= white_thresh:
                white += 1

    if total == 0:
        return False
    return (white / total) >= frac_needed
