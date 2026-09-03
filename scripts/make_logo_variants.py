"""Derive the two transparent logo variants the app and the workbooks need.

The shipped mark is a JPG: a near-black plate (85 % of the image) with the
leaf in Versigent orange and the wordmark in white. That plate is why the
logo read as invisible in the dark rail — the mark itself occupied a
quarter of the box — and why it would print as a black rectangle on a white
Excel sheet.

    python scripts/make_logo_variants.py

writes, next to the source:

* ``versigent_logo_dark.png``  — cropped, transparent, white wordmark (dark UI)
* ``versigent_logo_light.png`` — cropped, transparent, ink wordmark (white paper)

Both are committed; this script only has to run again if the source mark
changes.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

ASSETS = Path(__file__).resolve().parents[1] / "assets"
SOURCE = ASSETS / "versigent_logo_horizontal.jpg"
INK = (20, 24, 31)          # the study's ink, for white grounds
EDGE = 60                   # channel distance at which a pixel is fully opaque
PAD = 8                     # breathing room around the mark, in source pixels


def build() -> list[Path]:
    src = Image.open(SOURCE).convert("RGB")
    plate = src.getpixel((0, 0))
    px = src.load()
    width, height = src.size

    def distance(x: int, y: int) -> int:
        r, g, b = px[x, y]
        return max(abs(r - plate[0]), abs(g - plate[1]), abs(b - plate[2]))

    # tight crop on anything that is not the plate
    xs = [x for x in range(width) if any(distance(x, y) > EDGE for y in range(height))]
    ys = [y for y in range(height) if any(distance(x, y) > EDGE for x in range(width))]
    box = (max(min(xs) - PAD, 0), max(min(ys) - PAD, 0),
           min(max(xs) + PAD + 1, width), min(max(ys) + PAD + 1, height))
    cropped = src.crop(box)
    cw, ch = cropped.size
    cpx = cropped.load()

    dark = Image.new("RGBA", (cw, ch))
    light = Image.new("RGBA", (cw, ch))
    dpx, lpx = dark.load(), light.load()
    for y in range(ch):
        for x in range(cw):
            r, g, b = cpx[x, y]
            dist = max(abs(r - plate[0]), abs(g - plate[1]), abs(b - plate[2]))
            alpha = min(255, round(dist * 255 / EDGE))
            dpx[x, y] = (r, g, b, alpha)
            # the wordmark is neutral, the leaf is not: recolour only neutrals
            if max(r, g, b) - min(r, g, b) < 30:
                lpx[x, y] = (*INK, alpha)
            else:
                lpx[x, y] = (r, g, b, alpha)

    made = []
    for name, image in (("versigent_logo_dark.png", dark),
                        ("versigent_logo_light.png", light)):
        path = ASSETS / name
        image.save(path, optimize=True)
        made.append(path)
    return made


if __name__ == "__main__":
    for path in build():
        image = Image.open(path)
        print(f"{path.name}: {image.size[0]}x{image.size[1]} "
              f"{path.stat().st_size:,} B")
