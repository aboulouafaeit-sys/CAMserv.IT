"""CAMserv - Production Brand Asset Generator & 100% Transparency Processor.

Eliminates all bounding boxes, dark rectangles, and halo artifacts from GitHub README
and Web Console assets, producing true 100% transparent PNGs with mathematically
clean alpha antialiasing and color decontamination.
"""

import os
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

BRAIN_DIR = r"C:\Users\MPront\.gemini\antigravity\brain\61f95269-dd17-48f8-a02a-17087ae718a2"
CONCEPT_JPG = os.path.join(BRAIN_DIR, "camserv_logo_concept_1794606854279.jpg")
SYMBOL_JPG = os.path.join(BRAIN_DIR, "camserv_symbol_isolated_dark_1794606905422.jpg")

BRAND_DIR = r"c:\Users\MPront\Documents\CAMserv\assets\branding"
WEB_DIR = r"c:\Users\MPront\Documents\CAMserv\src\camserv\web\assets"

os.makedirs(BRAND_DIR, exist_ok=True)
os.makedirs(WEB_DIR, exist_ok=True)


def generate_transparent_shield_logo():
    """Extracts master shield emblem and typography with 100% transparent background."""
    print("Processing Master Shield Emblem...")
    img = cv2.imread(CONCEPT_JPG)
    h, w, _ = img.shape
    b, g, r = cv2.split(img)
    lum = 0.114 * b + 0.587 * g + 0.299 * r

    # 1. Segment Shield (y: 140..680, x: 150..874)
    shield_roi = lum[140:680, 150:874]
    bright_shield = (shield_roi > 35).astype(np.uint8) * 255
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
    closed_shield = cv2.morphologyEx(bright_shield, cv2.MORPH_CLOSE, kernel)

    # Fill shield interior plates
    contours, _ = cv2.findContours(closed_shield, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    shield_filled = np.zeros_like(shield_roi, dtype=np.uint8)
    for c in contours:
        if cv2.contourArea(c) > 1000:
            cv2.drawContours(shield_filled, [c], -1, 255, -1)

    full_mask = np.zeros((h, w), dtype=np.uint8)
    full_mask[140:680, 150:874] = shield_filled

    # 2. Segment Typography (y: 720..880, x: 100..924)
    text_roi = lum[720:880, 100:924]
    letter_mask = (text_roi > 30).astype(np.uint8) * 255
    contours_t, _ = cv2.findContours(letter_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    clean_letters = np.zeros_like(text_roi, dtype=np.uint8)
    for c in contours_t:
        if cv2.contourArea(c) > 15:
            cv2.drawContours(clean_letters, [c], -1, 255, -1)
    full_mask[720:880, 100:924] = clean_letters

    # 3. Subpixel antialiasing with signed distance transform
    dist_in = cv2.distanceTransform(full_mask, cv2.DIST_L2, 3)
    dist_out = cv2.distanceTransform(255 - full_mask, cv2.DIST_L2, 3)
    signed = dist_in - dist_out
    alpha = np.clip((signed + 1.5) / 3.0, 0.0, 1.0)

    # 4. Color decontamination
    bg_est = cv2.GaussianBlur(img, (51, 51), 0).astype(float)
    decontam = np.zeros_like(img, dtype=float)
    for c in range(3):
        decontam[:, :, c] = (img[:, :, c].astype(float) - (1.0 - alpha) * bg_est[:, :, c]) / np.maximum(alpha, 0.05)
    decontam = np.clip(decontam, 0, 255).astype(np.uint8)

    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    rgba[:, :, :3] = cv2.cvtColor(decontam, cv2.COLOR_BGR2RGB)
    rgba[:, :, 3] = (alpha * 255).astype(np.uint8)

    # Crop with 25px uniform transparent padding
    y_idx, x_idx = np.where(rgba[:, :, 3] > 0)
    pad = 25
    x1, x2 = max(0, x_idx.min() - pad), min(w, x_idx.max() + pad)
    y1, y2 = max(0, y_idx.min() - pad), min(h, y_idx.max() + pad)
    cropped = rgba[y1:y2, x1:x2]

    im_shield = Image.fromarray(cropped)
    im_shield.save(os.path.join(BRAND_DIR, "camserv-logo-transparent.png"), "PNG")
    im_shield.save(os.path.join(BRAND_DIR, "camserv-logo-master.png"), "PNG")
    im_shield.save(os.path.join(WEB_DIR, "camserv-logo-transparent.png"), "PNG")
    im_shield.save(os.path.join(WEB_DIR, "logo-primary-dark.png"), "PNG")
    print(f"Master Shield Logo saved: {im_shield.size}")
    return im_shield


def generate_transparent_symbol():
    """Extracts isolated cyber-eagle symbol mark on 100% transparent background."""
    print("Processing Isolated Cyber-Eagle Symbol...")
    sym_raw = cv2.imread(SYMBOL_JPG)
    b, g, r = cv2.split(sym_raw)
    lum = 0.114 * b + 0.587 * g + 0.299 * r

    # Smooth alpha from black background
    alpha = np.clip((lum - 6.0) / 32.0, 0.0, 1.0)
    decontam = np.zeros_like(sym_raw, dtype=float)
    for c in range(3):
        decontam[:, :, c] = sym_raw[:, :, c].astype(float) / np.maximum(alpha, 0.05)
    decontam = np.clip(decontam, 0, 255).astype(np.uint8)

    sym_rgba = np.zeros((sym_raw.shape[0], sym_raw.shape[1], 4), dtype=np.uint8)
    sym_rgba[:, :, :3] = cv2.cvtColor(decontam, cv2.COLOR_BGR2RGB)
    sym_rgba[:, :, 3] = (alpha * 255).astype(np.uint8)

    y_idx, x_idx = np.where(sym_rgba[:, :, 3] > 0)
    pad = 20
    x1, x2 = max(0, x_idx.min() - pad), min(sym_raw.shape[1], x_idx.max() + pad)
    y1, y2 = max(0, y_idx.min() - pad), min(sym_raw.shape[0], y_idx.max() + pad)
    cropped = sym_rgba[y1:y2, x1:x2]

    im_sym = Image.fromarray(cropped)
    im_sym.save(os.path.join(BRAND_DIR, "camserv-symbol.png"), "PNG")
    im_sym.save(os.path.join(WEB_DIR, "logo-symbol.png"), "PNG")
    print(f"Cyber-Eagle Symbol saved: {im_sym.size}")
    return im_sym


def generate_transparent_wordmark(im_sym):
    """Generates horizontal wordmark banner on 100% transparent canvas."""
    print("Generating Pristine Transparent Wordmark...")
    canvas_w = 840
    canvas_h = 180
    canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))

    # Resize symbol
    sym_size = 140
    sym_aspect = im_sym.width / im_sym.height
    sym_w = int(sym_size * sym_aspect)
    sym_h = sym_size
    sym_resized = im_sym.resize((sym_w, sym_h), Image.LANCZOS)

    sym_x = 25
    sym_y = (canvas_h - sym_h) // 2
    canvas.alpha_composite(sym_resized, (sym_x, sym_y))

    # Typography
    font_title = ImageFont.truetype(r"C:\Windows\Fonts\segoeuib.ttf", 72)
    font_sub = ImageFont.truetype(r"C:\Windows\Fonts\segoeui.ttf", 20)

    text_x = sym_x + sym_w + 35
    title_y = 32
    draw = ImageDraw.Draw(canvas)

    # 'CAM' in white #FFFFFF
    draw.text((text_x, title_y), "CAM", font=font_title, fill=(255, 255, 255, 255))
    cam_width = font_title.getlength("CAM")

    # 'serv' in vibrant cyan #22D3EE
    draw.text((text_x + cam_width, title_y), "serv", font=font_title, fill=(34, 211, 238, 255))

    # Subtitle 'SECURITY INTELLIGENCE PLATFORM'
    sub_y = title_y + 80
    sub_text = "S E C U R I T Y   I N T E L L I G E N C E   P L A T F O R M"
    draw.text((text_x + 2, sub_y), sub_text, font=font_sub, fill=(56, 189, 248, 240))

    bbox = canvas.getbbox()
    pad_x = 25
    pad_y = 15
    cropped = canvas.crop((max(0, bbox[0] - pad_x), max(0, bbox[1] - pad_y), min(canvas_w, bbox[2] + pad_x), min(canvas_h, bbox[3] + pad_y)))

    cropped.save(os.path.join(BRAND_DIR, "camserv-wordmark.png"), "PNG")
    print(f"Wordmark saved: {cropped.size}")
    return cropped


