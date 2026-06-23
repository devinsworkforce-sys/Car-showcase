#!/usr/bin/env python3
"""
run_pipeline.py

The "main" entry point. Run this on a schedule (every 30-60+ minutes) and it
will:
  1. Check the dealer's public used-inventory pages for VINs not seen before
  2. For each new vehicle: pull its photos, sort exterior/interior
  3. Scrape price/mileage off the vehicle detail page
  4. Generate a branded showcase video
  5. Generate a suggested social caption (plain text, ready to paste)

Everything lands in ready_to_post/<VIN>/ -- video.mp4 + caption.txt.

Usage:
    python3 run_pipeline.py --base-url https://www.metronissanmontclair.com/inventory/used/ \\
        --dealer-name "Metro Nissan of Montclair" --dealer-phone "(909) 403-1121"

First run note: the first time you run this, every car currently listed will
look "new" (there's no prior history to compare against), so it will quietly
save a baseline and generate nothing. From the second run onward, only
genuinely new listings get videos made.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys

import requests

import detect_new_vehicles as detector
import fetch_vehicle_photos as photos_fetcher

HEADERS = photos_fetcher.HEADERS

PRICE_RE = re.compile(r'Sale Price[^$]{0,60}?\$\s*([\d,]+)')
RETAIL_PRICE_RE = re.compile(r'Retail Price[^$]{0,60}?\$\s*([\d,]+)')
MILEAGE_RE = re.compile(r'([\d]{1,3}(?:,\d{3})*)\s*Miles')


def scrape_details(vdp_html):
    price_match = PRICE_RE.search(vdp_html) or RETAIL_PRICE_RE.search(vdp_html)
    mileage_match = MILEAGE_RE.search(vdp_html)
    price = f"${price_match.group(1)}" if price_match else ""
    mileage = f"{mileage_match.group(1)} mi" if mileage_match else ""
    return price, mileage


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--dealer-name", required=True)
    ap.add_argument("--dealer-phone", default="")
    ap.add_argument("--salesperson", default="")
    ap.add_argument("--cta", default="DM \"INFO\" BEFORE IT'S GONE")
    ap.add_argument("--state-file", default="known_vins.json")
    ap.add_argument("--videoed-state-file", default="videoed_vins.json")
    ap.add_argument("--work-dir", default="work")
    ap.add_argument("--out-dir", default="ready_to_post")
    ap.add_argument("--orientation", default="vertical", choices=["vertical", "square", "horizontal"])
    ap.add_argument("--notify", action="store_true",
                     help="Email the finished video automatically (requires SMTP_* env vars, see README)")
    args = ap.parse_args()

    os.makedirs(args.work_dir, exist_ok=True)
    os.makedirs(args.out_dir, exist_ok=True)

    print("Step 1/3: checking inventory for new vehicles...")
    current = detector.collect_listings(args.base_url)
    known = json.load(open(args.state_file)) if os.path.exists(args.state_file) else {}
    videoed = set(json.load(open(args.videoed_state_file))) if os.path.exists(args.videoed_state_file) else set()
    first_run = not known
    new_vins = [v for v in current if v not in known]
    json.dump(current, open(args.state_file, "w"), indent=2)

    if first_run:
        print(f"First run: saved baseline of {len(current)} vehicles. "
              f"Nothing to generate yet -- next run will catch real new arrivals.")
        return

    # Candidates = brand-new VINs we've never seen, PLUS any VIN that's still
    # listed but never got a video made (e.g. it had too few photos last
    # time -- this is what lets a car get picked up automatically once the
    # dealer adds more photos a day or two later, instead of being skipped
    # forever).
    retry_vins = [v for v in current if v in known and v not in videoed]
    candidates = list(dict.fromkeys(new_vins + retry_vins))  # de-duped, order preserved

    if not candidates:
        print("No new vehicles, and nothing pending a retry.")
        return

    print(f"Found {len(new_vins)} brand-new vehicle(s) and {len(retry_vins)} "
          f"pending retry: {', '.join(candidates)}")

    # Pre-scan to detect stock/placeholder images reused across vehicles, so
    # cars that haven't been photographed yet get skipped (and retried later)
    # instead of producing a video full of generic stock graphics.
    cand_html = {}
    cand_urls = {}
    for vin in candidates:
        try:
            cand_html[vin] = photos_fetcher.fetch_html(current[vin]["url"])
            cand_urls[vin] = photos_fetcher.extract_photo_urls(cand_html[vin])
        except requests.RequestException:
            continue
    placeholder_hashes = photos_fetcher.find_placeholder_hashes(cand_urls)

    for vin in candidates:
        info = current[vin]
        print(f"\nStep 2/3: processing {info['year']} {info['make']} {info['model']} ({vin})")

        vdp_html = cand_html.get(vin)
        if vdp_html is None:
            print("  could not load VDP page earlier, skipping.")
            continue

        photo_urls = photos_fetcher.extract_photo_urls(
            vdp_html, extra_placeholder_hashes=placeholder_hashes)
        if len(photo_urls) < 2:
            print(f"  no real photos yet (only stock/placeholder images) -- skipping. "
                  f"This VIN will be checked again automatically on future runs "
                  f"and picked up as soon as real photos are added.")
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
                print(f"  photo download failed ({url}): {e}")

        price, mileage = scrape_details(vdp_html)

        out_video_dir = os.path.join(args.out_dir, vin)
        os.makedirs(out_video_dir, exist_ok=True)
        video_path = os.path.join(out_video_dir, "video.mp4")

        cfg = {
            "year": info["year"],
            "make": info["make"],
            "model": info["model"],
            "trim": info["trim"],
            "price": price,
            "mileage": mileage,
            "stock": vin,
            "dealer_name": args.dealer_name,
            "dealer_phone": args.dealer_phone,
            "salesperson": args.salesperson,
            "cta": args.cta,
            "exterior_dir": ext_dir,
            "interior_dir": int_dir,
            "output": video_path,
            "orientation": args.orientation,
        }
        cfg_path = os.path.join(args.work_dir, f"{vin}_config.json")
        json.dump(cfg, open(cfg_path, "w"), indent=2)

        print("Step 3/3: rendering video...")
        script_dir = os.path.dirname(os.path.abspath(__file__))
        result = subprocess.run(
            [sys.executable, os.path.join(script_dir, "make_showcase_video.py"), "--config", cfg_path],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            print(f"  video generation failed:\n{result.stderr}")
            continue

        caption = build_caption(info, price, mileage, args.dealer_name, info["url"])
        caption_path = os.path.join(out_video_dir, "caption.txt")
        with open(caption_path, "w") as f:
            f.write(caption)

        print(f"  done -> {video_path}")

        # Mark as videoed right away (and save immediately, not just at the
        # end) so a later failure in this run can't cause a duplicate video
        # next time.
        videoed.add(vin)
        json.dump(sorted(videoed), open(args.videoed_state_file, "w"), indent=2)

        if args.notify:
            subject = f"New: {info['year']} {info['make']} {info['model']} {info['trim']}".strip()
            notify_result = subprocess.run(
                [sys.executable, os.path.join(script_dir, "notify.py"),
                 "--video", video_path, "--caption", caption_path, "--subject", subject],
                capture_output=True, text=True,
            )
            if notify_result.returncode != 0:
                print(f"  email notification failed:\n{notify_result.stderr}")
            else:
                print(f"  emailed to {os.environ.get('NOTIFY_TO', '(NOTIFY_TO not set)')}")

    print(f"\nAll set. Check {args.out_dir}/ for finished videos + captions.")


def build_caption(info, price, mileage, dealer_name, vdp_url):
    name = f"{info['year']} {info['make']} {info['model']} {info['trim']}".strip()

    hook = f"POV: you just found a {info['year']} {info['make']} {info['model']} for {price} \U0001F440" if price \
        else f"POV: you just found this {name} \U0001F440"

    parts = [hook, ""]
    specs = []
    if price:
        specs.append(f"\U0001F4B0 {price}")
    if mileage:
        specs.append(f"\U0001F6E3 {mileage}")
    if specs:
        parts.append("  ".join(specs))
        parts.append("")
    parts.append(f"\U0001F4CD {dealer_name}")
    parts.append("\U0001F525 DM \"INFO\" or comment below before it's gone")
    parts.append("")
    parts.append(
        "#usedcars #carsforsale #cardeals #fyp #carsoftiktok #dealalert "
        f"#{info['make'].replace(' ', '')} #{info['model'].replace(' ', '')}"
    )
    return "\n".join(parts)


if __name__ == "__main__":
    main()
