"""
Fetches the current "Currently Reading" book plus this week's logged reading
activity from Hardcover, renders a reading-streak-style card image to
assets/reading_card.png, and makes sure the
<!--START_SECTION:reading--> ... <!--END_SECTION:reading--> block in Readme.md
embeds it.
"""

import io
import os
import re
import sys
import urllib.request
import json
from datetime import date, timedelta

from PIL import Image, ImageDraw, ImageFont

API_URL = "https://api.hardcover.app/v1/graphql"

CURRENT_BOOK_QUERY = """
{
  me {
    user_books(where: {status_id: {_eq: 2}}, order_by: {last_read_date: desc}, limit: 1) {
      edition { pages }
      user_book_reads(order_by: {id: desc}, limit: 1) { progress_pages }
      book {
        title
        slug
        cached_image
      }
    }
  }
}
"""

ALL_READS_QUERY = """
{
  me {
    user_books {
      user_book_reads(order_by: {started_at: asc}) {
        started_at
        progress_pages
      }
    }
  }
}
"""

START = "<!--START_SECTION:reading-->"
END = "<!--END_SECTION:reading-->"
IMAGE_PATH_LIGHT = "assets/reading_card_light.png"
IMAGE_PATH_DARK = "assets/reading_card_dark.png"

# Sunday-first week, matching S M T W T F S display order.
WEEKDAY_LETTERS = ["S", "M", "T", "W", "T", "F", "S"]

# Logical (CSS-displayed) size; actual canvas is rendered at SCALE x this for sharpness.
W, H = 300, 150
SCALE = 3

GOLD = (244, 180, 66, 255)

PALETTES = {
    "light": {"text": (40, 40, 40, 255), "muted": (110, 110, 110, 255), "line": (200, 200, 200, 255), "outline": (170, 170, 170, 255)},
    "dark": {"text": (235, 235, 235, 255), "muted": (170, 170, 170, 255), "line": (80, 80, 80, 255), "outline": (110, 110, 110, 255)},
}

FONT_CANDIDATES_BOLD = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    r"C:\Users\LumosDhia\Downloads\JetBrainsMono\JetBrainsMonoNerdFont-Bold.ttf",
]
FONT_CANDIDATES_REG = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    r"C:\Users\LumosDhia\Downloads\JetBrainsMono\JetBrainsMonoNerdFont-Regular.ttf",
]


