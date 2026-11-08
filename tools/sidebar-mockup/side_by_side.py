"""Put mockup PNGs next to each other under labels.

    python3 side_by_side.py <out.png> <a.png> <label a> <b.png> <label b> ...
"""
import os
import sys

from PIL import Image, ImageDraw, ImageFont

FONTS = ["/usr/share/fonts/truetype/hack/Hack-Bold.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"]


def main():
    if len(sys.argv) < 4 or len(sys.argv) % 2:
        raise SystemExit(__doc__)
    out, items = sys.argv[1], sys.argv[2:]
    images = [(Image.open(path), label) for path, label in zip(items[::2], items[1::2])]
    font = ImageFont.truetype(next(path for path in FONTS if os.path.exists(path)), 15)
    canvas = Image.new(
        "RGB",
        (sum(img.width for img, _ in images) + 20 * (len(images) - 1),
         max(img.height for img, _ in images) + 30),
        (20, 20, 20),
    )
    draw = ImageDraw.Draw(canvas)
    x = 0
    for img, label in images:
        draw.text((x + 8, 6), label, fill=(230, 230, 230), font=font)
        canvas.paste(img, (x, 30))
        x += img.width + 20
    canvas.save(out)


if __name__ == "__main__":
    main()
