#!/usr/bin/env python3
"""
weekly_script.py

Every Monday morning, pulls the current used inventory, picks the 3-4 most
postable cars (premium/luxury, best value, lowest mileage), and emails
Devin a ready-to-record 30-second script for a personal brand video.
"""

import argparse
import os
import re
import smtplib
from email.message import EmailMessage

import requests

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; InventoryWatcher/1.0)"}

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


def fetch_price_mileage(url):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        html = resp.text
        price_match = PRICE_RE.search(html) or RETAIL_PRICE_RE.search(html)
        mileage_match = MILEAGE_RE.search(html)
        price = int(price_match.group(1).replace(",", "")) if price_match else 999999
        mileage = int(mileage_match.group(1).replace(",", "")) if mileage_match else 999999
        price_str = f"${price_match.group(1)}" if price_match else ""
        mileage_str = f"{mileage_match.group(1)} miles" if mileage_match else ""
        return price, mileage, price_str, mileage_str
    except Exception:
        return 999999, 999999, "", ""


def pick_featured_cars(inventory, n=4):
    premium_makes = {"BMW", "Mercedes-Benz", "Audi", "Cadillac", "Buick",
                     "Lexus", "Porsche", "Infiniti", "Acura", "GMC"}
    cars_with_details = []
    for vin, info in list(inventory.items())[:30]:
        price, mileage, price_str, mileage_str = fetch_price_mileage(info["url"])
        cars_with_details.append({**info, "price_num": price, "mileage_num": mileage,
                                  "price_str": price_str, "mileage_str": mileage_str})

    featured = []
    premium = [c for c in cars_with_details if c["make"] in premium_makes]
    if premium:
        featured.append(sorted(premium, key=lambda x: x["price_num"], reverse=True)[0])

    budget = [c for c in cars_with_details if c["price_num"] < 20000 and c not in featured]
    if budget:
        featured.append(sorted(budget, key=lambda x: x["price_num"])[0])

    low_mile = [c for c in cars_with_details if c["mileage_num"] < 30000 and c not in featured]
    if low_mile:
        featured.append(sorted(low_mile, key=lambda x: x["mileage_num"])[0])

    remaining = [c for c in cars_with_details if c not in featured]
    remaining.sort(key=lambda x: x["price_num"])
    while len(featured) < n and remaining:
        featured.append(remaining.pop(0))
    return featured[:n]


def write_script(featured_cars, dealer_name, phone):
    car_lines = []
    for c in featured_cars:
        name = f"{c['year']} {c['make']} {c['model']}"
        details = [d for d in [c.get("price_str"), c.get("mileage_str")] if d]
        detail_str = f" — {', '.join(details)}" if details else ""
        car_lines.append(f"{name}{detail_str}")

    total = len(car_lines)
    if total == 1:
        car_mention = car_lines[0]
    elif total == 2:
        car_mention = f"{car_lines[0]} and {car_lines[1]}"
    else:
        car_mention = ", ".join(car_lines[:-1]) + f", and {car_lines[-1]}"

    return f"""
========== YOUR MONDAY SCRIPT — READ THIS ON CAMERA ==========

[Point camera at yourself, standing on the lot or near a car]

"Hey what's up everyone — it's Devin at {dealer_name}.

It's a new week and we just got some FIRE inventory in.

We're talking {car_mention}.

These are going FAST — I'm not playing.

If you want first dibs, text me RIGHT NOW at {phone}.
I'll send you everything — pictures, price, all of it.

No games, no runaround. Just text me. Let's get you in something. 🔥"

========== POSTING TIPS ==========
• Record this in ONE take — raw and real performs better than polished
• Stand next to the most eye-catching car while you record
• Keep it under 45 seconds
• Add trending audio in TikTok/Reels editor AFTER recording
• Post to TikTok first, then share to Facebook/Instagram

========== CAPTION (copy-paste) ==========
POV: your plug at the dealership just dropped the new inventory 👀

{chr(10).join("🔥 " + c for c in car_lines)}

Text me to claim yours before it's gone 📱 {phone}

#usedcars #carsforsale #fyp #carsoftiktok #InlandEmpire #newInventory #cardeals
========== END ==========
""".strip()


def send_script_email(script, featured_cars):
    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ["SMTP_USER"]
    password = os.environ["SMTP_PASS"]
    to_addr = os.environ["NOTIFY_TO"]

    msg = EmailMessage()
    msg["Subject"] = f"🎬 Your Monday Script — {len(featured_cars)} cars to feature this week"
    msg["From"] = user
    msg["To"] = to_addr
    msg.set_content(script)

    with smtplib.SMTP(host, port) as server:
        server.starttls()
        server.login(user, password)
        server.send_message(msg)
    print(f"Monday script emailed to {to_addr}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--platform", default="foxdealer", choices=["foxdealer", "dealerinspire"])
    ap.add_argument("--salesperson", default="Devin Rangel")
    ap.add_argument("--dealer-name", default="")
    ap.add_argument("--phone", default="818-450-6500")
    args = ap.parse_args()

    detector = get_detector(args.platform)
    print("Pulling current inventory...")
    inventory = detector.collect_listings(args.base_url)
    print(f"Found {len(inventory)} vehicles. Picking the best ones to feature...")

    featured = pick_featured_cars(inventory, n=4)
    if not featured:
        print("No cars found to feature.")
        return

    for c in featured:
        print(f"  {c['year']} {c['make']} {c['model']} — {c.get('price_str', 'N/A')}")

    script = write_script(featured, args.dealer_name, args.phone)
    send_script_email(script, featured)


if __name__ == "__main__":
    main()
