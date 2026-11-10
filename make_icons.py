"""Generate PWA icons (run once). Requires Pillow."""
from pathlib import Path
from PIL import Image, ImageDraw

OUT = Path(__file__).parent / "static" / "icons"
OUT.mkdir(parents=True, exist_ok=True)


def make_icon(size: int, path: Path):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    pad = size // 10
    radius = size // 8
    # Sticky note body
    d.rounded_rectangle(
        [pad, pad, size - pad, size - pad],
        radius=radius,
        fill=(254, 243, 199, 255),
        outline=(251, 191, 36, 255),
        width=max(2, size // 60),
    )
    # Folded corner
    fold = size // 4
    d.polygon(
        [(size - pad - fold, size - pad), (size - pad, size - pad - fold),
         (size - pad, size - pad)],
        fill=(251, 191, 36, 255),
    )
    # Lines
    line_color = (120, 53, 15, 255)
    line_h = max(3, size // 40)
    left = pad + size // 8
    right = size - pad - size // 8
    for i, y in enumerate(range(pad + size // 5, size - pad - size // 5, size // 8)):
        end = right if i % 3 != 2 else right - size // 6
        d.rounded_rectangle([left, y, end, y + line_h], radius=line_h // 2, fill=line_color)

    img.save(path, format="PNG")
    print(f"wrote {path}")


make_icon(192, OUT / "icon-192.png")
make_icon(512, OUT / "icon-512.png")