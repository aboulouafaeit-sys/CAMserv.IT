#!/usr/bin/env python3
"""
scripts/generate_social_preview.py
==================================

Generates the official GitHub Social Preview Card (1280x640) and Documentation Header (1200x300)
for CAMserv using official brand assets, tactical gridlines, and typography.
"""

from __future__ import annotations

import math
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter


def create_social_preview() -> None:
    width, height = 1280, 640
    # Create base dark command canvas: #0A0F1D -> #0F172A
    canvas = Image.new("RGBA", (width, height), (10, 15, 29, 255))
    draw = ImageDraw.Draw(canvas)

    # 1. Subtle radial ambient glow on left where emblem sits
    glow_center_x, glow_center_y = 300, 320
    glow_radius = 420
    glow_layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow_layer)

    for r in range(glow_radius, 0, -12):
        alpha = int(45 * (1.0 - (r / glow_radius) ** 1.5))
        glow_draw.ellipse(
            [glow_center_x - r, glow_center_y - r, glow_center_x + r, glow_center_y + r],
            fill=(0, 229, 255, alpha),
        )
    canvas = Image.alpha_composite(canvas, glow_layer)
    draw = ImageDraw.Draw(canvas)

    # 2. Subtle technical gridlines in background
    grid_color = (30, 41, 59, 70)
    for x in range(0, width, 40):
        draw.line([(x, 0), (x, height)], fill=grid_color, width=1)
    for y in range(0, height, 40):
        draw.line([(0, y), (width, y)], fill=grid_color, width=1)

    # Technical corner crosshairs
    corners = [(40, 40), (width - 40, 40), (40, height - 40), (width - 40, height - 40)]
    for cx, cy in corners:
        draw.line([(cx - 15, cy), (cx + 15, cy)], fill=(0, 229, 255, 180), width=2)
        draw.line([(cx, cy - 15), (cx, cy + 15)], fill=(0, 229, 255, 180), width=2)

    # 3. Paste Official Emblem
    emblem_path = Path("assets/branding/camserv-logo-transparent.png")
    if emblem_path.exists():
        emblem = Image.open(emblem_path).convert("RGBA")
        # Resize preserving aspect ratio (height ~460px)
        aspect = emblem.width / emblem.height
        target_h = 440
        target_w = int(target_h * aspect)
        emblem_resized = emblem.resize((target_w, target_h), Image.Resampling.LANCZOS)
        emblem_x = 90
        emblem_y = (height - target_h) // 2
        canvas.paste(emblem_resized, (emblem_x, emblem_y), emblem_resized)

    # 4. Text Typography on Right
    # Load fonts
    try:
        font_brand = ImageFont.truetype("arialbd.ttf", 78)
        font_sub = ImageFont.truetype("arialbd.ttf", 20)
        font_tagline = ImageFont.truetype("arial.ttf", 26)
        font_pill = ImageFont.truetype("arialbd.ttf", 16)
    except Exception:
        font_brand = font_sub = font_tagline = font_pill = ImageFont.load_default()

    text_x = 540
    # Top Category Pill: "ENTERPRISE SECURITY INTELLIGENCE"
    pill_text = "ENTERPRISE SECURITY INTELLIGENCE"
    pill_w = 340
    pill_h = 32
    pill_y = 130
    draw.rounded_rectangle([text_x, pill_y, text_x + pill_w, pill_y + pill_h], radius=6, fill=(30, 41, 59, 220), outline=(0, 229, 255, 160), width=1)
    draw.text((text_x + 18, pill_y + 6), pill_text, fill=(0, 229, 255, 255), font=font_pill)

    # Brand Title: "CAMserv"
    title_y = 185
    draw.text((text_x, title_y), "CAM", fill=(255, 255, 255, 255), font=font_brand)
    # Get width of "CAM"
    cam_bbox = draw.textbbox((text_x, title_y), "CAM", font=font_brand)
    cam_w = cam_bbox[2] - cam_bbox[0]
    draw.text((text_x + cam_w + 4, title_y), "serv", fill=(0, 229, 255, 255), font=font_brand)

    # Subtitle Divider & Text
    div_y = title_y + 92
    draw.line([(text_x, div_y), (width - 90, div_y)], fill=(59, 130, 246, 180), width=2)
    draw.ellipse([text_x - 3, div_y - 3, text_x + 3, div_y + 3], fill=(0, 229, 255, 255))
    draw.ellipse([width - 93, div_y - 3, width - 87, div_y + 3], fill=(59, 130, 246, 255))

    # Core Tagline
    tagline_y = div_y + 24
    draw.text(
        (text_x, tagline_y),
        "Privacy-First Video Intelligence\nAdaptive Edge AI & Verifiable Evidence",
        fill=(226, 232, 240, 255),
        font=font_tagline,
        spacing=8,
    )

    # Feature Badges Row
    badge_y = tagline_y + 95
    badges = [
        ("100% On-Premise", (16, 185, 129)),  # Emerald
        ("Fail-Closed Privacy", (0, 229, 255)),  # Cyan
        ("Dual-Control Quorum", (59, 130, 246)),  # Blue
        ("Ed25519 Signed", (139, 92, 246)),  # Purple
    ]

    bx = text_x
    for label, col in badges:
        bw = draw.textlength(label, font=font_pill) + 24
        draw.rounded_rectangle([bx, badge_y, bx + bw, badge_y + 28], radius=5, fill=(15, 23, 42, 240), outline=col, width=1)
        draw.text((bx + 12, badge_y + 5), label, fill=col, font=font_pill)
        bx += bw + 12

    # Save output
    out_path = Path("assets/branding/camserv-social-preview.png")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path, format="PNG")
    print(f"[*] Generated: {out_path} ({width}x{height})")


