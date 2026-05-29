"""One-off: add a thin white outline to the favorite heart sprites.

Reads the full-res Desktop originals, strokes the heart shape with white via
alpha dilation, crops tight to content, and writes downscaled PNGs into
static/images/.
"""
import glob
from PIL import Image, ImageFilter

JOBS = [
    ("/Users/sina/Desktop/Screenshot*1.40.42*.png", "static/images/fav-off.png"),  # broken heart
    ("/Users/sina/Desktop/Screenshot*1.40.38*.png", "static/images/fav-on.png"),   # whole heart
]

WORK = 512          # working resolution (long edge) for a smooth stroke
STROKE = 7          # outline radius in working px (thin)
OUT_MAX = 256       # final long-edge size

for pattern, dst in JOBS:
    src = glob.glob(pattern)[0]
    img = Image.open(src).convert("RGBA")
    img.thumbnail((WORK, WORK), Image.LANCZOS)

    # Solid silhouette from the alpha channel, then dilate it to form the stroke.
    mask = img.getchannel("A").point(lambda a: 255 if a > 40 else 0)
    dilated = mask.filter(ImageFilter.MaxFilter(STROKE * 2 + 1))

    # White layer shaped like the dilated silhouette, with the heart composited on top.
    outline = Image.new("RGBA", img.size, (255, 255, 255, 0))
    outline.putalpha(dilated)
    outline.paste((255, 255, 255, 255), (0, 0), dilated)
    out = Image.alpha_composite(outline, img)

    bbox = out.getchannel("A").getbbox()
    if bbox:
        out = out.crop(bbox)
    out.thumbnail((OUT_MAX, OUT_MAX), Image.LANCZOS)
    out.save(dst)
    print(f"{src.split('/')[-1]} -> {dst}  {out.size}")
