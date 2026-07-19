"""
Scrape routes — FB posts job management + profile scraper.
No scraping logic. Only job orchestration.
"""
from __future__ import annotations
import threading
import json
from fastapi import APIRouter, HTTPException
from schemas.scraper import FbScrapeRequest, ProfileScrapeRequest
from jobs.job_store import default_job_store
from session.browser_session import browser_session
from storage.sqlite_storage import default_storage
from config.settings import MAX_SCROLL_ROUNDS_UNLIMITED

router = APIRouter(prefix="/scrape", tags=["scrape"])


# ── Background worker ─────────────────────────────────────────────────────────

def _run_scrape_job(job_id: str, url: str, cookies: dict, browser: str,
                    max_posts: int, scroll_rounds: int,
                    date_from: str = "", date_to: str = ""):
    from scrapers.fb_posts_scraper import scrape_facebook_posts
    job = default_job_store.get(job_id)
    if not job:
        return
    job.status   = "running"
    job.progress = 10
    job.message  = "Browser launch ho raha hai..."
    try:
        def on_progress(pct: int, msg: str = ""):
            job.progress = pct
            if msg:
                job.message = msg

        result = scrape_facebook_posts(
            page_url=url, cookies=cookies, browser=browser,
            max_posts=max_posts, scroll_rounds=scroll_rounds,
            date_from=date_from, date_to=date_to, on_progress=on_progress,
        )
        if "error" in result:
            job.status = "error"
            job.error  = result.get("message", "Scraping fail ho gaya")
            return

        if result.get("posts") or result.get("reels"):
            session_id = default_storage.save_session(
                page_url=url,
                page_meta=result.get("page_meta", {}),
                posts=result.get("posts", []),
                reels=result.get("reels", []),
            )
            result["session_id"] = session_id
            result["saved"]      = True

        job.result   = result
        job.status   = "done"
        job.progress = 100
        job.message  = f"{result.get('posts_count',0)} posts, {result.get('reels_count',0)} reels!"
    except Exception as e:
        job.status = "error"
        job.error  = str(e)
        job.message = str(e)


# ── FB Posts ──────────────────────────────────────────────────────────────────

@router.post("/fb-posts")
def scrape_fb_posts(req: FbScrapeRequest):
    url = req.page_url

    # Resolve cookies
    req_cookies = {"c_user": req.c_user, "xs": req.xs,
                   "datr": req.datr, "sb": req.sb, "fr": req.fr}
    if req_cookies.get("c_user") and req_cookies.get("xs"):
        cookies = req_cookies
    elif browser_session.is_logged_in:
        cookies = browser_session.active_cookies
    else:
        cookies = req_cookies

    max_posts = req.max_posts if req.max_posts > 0 else 9999
    scroll_rounds = req.scroll_rounds or 5
    if max_posts >= 9999:
        scroll_rounds = MAX_SCROLL_ROUNDS_UNLIMITED

    try:
        job = default_job_store.create()
    except RuntimeError as e:
        raise HTTPException(429, str(e))

    t = threading.Thread(
        target=_run_scrape_job,
        args=(job.job_id, url, cookies, req.browser, max_posts, scroll_rounds),
        kwargs={"date_from": req.date_from, "date_to": req.date_to},
        daemon=True,
    )
    t.start()
    return {"job_id": job.job_id, "status": "pending", "message": "Scraping shuru ho rahi hai..."}


@router.get("/fb-posts/status/{job_id}")
def scrape_fb_posts_status(job_id: str):
    job = default_job_store.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    resp = job.to_dict()
    return resp


# ── Profile scraper ───────────────────────────────────────────────────────────

SELENIUM_PLATFORMS = {"facebook", "reddit", "github", "tiktok", "pinterest"}
API_PLATFORMS      = {"instagram", "twitter"}


