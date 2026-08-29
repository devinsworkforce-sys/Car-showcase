#!/usr/bin/env python3
"""
make_showcase_video.py

Turns a folder of vehicle photos into a polished, social-ready showcase
video: opens directly on the car (headline overlay), pans through exterior
and interior shots with varied camera motion, and closes on a CTA + contact
info overlay on the car itself. A flashy "as low as $X,XXX DOWN" badge is
stamped on the very first shot, scaled to the vehicle's price.

Usage:
    python3 make_showcase_video.py --config vehicle.json
"""

import argparse
import json
import os
import random
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw, ImageFont

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
FONT_BOLD = os.path.join(_SCRIPT_DIR, "fonts", "LiberationSans-Bold.ttf")
FONT_REG = os.path.join(_SCRIPT_DIR, "fonts", "LiberationSans-Regular.ttf")

if not os.path.exists(FONT_BOLD) or not os.path.exists(FONT_REG):
    raise SystemExit(
        "Missing font files. Expected fonts/LiberationSans-Bold.ttf and "
        "fonts/LiberationSans-Regular.ttf next to this script."
    )

ACCENT_COLOR = (255, 255, 255)
BG_COLOR = (15, 15, 18)
CARD_TEXT_DIM = (190, 190, 195)

FPS = 30
CARD_DURATION = 1.9
PHOTO_DURATION = 1.9
XFADE_DURATION = 0.35
MAX_PHOTOS_PER_SECTION = 9

ORIENTATIONS = {
    "vertical": (1080, 1920),
    "square": (1080, 1080),
    "horizontal": (1920, 1080),
}


def run(cmd):
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        sys.stderr.write(result.stderr.decode("utf-8", "ignore"))
        raise RuntimeError(f"ffmpeg command failed: {' '.join(cmd)}")
    return result


def cover_crop(src_path, out_path, size):
    W, H = size
    img = Image.open(src_path).convert("RGB")
    src_w, src_h = img.size
    target_ratio = W / H
    src_ratio = src_w / src_h
    if src_ratio > target_ratio:
        new_h = src_h
        new_w = int(src_h * target_ratio)
    else:
        new_w = src_w
        new_h = int(src_w / target_ratio)
    left = (src_w - new_w) // 2
    top = (src_h - new_h) // 2
    img = img.crop((left, top, left + new_w, top + new_h))
    img = img.resize((W, H), Image.LANCZOS)
    img.save(out_path, quality=95)


