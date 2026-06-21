# Used-Car Showcase Video Pipeline

Generates a branded, social-ready showcase video automatically whenever a new
vehicle shows up on Metro Nissan of Montclair's public used-inventory pages.

**Read this before you rely on it.** A few honest limitations, up front:

1. **This is not a true 360° spin.** A real continuous rotation needs actual
   video or turntable footage of the physical car. Since you only have
   access to the website's listing photos, this builds a polished
   *multi-angle showcase reel* instead -- smooth pan/zoom across whatever
   exterior and interior photos the listing has, with price/spec overlays.
   It looks professional, but it's photos-in-motion, not a spin.
2. **No backend access = no instant trigger.** There's no webhook from the
   dealer's site telling you the moment a car is added. Instead, this polls
   the public inventory pages on a schedule you control (e.g. every 30-60
   minutes) and compares VINs against what it saw last time.
3. **Photo quality/quantity varies a lot.** "In Transit" listings sometimes
   only have a single generic placeholder photo. The pipeline skips
   generating a video if it finds fewer than 2 real photos, and will pick
   the vehicle up automatically once more photos appear (you may need to
   manually remove that VIN from `known_vins.json` to force a retry sooner).
4. **Exterior/interior sorting is a heuristic** (first ~60% of photos =
   exterior, rest = interior), since the public photo feed doesn't label
   which is which. Spot-check it; it's usually right but not guaranteed.
5. **You should run a quick test against the live site before trusting it
   unattended.** I built and tested the video-rendering engine fully (see
   `vehicle_sample.json`), but the web-scraping parts (`detect_new_vehicles.py`,
   `fetch_vehicle_photos.py`) were written against the page structure I
   could observe remotely, not run live end-to-end -- I don't have outbound
   network access in this environment to test against the real site. Run
   `detect_new_vehicles.py` once by hand first (see below) and tell me what
   happens if anything looks off; it's usually a 5-minute fix.

## Setup

```bash
pip install -r requirements.txt
# ffmpeg must be installed and on PATH (brew install ffmpeg / apt install ffmpeg)
```

## 1. Test the video engine (no internet needed)

```bash
python3 make_showcase_video.py --config vehicle_sample.json
```

Outputs `output/showcase_sample.mp4` using the bundled sample photos --
confirms ffmpeg/fonts/Pillow are all working before you touch the live site.

## 2. Test detection against the real site (run once by hand)

```bash
python3 detect_new_vehicles.py --base-url https://www.metronissanmontclair.com/inventory/used/
```

First run just saves a baseline (every current car looks "new" since there's
no history yet -- that's expected). Run it a second time right after; it
should report 0 new vehicles. If it reports an error or 0 listings even on
the first run, the page structure may differ from what I assumed -- send me
the error and I'll adjust the regex.

## 3. Make it fully hands-off (one-time setup, ~15 minutes)

This is the part that lets it "just run" without you touching it -- it uses
GitHub Actions (free) as the always-on machine, and emails you each finished
video. You do this once; after that, nothing requires your attention except
checking your inbox.

**A. Get an email "app password" (so the bot can send mail as you)**
If you use Gmail: Google Account -> Security -> 2-Step Verification (turn on
if not already) -> App Passwords -> create one named "inventory bot". Copy
the 16-character password it gives you. (Any email provider with SMTP works
the same way -- Gmail is just the most common.)

**B. Put this project on GitHub**
1. Create a free GitHub account if you don't have one, and a new **private**
   repository (e.g. `car-showcase`).
2. Upload everything in this folder to that repo (drag-and-drop on
   github.com works fine, or `git push` if you're comfortable with git).
   The `.github/workflows/check-inventory.yml` file is already included --
   that's what makes it run automatically.

**C. Add your credentials as repo secrets**
In your new repo: Settings -> Secrets and variables -> Actions -> New
repository secret. Add these five:

| Secret name | Value |
|---|---|
| `SMTP_HOST` | `smtp.gmail.com` (or your provider's) |
| `SMTP_PORT` | `587` |
| `SMTP_USER` | the email address sending the videos |
| `SMTP_PASS` | the app password from step A |
| `NOTIFY_TO` | the email address that should *receive* the videos (can be the same as SMTP_USER, or a different one -- e.g. your personal email you check on your phone) |

**D. Turn it on**
Go to the repo's "Actions" tab and enable workflows if prompted. That's it.
It now checks inventory every 30 minutes, forever, on GitHub's servers --
not your computer, not your phone, nothing that needs to stay open. When a
new vehicle shows up, you'll get an email with the finished video attached
and a suggested caption, ready to download to your phone and post.

You can also trigger it manually anytime from the Actions tab ("Run
workflow") if you want a video right now instead of waiting for the next
scheduled check.

### If you'd rather not use GitHub at all

Two alternatives, both still automatic once set up, but tied to a physical
machine being on:

- **A computer that's always on** (e.g. a PC at the dealership): use cron
  (Mac/Linux) or Task Scheduler (Windows) to run
  `python3 run_pipeline.py ... --notify` every 30-60 minutes. Same
  `--notify` email flow applies -- just set the same five environment
  variables on that machine instead of as GitHub secrets.
- **Ask whoever manages the dealership's IT** if there's already a server
  this could run on.

GitHub Actions is the one that needs the least from you long-term, which is
why it's the default here.

## 4. Posting

Videos are silent on purpose -- add trending audio directly in
Instagram/TikTok's editor before posting (their built-in audio library is
genuinely better for reach than a baked-in track, and sidesteps licensing
questions). The caption in each email is a starting point, not a finished
caption -- personalize it before you post.

## Files

| File | Purpose |
|---|---|
| `make_showcase_video.py` | Turns a folder of photos into the branded video |
| `detect_new_vehicles.py` | Polls inventory pages, tracks seen VINs |
| `fetch_vehicle_photos.py` | Downloads + sorts photos for one VIN |
| `run_pipeline.py` | Runs all of the above end to end |
| `notify.py` | Emails the finished video to you automatically |
| `.github/workflows/check-inventory.yml` | Makes the whole thing run on a timer with no machine of yours needed |
| `vehicle_sample.json` / `sample_photos/` | Test fixtures, safe to delete later |
