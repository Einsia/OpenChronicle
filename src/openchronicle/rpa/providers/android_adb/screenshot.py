"""Screenshot helpers for Android RPA."""

from __future__ import annotations

from pathlib import Path


def crop_region(image_path: str, region: list[int], output_path: str) -> str:
    """Crop a screenshot region using Pillow when available."""
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("Pillow is required for screenshot_region") from exc

    x1, y1, x2, y2 = [int(v) for v in region]
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(image_path) as image:
        image.crop((x1, y1, x2, y2)).save(out)
    return str(out)
