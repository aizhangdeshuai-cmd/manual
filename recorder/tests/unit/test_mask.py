import subprocess
from pathlib import Path
from PIL import Image
from recorder_plugin.mask import mask_image_pillow, mask_video_ffmpeg


def test_mask_image_pillow(tmp_path):
    """Masking a region that contains both black text and white background should blur them together."""
    from PIL import ImageDraw
    # Source: white background with small black "text" near the corner of the mask region
    src = tmp_path / "src.png"
    img = Image.new("RGB", (200, 200), "white")
    ImageDraw.Draw(img).text((5, 5), "secret", fill="black")
    img.save(src)

    # Mask a 60x40 region that INCLUDES the text; blur should mix black with white
    dst = tmp_path / "masked.png"
    regions = [{"x": 0, "y": 0, "w": 60, "h": 40, "blur_pixels": 8}]
    mask_image_pillow(src, dst, regions)
    assert dst.exists()
    # Sample a pixel where the blur window straddles text-vs-background.
    # After blur, the "secret" text should no longer be crisp black.
    masked_img = Image.open(dst)
    # The text at (5,5) covers a few pixels; after strong blur, those pixels
    # should be a gray-ish mix, not pure black or pure white.
    px_in_masked = masked_img.getpixel((20, 10))
    is_mixed = px_in_masked != (0, 0, 0) and px_in_masked != (255, 255, 255)
    assert is_mixed, f"expected blur to mix black text with white bg, got {px_in_masked}"
    # Pixel FAR outside the masked region should still be pure white
    px_outside = masked_img.getpixel((150, 150))
    assert px_outside == (255, 255, 255), f"non-masked pixel changed: {px_outside}"


def test_mask_video_ffmpeg_produces_output(tmp_path):
    src = tmp_path / "input.webm"
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=duration=1:size=320x240:rate=10",
        "-c:v", "libvpx", "-b:v", "100k", str(src)
    ], check=True, capture_output=True)
    dst = tmp_path / "masked.webm"
    regions = [{"x": 10, "y": 10, "w": 100, "h": 50, "blur_pixels": 8}]
    mask_video_ffmpeg(src, dst, regions)
    assert dst.exists()
    assert dst.stat().st_size > 100


def test_mask_video_ffmpeg_no_regions_passthrough(tmp_path):
    src = tmp_path / "input.webm"
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=duration=1:size=320x240:rate=10",
        "-c:v", "libvpx", "-b:v", "100k", str(src)
    ], check=True, capture_output=True)
    dst = tmp_path / "passthrough.webm"
    mask_video_ffmpeg(src, dst, [])
    assert dst.exists()
