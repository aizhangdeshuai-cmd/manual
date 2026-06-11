"""Privacy masking. Screenshots: Pillow GaussianBlur. Video: ffmpeg boxblur filter."""
from __future__ import annotations
import subprocess
from pathlib import Path
from typing import Iterable


def mask_image_pillow(src: Path, dst: Path, regions: Iterable[dict]) -> None:
    """Apply GaussianBlur to rectangular regions in a screenshot."""
    from PIL import Image, ImageFilter
    img = Image.open(src).convert("RGB")
    for r in regions:
        x, y, w, h = r["x"], r["y"], r["w"], r["h"]
        crop = img.crop((x, y, x + w, y + h))
        blurred = crop.filter(ImageFilter.GaussianBlur(radius=r.get("blur_pixels", 8)))
        img.paste(blurred, (x, y))
    dst.parent.mkdir(parents=True, exist_ok=True)
    img.save(dst)


def mask_video_ffmpeg(src: Path, dst: Path, regions: Iterable[dict]) -> None:
    """Apply boxblur filter to rectangular regions in a video, frame by frame."""
    regions = list(regions)
    if not regions:
        subprocess.run([
            "ffmpeg", "-y", "-i", str(src), "-c", "copy", str(dst)
        ], check=True, capture_output=True)
        return
    # Build a chain of split/crop/boxblur/overlay filter graph
    chain = "[0:v]"
    last = "base"
    for i, r in enumerate(regions):
        x, y, w, h = r["x"], r["y"], r["w"], r["h"]
        blur = r.get("blur_pixels", 8)
        cropped_label = f"c{i}"
        blurred_label = f"b{i}"
        out_label = f"o{i}"
        chain += (
            f"split=2[{last}_keep][{cropped_label}];"
            f"[{cropped_label}]crop={w}:{h}:{x}:{y},boxblur={blur}:1[{blurred_label}];"
            f"[{last}_keep][{blurred_label}]overlay={x}:{y}[{out_label}]"
        )
        last = out_label
        if i + 1 < len(regions):
            chain += ";"
    subprocess.run([
        "ffmpeg", "-y", "-i", str(src),
        "-filter_complex", chain,
        "-map", f"[{last}]",
        "-c:v", "libvpx", "-b:v", "1M",
        str(dst),
    ], check=True, capture_output=True)