def create_docs_header() -> None:
    width, height = 1200, 300
    canvas = Image.new("RGBA", (width, height), (10, 15, 29, 255))
    draw = ImageDraw.Draw(canvas)

    # Gridlines
    grid_color = (30, 41, 59, 60)
    for x in range(0, width, 40):
        draw.line([(x, 0), (x, height)], fill=grid_color, width=1)
    for y in range(0, height, 40):
        draw.line([(0, y), (width, y)], fill=grid_color, width=1)

    # Gradient line on top
    for x in range(width):
        frac = x / width
        r = int(0 * (1 - frac) + 59 * frac)
        g = int(229 * (1 - frac) + 130 * frac)
        b = int(255 * (1 - frac) + 246 * frac)
        draw.line([(x, 0), (x, 3)], fill=(r, g, b, 255))

    # Paste Emblem on left
    emblem_path = Path("assets/branding/camserv-logo-transparent.png")
    if emblem_path.exists():
        emblem = Image.open(emblem_path).convert("RGBA")
        aspect = emblem.width / emblem.height
        target_h = 230
        target_w = int(target_h * aspect)
        emblem_resized = emblem.resize((target_w, target_h), Image.Resampling.LANCZOS)
        canvas.paste(emblem_resized, (60, (height - target_h) // 2), emblem_resized)

    try:
        font_brand = ImageFont.truetype("arialbd.ttf", 64)
        font_sub = ImageFont.truetype("arialbd.ttf", 15)
        font_desc = ImageFont.truetype("arial.ttf", 20)
    except Exception:
        font_brand = font_sub = font_desc = ImageFont.load_default()

    tx = 330
    draw.text((tx, 65), "CAM", fill=(255, 255, 255, 255), font=font_brand)
    cam_w = draw.textlength("CAM", font=font_brand)
    draw.text((tx + cam_w + 3, 65), "serv", fill=(0, 229, 255, 255), font=font_brand)

    draw.text((tx, 145), "ADVANCED SECURITY INTELLIGENCE PLATFORM", fill=(0, 229, 255, 255), font=font_sub)
    draw.text((tx, 180), "Official Engineering & Technical Documentation Architecture", fill=(148, 163, 184, 255), font=font_desc)

    out_path = Path("assets/branding/camserv-docs-header.png")
    canvas.save(out_path, format="PNG")
    print(f"[*] Generated: {out_path} ({width}x{height})")


if __name__ == "__main__":
    create_social_preview()
    create_docs_header()
