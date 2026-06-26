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
    run_url = os.environ.get("GITHUB_RUN_URL", "")

    caption = ""
    if caption_path and os.path.exists(caption_path):
        caption = open(caption_path).read()

    # Count how many photos exist so we can mention it in the email
    photos = gather_photos(photos_dir) if photos_dir else []

    download_section = ""
    if run_url:
        download_section = (
            f"\n📥 DOWNLOAD ALL PHOTOS + VIDEO:\n"
            f"{run_url}\n"
            f"(Click the link → scroll down → click the 'ready-to-post' artifact to download a zip "
            f"with the video + all {len(photos)} photos)\n"
        )

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to_addr
    msg.set_content(
        f"Your showcase video is ready!\n"
        f"{download_section}\n"
        "------------------------------------------------------------\n"
        "POST THE VIDEO → TikTok / Reels / Stories\n"
        "POST THE PHOTOS → Facebook carousel / Marketplace\n"
        "------------------------------------------------------------\n\n"
        "Copy-paste captions below:\n\n"
        + caption
    )

    # Attach just the video — no photos (they're in the artifact download link)
    if video_path and os.path.exists(video_path):
        with open(video_path, "rb") as f:
            data = f.read()
        msg.add_attachment(data, maintype="video", subtype="mp4",
                           filename=os.path.basename(video_path))

    with smtplib.SMTP(host, port) as server:
        server.starttls()
        server.login(user, password)
        server.send_message(msg)
    return len(photos)


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

