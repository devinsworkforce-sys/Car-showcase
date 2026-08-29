#!/usr/bin/env python3
"""
run_pipeline.py

The "main" entry point. Run this on a schedule and it will:
  1. Check the dealer's public used-inventory pages for VINs not seen before
  2. For each new/retry vehicle: pull its photos, filter out studio/stock
     shots, sort exterior/interior
  3. Scrape price/mileage off the vehicle detail page
  4. Generate a branded showcase video
  5. Generate TikTok + Facebook captions
  6. Email the video + best photos + captions

Supports two dealer website platforms via --platform:
  foxdealer      -- e.g. Metro Nissan of Montclair (plain HTML inventory)
  dealerinspire  -- e.g. Mark Christopher Auto Center (JS-rendered inventory,
                    uses a headless browser via scrape_dealerinspire.py)

First run note: the first time you run this, every car currently listed will
look "new" (no prior history to compare against), so it saves a baseline and
generates nothing. From the second run onward, only genuinely new listings
(or ones still pending a video) get processed.
"""

import argparse
import json
import os
import re
import subprocess
import sys

import requests

import fetch_vehicle_photos as photos_fetcher
from safe_state import safe_load

HEADERS = photos_fetcher.HEADERS

PRICE_RE = re.compile(r'Sale Price[^$]{0,60}?\$\s*([\d,]+)')
RETAIL_PRICE_RE = re.compile(r'Retail Price[^$]{0,60}?\$\s*([\d,]+)')
MILEAGE_RE = re.compile(r'([\d]{1,3}(?:,\d{3})*)\s*Miles')


def get_detector(platform):
    if platform == "dealerinspire":
        import scrape_dealerinspire as d
        return d
    else:
        import detect_new_vehicles as d
        return d


