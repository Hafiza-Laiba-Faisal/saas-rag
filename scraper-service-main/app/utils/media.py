"""
Media utilities — image resize, content-type detection, filename sanitization.
"""
from __future__ import annotations
import io
import mimetypes
from pathlib import Path


def sanitize_filename(name: str, fallback: str = "file") -> str:
    safe = "".join(c for c in name if c.isalnum() or c in ".-_")
    return safe or fallback


def detect_content_type(url: str, server_ct: str = "") -> str:
    if server_ct and server_ct != "application/octet-stream":
        return server_ct.split(";")[0].strip()
    url_lower = url.lower().split("?")[0]
    if url_lower.endswith(".mp4") or "video" in url_lower:
        return "video/mp4"
    if url_lower.endswith(".webm"):
        return "video/webm"
    if url_lower.endswith(".png"):
        return "image/png"
    if url_lower.endswith(".gif"):
        return "image/gif"
    if url_lower.endswith(".webp"):
        return "image/webp"
    return "image/jpeg"


def resize_image(data: bytes, width: int = 160, height: int = 160) -> io.BytesIO | None:
    try:
        from PIL import Image as PILImage
        buf = io.BytesIO(data)
        with PILImage.open(buf) as im:
            im = im.convert("RGB")
            im.thumbnail((width, height), PILImage.LANCZOS)
            bg = PILImage.new("RGB", (width, height), (245, 245, 245))
            bg.paste(im, ((width - im.width) // 2, (height - im.height) // 2))
            out = io.BytesIO()
            bg.save(out, format="PNG", optimize=True)
            out.seek(0)
            return out
    except Exception:
        return None
