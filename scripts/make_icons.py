"""
Generate Lumen's icon set from code (no binary assets checked in).

Produces, in lumen/assets/:
    lumen.png         1024x1024 master
    lumen_256.png     256x256 (tray / linux)
    lumen.ico         multi-size Windows icon
    lumen.iconset/    PNG set for building lumen.icns on macOS

The mark: a rounded-square "aperture" with a warm light gradient and a
crescent that evokes brightness / gamma falloff — bright on one edge, deep on
the other, with a soft glow.
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ASSETS = Path(__file__).resolve().parent.parent / "lumen" / "assets"
ASSETS.mkdir(parents=True, exist_ok=True)

# Brand palette
BG_TOP = (18, 18, 26)
BG_BOTTOM = (9, 9, 14)
AMBER = (245, 166, 35)
AMBER_HI = (255, 205, 120)
GLOW = (255, 180, 70)


def _rounded_mask(size: int, radius_frac: float = 0.22) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(mask)
    r = int(size * radius_frac)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=r, fill=255)
    return mask


def _vertical_gradient(size: int, top, bottom) -> Image.Image:
    grad = Image.new("RGB", (1, size))
    for y in range(size):
        t = y / max(1, size - 1)
        grad.putpixel((0, y), tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    return grad.resize((size, size))


def make_master(size: int = 1024) -> Image.Image:
    base = _vertical_gradient(size, BG_TOP, BG_BOTTOM).convert("RGBA")

    # Radial warm glow behind the mark
    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    cx, cy = size * 0.5, size * 0.46
    max_r = size * 0.42
    steps = 60
    for i in range(steps, 0, -1):
        t = i / steps
        r = max_r * t
        alpha = int(70 * (1 - t))
        gd.ellipse([cx - r, cy - r, cx + r, cy + r],
                   fill=(GLOW[0], GLOW[1], GLOW[2], alpha))
    glow = glow.filter(ImageFilter.GaussianBlur(size * 0.03))
    base = Image.alpha_composite(base, glow)

    # The luminous disc
    disc = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    dd = ImageDraw.Draw(disc)
    R = size * 0.30
    # radial fill: bright top-left -> amber -> dark bottom-right (gamma falloff)
    grid = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    px = grid.load()
    lx, ly = cx - R * 0.4, cy - R * 0.4
    for y in range(int(cy - R), int(cy + R) + 1):
        for x in range(int(cx - R), int(cx + R) + 1):
            if 0 <= x < size and 0 <= y < size:
                if (x - cx) ** 2 + (y - cy) ** 2 <= R * R:
                    d = math.hypot(x - lx, y - ly) / (R * 1.7)
                    d = min(1.0, d)
                    col = tuple(int(AMBER_HI[i] + (BG_BOTTOM[i] - AMBER_HI[i]) * d) for i in range(3))
                    px[x, y] = (col[0], col[1], col[2], 255)
    disc = Image.alpha_composite(disc, grid)

    # Crescent shadow: offset dark circle subtracts from the disc for a sleek cut
    cres = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    cd = ImageDraw.Draw(cres)
    off = R * 0.55
    cd.ellipse([cx - R + off, cy - R - off * 0.2, cx + R + off, cy + R - off * 0.2],
               fill=(BG_BOTTOM[0], BG_BOTTOM[1], BG_BOTTOM[2], 255))
    # keep crescent within the disc only
    disc_mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(disc_mask).ellipse([cx - R, cy - R, cx + R, cy + R], fill=255)
    cres.putalpha(Image.composite(cres.getchannel("A"), Image.new("L", (size, size), 0), disc_mask))
    disc = Image.alpha_composite(disc, cres)

    base = Image.alpha_composite(base, disc)

    # Thin amber rim
    rim = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(rim).ellipse([cx - R, cy - R, cx + R, cy + R],
                                outline=(AMBER[0], AMBER[1], AMBER[2], 230),
                                width=max(2, int(size * 0.006)))
    base = Image.alpha_composite(base, rim)

    # Apply rounded-square mask
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(base, (0, 0), _rounded_mask(size))
    return out


def main():
    master = make_master(1024)
    master.save(ASSETS / "lumen.png")
    master.resize((256, 256), Image.LANCZOS).save(ASSETS / "lumen_256.png")

    # Windows .ico (multi-size)
    ico_sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    master.save(ASSETS / "lumen.ico", sizes=ico_sizes)

    # macOS .iconset folder (build .icns with `iconutil` on a Mac / CI)
    iconset = ASSETS / "lumen.iconset"
    iconset.mkdir(exist_ok=True)
    for base in (16, 32, 64, 128, 256, 512):
        master.resize((base, base), Image.LANCZOS).save(iconset / f"icon_{base}x{base}.png")
        master.resize((base * 2, base * 2), Image.LANCZOS).save(iconset / f"icon_{base}x{base}@2x.png")

    print(f"Icons written to {ASSETS}")


if __name__ == "__main__":
    main()
