#!/usr/bin/env python3
"""
notify.py

Emails a finished showcase video PLUS all the vehicle's photos, so you can
post either the video (TikTok/Reels) or a photo carousel (Facebook) straight
from your inbox. Credentials come from environment variables (never
hardcoded), which is what makes this safe to run unattended.

Required environment variables:
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, NOTIFY_TO

Usage:
    python3 notify.py --video path/to/video.mp4 --caption path/to/caption.txt \
        --photos-dir path/to/photos --subject "New: 2024 Nissan Kicks"
"""

import argparse
import os
import smtplib
from email.message import EmailMessage

# Gmail rejects messages over ~25MB total. Photos are attached until this
# budget is hit; the video is always attached first since it's the priority.
MAX_TOTAL_BYTES = 23 * 1024 * 1024


def gather_photos(photos_dir):
    if not photos_dir or not os.path.isdir(photos_dir):
        return []
    out = []
    for root, _, files in os.walk(photos_dir):
        for fn in sorted(files):
            if fn.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
                out.append(os.path.join(root, fn))
    return out


def send_email(video_path, caption_path, subject, photos_dir=None):
    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ["SMTP_USER"]
    password = os.environ["SMTP_PASS"]
    to_addr = os.environ["NOTIFY_TO"]

    caption = ""
    if caption_path and os.path.exists(caption_path):
        caption = open(caption_path).read()

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to_addr
    msg.set_content(
        "Your showcase video AND all the vehicle photos are attached.\n\n"
        "- Post the VIDEO on TikTok / Reels / Stories\n"
        "- Post the PHOTOS as a carousel on Facebook Marketplace / your page\n\n"
        "Copy-paste caption + hashtags below:\n"
        "------------------------------------------------------------\n\n"
        + caption
    )

    total = 0
    # Video first -- it's the priority attachment.
    if video_path and os.path.exists(video_path):
        with open(video_path, "rb") as f:
            data = f.read()
        msg.add_attachment(data, maintype="video", subtype="mp4",
                           filename=os.path.basename(video_path))
        total += len(data)

    # Then as many photos as fit in the size budget.
    photos = gather_photos(photos_dir)
    attached, skipped = 0, 0
    for i, p in enumerate(photos):
        size = os.path.getsize(p)
        if total + size > MAX_TOTAL_BYTES:
            skipped += 1
            continue
        with open(p, "rb") as f:
            data = f.read()
        ext = os.path.splitext(p)[1].lstrip(".").lower() or "jpg"
        subtype = "jpeg" if ext in ("jpg", "jpeg") else ext
        msg.add_attachment(data, maintype="image", subtype=subtype,
                           filename=f"photo_{i+1:02d}.{ext}")
        total += size
        attached += 1

    if skipped:
        # Let the reader know not all photos fit (rare; only very large sets).
        body = msg.get_content()
        body += (f"\n\n(Note: {attached} photos attached; {skipped} didn't fit "
                 f"the email size limit. The video has them all.)")
        msg.set_content(body)

    with smtplib.SMTP(host, port) as server:
        server.starttls()
        server.login(user, password)
        server.send_message(msg)
    return attached


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--caption", default=None)
    ap.add_argument("--photos-dir", default=None)
    ap.add_argument("--subject", default="New showcase video ready")
    args = ap.parse_args()
    n = send_email(args.video, args.caption, args.subject, photos_dir=args.photos_dir)
    print(f"Emailed {args.video} (+{n} photos) to {os.environ.get('NOTIFY_TO')}")


if __name__ == "__main__":
    main()

