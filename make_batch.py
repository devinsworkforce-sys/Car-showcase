#!/usr/bin/env python3
"""
make_batch.py

Make videos for vehicles CURRENTLY listed on the lot (not just future
arrivals). Useful for catching up your existing inventory. Processes up to
--limit vehicles, newest-listed first, skips any VIN that already has a
video (tracked in videoed_vins.json, shared with the automation so the two
never duplicate each other's work), and emails each one as it finishes if
--email is passed.

Usage:
    python3 make_batch.py \
        --base-url https://www.metronissanmontclair.com/inventory/used/ \
        --dealer-name "Metro Nissan of Montclair" \
        --dealer-phone "818-450-6500" \
        --salesperson "Devin Rangel" \
        --limit 10 \
        --email

For --email to work from your own computer, the SMTP_* environment variables
must be set in the same terminal session first (see README "make --email
work on your Mac"). The automation on GitHub already has them as secrets.
"""

import argparse
import json
import os
import subprocess
import sys

import requests

import detect_new_vehicles as detector
import fetch_vehicle_photos as photos_fetcher
import run_pipeline as pipeline

HEADERS = photos_fetcher.HEADERS


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--dealer-name", required=True)
    ap.add_argument("--dealer-phone", default="")
    ap.add_argument("--salesperson", default="")
    ap.add_argument("--cta", default="DM \"INFO\" BEFORE IT'S GONE")
    ap.add_argument("--limit", type=int, default=10,
                     help="Max number of vehicles to make videos for this run")
    ap.add_argument("--videoed-state-file", default="videoed_vins.json")
    ap.add_argument("--orientation", default="vertical", choices=["vertical", "square", "horizontal"])
    ap.add_argument("--out-dir", default="ready_to_post")
    ap.add_argument("--work-dir", default="work")
    ap.add_argument("--email", action="store_true",
                     help="Email each finished video (requires SMTP_* env vars set)")
    args = ap.parse_args()

    os.makedirs(args.work_dir, exist_ok=True)
    os.makedirs(args.out_dir, exist_ok=True)
    script_dir = os.path.dirname(os.path.abspath(__file__))

    print("Reading current inventory...")
    current = detector.collect_listings(args.base_url)
    videoed = set(json.load(open(args.videoed_state_file))) if os.path.exists(args.videoed_state_file) else set()

    # Newest-listed first: collect_listings preserves page order (top of
    # page 1 = newest), so just respect that order and drop already-done VINs.
    todo = [vin for vin in current if vin not in videoed][:args.limit]

    if not todo:
        print("Nothing to do -- every current vehicle already has a video.")
        return

    print(f"Will make videos for {len(todo)} vehicle(s) (limit {args.limit}). "
          f"{len(videoed)} already done and skipped.\n")

    # Pre-scan pass: fetch each candidate's photo URLs once, then detect which
    # image hashes are reused across multiple different cars. Those reused
    # images are stock/placeholder graphics (a real photo is unique to one
    # car), so any vehicle whose photos are ALL placeholders gets skipped --
    # it just hasn't been photographed yet.
    print("Scanning photos to detect stock/placeholder images...")
    vin_html = {}
    vin_urls = {}
    for vin in todo:
        try:
            html = photos_fetcher.fetch_html(current[vin]["url"])
        except requests.RequestException:
            continue
        vin_html[vin] = html
        vin_urls[vin] = photos_fetcher.extract_photo_urls(html)
    placeholder_hashes = photos_fetcher.find_placeholder_hashes(vin_urls)
    if placeholder_hashes:
        print(f"  detected {len(placeholder_hashes)} reused stock/placeholder image(s) "
              f"-- cars using only these will be skipped until real photos are added.\n")

    made = 0
    for idx, vin in enumerate(todo, 1):
        info = current[vin]
        label = f"{info['year']} {info['make']} {info['model']} {info['trim']}".strip()
        print(f"[{idx}/{len(todo)}] {label} ({vin})")

        html = vin_html.get(vin)
        if html is None:
            print("  couldn't load page earlier, skipping.")
            continue

        photo_urls = photos_fetcher.extract_photo_urls(
            html, extra_placeholder_hashes=placeholder_hashes)
        if len(photo_urls) < 2:
            print(f"  no real photos yet (only stock/placeholder images) -- skipping. "
                  f"This car will be picked up automatically once real photos are added.")
            continue

        vin_photo_dir = os.path.join(args.work_dir, "photos", vin)
        ext_dir = os.path.join(vin_photo_dir, "exterior")
        int_dir = os.path.join(vin_photo_dir, "interior")
        os.makedirs(ext_dir, exist_ok=True)
        os.makedirs(int_dir, exist_ok=True)
        split_idx = max(1, int(len(photo_urls) * 0.6))
        for i, url in enumerate(photo_urls):
            target = ext_dir if i < split_idx else int_dir
            ext = os.path.splitext(url)[1] or ".jpg"
            try:
                photos_fetcher.download(url, os.path.join(target, f"{i:02d}{ext}"))
            except requests.RequestException as e:
                print(f"  photo download failed: {e}")

        price, mileage = pipeline.scrape_details(html)

        out_video_dir = os.path.join(args.out_dir, vin)
        os.makedirs(out_video_dir, exist_ok=True)
        video_path = os.path.join(out_video_dir, "video.mp4")

        cfg = {
            "year": info["year"], "make": info["make"], "model": info["model"],
            "trim": info["trim"], "price": price, "mileage": mileage, "stock": vin,
            "dealer_name": args.dealer_name, "dealer_phone": args.dealer_phone,
            "salesperson": args.salesperson, "cta": args.cta,
            "exterior_dir": ext_dir, "interior_dir": int_dir,
            "output": video_path, "orientation": args.orientation,
        }
        cfg_path = os.path.join(args.work_dir, f"{vin}_config.json")
        json.dump(cfg, open(cfg_path, "w"), indent=2)

        print("  rendering...")
        result = subprocess.run(
            [sys.executable, os.path.join(script_dir, "make_showcase_video.py"), "--config", cfg_path],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            print(f"  render failed:\n{result.stderr}")
            continue

        caption = pipeline.build_caption(info, price, mileage, args.dealer_name, info["url"])
        caption_path = os.path.join(out_video_dir, "caption.txt")
        with open(caption_path, "w") as f:
            f.write(caption)

        videoed.add(vin)
        json.dump(sorted(videoed), open(args.videoed_state_file, "w"), indent=2)
        made += 1
        print(f"  done -> {video_path}")

        if args.email:
            email_result = subprocess.run(
                [sys.executable, os.path.join(script_dir, "notify.py"),
                 "--video", video_path, "--caption", caption_path,
                 "--photos-dir", vin_photo_dir, "--subject", label],
                capture_output=True, text=True,
            )
            if email_result.returncode != 0:
                print(f"  email failed (video still saved): check SMTP_* env vars")
            else:
                print(f"  emailed to {os.environ.get('NOTIFY_TO', '(NOTIFY_TO not set)')}")

    print(f"\nFinished. Made {made} new video(s); all saved under {args.out_dir}/.")


if __name__ == "__main__":
    main()
