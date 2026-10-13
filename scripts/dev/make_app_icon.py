"""Package the team's supplied AIA logo without redrawing it.

Run with Pillow available: python scripts/dev/make_app_icon.py
Pillow is not a project dependency, so a throwaway environment works too:
uv run --no-project --with pillow python scripts/dev/make_app_icon.py
Only transparent padding is trimmed. Original pixels and aspect ratio remain.
Windows ICO and PNG sizes are format conversions, not a new logo design.
The app icon sets the logo on a white disc, the same white circle the app's
sidebar logo sits on, so it stays visible on dark title bars and taskbars.
"""

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "packaging/windows/aia-logo-source.png"
ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
DISC = (255, 255, 255, 255)  # --brand-surface in frontend/src/styles/theme.css
EDGE = (200, 194, 218, 255)  # thin rim so the white disc still shows on a light taskbar
LOGO_SHARE = 0.84  # logo width as a share of the disc
SUPERSAMPLE = 4


def icon_tile(logo: Image.Image, size: int) -> Image.Image:
    """Draw one icon size on its own so the rim stays a crisp pixel when small."""
    big = size * SUPERSAMPLE
    rim = max(1, round(size / 64)) * SUPERSAMPLE
    disc = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(disc)
    draw.ellipse((0, 0, big - 1, big - 1), fill=EDGE)
    draw.ellipse((rim, rim, big - 1 - rim, big - 1 - rim), fill=DISC)
    tile = disc.resize((size, size), Image.Resampling.LANCZOS)
    width = round(size * LOGO_SHARE)
    fitted = logo.resize((width, max(1, round(width * logo.height / logo.width))), Image.Resampling.LANCZOS)
    tile.alpha_composite(fitted, ((size - fitted.width) // 2, (size - fitted.height) // 2))
    return tile


def main() -> None:
    with Image.open(SOURCE) as source:
        logo = source.convert("RGBA")
    bounds = logo.getchannel("A").getbbox()
    if bounds is None:
        raise ValueError("The supplied logo is empty")
    logo = logo.crop(bounds)
    frontend = ROOT / "frontend/src/assets/aia-logo.png"
    frontend.parent.mkdir(parents=True, exist_ok=True)
    logo.save(frontend)
    # Faint stray pixels around the letters would shrink the logo inside a small icon.
    letters = logo.crop(logo.getchannel("A").point(lambda alpha: 255 if alpha > 24 else 0).getbbox())
    tile = icon_tile(letters, 512)
    tile.save(ROOT / "packaging/windows/aia-icon-512.png")
    tile.save(ROOT / "src/aia_web/static/favicon.png")
    tiles = [icon_tile(letters, size) for size in reversed(ICON_SIZES)]
    tiles[0].save(
        ROOT / "packaging/windows/aia.ico",
        sizes=[(size, size) for size in ICON_SIZES],
        append_images=tiles[1:],
    )
    print("Generated AIA logo assets and Windows icon from", SOURCE)


if __name__ == "__main__":
    main()
