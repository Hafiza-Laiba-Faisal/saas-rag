from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class CrawlMode(str, Enum):
    IMAGES = "images"
    PDFS = "pdfs"
    FULL_SITE = "full_site"


class AssetItem(BaseModel):
    url: str
    alt: str = ""
    source: str  # img_tag | srcset | css_bg | meta_tag | json_ld
    width: Optional[int] = None
    height: Optional[int] = None
    bytes: Optional[int] = None
    page_url: Optional[str] = None


class PdfItem(BaseModel):
    url: str
    title: Optional[str] = None
    page_url: Optional[str] = None
    source: str  # wp_media | sitemap | link_scan | content_sniff


class CrawlRequest(BaseModel):
    url: str
    mode: CrawlMode
    max_pages: int = 50
    max_depth: int = 3
    min_image_dimension: int = 150


class CrawlSummary(BaseModel):
    mode: CrawlMode
    pages_visited: int = 0
    assets: list[AssetItem] = Field(default_factory=list)
    pdfs: list[PdfItem] = Field(default_factory=list)
    pages: list[str] = Field(default_factory=list)
    pages_content: list[dict] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    elapsed_sec: float = 0.0
