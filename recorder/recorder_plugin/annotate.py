"""Image annotation. PIL-based. Renders box/arrow/number/highlight/composite onto screenshots."""
from __future__ import annotations
import shutil
from dataclasses import dataclass
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

RED = (220, 30, 30)
YELLOW_FILL = (255, 220, 0, 80)
WHITE = (255, 255, 255)
BOX_WIDTH = 3

_FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/System/Library/AssetsV2/com_apple_MobileAsset_Font8/a304e3396d019087ab67af77f5e398977529007d.asset/AssetData/Libian.ttc",
    "/System/Library/AssetsV2/com_apple_MobileAsset_Font8/88d6cc32a907955efa1d014207889413890573be.asset/AssetData/Kaiti.ttc",
    "/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Helvetica.ttc",
]


def _font(size: int) -> ImageFont.ImageFont:
    for path in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


@dataclass
class Annotation:
    shape: str  # "box" | "arrow" | "number" | "highlight" | "composite"
    x: int | None = None
    y: int | None = None
    w: int | None = None
    h: int | None = None
    label: str = ""
    from_xy: tuple[int, int] | None = None
    to_xy: tuple[int, int] | None = None
    n: int | None = None  # for "number"

    @staticmethod
    def from_dict(d: dict) -> "Annotation":
        return Annotation(
            shape=d["shape"],
            x=d.get("x"),
            y=d.get("y"),
            w=d.get("w"),
            h=d.get("h"),
            label=d.get("label", ""),
            from_xy=tuple(d["from_xy"]) if d.get("from_xy") else None,
            to_xy=tuple(d["to_xy"]) if d.get("to_xy") else None,
            n=d.get("n"),
        )


def _draw_box(draw: ImageDraw.ImageDraw, a: Annotation) -> None:
    draw.rectangle([a.x, a.y, a.x + a.w, a.y + a.h], outline=RED, width=BOX_WIDTH)
    if a.label:
        f = _font(14)
        draw.rectangle([a.x, max(0, a.y - 18), a.x + 8 * len(a.label) + 4, a.y], fill=RED)
        draw.text((a.x + 2, max(0, a.y - 16)), a.label, fill=WHITE, font=f)


def _draw_arrow(draw: ImageDraw.ImageDraw, a: Annotation) -> None:
    if not a.from_xy or not a.to_xy:
        return
    draw.line([a.from_xy, a.to_xy], fill=RED, width=BOX_WIDTH)
    fx, fy = a.from_xy
    tx, ty = a.to_xy
    draw.polygon([(tx, ty), (tx - 8, ty - 4), (tx - 8, ty + 4)], fill=RED)
    if a.label:
        f = _font(12)
        draw.text((tx + 4, ty - 6), a.label, fill=RED, font=f)


def _draw_number(draw: ImageDraw.ImageDraw, a: Annotation) -> None:
    if a.n is None:
        return
    cx = a.x + a.w // 2
    cy = a.y + a.h // 2
    r = min(a.w, a.h) // 2
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=RED)
    f = _font(max(10, r))
    text = str(a.n)
    bbox = draw.textbbox((0, 0), text, font=f)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text((cx - tw // 2, cy - th // 2 - 2), text, fill=WHITE, font=f)


def _draw_highlight(draw_overlay: ImageDraw.ImageDraw, main_draw: ImageDraw.ImageDraw, a: Annotation) -> None:
    draw_overlay.rectangle([a.x, a.y, a.x + a.w, a.y + a.h], fill=YELLOW_FILL)
    if a.label:
        f = _font(12)
        main_draw.rectangle([a.x, max(0, a.y - 16), a.x + 8 * len(a.label) + 4, a.y], fill=RED)
        main_draw.text((a.x + 2, max(0, a.y - 14)), a.label, fill=WHITE, font=f)


def annotate_image(src: Path, dst: Path, annotations: list[Annotation]) -> None:
    """Copy `src` to `dst`, then draw annotations on top of `dst`."""
    if not annotations:
        shutil.copy(src, dst)
        return
    img = Image.open(src).convert("RGBA")
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    main_draw = ImageDraw.Draw(img)
    for a in annotations:
        if a.shape == "box":
            _draw_box(main_draw, a)
        elif a.shape == "arrow":
            _draw_arrow(main_draw, a)
        elif a.shape == "number":
            _draw_number(main_draw, a)
        elif a.shape == "highlight":
            _draw_highlight(overlay_draw, main_draw, a)
        elif a.shape == "composite":
            _draw_box(main_draw, a)
    img = Image.alpha_composite(img, overlay).convert("RGB")
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    img.save(dst)
