"""Transparent PNG overlays (label cards, clip tag) + thumbnail, rendered with Pillow."""
import platform
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

CARD_COLORS = {"CONFIRMED": (46, 160, 67), "ALLEGED": (214, 40, 40), "RUMOR": (230, 126, 34),
               "SPECULATION": (155, 89, 182), "CLAIM": (214, 40, 40), "QUOTE": (230, 230, 230), "DATE": (52, 152, 219)}

FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Impact.ttf",
    "/System/Library/Fonts/Supplemental/Arial Black.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]


def font(size, fonts_dir: Path = None):
    cands = []
    if fonts_dir and fonts_dir.exists():
        cands += sorted(str(p) for p in fonts_dir.glob("*.[ot]tf"))
    for p in cands + FONT_CANDIDATES:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default(size)


def label_card(kind, text, W, H, out: Path, fonts_dir=None):
    """Lower-left documentary card: colored tag + white statement."""
    s = W / 1920
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    col = CARD_COLORS.get(kind, (214, 40, 40))
    ft, fb = font(int(34 * s), fonts_dir), font(int(54 * s), fonts_dir)
    x, y = int(90 * s), int(H - 470 * s)  # above subtitle zone
    lines = textwrap.wrap(text.upper(), 30)[:2]
    tw = max([d.textlength(l, font=fb) for l in lines] + [d.textlength(kind, font=ft) + 40 * s])
    box_h = int((70 + 66 * len(lines)) * s)
    d.rectangle([x - 24 * s, y - 20 * s, x + tw + 36 * s, y + box_h], fill=(0, 0, 0, 175))
    d.rectangle([x - 24 * s, y - 20 * s, x - 14 * s, y + box_h], fill=col + (255,))
    d.rectangle([x, y, x + d.textlength(kind, font=ft) + 24 * s, y + 46 * s], fill=col + (255,))
    d.text((x + 12 * s, y + 4 * s), kind, font=ft, fill=(255, 255, 255, 255) if kind != "QUOTE" else (0, 0, 0, 255))
    for i, l in enumerate(lines):
        d.text((x, y + (62 + 64 * i) * s), l, font=fb, fill=(255, 255, 255, 255))
    img.save(out)
    return out


def clip_tag(text, W, H, out: Path, fonts_dir=None):
    s = W / 1920
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    f = font(int(30 * s), fonts_dir)
    x, y = int(W - 60 * s - d.textlength(text, font=f) - 50 * s), int(55 * s)
    d.rectangle([x, y, W - 60 * s, y + 52 * s], fill=(200, 20, 20, 230))
    d.ellipse([x + 14 * s, y + 18 * s, x + 30 * s, y + 34 * s], fill=(255, 255, 255, 255))
    d.text((x + 40 * s, y + 9 * s), text, font=f, fill=(255, 255, 255, 255))
    img.save(out)
    return out


def thumbnail(frame: Path, text, out: Path, fonts_dir=None):
    im = Image.open(frame).convert("RGB").resize((1280, 720))
    im = ImageEnhance.Contrast(ImageEnhance.Color(im).enhance(1.25)).enhance(1.2)
    grad = Image.new("L", (1280, 720))
    gd = ImageDraw.Draw(grad)
    for x in range(1280):
        gd.line([(x, 0), (x, 720)], fill=int(max(0, 230 - x * 0.35)))
    dark = Image.new("RGB", (1280, 720), (0, 0, 0))
    im = Image.composite(dark, im, grad)
    d = ImageDraw.Draw(im)
    words = text.upper().split()
    lines, cur = [], ""
    for w in words:
        if len(cur + " " + w) > 12 and cur:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    lines.append(cur)
    f = font(118 if len(lines) <= 2 else 92, fonts_dir)
    y = 360 - len(lines) * 62
    for i, l in enumerate(lines[:3]):
        fill = (255, 214, 0) if i == len(lines[:3]) - 1 else (255, 255, 255)
        for dx, dy in [(-4, 0), (4, 0), (0, -4), (0, 4), (5, 5)]:
            d.text((60 + dx, y + dy), l, font=f, fill=(0, 0, 0))
        d.text((60, y), l, font=f, fill=fill)
        y += f.size + 10
    im.save(out, quality=92)
    return out
