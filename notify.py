#!/usr/bin/env python3
"""
notify.py

Emails a finished showcase video to you automatically, so there's nothing to
log into or check manually. Credentials come from environment variables
(never hardcoded), which is what makes this safe to run unattended in
GitHub Actions or anywhere else.

Required environment variables:
    SMTP_HOST   e.g. smtp.gmail.com
    SMTP_PORT   e.g. 587
    SMTP_USER   the sending email address
    SMTP_PASS   an APP PASSWORD (not your normal email password -- see README)
    NOTIFY_TO   the email address that should receive finished videos
                (can be your own address, or even your phone's
                "number@carrier-sms-gateway" if you want a text alert instead)

Usage (called automatically by run_pipeline.py when --notify is passed):
    python3 notify.py --video path/to/video.mp4 --caption path/to/caption.txt --subject "New: 2024 Nissan Kicks"
"""

import argparse
import os
import smtplib
from email.message import EmailMessage


def send_email(video_path, caption_path, subject):
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
        "New showcase video is ready -- attached.\n\n"
        "Suggested caption (edit before posting):\n\n" + caption
    )

    with open(video_path, "rb") as f:
        msg.add_attachment(
            f.read(), maintype="video", subtype="mp4",
            filename=os.path.basename(video_path),
        )

    with smtplib.SMTP(host, port) as server:
        server.starttls()
        server.login(user, password)
        server.send_message(msg)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--caption", default=None)
    ap.add_argument("--subject", default="New showcase video ready")
    args = ap.parse_args()
    send_email(args.video, args.caption, args.subject)
    print(f"Emailed {args.video} to {os.environ.get('NOTIFY_TO')}")


if __name__ == "__main__":
    main()