def _graphql(api_key: str, query: str) -> dict:
    req = urllib.request.Request(
        API_URL,
        data=json.dumps({"query": query}).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.load(resp)


def fetch_current_book(api_key: str):
    payload = _graphql(api_key, CURRENT_BOOK_QUERY)
    user_books = payload.get("data", {}).get("me", [{}])[0].get("user_books", [])
    return user_books[0] if user_books else None


def week_start(today: date) -> date:
    """Most recent Sunday on/before today."""
    return today - timedelta(days=(today.weekday() + 1) % 7)


def fetch_week_activity(api_key: str, today: date):
    """
    Returns (days_active, pages_this_week):
    - days_active: list of 7 bools, Sun..Sat, True if any book had a read logged that day.
    - pages_this_week: pages advanced this week, computed as the delta over each
      book's progress baseline from before the week started (avoids double-counting
      the cumulative progress_pages value across multiple log entries).
    """
    payload = _graphql(api_key, ALL_READS_QUERY)
    user_books = payload.get("data", {}).get("me", [{}])[0].get("user_books", [])

    start = week_start(today)
    days_active = [False] * 7
    pages_this_week = 0

    for ub in user_books:
        prior_max = 0
        for r in ub.get("user_book_reads") or []:
            if not r.get("started_at"):
                continue
            d = date.fromisoformat(r["started_at"])
            pages = r.get("progress_pages") or 0
            if d < start:
                prior_max = max(prior_max, pages)
                continue
            idx = (d - start).days
            if 0 <= idx < 7:
                days_active[idx] = True
            pages_this_week += max(0, pages - prior_max)
            prior_max = max(prior_max, pages)

    return days_active, pages_this_week


def load_font(candidates, size):
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def draw_bolt(draw, cx, cy, size=6, color=GOLD):
    pts = [
        (cx - size * 0.15, cy - size),
        (cx + size * 0.35, cy - size),
        (cx - size * 0.05, cy),
        (cx + size * 0.3, cy),
        (cx - size * 0.35, cy + size),
        (cx - size * 0.1, cy + size * 0.15),
        (cx - size * 0.55, cy + size * 0.15),
    ]
    draw.polygon(pts, fill=color)


def rounded_mask(size, radius):
    mask = Image.new("L", size, 0)
    d = ImageDraw.Draw(mask)
    d.rounded_rectangle([0, 0, size[0], size[1]], radius=radius, fill=255)
    return mask


def fetch_cover(cover_url, cover_w, cover_h):
    try:
        req = urllib.request.Request(cover_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            cover = Image.open(io.BytesIO(resp.read())).convert("RGB")
    except Exception:
        return Image.new("RGB", (cover_w, cover_h), (80, 80, 80))

    cw, ch = cover.size
    scale = max(cover_w / cw, cover_h / ch)
    cover = cover.resize((int(cw * scale), int(ch * scale)))
    left = (cover.width - cover_w) // 2
    top = (cover.height - cover_h) // 2
    return cover.crop((left, top, left + cover_w, top + cover_h))


def render_card(cover_url, pages_this_week, days_active, out_path, theme="light"):
    pal = PALETTES[theme]
    SS = 3  # supersample multiplier on top of SCALE, downsampled at the end for anti-aliasing
    s = SCALE * SS
    img = Image.new("RGBA", (W * s, H * s), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    cover_w, cover_h = 85 * s, 125 * s
    cover = fetch_cover(cover_url, cover_w, cover_h)
    cover_rgba = cover.convert("RGBA")
    cover_rgba.putalpha(rounded_mask((cover_w, cover_h), 8 * s))
    img.paste(cover_rgba, (16 * s, 12 * s), cover_rgba)

    col_left = (16 + 85 + 16) * s  # right column start, after the cover
    col_right = (W - 16) * s

    num_font = load_font(FONT_CANDIDATES_BOLD, 40 * s)
    label_font = load_font(FONT_CANDIDATES_REG, 12 * s)
    num_text = str(pages_this_week)
    bbox = draw.textbbox((0, 0), num_text, font=num_font)
    num_w = bbox[2] - bbox[0]
    draw.text((col_right - num_w, 18 * s), num_text, font=num_font, fill=(255, 255, 255, 255))

    label_text = "pages read"
    lbbox = draw.textbbox((0, 0), label_text, font=label_font)
    lw = lbbox[2] - lbbox[0]
    draw.text((col_right - lw, 66 * s), label_text, font=label_font, fill=pal["muted"])

    draw.line([col_left, 90 * s, col_right, 90 * s], fill=pal["line"], width=max(1, s // 2))

    letter_font = load_font(FONT_CANDIDATES_REG, 12 * s)
    col_w = (col_right - col_left) / 7
    cy = 116 * s
    r = 9 * s
    for i, letter in enumerate(WEEKDAY_LETTERS):
        cx = col_left + col_w * i + col_w / 2
        outline_color = GOLD if days_active[i] else pal["outline"]
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=outline_color, width=max(1, s // 2))
        if days_active[i]:
            draw_bolt(draw, cx, cy, size=6 * s)
        else:
            lb = draw.textbbox((0, 0), letter, font=letter_font)
            lw2 = lb[2] - lb[0]
            lh2 = lb[3] - lb[1]
            draw.text((cx - lw2 / 2, cy - lh2 / 2 - lb[1]), letter, font=letter_font, fill=pal["muted"])

    img = img.resize((W * SCALE, H * SCALE), Image.LANCZOS)
    img.save(out_path)


def main():
    api_key = os.environ.get("HARDCOVER_API_KEY")
    if not api_key:
        print("Missing HARDCOVER_API_KEY", file=sys.stderr)
        sys.exit(1)

    readme_path = sys.argv[1] if len(sys.argv) > 1 else "Readme.md"
    repo_root = os.path.dirname(os.path.abspath(readme_path))
    today = date.today()

    entry = fetch_current_book(api_key)
    days_active, pages_this_week = fetch_week_activity(api_key, today)

    if entry is None:
        block = f"{START}\n📖 No book currently being tracked as reading on Hardcover.\n{END}"
    else:
        cover_url = (entry["book"].get("cached_image") or {}).get("url", "")
        render_card(cover_url, pages_this_week, days_active, os.path.join(repo_root, IMAGE_PATH_LIGHT), theme="light")
        render_card(cover_url, pages_this_week, days_active, os.path.join(repo_root, IMAGE_PATH_DARK), theme="dark")
        alt = f"Currently reading — {pages_this_week} pages this week"
        block = (
            f"{START}\n"
            '<p align="center"><picture>\n'
            f'  <source media="(prefers-color-scheme: dark)" srcset="{IMAGE_PATH_DARK}">\n'
            f'  <img src="{IMAGE_PATH_LIGHT}" alt="{alt}" width="400">\n'
            f"</picture></p>\n{END}"
        )

    with open(readme_path, "r", encoding="utf-8") as f:
        content = f.read()

    pattern = re.compile(f"{re.escape(START)}.*?{re.escape(END)}", re.DOTALL)
    if not pattern.search(content):
        print(f"No {START}/{END} markers found in {readme_path}", file=sys.stderr)
        sys.exit(1)

    new_content = pattern.sub(block, content)

    if new_content != content:
        with open(readme_path, "w", encoding="utf-8") as f:
            f.write(new_content)
        print("Readme.md updated.")
    else:
        print("No changes to Readme.md.")


if __name__ == "__main__":
    main()
