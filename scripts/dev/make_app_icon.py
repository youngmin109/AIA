"""Package the team's supplied AIA logo without redrawing it.

Run with Pillow available: python scripts/dev/make_app_icon.py
Only transparent padding is trimmed. Original pixels and aspect ratio remain.
Windows ICO and PNG sizes are format conversions, not a new logo design.
"""

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "packaging/windows/aia-logo-source.png"


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
    tile = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    fitted = logo.copy()
    fitted.thumbnail((464, 464), Image.Resampling.LANCZOS)
    tile.alpha_composite(fitted, ((512 - fitted.width) // 2, (512 - fitted.height) // 2))
    tile.save(ROOT / "packaging/windows/aia-icon-512.png")
    tile.save(ROOT / "packaging/windows/aia.ico", sizes=[(n, n) for n in (16, 20, 24, 32, 40, 48, 64, 128, 256)])
    tile.save(ROOT / "src/aia_web/static/favicon.png")
    print("Generated AIA logo assets and Windows icon from", SOURCE)


if __name__ == "__main__":
    main()
