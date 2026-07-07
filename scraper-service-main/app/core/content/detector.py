"""
Content type detection from URL and headers.
"""
from __future__ import annotations
from enum import Enum
from pathlib import Path


class ContentType(str, Enum):
    """Supported content types."""
    HTML = "html"
    PDF = "pdf"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    JSON = "json"
    XML = "xml"
    CSV = "csv"
    EXCEL = "excel"
    WORD = "word"
    POWERPOINT = "powerpoint"
    ZIP = "zip"
    TEXT = "text"
    UNKNOWN = "unknown"


class ContentDetector:
    """Detect content type from URL extension and Content-Type header."""

    EXTENSION_MAP = {
        # Documents
        ".html": ContentType.HTML,
        ".htm": ContentType.HTML,
        ".pdf": ContentType.PDF,
        ".doc": ContentType.WORD,
        ".docx": ContentType.WORD,
        ".xls": ContentType.EXCEL,
        ".xlsx": ContentType.EXCEL,
        ".ppt": ContentType.POWERPOINT,
        ".pptx": ContentType.POWERPOINT,
        ".txt": ContentType.TEXT,
        ".csv": ContentType.CSV,
        ".json": ContentType.JSON,
        ".xml": ContentType.XML,
        
        # Images
        ".jpg": ContentType.IMAGE,
        ".jpeg": ContentType.IMAGE,
        ".png": ContentType.IMAGE,
        ".gif": ContentType.IMAGE,
        ".webp": ContentType.IMAGE,
        ".svg": ContentType.IMAGE,
        ".bmp": ContentType.IMAGE,
        ".ico": ContentType.IMAGE,
        
        # Video
        ".mp4": ContentType.VIDEO,
        ".avi": ContentType.VIDEO,
        ".mov": ContentType.VIDEO,
        ".wmv": ContentType.VIDEO,
        ".flv": ContentType.VIDEO,
        ".webm": ContentType.VIDEO,
        ".mkv": ContentType.VIDEO,
        ".m4v": ContentType.VIDEO,
        
        # Audio
        ".mp3": ContentType.AUDIO,
        ".wav": ContentType.AUDIO,
        ".ogg": ContentType.AUDIO,
        ".m4a": ContentType.AUDIO,
        ".flac": ContentType.AUDIO,
        ".aac": ContentType.AUDIO,
        
        # Archive
        ".zip": ContentType.ZIP,
        ".rar": ContentType.ZIP,
        ".7z": ContentType.ZIP,
        ".tar": ContentType.ZIP,
        ".gz": ContentType.ZIP,
    }

    MIME_TYPE_MAP = {
        "text/html": ContentType.HTML,
        "application/pdf": ContentType.PDF,
        "application/json": ContentType.JSON,
        "application/xml": ContentType.XML,
        "text/xml": ContentType.XML,
        "text/csv": ContentType.CSV,
        "text/plain": ContentType.TEXT,
        
        # MS Office
        "application/msword": ContentType.WORD,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ContentType.WORD,
        "application/vnd.ms-excel": ContentType.EXCEL,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ContentType.EXCEL,
        "application/vnd.ms-powerpoint": ContentType.POWERPOINT,
        "application/vnd.openxmlformats-officedocument.presentationml.presentation": ContentType.POWERPOINT,
        
        # Images
        "image/jpeg": ContentType.IMAGE,
        "image/png": ContentType.IMAGE,
        "image/gif": ContentType.IMAGE,
        "image/webp": ContentType.IMAGE,
        "image/svg+xml": ContentType.IMAGE,
        "image/bmp": ContentType.IMAGE,
        
        # Video
        "video/mp4": ContentType.VIDEO,
        "video/mpeg": ContentType.VIDEO,
        "video/webm": ContentType.VIDEO,
        "video/quicktime": ContentType.VIDEO,
        "video/x-msvideo": ContentType.VIDEO,
        
        # Audio
        "audio/mpeg": ContentType.AUDIO,
        "audio/wav": ContentType.AUDIO,
        "audio/ogg": ContentType.AUDIO,
        "audio/mp4": ContentType.AUDIO,
        
        # Archive
        "application/zip": ContentType.ZIP,
        "application/x-rar-compressed": ContentType.ZIP,
        "application/x-7z-compressed": ContentType.ZIP,
        "application/x-tar": ContentType.ZIP,
        "application/gzip": ContentType.ZIP,
    }

    def detect_from_url(self, url: str) -> ContentType:
        """Detect content type from URL extension."""
        path = Path(url.split("?")[0])  # Remove query params
        ext = path.suffix.lower()
        return self.EXTENSION_MAP.get(ext, ContentType.UNKNOWN)

    def detect_from_headers(self, headers: dict) -> ContentType:
        """Detect content type from HTTP headers."""
        content_type = headers.get("content-type", "").lower().split(";")[0].strip()
        return self.MIME_TYPE_MAP.get(content_type, ContentType.UNKNOWN)

    def detect(self, url: str, headers: dict | None = None) -> ContentType:
        """
        Detect content type using both URL and headers.
        Headers take precedence if available.
        """
        if headers:
            header_type = self.detect_from_headers(headers)
            if header_type != ContentType.UNKNOWN:
                return header_type
        
        return self.detect_from_url(url)

    def should_download(self, content_type: ContentType) -> bool:
        """Check if content type should be downloaded vs processed inline."""
        return content_type in {
            ContentType.PDF,
            ContentType.IMAGE,
            ContentType.VIDEO,
            ContentType.AUDIO,
            ContentType.WORD,
            ContentType.EXCEL,
            ContentType.POWERPOINT,
            ContentType.ZIP,
        }

    def should_parse_html(self, content_type: ContentType) -> bool:
        """Check if content should be parsed as HTML."""
        return content_type in {ContentType.HTML, ContentType.UNKNOWN}
