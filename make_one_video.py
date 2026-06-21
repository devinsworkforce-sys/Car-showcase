#!/usr/bin/env python3
"""
make_one_video.py

Generate a showcase video for ONE specific real listing right now, by
pasting its vehicle detail page URL. Useful for testing, or whenever you
want a video for a car that's already on the site (not just brand-new
arrivals, which is what run_pipeline.py watches for automatically).

Usage:
    python3 make_one_video.py \
        --vdp-url "https://www.metronissanmontclair.com/inventory/Used-2024-Nissan-Kicks-SV-3N1CP5CV4RL561172/" \
        --dealer-name "Metro Nissan of Montclair" \
        --dealer-phone "(909) 403-1121"

Grab a --vdp-url by going to the inventory page, clicking into any car, and
copying the URL from your browser's address bar.
"""

import argparse
import json
import os
import re
import subprocess
import sys

import detect_new_vehicles as detector
import fetch_vehicle_photos as photos_fetcher
import run_pipeline as pipeline

SLUG_RE = re.compile(r'/inventory/(Used-[^/"]+-([A-HJ-NPR-Z0-9]{17}))/')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vdp-url", required=True)
    ap.add_argument("--dealer-name", required=True)
    ap.add_argument("--dealer-phone", default="")
    ap.add_argument("--salesperson", default="")
    ap.add_argument("--cta", default="DM \"INFO\" BEFORE IT'S GONE")
    ap.add_argument("--orientation", default="vertical", choices=["vertical", "square", "horizontal"])
    ap.add_argument("--out-dir", default="ready_to_post")
    ap.add_argument("--work-dir", default="work")
    args = ap.parse_args()

    m = SLUG_RE.search(args.vdp_url)
    if not m:
        sys.exit("Couldn't find a VIN in that URL. Make sure it's a full vehicle "
                  "page link, like .../inventory/Used-2024-Nissan-Kicks-SV-VIN/")
    slug, vin = m.groups()
    year, make, model, trim = detector.parse_slug(slug, vin)

    print(f"Fetching {args.vdp_url}")
    html = photos_fetcher.fetch_html(args.vdp_url)
    photo_urls = photos_fetcher.extract_photo_urls(html)
    if len(photo_urls) < 2:
        sys.exit(f"Only found {len(photo_urls)} real photo(s) for this listing -- "
                  f"not enough for a good video. Try a different car, or wait for "
                  f"the dealer to add more photos to this one.")
    print(f"Found {len(photo_urls)} photos")

    vin_photo_dir = os.path.join(args.work_dir, "photos", vin)
    ext_dir = os.path.join(vin_photo_dir, "exterior")
    int_dir = os.path.join(vin_photo_dir, "interior")
    os.makedirs(ext_dir, exist_ok=True)
    os.makedirs(int_dir, exist_ok=True)
    split_idx = max(1, int(len(photo_urls) * 0.6))
    for i, url in enumerate(photo_urls):
        target = ext_dir if i < split_idx else int_dir
        ext = os.path.splitext(url)[1] or ".jpg"
        photos_fetcher.download(url, os.path.join(target, f"{i:02d}{ext}"))

    price, mileage = pipeline.scrape_details(html)

    out_video_dir = os.path.join(args.out_dir, vin)
    os.makedirs(out_video_dir, exist_ok=True)
    video_path = os.path.join(out_video_dir, "video.mp4")

    cfg = {
        "year": year, "make": make, "model": model, "trim": trim,
        "price": price, "mileage": mileage, "stock": vin,
        "dealer_name": args.dealer_name, "dealer_phone": args.dealer_phone,
        "salesperson": args.salesperson,
        "cta": args.cta,
        "exterior_dir": ext_dir, "interior_dir": int_dir,
        "output": video_path, "orientation": args.orientation,
    }
    cfg_path = os.path.join(args.work_dir, f"{vin}_config.json")
    json.dump(cfg, open(cfg_path, "w"), indent=2)

    print("Rendering video...")
    script_dir = os.path.dirname(os.path.abspath(__file__))
    result = subprocess.run(
        [sys.executable, os.path.join(script_dir, "make_showcase_video.py"), "--config", cfg_path]
    )
    if result.returncode != 0:
        sys.exit("Video generation failed -- see the error above.")

    info = {"year": year, "make": make, "model": model, "trim": trim, "url": args.vdp_url}
    caption = pipeline.build_caption(info, price, mileage, args.dealer_name, args.vdp_url)
    with open(os.path.join(out_video_dir, "caption.txt"), "w") as f:
        f.write(caption)

    print(f"\nDone!")
    print(f"  Video:   {video_path}")
    print(f"  Caption: {os.path.join(out_video_dir, 'caption.txt')}")


if __name__ == "__main__":
    main()