@router.post("/profile")
def scrape_profile(req: ProfileScrapeRequest):
    platform = req.platform.lower().strip()
    username = req.username.strip().lstrip("@")
    if not username:
        raise HTTPException(400, "Username is required")
    if platform not in (API_PLATFORMS | SELENIUM_PLATFORMS):
        raise HTTPException(400, f"Unsupported platform: {platform}")
    try:
        if platform == "instagram":
            from instagram import Instagram
            raw = Instagram.scrap(username, proxy=req.proxy)
            data = json.loads(raw) if isinstance(raw, str) else raw
            return {"platform": platform, "username": username, "data": _norm_instagram(data)}
        elif platform == "twitter":
            from twitter import Twitter
            raw = Twitter.scrap(username)
            data = json.loads(raw) if isinstance(raw, str) else raw
            return {"platform": platform, "username": username, "data": _norm_twitter(data)}
        else:
            scrapers = {
                "facebook":  ("facebook",  "Facebook"),
                "reddit":    ("reddit",    "Reddit"),
                "github":    ("github",    "Github"),
                "tiktok":    ("tiktok",    "Tiktok"),
                "pinterest": ("pinterest", "Pinterest"),
            }
            mod_name, cls_name = scrapers[platform]
            mod  = __import__(mod_name)
            cls  = getattr(mod, cls_name)
            data = cls.scrap(username, req.browser or "chrome")
            data = json.loads(data) if isinstance(data, str) else data
            return {"platform": platform, "username": username, "data": data}
    except HTTPException:
        raise
    except SystemExit:
        raise HTTPException(503, f"Scraper deps missing for '{platform}'")
    except Exception as e:
        raise HTTPException(500, str(e))


def _norm_instagram(d: dict) -> dict:
    if not d: return {}
    return {"full_name": d.get("full_name"), "username": d.get("username"),
            "bio": d.get("biography"), "followers": d.get("edge_followed_by", {}).get("count"),
            "following": d.get("edge_follow", {}).get("count"),
            "posts": d.get("edge_owner_to_timeline_media", {}).get("count"),
            "profile_image": d.get("profile_pic_url_hd") or d.get("profile_pic_url"),
            "is_verified": d.get("is_verified"), "is_private": d.get("is_private"),
            "website": d.get("external_url"), "category": d.get("category_name")}


def _norm_twitter(d: dict) -> dict:
    if not d: return {}
    user = d.get("user", {}).get("result", {})
    leg  = user.get("legacy", {})
    return {"full_name": leg.get("name"), "username": leg.get("screen_name"),
            "bio": leg.get("description"), "followers": leg.get("followers_count"),
            "following": leg.get("friends_count"), "tweets": leg.get("statuses_count"),
            "likes": leg.get("favourites_count"),
            "profile_image": leg.get("profile_image_url_https"),
            "banner_image": leg.get("profile_banner_url"),
            "is_verified": leg.get("verified") or user.get("is_blue_verified"),
            "location": leg.get("location"), "website": leg.get("url"),
            "created_at": leg.get("created_at")}


# ── WordPress scraper ─────────────────────────────────────────────────────────

from pydantic import BaseModel
from schemas.base import ApiResponse
from scrapers.wordpress_scraper import WordPressScraper

_wp_scraper = WordPressScraper()


class WordPressScrapeRequest(BaseModel):
    url: str
    max_pages: int = 10
    include_pages: bool = True
    include_media: bool = True


@router.post("/wordpress", summary="Scrape WordPress site via REST API")
async def scrape_wordpress(req: WordPressScrapeRequest):
    """
    Detect and scrape a WordPress site.
    Tries WP REST API first (/wp-json/wp/v2/posts), falls back to HTML parsing.
    Returns posts, pages, media, and metadata in one shot.
    """
    url = req.url.strip()
    if not url.startswith(("http://", "https://")):
        return ApiResponse.fail("validator", "invalid_url",
                                "URL must start with http:// or https://")
    result = await _wp_scraper.scrape(
        url,
        max_pages=req.max_pages,
        include_pages=req.include_pages,
        include_media=req.include_media,
    )
    return ApiResponse.ok({
        "url": result.url,
        "is_wordpress": result.is_wordpress,
        "detected_by": result.detected_by,
        "posts": result.posts,
        "pages": result.pages,
        "media": result.media,
        "stats": result.stats,
        "error": result.error,
        "elapsed_ms": result.elapsed_ms,
    })
