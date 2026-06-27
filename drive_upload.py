#!/usr/bin/env python3
"""
drive_upload.py

Uploads a vehicle's photos to Google Drive and returns a single shareable
folder link. The recipient opens the link and can download all photos at once
("Download all" zips them automatically) -- one click, no GitHub, no saving
photos one by one.

Auth uses a Google "service account" whose JSON key is provided via the
GOOGLE_SERVICE_ACCOUNT_JSON environment variable (the whole JSON blob as a
string). The target Drive folder is shared with the service account so it can
write into your normal Drive. See README for the one-time setup.

Required env vars:
    GOOGLE_SERVICE_ACCOUNT_JSON   the full service-account JSON key (as text)
    DRIVE_PARENT_FOLDER_ID        the ID of the Drive folder to put car folders in

If these aren't set, upload_photos() returns None so the pipeline can fall
back gracefully (it just won't include a Drive link).
"""

import io
import json
import os


def _get_service():
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if not raw:
        return None
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError:
        print("  (google api libraries not installed; skipping Drive upload)")
        return None
    try:
        info = json.loads(raw)
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=["https://www.googleapis.com/auth/drive"])
        return build("drive", "v3", credentials=creds, cache_discovery=False)
    except Exception as e:
        print(f"  (Drive auth failed: {e})")
        return None


def upload_photos(folder_name, photo_paths):
    """Create a Drive subfolder, upload all photos, make it link-viewable,
    and return the shareable folder URL. Returns None on any failure."""
    service = _get_service()
    if service is None:
        return None
    parent = os.environ.get("DRIVE_PARENT_FOLDER_ID", "").strip()
    if not parent:
        print("  (DRIVE_PARENT_FOLDER_ID not set; skipping Drive upload)")
        return None

    try:
        from googleapiclient.http import MediaFileUpload

        # Create the per-vehicle folder
        folder = service.files().create(
            body={
                "name": folder_name,
                "mimeType": "application/vnd.google-apps.folder",
                "parents": [parent],
            },
            fields="id",
            supportsAllDrives=True,
        ).execute()
        folder_id = folder["id"]

        # Upload each photo
        for i, p in enumerate(photo_paths):
            if not os.path.exists(p):
                continue
            ext = os.path.splitext(p)[1].lstrip(".").lower() or "jpg"
            mt = "image/jpeg" if ext in ("jpg", "jpeg") else f"image/{ext}"
            media = MediaFileUpload(p, mimetype=mt, resumable=False)
            service.files().create(
                body={"name": f"photo_{i+1:02d}.{ext}", "parents": [folder_id]},
                media_body=media,
                fields="id",
                supportsAllDrives=True,
            ).execute()

        # Make the folder viewable by anyone with the link
        service.permissions().create(
            fileId=folder_id,
            body={"role": "reader", "type": "anyone"},
            supportsAllDrives=True,
        ).execute()

        return f"https://drive.google.com/drive/folders/{folder_id}"
    except Exception as e:
        print(f"  (Drive upload failed: {e})")
        return None
