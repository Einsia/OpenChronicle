"""Screenshot capture via mss + PIL. Extracted from Einsia-Partner capture_service.py."""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass

from ..logger import get

logger = get("openchronicle.capture")


@dataclass
class Screenshot:
    image_base64: str
    mime_type: str = "image/jpeg"
    width: int = 0
    height: int = 0


def grab(max_width: int = 1920, jpeg_quality: int = 80) -> Screenshot | None:
    """Capture the primary monitor and return a base64-encoded JPEG."""
    try:
        import mss
        from PIL import Image
    except ImportError as exc:
        logger.warning("mss/Pillow not installed: %s", exc)
        return None

    try:
        with mss.mss() as sct:
            monitors = sct.monitors
            if len(monitors) < 2:
                logger.warning("No monitors reported by mss")
                return None
            mon = monitors[1]  # index 0 is the "all monitors" virtual screen
            raw = sct.grab(mon)
            img = Image.frombytes("RGB", raw.size, raw.rgb)
    except Exception as exc:  # noqa: BLE001 — mss can raise a variety of OS errors
        logger.warning("Screenshot grab failed: %s", exc)
        return None

    if max_width and img.width > max_width:
        ratio = max_width / img.width
        new_size = (max_width, int(img.height * ratio))
        img = img.resize(new_size, Image.Resampling.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=jpeg_quality, optimize=True)
    encoded = base64.b64encode(buf.getvalue()).decode("ascii")
    return Screenshot(image_base64=encoded, width=img.width, height=img.height)
