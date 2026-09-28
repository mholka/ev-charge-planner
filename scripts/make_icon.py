"""Render the integration icon (battery + bolt + sun) for home-assistant/brands.

Usage: python scripts/make_icon.py  ->  brand/icon.png (256px), brand/icon@2x.png (512px)
"""

import math
from pathlib import Path

from PIL import Image, ImageDraw

S = 2048  # supersampled canvas
SUN = (255, 179, 0, 255)
BATTERY = (3, 169, 244, 255)
BATTERY_DARK = (2, 119, 189, 255)
BOLT = (255, 255, 255, 255)


def draw() -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Sun behind the battery, top right
    cx, cy, r = 1500, 520, 260
    for i in range(10):
        a = math.radians(i * 36 + 18)
        inner, outer, w = r + 70, r + 230, 60
        d.line(
            [
                (cx + inner * math.cos(a), cy + inner * math.sin(a)),
                (cx + outer * math.cos(a), cy + outer * math.sin(a)),
            ],
            fill=SUN,
            width=w,
        )
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=SUN)

    # Battery body with terminal
    body = [140, 820, 1720, 1720]
    d.rounded_rectangle(body, radius=170, fill=BATTERY_DARK)
    inset = 70
    d.rounded_rectangle(
        [body[0] + inset, body[1] + inset, body[2] - inset, body[3] - inset],
        radius=110,
        fill=BATTERY,
    )
    d.rounded_rectangle([1680, 1090, 1900, 1450], radius=70, fill=BATTERY_DARK)

    # Lightning bolt
    bx, by = 930, 1270
    bolt = [
        (bx + 110, by - 380),
        (bx - 250, by + 60),
        (bx - 20, by + 60),
        (bx - 110, by + 380),
        (bx + 250, by - 60),
        (bx + 20, by - 60),
    ]
    d.polygon(bolt, fill=BOLT)
    return img


def trim_square(img: Image.Image) -> Image.Image:
    """Crop transparent margins and pad to a square."""
    img = img.crop(img.getbbox())
    side = max(img.size)
    out = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    out.paste(img, ((side - img.width) // 2, (side - img.height) // 2))
    return out


def main() -> None:
    out_dir = Path(__file__).resolve().parent.parent / "brand"
    out_dir.mkdir(exist_ok=True)
    icon = trim_square(draw())
    for name, size in (("icon.png", 256), ("icon@2x.png", 512)):
        icon.resize((size, size), Image.LANCZOS).save(out_dir / name, optimize=True)


if __name__ == "__main__":
    main()
