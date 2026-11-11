"""Render the app icons and the native icon / splash sources from web/icons/icon.svg.

    pip install playwright pillow && python -m playwright install chromium
    python3 tools/make_icons.py          # (or: npm run assets)

It writes the web icons, the masters in resources/, and the Android and iOS icon and splash sets.

The sprig drawing lives in web/icons/icon.svg; change it there and run this again.
"""
import asyncio
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SVG = (ROOT / "web/icons/icon.svg").read_text()
SPRIG = re.search(r"(<g transform.*</g>)", SVG, re.S).group(1)       # the drawing without its background
GREEN = "#12994f"


def page(size: int, body: str, background: str = "transparent") -> str:
    return (f"<style>html,body{{margin:0;background:{background}}}"
            f"svg{{display:block;width:{size}px;height:{size}px}}</style>{body}")


def boxed(inner: str, scale: float = 1.0) -> str:
    """The sprig in a 512 box, optionally shrunk about the centre (Android crops the outer third)."""
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">'
            f'<g transform="translate(256 256) scale({scale}) translate(-256 -256)">{inner}</g></svg>')


def splash(background: str) -> str:
    tile = (f'<g transform="translate(1166 1166)"><rect width="400" height="400" rx="96" fill="{GREEN}"/>'
            f'<g transform="scale(.78125)">{SPRIG}</g></g>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 2732 2732">'
            f'<rect width="2732" height="2732" fill="{background}"/>{tile}</svg>')


async def main() -> None:
    from playwright.async_api import async_playwright

    web, res = ROOT / "web/icons", ROOT / "resources"
    res.mkdir(exist_ok=True)
    jobs = [
        (web / "icon-192.png", 192, SVG, "transparent"),
        (web / "icon-512.png", 512, SVG, "transparent"),
        (web / "icon-maskable-512.png", 512, SVG, "transparent"),
        (web / "apple-touch-icon.png", 180, SVG, "transparent"),
        (res / "icon-only.png", 1024, SVG, "transparent"),
        (res / "icon-foreground.png", 1024, boxed(SPRIG, 0.72), "transparent"),
        (res / "icon-background.png", 1024, boxed(f'<rect width="512" height="512" fill="{GREEN}"/>'), "transparent"),
        (res / "splash.png", 2732, splash("#dff3e6"), "transparent"),
        (res / "splash-dark.png", 2732, splash("#15251c"), "transparent"),
    ]
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        for path, size, body, background in jobs:
            pg = await browser.new_page(viewport={"width": size, "height": size})
            await pg.set_content(page(size, body, background))
            await pg.screenshot(path=str(path), omit_background=True)
            await pg.close()
            print("wrote", path.relative_to(ROOT))
        await browser.close()


def native() -> None:
    """Cut the Android and iOS icon and splash sets from the masters in resources/."""
    from PIL import Image, ImageDraw

    res = ROOT / "resources"
    icon = Image.open(res / "icon-only.png").convert("RGBA")
    fore = Image.open(res / "icon-foreground.png").convert("RGBA")
    light = Image.open(res / "splash.png").convert("RGB")
    tile = light.crop((1166, 1166, 1566, 1566))
    mask = Image.new("L", (400, 400), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, 399, 399), radius=96, fill=255)
    wash = light.getpixel((10, 10))

    def splash(w: int, h: int) -> Image.Image:
        out = Image.new("RGB", (w, h), wash)
        side = round(min(w, h) * 0.3)
        out.paste(tile.resize((side, side), Image.LANCZOS), ((w - side) // 2, (h - side) // 2), mask.resize((side, side), Image.LANCZOS))
        return out

    android = ROOT / "android/app/src/main/res"
    if android.is_dir():
        for name, px in [("mdpi", 48), ("hdpi", 72), ("xhdpi", 96), ("xxhdpi", 144), ("xxxhdpi", 192)]:
            d = android / f"mipmap-{name}"
            icon.resize((px, px), Image.LANCZOS).save(d / "ic_launcher.png")
            big = px * 4
            circle = Image.new("L", (big, big), 0)
            ImageDraw.Draw(circle).ellipse((0, 0, big - 1, big - 1), fill=255)
            rnd = icon.resize((big, big), Image.LANCZOS)
            rnd.putalpha(circle)
            rnd.resize((px, px), Image.LANCZOS).save(d / "ic_launcher_round.png")
            fpx = px * 108 // 48
            fore.resize((fpx, fpx), Image.LANCZOS).save(d / "ic_launcher_foreground.png")
        (android / "values/ic_launcher_background.xml").write_text(
            f'<?xml version="1.0" encoding="utf-8"?>\n<resources>\n    <color name="ic_launcher_background">{GREEN.upper()}</color>\n</resources>\n')
        for f in sorted(android.glob("drawable*/splash.png")):
            w, h = Image.open(f).size
            splash(w, h).save(f)
        print("wrote Android icons and splash screens")

    ios = ROOT / "ios/App/App/Assets.xcassets"
    if ios.is_dir():
        icon.convert("RGB").save(ios / "AppIcon.appiconset/AppIcon-512@2x.png")      # iOS icons must have no transparency
        for f in sorted((ios / "Splash.imageset").glob("*.png")):
            light.save(f)
        print("wrote iOS icon and splash screens")


if __name__ == "__main__":
    asyncio.run(main())
    native()
