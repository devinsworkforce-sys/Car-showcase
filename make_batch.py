#!/usr/bin/env python3
"""
make_batch.py

Make videos for vehicles CURRENTLY listed on the lot (not just future
arrivals) -- useful right after switching dealerships, when you want
content today instead of waiting for a new arrival to trigger the
automation. Processes up to --limit vehicles, skips any VIN that already
has a video (tracked in videoed_vins.json, shared with the automation so
the two never duplicate each other's work), and emails each one as it
finishes if --email is passed.

Usage:
    python3 make_batch.py \
        --base-url https://www.markchristopher.com/used-vehicles/ \
        --platform dealerinspire \
        --dealer-name "Mark Christopher Auto Center" \
        --dealer-phone "818-450-6500" \
        --salesperson "Devin Rangel" \
        --limit 10 \
        --email
"""

import argparse
import json
import os
import subprocess
import sys

import requests

import fetch_vehicle_photos as photos_fetcher
import run_pipeline as pipeline

HEADERS = photos_fetcher.HEADERS


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--platform", default="foxdealer", choices=["foxdealer", "dealerinspire"])
    ap.add_argument("--dealer-name", required=True)
    ap.add_argument("--dealer-phone", default="")
    ap.add_argument("--salesperson", default="")
    ap.add_argument("--cta", default="DM \"INFO\" BEFORE IT'S GONE")
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--videoed-state-file", default="videoed_vins.json")
    ap.add_argument("--orientation", default="vertical", choices=["vertical", "square", "horizontal"])
    ap.add_argument("--out-dir", default="ready_to_post")
    ap.add_argument("--work-dir", default="work")
    ap.add_argument("--email", action="store_true")
    args = ap.parse_args()

    os.makedirs(args.work_dir, exist_ok=True)
    os.makedirs(args.out_dir, exist_ok=True)
    script_dir = os.path.dirname(os.path.abspath(__file__))

    detector = pipeline.get_detector(args.platform)

    print("Reading current inventory...")
    current = detector.collect_listings(args.base_url)
    videoed = set(json.load(open(args.videoed_state_file))) if os.path.exists(args.videoed_state_file) else set()

    todo = [vin for vin in current if vin not in videoed][:args.limit]
    if not todo:
        print("Nothing to do -- every current vehicle already has a video.")
        return

    print(f"Will make videos for {len(todo)} vehicle(s) (limit {args.limit}). "
          f"{len(videoed)} already done and skipped.\n")

    print("Scanning photos to detect stock/placeholder images...")
    vin_html, vin_urls = {}, {}
    for vin in todo:
        try:
            html = photos_fetcher.fetch_html(current[vin]["url"])
        except requests.RequestException:
            continue
        vin_html[vin] = html
        vin_urls[vin] = photos_fetcher.extract_photo_urls(html)
    placeholder_hashes = photos_fetcher.find_placeholder_hashes(vin_urls)
    if placeholder_hashes:
        print(f"  detected {len(placeholder_hashes)} reused stock/placeholder image(s)\n")

    made = 0
    for idx, vin in enumerate(todo, 1):
        info = current[vin]
        label = f"{info['year']} {info['make']} {info['model']} {info['trim']}".strip()
        print(f"[{idx}/{len(todo)}] {label} ({vin})")

        html = vin_html.get(vin)
        if html is None:
            print("  couldn't load page earlier, skipping.")
            continue

        photo_urls = photos_fetcher.extract_photo_urls(html, extra_placeholder_hashes=placeholder_hashes)
        if len(photo_urls) < 2:
            print("  no real photos yet -- skipping.")
            continue

        vin_photo_dir = os.path.join(args.work_dir, "photos", vin)
        ext_dir = os.path.join(vin_photo_dir, "exterior")
        int_dir = os.path.join(vin_photo_dir, "interior")
        os.makedirs(ext_dir, exist_ok=True)
        os.makedirs(int_dir, exist_ok=True)

        stage_dir = os.path.join(vin_photo_dir, "_stage")
        os.makedirs(stage_dir, exist_ok=True)
        real_photos = []
        for i, url in enumerate(photo_urls):
            ext = os.path.splitext(url)[1] or ".jpg"
            sp = os.path.join(stage_dir, f"{i:02d}{ext}")
            try:
                photos_fetcher.download(url, sp)
            except requests.RequestException as e:
                print(f"  photo download failed: {e}")
                continue
            if photos_fetcher.looks_like_studio_photo(sp):
                os.remove(sp)
                continue
            real_photos.append(sp)

        if len(real_photos) < 2:
            print("  only manufacturer/studio stock photos found -- skipping.")
            continue

        split_idx = max(1, int(len(real_photos) * 0.6))
        for i, sp in enumerate(real_photos):
            target = ext_dir if i < split_idx else int_dir
            os.rename(sp, os.path.join(target, os.path.basename(sp)))

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

        caption = pipeline.build_caption(info, price, mileage, args.dealer_name, info["url"], args.dealer_phone)
        caption_path = os.path.join(out_video_dir, "caption.txt")
        with open(caption_path, "w") as f:
            f.write(caption)

        ext_files = sorted(os.listdir(ext_dir)) if os.path.isdir(ext_dir) else []
        int_files = sorted(os.listdir(int_dir)) if os.path.isdir(int_dir) else []
        best_photos = [os.path.join(ext_dir, f) for f in ext_files[:4]] + \
                      [os.path.join(int_dir, f) for f in int_files[:4]]
        photo_list_path = os.path.join(out_video_dir, "photo_list.txt")
        with open(photo_list_path, "w") as f:
            f.write("\n".join(best_photos))

        videoed.add(vin)
        json.dump(sorted(videoed), open(args.videoed_state_file, "w"), indent=2)
        made += 1
        print(f"  done -> {video_path}")

        if args.email:
            subject = f"{label}"
            if price:
                subject += f" — {price}"
            email_result = subprocess.run(
                [sys.executable, os.path.join(script_dir, "notify.py"),
                 "--video", video_path, "--caption", caption_path,
                 "--photo-list", photo_list_path, "--subject", subject],
                capture_output=True, text=True,
            )
            if email_result.returncode != 0:
                print("  email failed (video still saved): check SMTP_* env vars")
            else:
                print(f"  emailed to {os.environ.get('NOTIFY_TO', '(NOTIFY_TO not set)')}")

    print(f"\nFinished. Made {made} new video(s); all saved under {args.out_dir}/.")


if __name__ == "__main__":
    main()
