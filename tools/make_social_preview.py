"""Build the 1280x640 GitHub social preview card from the GUI screenshot."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
SHOT = ROOT / "docs" / "gui-howto.png"
OUT = ROOT / "docs" / "social-preview.png"

W, H = 1280, 640
FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")
BOLD = FONT_DIR / "DejaVuSans-Bold.ttf"
REG = FONT_DIR / "DejaVuSans.ttf"


def gradient() -> Image.Image:
    img = Image.new("RGB", (W, H))
    px = img.load()
    top, bottom = (10, 17, 30), (18, 35, 58)
    for y in range(H):
        t = y / (H - 1)
        row = tuple(round(a + (b - a) * t) for a, b in zip(top, bottom))
        for x in range(W):
            px[x, y] = row
    return img


def add_glow(img: Image.Image) -> Image.Image:
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(glow)
    d.ellipse((640, -260, 1500, 700), fill=(46, 116, 182, 90))
    glow = glow.filter(ImageFilter.GaussianBlur(130))
    return Image.alpha_composite(img.convert("RGBA"), glow)


def add_dots(img: Image.Image) -> Image.Image:
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for x in range(20, W, 34):
        for y in range(20, H, 34):
            d.ellipse((x, y, x + 1, y + 1), fill=(160, 200, 240, 16))
    return Image.alpha_composite(img, layer)


def screenshot_card() -> Image.Image:
    shot = Image.open(SHOT).convert("RGB")
    cw, ch = 596, 384
    shot = shot.resize((cw, ch), Image.LANCZOS)

    radius = 16
    mask = Image.new("L", (cw, ch), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, cw - 1, ch - 1), radius=radius, fill=255)

    card = Image.new("RGBA", (cw + 24, ch + 24), (0, 0, 0, 0))
    shadow = Image.new("RGBA", card.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((8, 10, cw + 16, ch + 20), radius=radius + 4, fill=(0, 0, 0, 150))
    shadow = shadow.filter(ImageFilter.GaussianBlur(12))
    card = Image.alpha_composite(card, shadow)

    shot_rgba = shot.convert("RGBA")
    shot_rgba.putalpha(mask)
    card.alpha_composite(shot_rgba, (12, 12))
    ImageDraw.Draw(card).rounded_rectangle((12, 12, 12 + cw - 1, 12 + ch - 1), radius=radius, outline=(90, 140, 190, 120), width=1)
    return card


def main() -> None:
    img = gradient()
    img = add_glow(img)
    img = add_dots(img)

    card = screenshot_card()
    img.alpha_composite(card, (642, 108))

    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, W, 6), fill=(47, 111, 159))

    badge = ImageFont.truetype(str(REG), 18)
    subtitle = ImageFont.truetype(str(REG), 28)
    note = ImageFont.truetype(str(REG), 21)
    small = ImageFont.truetype(str(REG), 18)

    title_text = "uncompressMRI"
    title_size = 74
    while title_size > 44:
        title = ImageFont.truetype(str(BOLD), title_size)
        if d.textlength(title_text, font=title) <= 548:
            break
        title_size -= 2

    d.text((64, 92), "OPEN SOURCE  ·  APACHE-2.0", font=badge, fill=(126, 178, 226))
    d.text((62, 132 + (74 - title_size) // 2), title_text, font=title, fill=(245, 249, 253))

    lines = ["Enhanced multi-frame MRI →", "single-frame DICOM for", "Eclipse / Aria / Monaco"]
    y = 252
    for line in lines:
        d.text((64, y), line, font=subtitle, fill=(206, 221, 236))
        y += 38

    d.text((64, 402), "Windows .exe  ·  CLI  ·  GUI  ·  no Python required", font=note, fill=(143, 179, 217))
    d.text((64, 446), "github.com/loonies321/uncompressMRI", font=small, fill=(110, 150, 190))

    d.text((652, 532), "uncompressMRI 2.3.1  ·  Windows x64", font=small, fill=(150, 180, 210))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(OUT, "PNG", optimize=True)
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