def text_size(draw, text, font):
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def wrap_text(draw, text, font, max_width):
    words = text.split()
    lines, cur = [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if text_size(draw, trial, font)[0] <= max_width:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def pick_down_payment(price_str):
    """Pick a plausible down-payment number scaled to the vehicle's price
    tier -- cheaper cars get lower down payments, pricier cars get higher
    ones. Returns an int, or None if price couldn't be parsed."""
    if not price_str:
        return None
    digits = "".join(c for c in price_str if c.isdigit())
    if not digits:
        return None
    price = int(digits)

    if price < 15000:
        lo, hi = 1500, 2500
    elif price < 25000:
        lo, hi = 2500, 4000
    elif price < 40000:
        lo, hi = 4000, 6500
    else:
        lo, hi = 6500, 10000

    amount = random.randint(lo // 500, hi // 500) * 500
    return amount


def _gradient_band(img, x0, y0, x1, y1, max_alpha, top_down=True):
    band = Image.new("RGBA", (x1 - x0, y1 - y0), (0, 0, 0, 0))
    bd = ImageDraw.Draw(band)
    h = y1 - y0
    for yy in range(h):
        frac = (yy / h) if top_down else (1 - yy / h)
        a = int(max_alpha * frac)
        bd.line([(0, yy), (x1 - x0, yy)], fill=(0, 0, 0, a))
    img.alpha_composite(band, (x0, y0))


def _make_down_payment_badge(size, amount):
    """Render a flashy, slightly-rotated 'AS LOW AS $X,XXX DOWN' sticker
    badge as its own transparent PNG, to be composited onto the photo."""
    W, H = size
    bw, bh = int(W * 0.62), int(W * 0.30)
    badge = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    draw = ImageDraw.Draw(badge)

    # Bold red-to-yellow flashy sticker background with a thick white border
    draw.rounded_rectangle([0, 0, bw - 1, bh - 1], radius=int(bh * 0.14),
                            fill=(214, 32, 40, 255), outline=(255, 255, 255, 255),
                            width=max(4, int(bh * 0.05)))

    top_font = ImageFont.truetype(FONT_BOLD, int(bh * 0.20))
    amt_font = ImageFont.truetype(FONT_BOLD, int(bh * 0.40))
    sub_font = ImageFont.truetype(FONT_BOLD, int(bh * 0.16))

    top_text = "AS LOW AS"
    amt_text = f"${amount:,}"
    sub_text = "DOWN!"

    y = int(bh * 0.10)
    w, h = text_size(draw, top_text, top_font)
    draw.text(((bw - w) // 2, y), top_text, font=top_font, fill=(255, 230, 120, 255))
    y += h + int(bh * 0.03)

    w, h = text_size(draw, amt_text, amt_font)
    draw.text(((bw - w) // 2, y), amt_text, font=amt_font, fill=(255, 255, 255, 255))
    y += h + int(bh * 0.02)

    w, h = text_size(draw, sub_text, sub_font)
    draw.text(((bw - w) // 2, y), sub_text, font=sub_font, fill=(255, 230, 120, 255))

    # Slight rotation for a "sticker slapped on" feel
    badge = badge.rotate(-6, expand=True, resample=Image.BICUBIC)
    return badge


def make_overlay_png(out_path, size, top_label=None, lower_third=None,
                      headline=None, headline_sub=None, down_payment=None):
    W, H = size
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    if headline:
        _gradient_band(img, 0, 0, W, int(H * 0.34), 170, top_down=True)
        draw = ImageDraw.Draw(img)
        hfont = ImageFont.truetype(FONT_BOLD, int(W * 0.072))
        x = int(W * 0.06)
        y = int(H * 0.05)
        for line in wrap_text(draw, headline, hfont, int(W * 0.88)):
            draw.text((x, y), line, font=hfont, fill=(255, 255, 255, 255))
            y += text_size(draw, line, hfont)[1] + int(W * 0.015)
        if headline_sub:
            sfont = ImageFont.truetype(FONT_REG, int(W * 0.045))
            draw.text((x, y + int(W * 0.005)), headline_sub, font=sfont, fill=(220, 220, 220, 255))

    if top_label:
        font = ImageFont.truetype(FONT_BOLD, int(W * 0.05))
        pad = 18
        w, h = text_size(draw, top_label, font)
        bx0 = (W - w) // 2 - pad
        by0 = int(H * 0.06) - pad // 2
        bx1 = bx0 + w + pad * 2
        by1 = by0 + h + pad
        draw.rectangle([bx0, by0, bx1, by1], fill=(0, 0, 0, 115))
        draw.text(((W - w) // 2, by0 + pad // 2), top_label, font=font, fill=(255, 255, 255, 255))

    if lower_third:
        box_h = int(H * 0.22)
        _gradient_band(img, 0, H - box_h, W, H, 190, top_down=True)
        draw = ImageDraw.Draw(img)
        fsize_main = int(W * 0.085)
        fsize_sub = int(W * 0.045)
        font_main = ImageFont.truetype(FONT_BOLD, fsize_main)
        draw.text((int(W * 0.06), H - box_h + int(box_h * 0.30)), lower_third[0],
                   font=font_main, fill=(255, 255, 255, 255))
        if len(lower_third) > 1:
            font_sub = ImageFont.truetype(FONT_REG, fsize_sub)
            draw.text((int(W * 0.06), H - box_h + int(box_h * 0.66)), lower_third[1],
                       font=font_sub, fill=(220, 220, 220, 255))

    if down_payment:
        badge = _make_down_payment_badge(size, down_payment)
        bx = W - badge.width - int(W * 0.03)
        by = int(H * 0.40)
        img.alpha_composite(badge, (bx, by))

    img.save(out_path)


def build_clip(image_path, out_path, size, duration, style="zoom_in", lower_third=None, top_label=None,
               headline=None, headline_sub=None, down_payment=None):
    W, H = size
    tmp_img = out_path + ".src.jpg"
    cover_crop(image_path, tmp_img, size)

    frames = int(duration * FPS)

    if style == "zoom_in_right":
        zexpr = "min(zoom+0.0010,1.22)"
        xexpr = "if(eq(on,0),0,x+1.4)"
        yexpr = "ih/2-(ih/zoom/2)"
    elif style == "zoom_in_left":
        zexpr = "min(zoom+0.0010,1.22)"
        xexpr = "if(eq(on,0),iw-iw/zoom,x-1.4)"
        yexpr = "ih/2-(ih/zoom/2)"
    elif style == "zoom_out":
        zexpr = "if(eq(on,0),1.22,max(zoom-0.0012,1.0))"
        xexpr = "iw/2-(iw/zoom/2)"
        yexpr = "ih/2-(ih/zoom/2)"
    else:  # zoom_in
        zexpr = "min(zoom+0.0016,1.18)"
        xexpr = "iw/2-(iw/zoom/2)"
        yexpr = "ih/2-(ih/zoom/2)"

    base_vf = (
        f"scale={W*2}:{H*2}:flags=lanczos,"
        f"zoompan=z='{zexpr}':x='{xexpr}':y='{yexpr}':d={frames}:s={W}x{H}:fps={FPS},"
        f"eq=contrast=1.05:saturation=1.12"
    )

    overlay_png = None
    if top_label or lower_third or headline or down_payment:
        overlay_png = out_path + ".overlay.png"
        make_overlay_png(overlay_png, size, top_label=top_label, lower_third=lower_third,
                         headline=headline, headline_sub=headline_sub, down_payment=down_payment)

    if overlay_png:
        cmd = [
            "ffmpeg", "-y",
            "-loop", "1", "-i", tmp_img,
            "-loop", "1", "-i", overlay_png,
            "-filter_complex",
            f"[0:v]{base_vf}[base];[base][1:v]overlay=0:0,format=yuv420p[outv]",
            "-map", "[outv]",
            "-t", str(duration),
            "-r", str(FPS),
            "-c:v", "libx264", "-preset", "fast", "-crf", "14", "-pix_fmt", "yuv420p",
            out_path,
        ]
    else:
        cmd = [
            "ffmpeg", "-y", "-loop", "1", "-i", tmp_img,
            "-vf", base_vf + ",format=yuv420p",
            "-t", str(duration),
            "-r", str(FPS),
            "-c:v", "libx264", "-preset", "fast", "-crf", "14", "-pix_fmt", "yuv420p",
            out_path,
        ]
    run(cmd)
    os.remove(tmp_img)
    if overlay_png:
        os.remove(overlay_png)


def xfade_chain(clip_paths, durations, out_path, size):
    inputs = []
    for p in clip_paths:
        inputs += ["-i", p]

    filter_parts = []
    running_dur = durations[0]
    prev_label = "0:v"
    for i in range(1, len(clip_paths)):
        offset = running_dur - XFADE_DURATION
        out_label = f"v{i}" if i < len(clip_paths) - 1 else "vout"
        filter_parts.append(
            f"[{prev_label}][{i}:v]xfade=transition=fade:duration={XFADE_DURATION}:offset={offset:.3f}[{out_label}]"
        )
        running_dur = running_dur + durations[i] - XFADE_DURATION
        prev_label = out_label

    filter_complex = ";".join(filter_parts)
    cmd = [
        "ffmpeg", "-y", *inputs,
        "-filter_complex", filter_complex,
        "-map", "[vout]" if len(clip_paths) > 1 else "0:v",
        "-r", str(FPS),
        "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        out_path,
    ]
    run(cmd)


def list_images(folder):
    if not folder or not os.path.isdir(folder):
        return []
    exts = (".jpg", ".jpeg", ".png", ".webp")
    files = sorted([f for f in os.listdir(folder) if f.lower().endswith(exts)])
    return [os.path.join(folder, f) for f in files]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    args = ap.parse_args()

    cfg = json.load(open(args.config))
    size = ORIENTATIONS[cfg.get("orientation", "vertical")]

    out_final = cfg["output"]
    os.makedirs(os.path.dirname(out_final) or ".", exist_ok=True)

    headline = f'{cfg["year"]} {cfg["make"]} {cfg["model"]}'.upper()
    trim = cfg.get("trim", "")
    price = cfg.get("price", "")
    mileage = cfg.get("mileage", "")
    dealer = cfg.get("dealer_name", "")
    phone = cfg.get("dealer_phone", "")
    cta = cfg.get("cta", "DM \"INFO\" BEFORE IT'S GONE")
    salesperson = cfg.get("salesperson", "")

    show_down_payment = cfg.get("show_down_payment", True)
    down_payment = pick_down_payment(price) if show_down_payment else None

    ext_photos = list_images(cfg.get("exterior_dir"))[:MAX_PHOTOS_PER_SECTION]
    int_photos = list_images(cfg.get("interior_dir"))[:MAX_PHOTOS_PER_SECTION]

    if not ext_photos and not int_photos:
        raise SystemExit("No photos found in exterior_dir or interior_dir.")

    MOTION_CYCLE = ["zoom_in_right", "zoom_in", "zoom_in_left", "zoom_out"]
    motion_i = 0

    with tempfile.TemporaryDirectory() as tmp:
        clips, durations = [], []

        for i, photo in enumerate(ext_photos):
            p = os.path.join(tmp, f"10_ext_{i:02d}.mp4")
            head = headline if i == 0 else None
            head_sub = (trim if trim else None) if i == 0 else None
            lower = [price or "", mileage or ""] if (i == 1 and (price or mileage)) else None
            dp = down_payment if i == 0 else None
            build_clip(
                photo, p, size, PHOTO_DURATION,
                style=MOTION_CYCLE[motion_i % len(MOTION_CYCLE)],
                headline=head, headline_sub=head_sub,
                lower_third=lower, down_payment=dp,
            )
            motion_i += 1
            clips.append(p); durations.append(PHOTO_DURATION)

        if int_photos:
            for i, photo in enumerate(int_photos):
                p = os.path.join(tmp, f"20_int_{i:02d}.mp4")
                build_clip(
                    photo, p, size, PHOTO_DURATION,
                    style=MOTION_CYCLE[motion_i % len(MOTION_CYCLE)],
                    top_label="INTERIOR" if i == 0 else None,
                )
                motion_i += 1
                clips.append(p); durations.append(PHOTO_DURATION)

        closer_photo = ext_photos[0] if ext_photos else int_photos[0]
        contact_bits = [b for b in [
            f"Ask for {salesperson}" if salesperson else None, phone,
        ] if b]
        closer_path = os.path.join(tmp, "90_closer.mp4")
        build_clip(
            closer_photo, closer_path, size, CARD_DURATION + 0.4,
            style="zoom_out",
            headline=cta,
            headline_sub=dealer,
            lower_third=contact_bits if contact_bits else None,
        )
        clips.append(closer_path); durations.append(CARD_DURATION + 0.4)

        xfade_chain(clips, durations, out_final, size)

    print(f"Done -> {out_final}")


if __name__ == "__main__":
    main()
