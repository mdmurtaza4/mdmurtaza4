"""The ELiXIR School wordmark, generated when no official logo PNG is supplied.

The dot of the lowercase "i" in ELiXIR is replaced with a fountain-pen nib.
For publication, supply the official logo file instead (BrandingSettings.logo_path).
"""

from __future__ import annotations

import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

BRAND_BLUE = (10, 79, 175, 255)  # #0A4FAF
WHITE = (255, 255, 255, 255)

_ASSET_FONTS = Path(__file__).resolve().parents[2] / "assets" / "fonts"
_WIN_FONTS = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"

REGULAR_CANDIDATES = [
    _ASSET_FONTS / "LibreBaskerville-Regular.ttf",
    _WIN_FONTS / "BASKVILL.TTF",
    _WIN_FONTS / "times.ttf",
    Path("/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"),
]
ITALIC_CANDIDATES = [
    _ASSET_FONTS / "LibreBaskerville-Italic.ttf",
    _WIN_FONTS / "timesi.ttf",
    Path("/usr/share/fonts/truetype/liberation/LiberationSerif-Italic.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf"),
]


def _font(candidates: list[Path], size: int) -> ImageFont.FreeTypeFont:
    for c in candidates:
        if c.exists():
            return ImageFont.truetype(str(c), size)
    return ImageFont.load_default(size)


def _nib(draw: ImageDraw.ImageDraw, cx: float, bottom: float, height: float, color) -> None:
    """Vertical fountain-pen nib, tip pointing down onto the stem of the i."""
    w = height * 0.5
    top = bottom - height
    shoulder = top + height * 0.38
    pts = [
        (cx - w * 0.34, top),
        (cx + w * 0.34, top),
        (cx + w * 0.5, shoulder),
        (cx + w * 0.12, bottom - height * 0.12),
        (cx, bottom),
        (cx - w * 0.12, bottom - height * 0.12),
        (cx - w * 0.5, shoulder),
    ]
    draw.polygon(pts, fill=color)
    hole_y = top + height * 0.42
    r = w * 0.12
    draw.ellipse((cx - r, hole_y - r, cx + r, hole_y + r), fill=(0, 0, 0, 0))
    slit_w = max(1.0, w * 0.05)
    draw.rectangle((cx - slit_w / 2, hole_y + r, cx + slit_w / 2, bottom - height * 0.05), fill=(0, 0, 0, 0))


def wordmark(width: int, panel: bool = True) -> Image.Image:
    """Render the wordmark at the requested pixel width (RGBA)."""
    scale = 4  # supersample for crisp edges
    fs = 120 * scale
    main = _font(REGULAR_CANDIDATES, fs)
    tag = _font(ITALIC_CANDIDATES, int(fs * 0.32))

    pieces = ["The ", "EL", "\u0131", "XIR", " School"]  # dotless i receives the nib
    widths = [main.getlength(p) for p in pieces]
    ascent, descent = main.getmetrics()
    nib_h = fs * 0.42
    pad = fs * 0.28
    tag_h = fs * 0.45
    text_w = sum(widths)
    canvas_w = int(text_w + pad * 2)
    canvas_h = int(nib_h * 0.2 + ascent + descent * 0.4 + tag_h + pad * 1.4)

    img = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    mask = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(mask)
    baseline_top = pad * 0.6 + nib_h * 0.2
    x = pad
    i_center = 0.0
    for piece, pw in zip(pieces, widths, strict=True):
        d.text((x, baseline_top), piece, font=main, fill=BRAND_BLUE)
        if piece == "\u0131":
            i_center = x + pw / 2
        x += pw
    # top of the dotless i stem sits at x-height
    bbox = main.getbbox("\u0131")
    _nib(d, i_center, baseline_top + bbox[1] - fs * 0.05, nib_h, BRAND_BLUE)

    # Tagline centred under "ELiXIR School", not the full mark.
    span_start = pad + widths[0]
    span_end = pad + text_w
    tagline = "N u r t u r i n g   C r e a t i v i t y".replace("   ", "\u2002").replace(" ", "\u200a")
    tw = tag.getlength(tagline)
    d.text(((span_start + span_end - tw) / 2, baseline_top + ascent + descent * 0.1), tagline, font=tag, fill=BRAND_BLUE)

    if panel:
        bg = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(bg).rounded_rectangle((0, 0, canvas_w - 1, canvas_h - 1), radius=int(fs * 0.22), fill=WHITE)
        img = Image.alpha_composite(bg, mask)
    else:
        img = mask
    ratio = width / canvas_w
    return img.resize((width, max(1, int(canvas_h * ratio))), Image.LANCZOS)


def watermark_png(dest: Path, frame_width: int, logo_path: str | None = None) -> Path:
    """Write the overlay PNG sized for the output frame."""
    target_w = int(frame_width * (0.36 if frame_width < 1500 else 0.22))
    if logo_path and Path(logo_path).exists():
        logo = Image.open(logo_path).convert("RGBA")
        ratio = target_w / logo.width
        logo = logo.resize((target_w, int(logo.height * ratio)), Image.LANCZOS)
    else:
        logo = wordmark(target_w)
    dest.parent.mkdir(parents=True, exist_ok=True)
    logo.save(dest)
    return dest
