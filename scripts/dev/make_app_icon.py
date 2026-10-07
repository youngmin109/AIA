"""Generate the AIA product icon (EPIC-020).

The icon is a glossy rounded tile in the app's action gradient (pink → violet →
blue) with a white shield and a violet check, so it still reads at 16 px.
Pillow is only needed when regenerating; it is not a project dependency:

    uv run --with pillow python scripts/dev/make_app_icon.py

Writes packaging/windows/aia.ico (16–256 px) and a 512 px PNG preview. The
SVG favicon in src/aia_web/static is hand-written to the same design.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[2]
OUT_ICO = ROOT / "packaging" / "windows" / "aia.ico"
OUT_PNG = ROOT / "packaging" / "windows" / "aia-icon-512.png"
SIZE = 1024
STOPS = [(0.0, (255, 122, 209)), (0.45, (163, 91, 255)), (1.0, (91, 125, 255))]
CHECK = (110, 60, 240)


def lerp(a: tuple[int, ...], b: tuple[int, ...], t: float) -> tuple[int, ...]:
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def gradient_color(t: float) -> tuple[int, ...]:
    for (t0, c0), (t1, c1) in zip(STOPS, STOPS[1:]):
        if t <= t1:
            return lerp(c0, c1, (t - t0) / (t1 - t0))
    return STOPS[-1][1]


def diagonal_gradient(size: int) -> Image.Image:
    line = Image.new("RGB", (size * 2, 1))
    line.putdata([gradient_color(x / (size * 2 - 1)) for x in range(size * 2)])
    square = line.resize((size * 2, size * 2))
    rotated = square.rotate(-45, resample=Image.BICUBIC)
    offset = size // 2
    return rotated.crop((offset, offset, offset + size, offset + size))


def cubic(p0, p1, p2, p3, steps=40):
    for i in range(1, steps + 1):
        t = i / steps
        u = 1 - t
        yield (
            u**3 * p0[0] + 3 * u**2 * t * p1[0] + 3 * u * t**2 * p2[0] + t**3 * p3[0],
            u**3 * p0[1] + 3 * u**2 * t * p1[1] + 3 * u * t**2 * p2[1] + t**3 * p3[1],
        )


def shield_points() -> list[tuple[float, float]]:
    # Same outline as the app's shield icon (24-unit viewBox).
    points = [(12, 3), (4.5, 6), (4.5, 11.5)]
    points += list(cubic((4.5, 11.5), (4.5, 16.1), (7.7, 19.5), (12, 21)))
    points += list(cubic((12, 21), (16.3, 19.5), (19.5, 16.1), (19.5, 11.5)))
    points += [(19.5, 6), (12, 3)]
    return points


def to_canvas(points, scale: float, center: tuple[float, float]) -> list[tuple[float, float]]:
    return [(center[0] + (x - 12) * scale, center[1] + (y - 12) * scale) for x, y in points]


def draw_icon() -> Image.Image:
    radius = int(SIZE * 0.23)
    mask = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, SIZE - 1, SIZE - 1), radius=radius, fill=255)

    tile = diagonal_gradient(SIZE).convert("RGBA")
    # Glossy top highlight.
    gloss = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(gloss).ellipse((-SIZE * 0.3, -SIZE * 0.7, SIZE * 1.3, SIZE * 0.38), fill=48)
    gloss = gloss.filter(ImageFilter.GaussianBlur(SIZE * 0.09))
    tile = Image.composite(Image.new("RGBA", (SIZE, SIZE), (255, 255, 255, 255)), tile, gloss)

    scale = SIZE * 0.032
    center = (SIZE / 2, SIZE * 0.51)
    shield = to_canvas(shield_points(), scale, center)

    # Soft shadow under the shield.
    shadow = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(shadow).polygon([(x, y + SIZE * 0.025) for x, y in shield], fill=110)
    shadow = shadow.filter(ImageFilter.GaussianBlur(SIZE * 0.03))
    tile = Image.composite(Image.new("RGBA", (SIZE, SIZE), (40, 10, 90, 255)), tile, shadow)

    draw = ImageDraw.Draw(tile)
    draw.polygon(shield, fill=(255, 255, 255, 255))
    check = to_canvas([(8.4, 12.1), (11.0, 14.6), (15.6, 9.6)], scale, center)
    width = int(scale * 2.2)
    draw.line(check, fill=CHECK, width=width, joint="curve")
    for x, y in (check[0], check[-1]):
        draw.ellipse((x - width / 2, y - width / 2, x + width / 2, y + width / 2), fill=CHECK)

    icon = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    icon.paste(tile, (0, 0), mask)
    return icon


def main() -> None:
    icon = draw_icon()
    OUT_ICO.parent.mkdir(parents=True, exist_ok=True)
    icon.resize((512, 512), Image.LANCZOS).save(OUT_PNG)
    sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256]
    icon.resize((256, 256), Image.LANCZOS).save(OUT_ICO, sizes=[(size, size) for size in sizes])
    print(f"wrote {OUT_ICO} and {OUT_PNG}")


if __name__ == "__main__":
    main()
