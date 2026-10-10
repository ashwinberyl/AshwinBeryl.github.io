#!/usr/bin/env python3
"""Generate a LinkedIn / social share page + preview image for one blog post.

Why: the blog loads posts via '#path' URLs. Link-preview crawlers (LinkedIn,
X, Slack, WhatsApp) ignore everything after '#' and don't run JavaScript, so
they can't see a post's title or image. This script writes a tiny static page
per post with Open Graph tags; humans who open it are redirected to the real post.

Usage (from the repo root):
    python3 blogs/tools/make_share_card.py \
        --post data-engineering/01-what-is-data-engineering.md \
        --slug de-01 \
        --eyebrow "DATA ENGINEERING FROM FIRST PRINCIPLES  ·  POST 01 / 18" \
        --title "What Data Engineering Actually Is" \
        --subtitle "Facts, dimensions & the RepoSphere problem" \
        --description "One-sentence summary shown under the link preview."

Outputs:
    blogs/share/<slug>.html          share this URL on LinkedIn
    blogs/share/images/<slug>.png    1200x627 preview image

Needs ImageMagick (`convert`) with the DejaVu fonts.
"""
import argparse
import html
import subprocess
import textwrap
from pathlib import Path
from urllib.parse import quote

SITE = "https://ashwinberyl.github.io"
W, H = 1200, 627

BG = "#0f1720"
ACCENT = "#3fb8a3"
INK = "#f2f5f7"
MUTED = "#9aa8b4"


def make_image(out: Path, eyebrow: str, title: str, subtitle: str) -> None:
    title_lines = textwrap.wrap(title, width=24)[:3]
    title_size = 72 if len(title_lines) <= 2 else 60
    line_h = int(title_size * 1.15)

    cmd = ["convert", "-size", f"{W}x{H}", f"xc:{BG}",
           # accent bar on the left
           "-fill", ACCENT, "-draw", "rectangle 0,0 14,627",
           # eyebrow
           "-font", "DejaVu-Sans-Bold", "-pointsize", "24", "-fill", ACCENT,
           "-annotate", "+80+110", eyebrow]
    y = 110 + 40 + title_size
    for line in title_lines:
        cmd += ["-font", "DejaVu-Sans-Bold", "-pointsize", str(title_size),
                "-fill", INK, "-annotate", f"+80+{y}", line]
        y += line_h
    cmd += ["-font", "DejaVu-Sans", "-pointsize", "34", "-fill", MUTED,
            "-annotate", f"+80+{y + 30}", subtitle,
            # footer
            "-fill", "#1f2c38", "-draw", f"rectangle 0,{H - 90} {W},{H}",
            "-fill", ACCENT, "-draw", f"rectangle 0,{H - 90} 14,{H}",
            "-font", "DejaVu-Sans-Bold", "-pointsize", "28", "-fill", INK,
            "-annotate", f"+80+{H - 35}", "Ashwin Kalaichandran",
            "-font", "DejaVu-Sans", "-pointsize", "26", "-fill", MUTED,
            "-gravity", "SouthEast", "-annotate", "+60+29", "ashwinberyl.github.io/blogs",
            str(out)]
    subprocess.run(cmd, check=True)


def make_page(out: Path, slug: str, post: str, title: str, description: str) -> None:
    post_url = f"{SITE}/blogs/#{quote(post, safe='')}"
    share_url = f"{SITE}/blogs/share/{slug}.html"
    image_url = f"{SITE}/blogs/share/images/{slug}.png"
    t, d = html.escape(title, quote=True), html.escape(description, quote=True)
    out.write_text(f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{t} | Ashwin Blogs</title>
    <meta name="description" content="{d}">
    <link rel="canonical" href="{post_url}">

    <!-- Open Graph: LinkedIn, Facebook, WhatsApp, Slack -->
    <meta property="og:type" content="article">
    <meta property="og:site_name" content="Ashwin Blogs">
    <meta property="og:title" content="{t}">
    <meta property="og:description" content="{d}">
    <meta property="og:url" content="{share_url}">
    <meta property="og:image" content="{image_url}">
    <meta property="og:image:width" content="{W}">
    <meta property="og:image:height" content="{H}">
    <meta property="og:image:alt" content="{t}">
    <meta property="article:author" content="Ashwin Kalaichandran">

    <!-- X / Twitter -->
    <meta name="twitter:card" content="summary_large_image">
    <meta name="twitter:title" content="{t}">
    <meta name="twitter:description" content="{d}">
    <meta name="twitter:image" content="{image_url}">

    <!-- Send people (not crawlers) straight to the post -->
    <meta http-equiv="refresh" content="0; url={post_url}">
    <script>window.location.replace({post_url!r});</script>
</head>
<body>
    <p>Redirecting to <a href="{post_url}">{t}</a>…</p>
</body>
</html>
""")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--post", required=True, help="path under blogs/content/, e.g. data-engineering/01-x.md")
    p.add_argument("--slug", required=True, help="short file name for the share page, e.g. de-01")
    p.add_argument("--eyebrow", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--subtitle", required=True)
    p.add_argument("--description", required=True)
    a = p.parse_args()

    root = Path(__file__).resolve().parents[1] / "share"
    (root / "images").mkdir(parents=True, exist_ok=True)
    make_image(root / "images" / f"{a.slug}.png", a.eyebrow, a.title, a.subtitle)
    make_page(root / f"{a.slug}.html", a.slug, a.post, a.title, a.description)
    print(f"Share URL: {SITE}/blogs/share/{a.slug}.html")


if __name__ == "__main__":
    main()
