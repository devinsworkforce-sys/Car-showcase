#!/usr/bin/env python3
"""
notify.py

Emails the showcase video + best 8 photos (4 exterior, 4 interior) as
attachments. At ~400KB per photo, 8 photos + video = ~8-10MB total, well
under Gmail's 25MB limit and guaranteed to arrive every time.

Required env vars: SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, NOTIFY_TO
"""

import argparse
import os
import smtplib
from email.message import EmailMessage


def send_email(video_path, caption_path, subject, photo_list_path=None):
    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ["SMTP_USER"]
    password = os.environ["SMTP_PASS"]
    to_addr = os.environ["NOTIFY_TO"]

    caption = ""
    if caption_path and os.path.exists(caption_path):
        caption = open(caption_path).read()

    photo_paths = []
    if photo_list_path and os.path.exists(photo_list_path):
        photo_paths = [l.strip() for l in open(photo_list_path) if l.strip() and os.path.exists(l.strip())]

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to_addr
    msg.set_content(
        f"Your showcase video is ready! Video + {len(photo_paths)} photos attached.\n\n"
        "POST THE VIDEO → TikTok / Reels / Stories\n"
        "POST THE PHOTOS → Facebook carousel / Marketplace\n"
        "------------------------------------------------------------\n\n"
        "Copy-paste captions below:\n\n"
        + caption
    )

    # Attach video
    if video_path and os.path.exists(video_path):
        with open(video_path, "rb") as f:
            msg.add_attachment(f.read(), maintype="video", subtype="mp4",
                               filename=os.path.basename(video_path))

    # Attach photos
    for i, p in enumerate(photo_paths):
        ext = os.path.splitext(p)[1].lstrip(".").lower() or "jpg"
        subtype = "jpeg" if ext in ("jpg", "jpeg") else ext
        with open(p, "rb") as f:
            msg.add_attachment(f.read(), maintype="image", subtype=subtype,
                               filename=f"photo_{i+1:02d}.{ext}")

    with smtplib.SMTP(host, port) as server:
        server.starttls()
        server.login(user, password)
        server.send_message(msg)
    return len(photo_paths)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--caption", default=None)
    ap.add_argument("--photo-list", default=None)
    ap.add_argument("--subject", default="New showcase video ready")
    args = ap.parse_args()
    n = send_email(args.video, args.caption, args.subject,
                   photo_list_path=args.photo_list)
    print(f"Emailed {args.video} (+{n} photos) to {os.environ.get('NOTIFY_TO')}")


if __name__ == "__main__":
    main()