def scrape_details(vdp_html):
    price_match = PRICE_RE.search(vdp_html) or RETAIL_PRICE_RE.search(vdp_html)
    mileage_match = MILEAGE_RE.search(vdp_html)
    price = f"${price_match.group(1)}" if price_match else ""
    mileage = f"{mileage_match.group(1)} mi" if mileage_match else ""
    return price, mileage


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--platform", default="foxdealer",
                     choices=["foxdealer", "dealerinspire"],
                     help="Which dealer website platform this inventory page uses")
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
                     help="Email the finished video automatically (requires SMTP_* env vars)")
    args = ap.parse_args()

    os.makedirs(args.work_dir, exist_ok=True)
    os.makedirs(args.out_dir, exist_ok=True)

    detector = get_detector(args.platform)

    print(f"Step 1/3: checking inventory for new vehicles (platform: {args.platform})...")
    current = detector.collect_listings(args.base_url)
    known = safe_load(args.state_file, {})
    videoed = set(safe_load(args.videoed_state_file, []))
    first_run = not known
    new_vins = [v for v in current if v not in known]
    json.dump(current, open(args.state_file, "w"), indent=2)

    if first_run:
        print(f"First run: saved baseline of {len(current)} vehicles. "
              f"Nothing to generate yet -- next run will catch real new arrivals.")
        return

    retry_vins = [v for v in current if v in known and v not in videoed]
    candidates = list(dict.fromkeys(new_vins + retry_vins))

    if not candidates:
        print("No new vehicles, and nothing pending a retry.")
        return

    print(f"Found {len(new_vins)} brand-new vehicle(s) and {len(retry_vins)} "
          f"pending retry: {', '.join(candidates)}")

    # Pre-fetch VDP pages and detect stock/placeholder images reused across
    # multiple candidate vehicles (a real photo is unique to one car; a
    # reused/placeholder image is the giveaway).
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
                  f"Will be checked again automatically on future runs.")
            continue

        vin_photo_dir = os.path.join(args.work_dir, "photos", vin)
        ext_dir = os.path.join(vin_photo_dir, "exterior")
        int_dir = os.path.join(vin_photo_dir, "interior")
        os.makedirs(ext_dir, exist_ok=True)
        os.makedirs(int_dir, exist_ok=True)

        # Download to staging, drop manufacturer studio/press photos (car on
        # a near-pure-white background, not a real lot photo), keep the rest.
        stage_dir = os.path.join(vin_photo_dir, "_stage")
        os.makedirs(stage_dir, exist_ok=True)
        real_photos = []
        for i, url in enumerate(photo_urls):
            ext = os.path.splitext(url)[1] or ".jpg"
            sp = os.path.join(stage_dir, f"{i:02d}{ext}")
            try:
                photos_fetcher.download(url, sp)
            except requests.RequestException as e:
                print(f"  photo download failed ({url}): {e}")
                continue
            if photos_fetcher.looks_like_studio_photo(sp):
                os.remove(sp)
                continue
            real_photos.append(sp)

        if len(real_photos) < 2:
            print(f"  only manufacturer/studio stock photos found -- skipping. "
                  f"Will retry automatically once real photos are added.")
            continue

        split_idx = max(1, int(len(real_photos) * 0.6))
        for i, sp in enumerate(real_photos):
            target = ext_dir if i < split_idx else int_dir
            os.rename(sp, os.path.join(target, os.path.basename(sp)))

        price, mileage = scrape_details(vdp_html)

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

        print("Step 3/3: rendering video...")
        script_dir = os.path.dirname(os.path.abspath(__file__))
        result = subprocess.run(
            [sys.executable, os.path.join(script_dir, "make_showcase_video.py"), "--config", cfg_path],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            print(f"  video generation failed:\n{result.stderr}")
            continue

        caption = build_caption(info, price, mileage, args.dealer_name, info["url"], args.dealer_phone)
        caption_path = os.path.join(out_video_dir, "caption.txt")
        with open(caption_path, "w") as f:
            f.write(caption)

        # Pick best 8 photos (4 ext + 4 int) to attach directly to the email.
        ext_files = sorted(os.listdir(ext_dir)) if os.path.isdir(ext_dir) else []
        int_files = sorted(os.listdir(int_dir)) if os.path.isdir(int_dir) else []
        best_photos = [os.path.join(ext_dir, f) for f in ext_files[:4]] + \
                      [os.path.join(int_dir, f) for f in int_files[:4]]
        photo_list_path = os.path.join(out_video_dir, "photo_list.txt")
        with open(photo_list_path, "w") as f:
            f.write("\n".join(best_photos))

        print(f"  done -> {video_path}")

        videoed.add(vin)
        json.dump(sorted(videoed), open(args.videoed_state_file, "w"), indent=2)

        if args.notify:
            subject = f"New: {info['year']} {info['make']} {info['model']} {info['trim']}".strip()
            if price:
                subject += f" — {price}"
            if mileage:
                subject += f" | {mileage}"
            notify_result = subprocess.run(
                [sys.executable, os.path.join(script_dir, "notify.py"),
                 "--video", video_path, "--caption", caption_path,
                 "--photo-list", photo_list_path, "--subject", subject],
                capture_output=True, text=True,
            )
            if notify_result.returncode != 0:
                print(f"  email notification failed:\n{notify_result.stderr}")
            else:
                print(f"  emailed to {os.environ.get('NOTIFY_TO', '(NOTIFY_TO not set)')}")

    print(f"\nAll set. Check {args.out_dir}/ for finished videos + captions.")


def build_caption(info, price, mileage, dealer_name, vdp_url, phone):
    name = f"{info['year']} {info['make']} {info['model']} {info['trim']}".strip()
    make = info["make"]
    model = info["model"]

    tiktok_hook = (f"POV: you just found a {info['year']} {make} {model} for {price} \U0001F440"
                   if price else f"POV: you just found this {name} \U0001F440")
    tiktok = [tiktok_hook, ""]
    specs = []
    if price:
        specs.append(f"\U0001F4B0 {price}")
    if mileage:
        specs.append(f"\U0001F6E3 {mileage}")
    if specs:
        tiktok.append("  ".join(specs))
    tiktok.append("\U0001F525 DM \"INFO\" before it's gone")
    tiktok.append(f"\U0001F4F2 Text me: {phone}")
    tiktok.append("")
    tiktok.append(
        "#usedcars #carsforsale #cardeals #fyp #carsoftiktok #dealalert "
        f"#{make.replace(' ', '')} #{model.replace(' ', '')}"
    )

    fb = []
    fb.append(f"\U0001F697 {name} — Now Available at {dealer_name}!")
    fb.append("")
    line = []
    if price:
        line.append(f"Priced at {price}")
    if mileage:
        line.append(f"only {mileage}")
    if line:
        fb.append("\u2705 " + ", ".join(line) + ".")
    fb.append("\u2705 Clean, inspected, and ready to drive home today.")
    fb.append("\u2705 Easy financing available — all credit situations welcome.")
    fb.append("")
    fb.append(f"This one won't last long. Message me, Devin, directly or call/text "
              f"{phone} to set up a test drive. I'll take care of you from start to finish.")
    fb.append("")
    fb.append(f"\U0001F4F2 Tap to text me now: sms:+1{phone.replace('-', '').replace(' ', '')}")
    if vdp_url:
        fb.append("")
        fb.append(f"\U0001F517 See full details & photos: {vdp_url}")
    fb.append("")
    fb.append(
        f"#{make.replace(' ', '')} #{model.replace(' ', '')} #usedcars #carsforsale "
        f"#cardealership #InlandEmpire #SoCalCars #carfinancing "
        f"#goodcredit #badcredit #firstcar #cardeals #testdrive #drivehometoday"
    )

    out = []
    out.append("========== TIKTOK / REELS / STORIES ==========")
    out.append("\n".join(tiktok))
    out.append("")
    out.append("========== FACEBOOK / MARKETPLACE ==========")
    out.append("\n".join(fb))
    return "\n".join(out)


if __name__ == "__main__":
    main()