def generate_favicons_and_icons(im_sym):
    """Generates multi-resolution square app icons and favicons."""
    print("Generating App Icons and Favicons...")
    def make_square_icon(src_img, size):
        target_dim = int(size * 0.90)
        w, h = src_img.size
        ratio = min(target_dim / w, target_dim / h)
        nw, nh = int(w * ratio), int(h * ratio)
        resized = src_img.resize((nw, nh), Image.LANCZOS)
        canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        canvas.alpha_composite(resized, ((size - nw) // 2, (size - nh) // 2))
        return canvas

    # App icon 512x512
    app_icon = make_square_icon(im_sym, 512)
    app_icon.save(os.path.join(BRAND_DIR, "camserv-app-icon.png"), "PNG")

    # Favicons
    sizes = [16, 32, 48, 64, 128, 192, 256, 512, 1024]
    ico_imgs = []
    for s in sizes:
        fav = make_square_icon(im_sym, s)
        fav.save(os.path.join(BRAND_DIR, f"favicon-{s}x{s}.png"), "PNG")
        if s == 32:
            fav.save(os.path.join(BRAND_DIR, "camserv-favicon.png"), "PNG")
            fav.save(os.path.join(WEB_DIR, "favicon.png"), "PNG")
        if s in [16, 32, 48, 64, 128, 256]:
            ico_imgs.append(fav)

    ico_imgs[0].save(
        os.path.join(BRAND_DIR, "favicon.ico"),
        format="ICO",
        sizes=[(f.width, f.height) for f in ico_imgs],
        append_images=ico_imgs[1:]
    )
    ico_imgs[0].save(
        os.path.join(WEB_DIR, "favicon.ico"),
        format="ICO",
        sizes=[(f.width, f.height) for f in ico_imgs],
        append_images=ico_imgs[1:]
    )
    print("All favicons and ICO files generated successfully.")


def verify_transparency():
    """Rigorously verifies 100% transparency on GitHub themes."""
    print("\n--- Running Rigorous Transparency Verification ---")
    themes = {
        "GitHub Dark (#0d1117)": [13, 17, 23],
        "GitHub Dark Dimmed (#22272e)": [34, 39, 46],
        "GitHub Light (#ffffff)": [255, 255, 255],
    }

    files = [
        ("Master Shield", os.path.join(BRAND_DIR, "camserv-logo-transparent.png")),
        ("Symbol Mark", os.path.join(BRAND_DIR, "camserv-symbol.png")),
        ("Wordmark Banner", os.path.join(BRAND_DIR, "camserv-wordmark.png")),
    ]

    all_passed = True
    for label, path in files:
        im = Image.open(path)
        arr = np.array(im)
        alpha = arr[:, :, 3]

        # Check outer 10 pixels for alpha == 0
        top_a = alpha[:10, :].max()
        bot_a = alpha[-10:, :].max()
        left_a = alpha[:, :10].max()
        right_a = alpha[:, -10:].max()
        border_leak = max(top_a, bot_a, left_a, right_a)

        for theme_name, bg_rgb in themes.items():
            bg = Image.new("RGBA", im.size, (*bg_rgb, 255))
            comp = Image.alpha_composite(bg, im)
            comp_arr = np.array(comp)[:, :, :3]

            corners = [
                comp_arr[0, 0],
                comp_arr[0, -1],
                comp_arr[-1, 0],
                comp_arr[-1, -1]
            ]
            corner_diff = max(np.abs(c.astype(int) - bg_rgb).max() for c in corners)

            if border_leak != 0 or corner_diff != 0:
                print(f"[FAIL] {label} on {theme_name}: border_alpha={border_leak}, corner_diff={corner_diff}")
                all_passed = False
            else:
                print(f"[PASS] {label} on {theme_name}: 100% transparent blend (diff=0)")

    if all_passed:
        print("\nAll assets passed 100% true transparent verification!")
    else:
        raise RuntimeError("Transparency verification failed on some assets.")


if __name__ == "__main__":
    shield = generate_transparent_shield_logo()
    symbol = generate_transparent_symbol()
    wordmark = generate_transparent_wordmark(symbol)
    generate_favicons_and_icons(symbol)
    verify_transparency()
