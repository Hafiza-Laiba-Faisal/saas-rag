"""
Scraper-specific request and response schemas.
Pydantic v2 models — strong typing everywhere.
"""

from __future__ import annotations
from typing import Literal, Optional
from pydantic import BaseModel, Field, field_validator


# ── Media ─────────────────────────────────────────────────────────────────────

class MediaItem(BaseModel):
    type:      Literal["image", "video", "audio"]
    url:       str
    thumb:     str = ""
    audio_url: str = ""
    width:     int = 0
    height:    int = 0


# ── Post / Reel ───────────────────────────────────────────────────────────────

class PostItem(BaseModel):
    id:        str
    caption:   str  = ""
    media:     list[MediaItem] = Field(default_factory=list)
    likes:     int  = 0
    comments:  int  = 0
    shares:    int  = 0
    posted_at: str  = ""
    post_url:  str  = ""


# ── Page meta ─────────────────────────────────────────────────────────────────

class PageMeta(BaseModel):
    title:       str  = ""
    page_id:     str  = ""
    followers:   int  = 0
    likes:       int  = 0
    category:    str  = ""
    about:       str  = ""
    website:     str  = ""
    phone:       str  = ""
    address:     str  = ""
    cover_image: str  = ""
    description: str  = ""
    is_verified: bool = False
    links:       list[dict] = Field(default_factory=list)


# ── Scrape request ────────────────────────────────────────────────────────────

class FbScrapeRequest(BaseModel):
    page_url:     str
    c_user:       str = ""
    xs:           str = ""
    datr:         str = ""
    sb:           str = ""
    fr:           str = ""
    browser:      str = "chrome"
    max_posts:    int = 20
    scroll_rounds: int = 5
    date_from:    str = ""
    date_to:      str = ""

    @field_validator("page_url")
    @classmethod
    def normalise_url(cls, v: str) -> str:
        v = v.strip().replace("web.facebook.com", "www.facebook.com")
        v = v.split("?")[0].split("#")[0] if "watch" not in v else v
        if not v.startswith("http"):
            v = "https://www.facebook.com/" + v.lstrip("/")
        return v


class ProfileScrapeRequest(BaseModel):
    platform: str
    username: str
    browser:  Optional[str] = "chrome"
    proxy:    Optional[str] = None


# ── Scrape result ─────────────────────────────────────────────────────────────

class FbScrapeResult(BaseModel):
    page_url:    str
    page_meta:   PageMeta
    posts_count: int
    reels_count: int
    posts:       list[PostItem] = Field(default_factory=list)
    reels:       list[PostItem] = Field(default_factory=list)
    session_id:  Optional[int]  = None
    saved:       bool = False


# ── Job ───────────────────────────────────────────────────────────────────────

class JobStatus(BaseModel):
    job_id:   str
    status:   Literal["pending", "running", "done", "error"]
    progress: int  = 0
    message:  str  = ""
    error:    str  = ""
    result:   Optional[FbScrapeResult] = None


# ── Cookie auth ───────────────────────────────────────────────────────────────

class SetCookiesRequest(BaseModel):
    cookies: str   # raw document.cookie string


class CookieSet(BaseModel):
    c_user: str
    xs:     str
    datr:   str = ""
    sb:     str = ""
    fr:     str = ""
