"""
Facebook Posts Scraper — Selenium + session cookies
Extracts posts from page source JSON blobs + DOM fallback.
Fixed: proper scroll pagination, better JSON extraction, more post coverage.
"""

import json
import re
import time
import hashlib
from datetime import datetime
from typing import Optional
from urllib.parse import unquote

from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.firefox import GeckoDriverManager


# ── Driver setup ─────────────────────────────────────────────────────────────

def init_driver(browser: str = "chrome"):
    name = browser.strip().lower()
    if name == "chrome":
        opts = ChromeOptions()
        opts.add_argument("--headless=new")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--window-size=1920,1080")
        opts.add_argument("--disable-blink-features=AutomationControlled")
        opts.add_argument("--disable-extensions")
        opts.add_argument("--disable-web-security")
        opts.add_argument("--allow-running-insecure-content")
        opts.add_argument("--lang=en-US")
        opts.add_argument("--accept-lang=en-US,en;q=0.9")
        opts.add_experimental_option("excludeSwitches", ["enable-automation"])
        opts.add_experimental_option("useAutomationExtension", False)
        # Use a realistic Chrome 124 Windows user-agent to avoid mobile redirect
        opts.add_argument(
            "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        try:
            service = ChromeService(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=opts)
        except Exception:
            driver = webdriver.Chrome(options=opts)
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": """
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                window.chrome = {runtime: {}};
                Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
                Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
                Object.defineProperty(navigator, 'platform', {get: () => 'Win32'});
            """
        })
        # Override accept-language header via CDP
        try:
            driver.execute_cdp_cmd("Network.setExtraHTTPHeaders", {
                "headers": {"Accept-Language": "en-US,en;q=0.9"}
            })
        except Exception:
            pass
        return driver
    else:
        opts = FirefoxOptions()
        opts.add_argument("--headless")
        try:
            service = FirefoxService(GeckoDriverManager().install())
            return webdriver.Firefox(service=service, options=opts)
        except Exception:
            return webdriver.Firefox(options=opts)


def inject_cookies(driver, cookies: dict):
    """Inject Facebook session cookies into browser."""
    driver.get("https://www.facebook.com")
    time.sleep(2)
    for name, value in cookies.items():
        if value:
            try:
                driver.add_cookie({
                    "name": name,
                    "value": value,
                    "domain": ".facebook.com",
                    "path": "/",
                    "secure": True,
                    "sameSite": "None",
                })
            except Exception:
                pass
    # Reload after injecting cookies so FB recognizes the session
    driver.refresh()
    time.sleep(3)


# ── Helpers ───────────────────────────────────────────────────────────────────

def clean_text(text) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", str(text)).strip()


def _is_audio_only_url(url: str) -> bool:
    """Return True if a Facebook CDN URL points to an audio-only DASH segment.

    Facebook hides the stream type in the base64-encoded `efg` query param.
    The `encode_tag` field inside reveals whether it's video or audio-only.

    Strategy (in order of reliability):
    1. Decode the `efg` base64 param — most accurate
    2. Check for unambiguous audio-only URL path keywords
    """
    import base64

    lower = url.lower()

    # 1. Decode efg param — most reliable method
    try:
        efg_m = re.search(r'[?&]efg=([^&]+)', url)
        if efg_m:
            efg_raw = efg_m.group(1)
            efg_bytes = base64.b64decode(unquote(efg_raw) + "==")
            efg_json = json.loads(efg_bytes)
            tag = (efg_json.get("vencode_tag") or efg_json.get("encode_tag") or "").lower()
            # Only return True if tag is explicitly audio-only (no "video" in tag)
            if "audio" in tag and "video" not in tag:
                return True
            # If efg decoded successfully and has a tag with "video", it's NOT audio-only
            if tag and "video" in tag:
                return False
    except Exception:
        pass

    # 2. Unambiguous audio-only path patterns only (be conservative — don't false-positive)
    # Avoid "_a_" — it also appears in valid video URL paths like "dash_a_vbr" vs "dash_v_"
    # Only flag if the path segment clearly says it's audio with no video component
    audio_patterns = [
        r'/dash_audio[_/]',        # /dash_audio_something
        r'_audio_only',            # explicit "audio_only" in path
        r'[?&]type=audio',         # query param type=audio
        r'heaac[^v]',              # heaac NOT followed by 'v' (heaacv2 is valid audio codec in video)
    ]
    for pat in audio_patterns:
        if re.search(pat, lower):
            return True

    return False


def parse_count(text) -> int:
    if not text:
        return 0
    text = str(text).strip().replace(",", "").upper()
    try:
        if "K" in text:
            return int(float(text.replace("K", "")) * 1_000)
        if "M" in text:
            return int(float(text.replace("M", "")) * 1_000_000)
        nums = re.sub(r"[^\d]", "", text)
        return int(nums) if nums else 0
    except Exception:
        return 0


def _parse_dash_manifest(manifest_xml: str) -> dict:
    """Parse a DASH MPD manifest and return best video URL + audio URL.

    Facebook reels use DASH — video and audio are separate AdaptationSets.
    Returns: {"video_url": "...", "audio_url": "...", "width": int, "height": int}
    """
    try:
        import xml.etree.ElementTree as ET
        # Unescape common HTML entities in the manifest (except &amp; which is required for valid XML)
        manifest_xml = (manifest_xml
            .replace('&lt;', '<')
            .replace('&gt;', '>')
            .replace('&quot;', '"')
        )
        root = ET.fromstring(manifest_xml)
        ns_uri = 'urn:mpeg:dash:schema:mpd:2011'

        video_reps = []  # (bandwidth, height, width, url)
        audio_reps = []  # (bandwidth, url)

        for adaptation in root.findall(f'.//{{{ns_uri}}}AdaptationSet'):
            content_type = adaptation.get('contentType', '')
            mime = adaptation.get('mimeType', '')

            is_video = 'video' in content_type or 'video' in mime
            is_audio = 'audio' in content_type or 'audio' in mime

            for rep in adaptation.findall(f'{{{ns_uri}}}Representation'):
                base = rep.find(f'{{{ns_uri}}}BaseURL')
                if base is None or not base.text:
                    continue
                url = base.text.strip()
                bw = int(rep.get('bandwidth', '0'))

                if is_video:
                    h = int(rep.get('height', '0'))
                    w = int(rep.get('width', '0'))
                    video_reps.append((bw, h, w, url))
                elif is_audio:
                    audio_reps.append((bw, url))

        if not video_reps:
            return {}

        # Pick highest bandwidth video
        best_video = sorted(video_reps, reverse=True)[0]
        # Pick highest bandwidth audio
        best_audio = sorted(audio_reps, reverse=True)[0] if audio_reps else None

        return {
            "video_url": best_video[3],
            "audio_url": best_audio[1] if best_audio else "",
            "width":     best_video[2],
            "height":    best_video[1],
        }
    except Exception as e:
        return {}


def _extract_dash_from_source(src: str) -> list:
    """Find all DASH manifests in page source and extract video+audio URL pairs."""
    import xml.etree.ElementTree as ET

    results = []
    seen_video_ids = set()

    # Pattern: videoDeliveryResponseFragment -> dash_manifests -> manifest_xml
    manifest_pattern = re.compile(
        r'"manifest_xml"\s*:\s*"((?:[^"\\]|\\.)+)"'
    )

    for m in manifest_pattern.finditer(src):
        raw = m.group(1)
        # Unescape JSON string encoding
        manifest_xml = (raw
            .replace('\\n', '\n')
            .replace('\\"', '"')
            .replace('\\/', '/')
            .replace('\\u003C', '<')
            .replace('\\u003E', '>')
        )

        parsed = _parse_dash_manifest(manifest_xml)
        if not parsed.get("video_url"):
            continue

        # Get surrounding chunk for metadata
        start = max(0, m.start() - 6000)
        end   = min(len(src), m.end() + 500)
        chunk = src[start:end]

        # Video ID
        pfbid_m  = re.search(r'pfbid([A-Za-z0-9]+)', chunk)
        vid_id_m = re.search(r'"(?:video_id|story_fbid|id)"\s*:\s*"?(\d{10,})"?', chunk)
        if pfbid_m:
            post_id = f"pfbid{pfbid_m.group(1)}"
        elif vid_id_m:
            post_id = vid_id_m.group(1)
        else:
            post_id = hashlib.md5(parsed["video_url"].encode()).hexdigest()[:12]

        if post_id in seen_video_ids:
            continue
        seen_video_ids.add(post_id)

        # Thumbnail
        thumb_m = re.search(
            r'"uri"\s*:\s*"(https:[^"]+(?:thumbnail|t15\.5-|p\d+x\d+)[^"]*)"', chunk)
        thumb = thumb_m.group(1).replace("\\/", "/") if thumb_m else ""

        # Caption
        cap_m = re.search(r'"text"\s*:\s*"((?:[^"\\]|\\.){5,500})"', chunk)
        caption = cap_m.group(1).replace("\\n", " ").replace('\\"', '"') if cap_m else ""

        # Date
        ct_m = re.search(r'"creation_time"\s*:\s*(\d{10})', chunk)
        posted_at = unix_to_date(ct_m.group(1)) if ct_m else ""

        results.append({
            "id":        post_id,
            "url":       parsed["video_url"],
            "audio_url": parsed["audio_url"],
            "thumb":     thumb,
            "caption":   caption,
            "posted_at": posted_at,
            "width":     parsed.get("width", 0),
            "height":    parsed.get("height", 0),
        })

    return results


def unix_to_date(ts) -> str:
    try:
        return datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(ts)


def _parse_fb_date(text: str) -> str:
    """
    Convert Facebook's human-readable date strings to YYYY-MM-DD HH:MM.

    Handles:
      - "1 minute ago", "2 hours ago", "3 days ago"
      - "Yesterday at 3:45 PM"
      - "Monday at 10:00 AM"
      - "June 15 at 2:30 PM"
      - "June 15, 2023 at 2:30 PM"
      - Already formatted "2024-01-15 09:30"
    """
    from datetime import timedelta as _td

    if not text:
        return ""
    text = text.strip()
    now = datetime.now()
    tl = text.lower()

    # Already in YYYY-MM-DD format
    if re.match(r'\d{4}-\d{2}-\d{2}', text):
        return text[:16]

    # "X minutes ago" / "X hours ago" / "X days ago" / "X weeks ago"
    ago_m = re.match(r'(\d+)\s+(second|minute|hour|day|week|month)s?\s+ago', tl)
    if ago_m:
        n = int(ago_m.group(1))
        unit = ago_m.group(2)
        delta_map = {
            "second": _td(seconds=n),
            "minute": _td(minutes=n),
            "hour":   _td(hours=n),
            "day":    _td(days=n),
            "week":   _td(weeks=n),
            "month":  _td(days=n * 30),
        }
        dt = now - delta_map.get(unit, _td(0))
        return dt.strftime("%Y-%m-%d %H:%M")

    # "Yesterday at HH:MM AM/PM"
    if "yesterday" in tl:
        yesterday = now - _td(days=1)
        time_m = re.search(r'(\d{1,2}):(\d{2})\s*(am|pm)?', tl)
        if time_m:
            h, m = int(time_m.group(1)), int(time_m.group(2))
            ampm = time_m.group(3) or ""
            if ampm == "pm" and h < 12: h += 12
            if ampm == "am" and h == 12: h = 0
            return yesterday.replace(hour=h, minute=m, second=0).strftime("%Y-%m-%d %H:%M")
        return yesterday.strftime("%Y-%m-%d") + " 00:00"

    # "Monday at HH:MM" / "Tuesday at ..." (within last 7 days)
    weekdays = ["monday","tuesday","wednesday","thursday","friday","saturday","sunday"]
    for i, wd in enumerate(weekdays):
        if tl.startswith(wd):
            today_wd = now.weekday()
            diff = (today_wd - i) % 7
            if diff == 0:
                diff = 7
            target = now - _td(days=diff)
            time_m = re.search(r'(\d{1,2}):(\d{2})\s*(am|pm)?', tl)
            if time_m:
                h, m = int(time_m.group(1)), int(time_m.group(2))
                ampm = time_m.group(3) or ""
                if ampm == "pm" and h < 12: h += 12
                if ampm == "am" and h == 12: h = 0
                return target.replace(hour=h, minute=m, second=0).strftime("%Y-%m-%d %H:%M")
            return target.strftime("%Y-%m-%d") + " 00:00"

    # "June 15 at 2:30 PM" or "June 15, 2023 at 2:30 PM"
    month_map = {
        "january":1,"february":2,"march":3,"april":4,"may":5,"june":6,
        "july":7,"august":8,"september":9,"october":10,"november":11,"december":12
    }
    for month_name, month_num in month_map.items():
        if month_name in tl:
            day_m = re.search(rf'{month_name}\s+(\d{{1,2}})', tl)
            if not day_m:
                continue
            day = int(day_m.group(1))
            year_m = re.search(r'\b(20\d{2})\b', text)
            year = int(year_m.group(1)) if year_m else now.year
            if year == now.year and month_num > now.month:
                year -= 1
            time_m = re.search(r'(\d{1,2}):(\d{2})\s*(am|pm)?', tl)
            if time_m:
                h, m_t = int(time_m.group(1)), int(time_m.group(2))
                ampm = time_m.group(3) or ""
                if ampm == "pm" and h < 12: h += 12
                if ampm == "am" and h == 12: h = 0
            else:
                h, m_t = 0, 0
            try:
                dt = datetime(year, month_num, day, h, m_t)
                return dt.strftime("%Y-%m-%d %H:%M")
            except Exception:
                pass

    # "Just now"
    if "just now" in tl:
        return now.strftime("%Y-%m-%d %H:%M")

    # Short format: "1d", "2h", "5m", "3w" (Facebook mobile style)
    short_m = re.match(r'^(\d+)\s*([mhdw])$', tl.strip())
    if short_m:
        n = int(short_m.group(1))
        unit = short_m.group(2)
        from datetime import timedelta as _td2
        delta_map2 = {"m": _td2(minutes=n), "h": _td2(hours=n), "d": _td2(days=n), "w": _td2(weeks=n)}
        dt = now - delta_map2.get(unit, _td2(0))
        return dt.strftime("%Y-%m-%d %H:%M")

    # Fallback — return as-is
    return text


# ── Source-based extraction (primary method) ─────────────────────────────────

def extract_from_source(src: str) -> list:
    """
    Parse Facebook's inline JSON payloads to get posts.
    Handles __bbox, require() blobs, and ScheduledServerJS patterns.
    """
    posts = []
    seen = set()

    # Method A: extract all JSON blobs from script tags
    blobs = []

    # Standard script tags with JSON content
    for m in re.finditer(r'<script[^>]*>\s*(\{["\[].*?)\s*</script>', src, re.DOTALL):
        blobs.append(m.group(1))

    # data-sjs / __bbox blobs
    for m in re.finditer(r'data-sjs>(.*?)</script>', src, re.DOTALL):
        blobs.append(m.group(1))

    # ScheduledServerJS / require patterns (FB's main data carrier)
    for m in re.finditer(r'require\("ScheduledServerJS"\)\.handle\((.*?)\);\s*\}', src, re.DOTALL):
        blobs.append(m.group(1))

    # handleWithCustomApplyEach pattern
    for m in re.finditer(r'__d\("([^"]+)",\[\],(\{.*?\}),\d+\)', src, re.DOTALL):
        blobs.append(m.group(2))

    # Pull out large JSON objects from between script tags
    for m in re.finditer(r'>\s*(\{"require":\[.*?\])\s*<', src, re.DOTALL):
        blobs.append(m.group(1))

    for blob in blobs:
        try:
            data = json.loads(blob)
            _walk(data, posts, seen, depth=0)
        except Exception:
            # Try to extract sub-objects if full parse fails
            _try_partial_json(blob, posts, seen)

    # Method B: regex fallback on raw source
    if len(posts) < 3:
        regex_posts = _regex_extract(src, seen)
        posts.extend(regex_posts)

    # Method C: inject video URLs from raw source patterns
    _inject_video_urls_from_source(src, posts)

    return posts


def _try_partial_json(blob: str, posts: list, seen: set):
    """Try to extract valid JSON sub-objects from a partially-valid blob."""
    # Look for story/post nodes embedded in the blob
    for m in re.finditer(r'\{"__typename"\s*:\s*"(?:Story|Post)".*?"creation_time"\s*:\s*\d+', blob, re.DOTALL):
        start = m.start()
        # Try to find the matching closing brace
        depth = 0
        end = start
        for i, ch in enumerate(blob[start:], start):
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        if end > start:
            try:
                obj = json.loads(blob[start:end])
                _walk(obj, posts, seen, depth=0)
            except Exception:
                pass


def _inject_video_urls_from_source(src: str, posts: list):
    """Regex-scan raw page source for video URLs and attach them to matching posts.

    Priority: browser_native_hd > browser_native_sd > playable_url_hd > playable_url > stream_urls
    Progressive MP4s (browser_native_* and playable_url*) are preferred because they
    contain audio+video in a single file. DASH stream_urls may be video-only.
    """
    def clean(url: str) -> str:
        return url.replace("\\/", "/")

    existing_video_urls = {m["url"] for p in posts for m in p.get("media", []) if m.get("type") == "video"}

    # Use browser_native_hd as the anchor — it's the most reliable progressive MP4
    anchor_pattern = re.compile(
        r'"(?:browser_native_hd_url|browser_native_sd_url|playable_url_quality_hd'
        r'|playable_url|hd_stream_url|sd_stream_url)"\s*:\s*"(https:[^"]+)"'
    )

    # Priority fields: best progressive MP4 first
    priority_fields = [
        "browser_native_hd_url",
        "browser_native_sd_url",
        "playable_url_quality_hd",
        "playable_url",
        "hd_stream_url",
        "sd_stream_url",
    ]

    processed_chunks = set()  # avoid processing same region twice

    for m in anchor_pattern.finditer(src):
        chunk_key = m.start() // 4000  # bucket by position
        if chunk_key in processed_chunks:
            continue
        processed_chunks.add(chunk_key)

        start = max(0, m.start() - 3000)
        end = min(len(src), m.end() + 1000)
        chunk = src[start:end]

        # Pick the best URL available in this chunk
        video_url = ""
        for field in priority_fields:
            field_m = re.search(r'"' + re.escape(field) + r'"\s*:\s*"(https:[^"]+)"', chunk)
            if field_m:
                candidate = clean(field_m.group(1))
                if not any(x in candidate for x in [".mp4", "video", "fbcdn.net"]):
                    continue
                if _is_audio_only_url(candidate):
                    continue
                video_url = candidate
                break

        if not video_url or video_url in existing_video_urls:
            continue

        pfbid_m = re.search(r'pfbid([A-Za-z0-9]+)', chunk)
        post_id = f"pfbid{pfbid_m.group(1)}" if pfbid_m else None

        vid_id_m = re.search(r'"(?:story_fbid|id)"\s*:\s*"(\d{10,})"', chunk)
        vid_id = vid_id_m.group(1) if vid_id_m else None

        thumb_m = re.search(r'"uri"\s*:\s*"(https:[^"]+(?:p\d+x\d+|thumbnail)[^"]*)"', chunk)
        thumb_url = clean(thumb_m.group(1)) if thumb_m else ""

        video_entry = {"type": "video", "url": video_url, "thumb": thumb_url}

        matched = False
        if post_id:
            for post in posts:
                if post["id"] == post_id:
                    if not any(med["url"] == video_url for med in post["media"]):
                        post["media"].insert(0, video_entry)
                    existing_video_urls.add(video_url)
                    matched = True
                    break

        if not matched and vid_id:
            for post in posts:
                if post["id"] == vid_id or vid_id in post.get("postUrl", ""):
                    if not any(med["url"] == video_url for med in post["media"]):
                        post["media"].insert(0, video_entry)
                    existing_video_urls.add(video_url)
                    matched = True
                    break

        if not matched:
            for post in posts:
                if not post.get("media"):
                    post["media"] = [video_entry]
                    existing_video_urls.add(video_url)
                    matched = True
                    break

        if not matched:
            ct_m = re.search(r'"creation_time"\s*:\s*(\d{10})', chunk)
            cap_m = re.search(r'"text"\s*:\s*"((?:[^"\\]|\\.){5,300})"', chunk)
            caption = cap_m.group(1).replace("\\n", " ") if cap_m else ""
            new_post = {
                "id": hashlib.md5(video_url.encode()).hexdigest()[:12],
                "caption": caption,
                "media": [video_entry],
                "likes": 0, "comments": 0, "shares": 0,
                "postedAt": unix_to_date(ct_m.group(1)) if ct_m else "",
                "postUrl": "",
            }
            posts.append(new_post)
            existing_video_urls.add(video_url)


def _walk(obj, posts: list, seen: set, depth: int):
    if depth > 25:
        return

    if isinstance(obj, dict):
        typename = obj.get("__typename", "")

        is_post = (
            (typename in ("Story", "Post")) or
            ("creation_time" in obj and "message" in obj) or
            ("creation_time" in obj and "attachments" in obj) or
            ("creation_time" in obj and "comet_sections" in obj)
        )

        if is_post:
            post = _extract_post_node(obj)
            if post and post["id"] not in seen:
                seen.add(post["id"])
                posts.append(post)

        for v in obj.values():
            _walk(v, posts, seen, depth + 1)

    elif isinstance(obj, list):
        for item in obj:
            _walk(item, posts, seen, depth + 1)


def _extract_post_node(node: dict) -> Optional[dict]:
    # ── ID ────────────────────────────────────────────────────────────────
    post_id = None
    url = ""

    url_candidates = [
        node.get("url"),
        node.get("permalink_url"),
        _deep_get(node, ["comet_sections", "context_layout", "story", "url"]),
        _deep_get(node, ["wwwURL"]),
    ]
    for uc in url_candidates:
        if uc:
            url = str(uc)
            m = re.search(r"pfbid([A-Za-z0-9]+)", url)
            if m:
                post_id = f"pfbid{m.group(1)}"
                break

    if not post_id:
        raw_id = node.get("id") or node.get("story_fbid") or node.get("post_id") or ""
        if raw_id:
            post_id = str(raw_id)

    # ── Creation time ─────────────────────────────────────────────────────
    creation_time = (
        node.get("creation_time") or
        node.get("created_time") or
        _deep_get(node, ["comet_sections", "metadata", 0, "story", "creation_time"]) or
        ""
    )
    posted_at = unix_to_date(creation_time) if creation_time else ""

    # ── Caption / message ─────────────────────────────────────────────────
    caption = ""
    msg_candidates = [
        node.get("message"),
        _deep_get(node, ["comet_sections", "content", "story", "message"]),
        _deep_get(node, ["story", "message"]),
        _deep_get(node, ["message", "text"]),
    ]
    for msg in msg_candidates:
        if not msg:
            continue
        if isinstance(msg, dict):
            text = msg.get("text") or ""
            if text:
                caption = clean_text(text)
                break
        elif isinstance(msg, str) and msg:
            caption = clean_text(msg)
            break

    # ── Media ─────────────────────────────────────────────────────────────
    media = []
    attach_candidates = [
        node.get("attachments"),
        _deep_get(node, ["comet_sections", "content", "story", "attachments"]),
    ]
    for attachments in attach_candidates:
        if isinstance(attachments, list):
            for att in attachments:
                _extract_media_from_attachment(att, media)
            if media:
                break

    # ── Reactions ─────────────────────────────────────────────────────────
    likes = 0
    comments = 0

    reaction_node = (
        node.get("feedback") or
        _deep_get(node, ["comet_sections", "feedback", "story", "feedback_context",
                         "feedback_target_with_context", "ufi_renderer", "feedback"]) or
        {}
    )
    if isinstance(reaction_node, dict):
        rc = reaction_node.get("reaction_count") or reaction_node.get("reactors") or {}
        if isinstance(rc, dict):
            likes = rc.get("count", 0) or 0
        elif isinstance(rc, int):
            likes = rc

        comment_node = (
            _deep_get(reaction_node, ["comment_count"]) or
            _deep_get(reaction_node, ["total_comment_count"]) or
            {}
        )
        if isinstance(comment_node, dict):
            comments = comment_node.get("total_count", 0) or 0
        elif isinstance(comment_node, int):
            comments = comment_node

    if not post_id and not caption:
        return None

    if not post_id:
        post_id = hashlib.md5((caption + posted_at).encode()).hexdigest()[:12]

    return {
        "id": post_id,
        "caption": caption,
        "media": media,
        "likes": likes,
        "comments": comments,
        "shares": 0,
        "postedAt": posted_at,
        "postUrl": url,
    }


def _extract_media_from_attachment(att, media: list):
    if not isinstance(att, dict):
        return

    typename = att.get("__typename", "")

    # ── Video ─────────────────────────────────────────────────────────────
    video_url = ""

    # Priority: browser_native_hd/sd → playable_url_hd → playable_url → stream_urls
    # browser_native_* and playable_url* are progressive MP4 (audio+video combined)
    # stream_urls may be DASH (video-only segment)
    priority_video_fields = [
        "browser_native_hd_url", "browser_native_sd_url",
        "playable_url_quality_hd", "playable_url",
        "hd_stream_url", "sd_stream_url", "stream_url",
    ]

    # Direct video URL fields
    for field in priority_video_fields:
        v = att.get(field, "")
        if v and not _is_audio_only_url(v):
            video_url = v.replace("\\/", "/")
            break

    # Nested video node
    if not video_url:
        for key in ["video", "videoDeliveryLegacyFields", "videoDeliveryResponseFragment"]:
            vnode = att.get(key)
            if isinstance(vnode, dict):
                for field in priority_video_fields:
                    v = vnode.get(field, "")
                    if v and not _is_audio_only_url(v):
                        video_url = v.replace("\\/", "/")
                        break
            if video_url:
                break

    if video_url:
        if not any(m["url"] == video_url for m in media):
            thumb = ""
            thumb_node = att.get("preferred_thumbnail") or {}
            if isinstance(thumb_node, dict):
                img_n = thumb_node.get("image") or {}
                thumb = img_n.get("uri", "") if isinstance(img_n, dict) else ""
            media.append({"type": "video", "url": video_url, "thumb": thumb})
        return

    # ── Image ─────────────────────────────────────────────────────────────
    for img_key in ["large_share_image", "photo_image", "image", "full_image",
                    "preferred_thumbnail", "media"]:
        img = att.get(img_key)
        if isinstance(img, dict):
            uri = img.get("uri") or (img.get("image") or {}).get("uri", "")
            if uri and not any(m["url"] == uri for m in media):
                media.append({"type": "image", "url": uri})
                return

    # ── Recurse into nested wrappers ──────────────────────────────────────
    for key in ("media", "node", "target", "story_attachment", "attachments",
                "media_wrapper", "photo", "album_photo"):
        sub = att.get(key)
        if isinstance(sub, dict):
            _extract_media_from_attachment(sub, media)
        elif isinstance(sub, list):
            for item in sub:
                if isinstance(item, dict):
                    _extract_media_from_attachment(item, media)


def _deep_get(d, keys):
    try:
        for k in keys:
            if isinstance(d, list):
                d = d[int(k)]
            else:
                d = d[k]
        return d
    except Exception:
        return None


def _regex_extract(src: str, seen: set) -> list:
    """
    Regex fallback: extract posts from raw source using pfbid + creation_time + message patterns.
    Scans the source in chunks around each pfbid occurrence for nearby data.
    """
    posts = []

    # Find all pfbid occurrences with their positions
    pfbid_pattern = re.compile(r'pfbid([A-Za-z0-9]{20,})')

    for m in pfbid_pattern.finditer(src):
        pfbid = f"pfbid{m.group(1)}"
        if pfbid in seen:
            continue

        # Look at surrounding 4000 chars for context
        start = max(0, m.start() - 2000)
        end = min(len(src), m.end() + 2000)
        chunk = src[start:end]

        # Extract creation_time
        ct_m = re.search(r'"creation_time"\s*:\s*(\d{10})', chunk)
        posted_at = unix_to_date(ct_m.group(1)) if ct_m else ""

        # Extract message text
        caption = ""
        msg_m = re.search(r'"message"\s*:\s*\{"text"\s*:\s*"((?:[^"\\]|\\.){3,})"', chunk)
        if msg_m:
            caption = clean_text(msg_m.group(1).replace("\\n", "\n"))
        else:
            # Try alternate text pattern
            txt_m = re.search(r'"text"\s*:\s*"((?:[^"\\]|\\.){10,})"', chunk)
            if txt_m:
                caption = clean_text(txt_m.group(1).replace("\\n", "\n"))

        # Only add if we have at least a timestamp or caption
        if not posted_at and not caption:
            continue

        seen.add(pfbid)
        posts.append({
            "id": pfbid,
            "caption": caption,
            "media": [],
            "likes": 0,
            "comments": 0,
            "shares": 0,
            "postedAt": posted_at,
            "postUrl": f"https://www.facebook.com/permalink.php?story_fbid={pfbid}",
        })

    return posts


# ── DOM-based extraction (fallback) ──────────────────────────────────────────

def extract_from_dom(driver) -> list:
    """
    Use Selenium DOM to get captions and images from rendered post cards.
    Optimized with execute_script to prevent Selenium overhead.
    """
    js_script = r"""
    const posts = [];
    const post_els = document.querySelectorAll("div[aria-posinset], div[data-pagelet*='FeedUnit'], div[role='article']");

    post_els.forEach((el) => {
        let caption = "";
        const cap_selectors = [
            "div[data-ad-comet-preview='message']",
            "div[data-ad-preview='message']",
            "div[dir='auto'][style*='--']",
            "div[class*='xdj266r']"
        ];
        for (const sel of cap_selectors) {
            const els_cap = el.querySelectorAll(sel);
            for (const ce of els_cap) {
                const t = (ce.innerText || ce.textContent || "").trim();
                if (t.length > 15) {
                    caption = t;
                    break;
                }
            }
            if (caption) break;
        }
        
        if (!caption) {
            const spans = el.querySelectorAll("span[dir='auto']");
            let longest = "";
            spans.forEach((s) => {
                const t = (s.innerText || s.textContent || "").trim();
                if (t.length > 20 && t.length > longest.length) {
                    longest = t;
                }
            });
            caption = longest;
        }
        
        let post_id = "";
        let post_url = "";
        const anchors = el.querySelectorAll("a");
        for (const a of anchors) {
            const href = a.href || "";
            let m = href.match(/pfbid([A-Za-z0-9]+)/);
            if (m) {
                post_id = "pfbid" + m[1];
                post_url = href.split("?")[0].split("#")[0];
                break;
            }
            m = href.match(/\/posts\/([A-Za-z0-9_-]+)/);
            if (m) {
                post_id = m[1];
                post_url = href.split("?")[0].split("#")[0];
                break;
            }
            m = href.match(/story_fbid=(\d+)/);
            if (m) {
                post_id = m[1];
                post_url = href;
                break;
            }
            m = href.match(/\/reel(?:s)?\/(\d+)/);
            if (m) {
                post_id = m[1];
                post_url = href.split("?")[0].split("#")[0];
                break;
            }
            m = href.match(/\/videos\/(\d+)/);
            if (m) {
                post_id = m[1];
                post_url = href.split("?")[0].split("#")[0];
                break;
            }
        }
        
        let posted_at_raw = "";
        const time_links = el.querySelectorAll("a[role='link']");
        for (const a of time_links) {
            const href = a.href || "";
            if (href.includes("/posts/") || href.includes("pfbid") || href.includes("story_fbid") || href.includes("/videos/")) {
                for (const attr of ["aria-label", "title"]) {
                    const val = a.getAttribute(attr) || "";
                    const val_lower = val.toLowerCase();
                    const keywords = [
                        "january","february","march","april","may","june",
                        "july","august","september","october","november","december",
                        "hour","minute","yesterday","monday","tuesday","wednesday",
                        "thursday","friday","saturday","sunday","ago","at "
                    ];
                    if (val && keywords.some(kw => val_lower.includes(kw))) {
                        posted_at_raw = val;
                        break;
                    }
                }
            }
            if (posted_at_raw) break;
        }
        
        const media = [];
        const imgs = el.querySelectorAll("img[src*='fbcdn']");
        imgs.forEach((img) => {
            const src = img.src || "";
            if (src && !["p48x48", "p32x32", "p16x16", "emoji", "s32x32", "s48x48"].some(x => src.includes(x))) {
                if (!media.some(m => m.url === src)) {
                    media.push({type: "image", url: src});
                }
            }
        });
        
        const vids = el.querySelectorAll("video");
        vids.forEach((vid) => {
            const src = vid.src || "";
            const poster = vid.getAttribute("poster") || "";
            if (src && !media.some(m => m.url === src)) {
                media.push({type: "video", url: src, thumb: poster});
            }
        });
        
        let likes = 0;
        const spans = el.querySelectorAll("span[aria-label]");
        for (const span of spans) {
            const label = span.getAttribute("aria-label") || "";
            const label_lower = label.toLowerCase();
            if (label_lower.includes("reaction") || label_lower.includes("like")) {
                const nums = label.match(/[\d,]+/);
                if (nums) {
                    likes = nums[0];
                }
                break;
            }
        }
        
        if (post_id || caption) {
            posts.push({
                id: post_id,
                caption: caption,
                media: media,
                likes: likes,
                posted_at_raw: posted_at_raw,
                post_url: post_url
            });
        }
    });
    return posts;
    """
    try:
        raw_posts = driver.execute_script(js_script)
        if not raw_posts:
            return []
        
        posts = []
        seen = set()
        for rp in raw_posts:
            pid = rp.get("id", "")
            cap = clean_text(rp.get("caption", ""))
            
            # Fallback ID generation if none matched
            if not pid and cap:
                posted_at_temp = ""
                raw_date = rp.get("posted_at_raw", "")
                if raw_date:
                    posted_at_temp = _parse_fb_date(raw_date)
                pid = hashlib.md5((cap + posted_at_temp).encode()).hexdigest()[:12]
                
            if not pid:
                continue
                
            if pid in seen:
                continue
            seen.add(pid)
            
            # Reactions
            likes_val = rp.get("likes", 0)
            if isinstance(likes_val, str):
                likes_count = parse_count(likes_val)
            else:
                likes_count = int(likes_val)

            posted_at = ""
            raw_date = rp.get("posted_at_raw", "")
            if raw_date:
                posted_at = _parse_fb_date(raw_date)

            posts.append({
                "id": pid,
                "caption": cap,
                "media": rp.get("media", []),
                "likes": likes_count,
                "comments": 0,
                "shares": 0,
                "postedAt": posted_at,
                "postUrl": rp.get("post_url", ""),
            })
        return posts
    except Exception as e:
        print(f"Error in JS DOM extract: {e}")
        return []


# ── Page meta ─────────────────────────────────────────────────────────────────

def get_page_meta(driver) -> dict:
    """Extract page info: name, followers, likes, about, address, phone, website, category."""
    meta = {}
    src = driver.page_source

    # Title from og:title
    try:
        el = driver.find_element(By.CSS_SELECTOR, "meta[property='og:title']")
        og_title = el.get_attribute("content") or ""
        if og_title and og_title.lower() not in ("facebook", ""):
            meta["title"] = og_title
    except Exception:
        pass

    if not meta.get("title"):
        try:
            for sel in ["h1", "[data-testid='page-header-title']", "span[dir='auto']"]:
                els = driver.find_elements(By.CSS_SELECTOR, sel)
                for el in els:
                    txt = el.text.strip()
                    if txt and len(txt) > 2 and txt.lower() not in ("facebook", "home"):
                        meta["title"] = txt
                        break
                if meta.get("title"):
                    break
        except Exception:
            pass

    # Cover / profile image
    try:
        el = driver.find_element(By.CSS_SELECTOR, "meta[property='og:image']")
        meta["cover_image"] = el.get_attribute("content")
    except Exception:
        pass

    # Description
    try:
        el = driver.find_element(By.CSS_SELECTOR, "meta[name='description'], meta[property='og:description']")
        meta["description"] = el.get_attribute("content")
    except Exception:
        pass

    # Page name from JSON if og:title is generic
    if not meta.get("title") or meta.get("title", "").lower() == "facebook":
        for pattern in [
            r'"page_name"\s*:\s*"([^"]+)"',
            r'"name"\s*:\s*"([^"]+)".*?"__typename"\s*:\s*"Page"',
        ]:
            m = re.search(pattern, src)
            if m and m.group(1).lower() not in ("facebook", ""):
                meta["title"] = m.group(1)
                break

    # Followers
    for pattern in [
        r'"follower_count"\s*:\s*(\d+)',
        r'"fan_count"\s*:\s*(\d+)',
        r'"global_followers_count"\s*:\s*(\d+)',
    ]:
        m = re.search(pattern, src)
        if m:
            meta["followers"] = int(m.group(1))
            break

    # Likes
    if not meta.get("likes"):
        m = re.search(r'"like_count"\s*:\s*(\d+)', src)
        if m:
            meta["likes"] = int(m.group(1))

    # Category
    m = re.search(r'"category_list"\s*:\s*\[.*?"name"\s*:\s*"([^"]+)"', src, re.DOTALL)
    if m:
        meta["category"] = m.group(1)

    # About / biography
    for pattern in [
        r'"biography"\s*:\s*\{"text"\s*:\s*"((?:[^"\\]|\\.)+)"',
        r'"general_info"\s*:\s*\{"text"\s*:\s*"((?:[^"\\]|\\.)+)"',
        r'"blurb"\s*:\s*"((?:[^"\\]|\\.)+)"',
    ]:
        m = re.search(pattern, src)
        if m:
            try:
                meta["about"] = m.group(1).encode('raw_unicode_escape').decode('unicode_escape')
            except Exception:
                meta["about"] = m.group(1)
            break

    # Website, phone, address
    for key, pat in [
        ("website",  r'"website"\s*:\s*"([^"]+)"'),
        ("phone",    r'"phone"\s*:\s*"([^"]+)"'),
        ("address",  r'"single_line_address"\s*:\s*"([^"]+)"'),
    ]:
        m = re.search(pat, src)
        if m:
            meta[key] = m.group(1)

    # Verified
    m = re.search(r'"is_verified"\s*:\s*(true|false)', src)
    if m:
        meta["is_verified"] = m.group(1) == "true"

    # Page ID
    m = re.search(r'"pageID"\s*:\s*"(\d+)"', src)
    if not m:
        m = re.search(r'fb://profile/(\d+)', src)
    if m:
        meta["page_id"] = m.group(1)

    return meta


# ── Scroll helpers ────────────────────────────────────────────────────────────

def _scroll_page(driver, pause: float = 3.0):
    """
    Scroll to bottom and wait for new content to load.
    Uses multiple strategies to trigger Facebook's lazy loader.
    """
    last_height = driver.execute_script("return document.body.scrollHeight")

    # Strategy 1: scroll to bottom
    driver.execute_script("window.scrollTo(0, document.body.scrollHeight)")
    time.sleep(pause)

    new_height = driver.execute_script("return document.body.scrollHeight")
    if new_height > last_height:
        return True

    # Strategy 2: scroll up a bit then back down (triggers intersection observer)
    driver.execute_script("window.scrollBy(0, -500)")
    time.sleep(0.8)
    driver.execute_script("window.scrollTo(0, document.body.scrollHeight)")
    time.sleep(1.5)

    new_height = driver.execute_script("return document.body.scrollHeight")
    if new_height > last_height:
        return True

    # Strategy 3: scroll in increments (helps with virtualized lists)
    current = driver.execute_script("return window.pageYOffset")
    total   = driver.execute_script("return document.body.scrollHeight")
    if current < total - 1000:
        driver.execute_script(f"window.scrollTo(0, {total - 500})")
        time.sleep(0.5)
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(1)

    new_height = driver.execute_script("return document.body.scrollHeight")
    return new_height > last_height


def _get_video_urls_from_reels(driver, page_url: str) -> list:
    """
    Visit /reels page and extract video URLs.
    Strategy:
    1. Try JSON source patterns (works when FB embeds data in script tags)
    2. Click each reel thumbnail to open the player and grab the <video> src
    3. Try /videos page as well
    """
    entries = []
    seen_v = set()
    seen_ids = set()

    def _extract_from_src(src_text: str):
        """Extract video entries from raw page source.

        Strategy: for each anchor-point (any video URL field found), extract a 8000-char
        chunk around it and pick the BEST available URL in that chunk using priority order:
          1. browser_native_hd_url  — progressive MP4 with audio+video ✓
          2. browser_native_sd_url  — progressive MP4 with audio+video ✓
          3. playable_url_quality_hd — progressive MP4 ✓
          4. playable_url           — progressive MP4 ✓
          5. hd_stream_url          — may be DASH, use only as last resort
          6. sd_stream_url          — may be DASH, use only as last resort

        This avoids picking a DASH audio-only segment when a good progressive URL
        is also present in the same JSON blob.
        """

        # Find every occurrence of any video URL field to use as anchor points
        anchor_pattern = re.compile(
            r'"(?:browser_native_hd_url|browser_native_sd_url|playable_url_quality_hd'
            r'|playable_url|hd_stream_url|sd_stream_url)"\s*:\s*"(https:[^"]+)"'
        )

        # Priority order: best → worst
        url_fields = [
            "browser_native_hd_url",
            "browser_native_sd_url",
            "playable_url_quality_hd",
            "playable_url",
            "hd_stream_url",
            "sd_stream_url",
        ]

        for m in anchor_pattern.finditer(src_text):
            # Use a large chunk around this match to find metadata + best URL
            start = max(0, m.start() - 5000)
            end   = min(len(src_text), m.end() + 3000)
            chunk = src_text[start:end]

            # Pick the best available URL in this chunk
            best_url = ""
            for field in url_fields:
                field_m = re.search(
                    r'"' + re.escape(field) + r'"\s*:\s*"(https:[^"]+)"', chunk
                )
                if field_m:
                    candidate = field_m.group(1).replace("\\/", "/")
                    # Must look like a video URL
                    if not any(x in candidate for x in [".mp4", "video", "fbcdn.net"]):
                        continue
                    # Skip audio-only DASH segments
                    if _is_audio_only_url(candidate):
                        continue
                    best_url = candidate
                    break  # got best available

            if not best_url:
                continue
            if best_url in seen_v:
                continue
            seen_v.add(best_url)

            # Thumbnail — prefer video thumbnail images
            thumb_m = re.search(
                r'"uri"\s*:\s*"(https:[^"]+(?:thumbnail|t15\.5-|p\d+x\d+)[^"]*)"', chunk)
            thumb = thumb_m.group(1).replace("\\/", "/") if thumb_m else ""

            # Caption
            cap_m = re.search(r'"text"\s*:\s*"((?:[^"\\]|\\.){5,500})"', chunk)
            caption = cap_m.group(1).replace("\\n", " ").replace('\\"', '"') if cap_m else ""

            # Date
            ct_m = re.search(r'"creation_time"\s*:\s*(\d{10})', chunk)
            posted_at = unix_to_date(ct_m.group(1)) if ct_m else ""

            # ID — prefer pfbid, then numeric video/story id
            pfbid_m  = re.search(r'pfbid([A-Za-z0-9]+)', chunk)
            vid_id_m = re.search(r'"(?:video_id|story_fbid|id)"\s*:\s*"(\d{10,})"', chunk)
            if pfbid_m:
                post_id = f"pfbid{pfbid_m.group(1)}"
            elif vid_id_m:
                post_id = vid_id_m.group(1)
            else:
                post_id = hashlib.md5(best_url.encode()).hexdigest()[:12]

            if post_id in seen_ids:
                # If we already have this post, upgrade its URL if current is lower priority
                # (i.e., replace hd_stream_url entry with browser_native_hd_url if found later)
                for entry in entries:
                    if entry["id"] == post_id:
                        old_url = entry["url"]
                        old_priority = next(
                            (i for i, f in enumerate(url_fields)
                             if re.search(r'/' + re.escape(f.replace('_', '.')) + r'[?/]', old_url, re.IGNORECASE)),
                            len(url_fields)
                        )
                        new_priority = next(
                            (i for i, f in enumerate(url_fields[:4])  # only upgrade to top-4 progressive
                             if re.search(r'browser_native|playable_url', best_url)),
                            len(url_fields)
                        )
                        # Upgrade if the new URL is a known-good progressive MP4
                        if (re.search(r'browser_native|playable_url', best_url)
                                and not re.search(r'browser_native|playable_url', old_url)):
                            entry["url"] = best_url
                        break
                continue
            seen_ids.add(post_id)

            entries.append({
                "id": post_id,
                "url": best_url,
                "thumb": thumb,
                "caption": caption,
                "posted_at": posted_at,
            })

    def _try_dom_video_elements():
        """Get video src from actual <video> elements in DOM."""
        try:
            vids = driver.find_elements(By.TAG_NAME, "video")
            for vid in vids:
                src    = vid.get_attribute("src") or ""
                poster = vid.get_attribute("poster") or ""
                if src and src not in seen_v and src.startswith("http"):
                    seen_v.add(src)
                    # Try to get surrounding post container for metadata
                    try:
                        container = vid.find_element(By.XPATH, "./ancestor::div[@role='article' or @aria-label][1]")
                        caption_els = container.find_elements(By.CSS_SELECTOR, "span[dir='auto']")
                        caption = ""
                        for ce in caption_els:
                            t = clean_text(ce.text)
                            if len(t) > 15:
                                caption = t
                                break
                    except Exception:
                        caption = ""

                    post_id = hashlib.md5(src.encode()).hexdigest()[:12]
                    if post_id not in seen_ids:
                        seen_ids.add(post_id)
                        entries.append({
                            "id": post_id,
                            "url": src,
                            "thumb": poster,
                            "caption": caption,
                            "posted_at": "",
                        })
        except Exception:
            pass

    try:
        # ── Visit /reels ──────────────────────────────────────────────────
        reels_url = page_url.rstrip("/") + "/reels"
        driver.get(reels_url)
        time.sleep(6)

        # Scroll to load more reels
        for _ in range(4):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(3)

        # Method 1: JSON source extraction (browser_native_hd_url etc.)
        _extract_from_src(driver.page_source)

        # Method 1b: DASH manifest extraction (reels page uses DASH — no browser_native URLs)
        dash_entries = _extract_dash_from_source(driver.page_source)
        for de in dash_entries:
            if de["id"] not in seen_ids:
                seen_ids.add(de["id"])
                if de["url"] not in seen_v:
                    seen_v.add(de["url"])
                entries.append(de)

        # Method 2: DOM <video> elements (for autoplay previews)
        _try_dom_video_elements()

        # Method 3: Click each reel thumbnail to open the video player
        # This forces FB to load the actual video URL into the DOM
        if len(entries) == 0:
            try:
                # Reel thumbnails — various selectors FB uses
                reel_links = driver.find_elements(By.CSS_SELECTOR,
                    "a[href*='/reel/'], a[href*='/reels/'], div[role='article'] a[role='link']")
                reel_hrefs = []
                for a in reel_links[:15]:  # limit to 15 to avoid too long
                    href = a.get_attribute("href") or ""
                    if "/reel/" in href or "/reels/" in href:
                        if href not in reel_hrefs:
                            reel_hrefs.append(href)

                for href in reel_hrefs[:10]:
                    try:
                        driver.get(href)
                        time.sleep(4)
                        # Extract from source after loading individual reel
                        _extract_from_src(driver.page_source)
                        _try_dom_video_elements()
                        # Go back
                        driver.back()
                        time.sleep(2)
                    except Exception:
                        pass
            except Exception:
                pass

        # ── Also try /videos page ─────────────────────────────────────────
        try:
            driver.get(page_url.rstrip("/") + "/videos")
            time.sleep(5)
            for _ in range(3):
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight)")
                time.sleep(3)
            _extract_from_src(driver.page_source)
            dash_entries2 = _extract_dash_from_source(driver.page_source)
            for de in dash_entries2:
                if de["id"] not in seen_ids:
                    seen_ids.add(de["id"])
                    if de["url"] not in seen_v:
                        seen_v.add(de["url"])
                    entries.append(de)
            _try_dom_video_elements()
        except Exception:
            pass

    except Exception:
        pass

    return entries


# ── Main entry point ──────────────────────────────────────────────────────────

def scrape_facebook_posts(
    page_url: str,
    cookies: dict,
    browser: str = "chrome",
    max_posts: int = 20,
    scroll_rounds: int = 5,
    date_from: str = "",   # YYYY-MM-DD — stop if post older than this
    date_to: str = "",     # YYYY-MM-DD — skip posts newer than this
    on_progress=None,
) -> dict:

    # Parse date range once
    from datetime import date as _date
    _date_from = None
    _date_to   = None
    try:
        if date_from:
            _date_from = datetime.strptime(date_from[:10], "%Y-%m-%d")
    except Exception:
        pass
    try:
        if date_to:
            _date_to = datetime.strptime(date_to[:10], "%Y-%m-%d").replace(
                hour=23, minute=59, second=59
            )
    except Exception:
        pass

    def _in_range(posted_at: str) -> bool:
        """True if post date is within requested range."""
        if not posted_at:
            # If date range is set and we don't know the date, exclude it
            # to avoid polluting results with undated posts
            if _date_from or _date_to:
                return False
            return True
        try:
            dt = datetime.strptime(posted_at[:16], "%Y-%m-%d %H:%M")
            if _date_from and dt < _date_from:
                return False
            if _date_to and dt > _date_to:
                return False
            return True
        except Exception:
            return True

    def _past_range(posted_at: str) -> bool:
        """True if post is older than date_from — we can stop scrolling."""
        if not _date_from or not posted_at:
            return False
        try:
            dt = datetime.strptime(posted_at[:16], "%Y-%m-%d %H:%M")
            return dt < _date_from
        except Exception:
            return False

    def _future_of_range(posted_at: str) -> bool:
        """True if post is newer than date_to — skip but keep scrolling."""
        if not _date_to or not posted_at:
            return False
        try:
            dt = datetime.strptime(posted_at[:16], "%Y-%m-%d %H:%M")
            return dt > _date_to
        except Exception:
            return False

    def _progress(pct: int, msg: str = ""):
        if on_progress:
            try:
                on_progress(pct, msg)
            except Exception:
                pass
    driver = None
    try:
        driver = init_driver(browser)
        _progress(5, "Browser ready, cookies inject ho rahi hain...")

        # Inject cookies (this also refreshes page so session is active)
        if any(v for v in cookies.values() if v):
            inject_cookies(driver, cookies)
        else:
            driver.get("https://www.facebook.com")
            time.sleep(2)

        # Navigate to the target page
        _progress(10, "Facebook page load ho rahi hai...")
        driver.get(page_url)
        time.sleep(6)

        # Fix: if Facebook redirected to web.facebook.com (mobile lite),
        # navigate back to www.facebook.com which renders the desktop feed
        current_url_check = driver.current_url
        if "web.facebook.com" in current_url_check and "_rdc=1" in current_url_check:
            www_url = current_url_check.replace("web.facebook.com", "www.facebook.com")
            # Strip redirect params
            www_url = www_url.split("?")[0].split("#")[0]
            print(f"Detected web.facebook.com redirect, forcing www: {www_url}")
            driver.get(www_url)
            time.sleep(6)

        # Check login wall
        src = driver.page_source
        current_url = driver.current_url
        is_login_wall = (
            "login" in current_url.lower() or
            ('id="email"' in src and "create new account" in src.lower()) or
            ("log in" in src.lower() and "create new account" in src.lower() and len(src) < 30000)
        )
        if is_login_wall:
            return {
                "error": "login_wall",
                "message": "Facebook ne login maanga. 'Facebook se Login Karein' button use karo.",
            }

        # Check if the loaded URL is a Reels or Video URL
        current_url = driver.current_url.lower()
        is_reels_only = any(x in current_url for x in ["/reel", "/video", "/watch"]) or any(x in page_url.lower() for x in ["/reel", "/video", "/watch"])

        if is_reels_only:
            is_single_reel = "/reel/" in current_url or "/videos/" in current_url or "/watch" in current_url or "/reel/" in page_url.lower() or "/videos/" in page_url.lower() or "/watch" in page_url.lower()
            
            entries = []
            seen_v = set()
            seen_ids = set()

            def local_extract_from_src(src_text: str):
                # Two-pass approach:
                # Pass 1: combined video+audio fields (browser_native_hd_url, playable_url, etc.)
                # Pass 2: DASH base_url only if pass 1 found nothing (video-only, no audio)
                combined_pattern = re.compile(
                    r'"browser_native_hd_url"\s*:\s*"(https:[^"]+)"'
                    r'|"playable_url_quality_hd"\s*:\s*"(https:[^"]+)"'
                    r'|"browser_native_sd_url"\s*:\s*"(https:[^"]+)"'
                    r'|"playable_url"\s*:\s*"(https:[^"]+\.mp4[^"]*)"'
                    r'|"hd_stream_url"\s*:\s*"(https:[^"]+)"'
                    r'|"sd_stream_url"\s*:\s*"(https:[^"]+)"'
                )
                dash_pattern = re.compile(
                    r'"base_url"\s*:\s*"(https?:[^"]+\.mp4[^"]*)"'
                )

                def _process_matches(pattern_iter, group_count):
                    for m in pattern_iter:
                        raw = ""
                        for i in range(1, group_count + 1):
                            raw = m.group(i)
                            if raw:
                                break
                        if not raw:
                            continue
                        url = raw.replace("\\/", "/").replace("\\u0025", "%").replace("&amp;", "&")
                        if not any(x in url for x in [".mp4", "video", "fbcdn.net"]):
                            continue
                        if _is_audio_only_url(url):
                            continue
                        if url in seen_v:
                            continue
                        seen_v.add(url)

                        start = max(0, m.start() - 4000)
                        end   = min(len(src_text), m.end() + 1000)
                        chunk = src_text[start:end]

                        thumb_m = re.search(
                            r'"uri"\s*:\s*"(https:[^"]+(?:thumbnail|t15\.5-|p\d+x\d+)[^"]*)"', chunk)
                        thumb = thumb_m.group(1).replace("\\/", "/") if thumb_m else ""

                        cap_m = re.search(r'"text"\s*:\s*"((?:[^"\\]|\\.){5,500})"', chunk)
                        caption = cap_m.group(1).replace("\\n", " ").replace('\\"', '"') if cap_m else ""

                        ct_m = re.search(r'"creation_time"\s*:\s*(\d{10})', chunk)
                        posted_at = unix_to_date(ct_m.group(1)) if ct_m else ""

                        win_start = max(0, m.start() - 1000)
                        win_end = min(len(src_text), m.end() + 200)
                        window = src_text[win_start:win_end]

                        video_id_matches = []
                        for vid_m in re.finditer(r'"video_id"\s*:\s*"(\d+)"', window):
                            abs_pos = win_start + vid_m.start()
                            dist = abs(abs_pos - m.start())
                            video_id_matches.append((dist, vid_m.group(1)))

                        if video_id_matches:
                            video_id_matches.sort()
                            post_id = video_id_matches[0][1]
                        else:
                            id_matches = []
                            for id_m in re.finditer(r'"id"\s*:\s*"(\d{10,})"', window):
                                abs_pos = win_start + id_m.start()
                                dist = abs(abs_pos - m.start())
                                id_matches.append((dist, id_m.group(1)))

                            if id_matches:
                                id_matches.sort()
                                post_id = id_matches[0][1]
                            else:
                                pfbid_matches = []
                                for pf_m in re.finditer(r'pfbid([A-Za-z0-9]+)', window):
                                    abs_pos = win_start + pf_m.start()
                                    dist = abs(abs_pos - m.start())
                                    pfbid_matches.append((dist, f"pfbid{pf_m.group(1)}"))

                                if pfbid_matches:
                                    pfbid_matches.sort()
                                    post_id = pfbid_matches[0][1]
                                else:
                                    post_id = hashlib.md5(url.encode()).hexdigest()[:12]

                        if post_id in seen_ids:
                            continue
                        seen_ids.add(post_id)

                        entries.append({
                            "id": post_id,
                        "url": url,
                        "thumb": thumb,
                        "caption": caption,
                        "posted_at": posted_at,
                    })

                # Run pass 1: combined video+audio URLs
                _process_matches(combined_pattern.finditer(src_text), 6)
                # Run pass 2: DASH base_url only if pass 1 found nothing
                if not entries:
                    _process_matches(dash_pattern.finditer(src_text), 1)

            def local_try_dom_video_elements():
                try:
                    vids = driver.find_elements(By.TAG_NAME, "video")
                    for vid in vids:
                        src    = vid.get_attribute("src") or ""
                        poster = vid.get_attribute("poster") or ""
                        if src and src not in seen_v and src.startswith("http"):
                            seen_v.add(src)
                            caption = ""
                            try:
                                container = vid.find_element(By.XPATH, "./ancestor::div[@role='article' or @aria-label][1]")
                                caption_els = container.find_elements(By.CSS_SELECTOR, "span[dir='auto']")
                                for ce in caption_els:
                                    t = clean_text(ce.text)
                                    if len(t) > 15:
                                        caption = t
                                        break
                            except Exception:
                                pass

                            post_id = hashlib.md5(src.encode()).hexdigest()[:12]
                            if post_id not in seen_ids:
                                seen_ids.add(post_id)
                                entries.append({
                                    "id": post_id,
                                    "url": src,
                                    "thumb": poster,
                                    "caption": caption,
                                    "posted_at": "",
                                })
                except Exception:
                    pass

            # Initial extract
            local_extract_from_src(driver.page_source)
            local_try_dom_video_elements()

            if not is_single_reel:
                # ── Step 1: Collect reel IDs from the grid page by scrolling ──
                # Scroll to load all reel thumbnails in the grid
                rounds = min(scroll_rounds, 200)
                prev_count = 0
                no_new = 0
                for r in range(rounds):
                    _progress(20 + int((r / max(rounds, 1)) * 30), f"Reels grid scroll {r+1}/{rounds}...")
                    driver.execute_script("window.scrollTo(0, document.body.scrollHeight)")
                    time.sleep(2.5)
                    # Check how many reel links are now visible
                    try:
                        cur_count = driver.execute_script(
                            "return document.querySelectorAll('a[href*=\"/reel/\"]').length;"
                        ) or 0
                    except Exception:
                        cur_count = prev_count
                    if cur_count == prev_count:
                        no_new += 1
                        if no_new >= 3:
                            break
                    else:
                        no_new = 0
                    prev_count = cur_count

                # ── Step 2: Extract all reel IDs + thumbnails from grid DOM ──
                # Extract page username from URL to filter out suggested/recommended reels
                page_username = ""
                try:
                    import urllib.parse as _urlparse
                    _path = _urlparse.urlparse(page_url).path.strip("/").split("/")[0]
                    if _path and _path not in ("reel", "reels", "watch", "videos"):
                        page_username = _path.lower()
                except Exception:
                    pass

                js_grid = r"""
                const reels = [];
                const seen_ids = new Set();
                const pageUsername = arguments[0].toLowerCase();

                document.querySelectorAll('a[href*="/reel/"]').forEach((a) => {
                    const href = a.href || "";
                    const m = href.match(/\/reel(?:s)?\/(\d+)/);
                    if (!m) return;
                    const id = m[1];
                    if (seen_ids.has(id)) return;

                    // Filter: skip reels that are NOT inside the page's own reel container.
                    // Strategy: walk up the DOM and check if any ancestor has a data-pagelet
                    // or aria-label that matches the page, OR check that the reel card does NOT
                    // appear inside a "suggested" / "recommended" section.
                    //
                    // Facebook marks suggested reels with role="complementary" or
                    // data-pagelet="RightRail" or similar. The page's own reels are inside
                    // the main content area (role="main").
                    let el = a;
                    let isMainContent = false;
                    let isSuggested = false;
                    for (let i = 0; i < 20; i++) {
                        if (!el || !el.parentElement) break;
                        el = el.parentElement;
                        const role = (el.getAttribute("role") || "").toLowerCase();
                        const pagelet = (el.getAttribute("data-pagelet") || "").toLowerCase();
                        const ariaLabel = (el.getAttribute("aria-label") || "").toLowerCase();

                        if (role === "main") { isMainContent = true; }
                        if (pagelet.includes("rightrail") || pagelet.includes("sidebar") ||
                            ariaLabel.includes("suggested") || ariaLabel.includes("recommended") ||
                            pagelet.includes("suggested")) {
                            isSuggested = true;
                            break;
                        }
                    }

                    // If we have a username, also accept reels whose URL contains the page username
                    const hrefLower = href.toLowerCase();
                    const urlHasPage = pageUsername && hrefLower.includes("/" + pageUsername + "/");

                    // Accept if: in main content AND not suggested, OR URL explicitly has page name
                    if (isSuggested) return;
                    if (!isMainContent && !urlHasPage) return;

                    seen_ids.add(id);
                    const img = a.querySelector("img");
                    const thumb = img ? img.src : "";
                    let views = "";
                    const spans = a.querySelectorAll("span");
                    for (const span of spans) {
                        const t = (span.innerText || "").trim();
                        if (t && /^\d+(\.\d+)?[KkMm]?$/.test(t)) { views = t; break; }
                    }
                    reels.push({ id, post_url: `https://www.facebook.com/reel/${id}/`, thumb, views });
                });
                return reels;
                """
                try:
                    dom_reels = driver.execute_script(js_grid, page_username) or []
                except Exception as e:
                    print(f"Grid JS error: {e}")
                    dom_reels = []

                # NOTE: The grid-page DASH cross-check was removed.
                # Reason: the /reels grid page only auto-loads DASH manifests for the first
                # few visible reels, so filtering dom_reels by those IDs would falsely remove
                # valid reels that weren't auto-loaded. The DOM JS filter (isMainContent +
                # !isSuggested) is already the correct filter to exclude recommended reels.
                # Each reel's DASH manifest is fetched individually in Step 3 below.

                # Limit to requested count
                if max_posts and max_posts < 9999:
                    dom_reels = dom_reels[:max_posts]

                # ── Step 3: Visit each reel's own page to get the stream URL ──
                valid_reels = []
                total = len(dom_reels)

                # JS to extract video src directly from the DOM of each reel page
                _js_get_video = r"""
                var results = {stream_url: "", thumb: "", caption: ""};

                // Strategy 1: find <video> element with a src attribute
                var videos = document.querySelectorAll('video[src]');
                for (var v of videos) {
                    var s = v.src || v.getAttribute('src') || '';
                    if (s && (s.includes('.mp4') || s.includes('fbcdn') || s.includes('video'))) {
                        results.stream_url = s;
                        results.thumb = v.poster || '';
                        break;
                    }
                }

                // Strategy 2: Legacy patterns — browser_native_hd_url / playable_url
                // These are combined video+audio progressive downloads (best quality)
                if (!results.stream_url) {
                    var legacyPatterns = [
                        /"browser_native_hd_url"\s*:\s*"(https:[^"]+)"/,
                        /"playable_url_quality_hd"\s*:\s*"(https:[^"]+)"/,
                        /"browser_native_sd_url"\s*:\s*"(https:[^"]+)"/,
                        /"playable_url"\s*:\s*"(https:[^"]+\.mp4[^"]*)"/,
                        /"hd_stream_url"\s*:\s*"(https:[^"]+)"/,
                        /"sd_stream_url"\s*:\s*"(https:[^"]+)"/
                    ];
                    var scripts2 = document.querySelectorAll('script[type="application/json"]');
                    outer2: for (var sc of scripts2) {
                        var text = sc.textContent || '';
                        if (text.length < 100) continue;
                        for (var pat of legacyPatterns) {
                            var lm = text.match(pat);
                            if (lm) {
                                results.stream_url = lm[1].replace(/\\\//g, '/');
                                break outer2;
                            }
                        }
                    }
                }

                // Strategy 3: DASH base_url scan — last resort (video-only streams, no audio)
                // Only used when no combined stream found above
                if (!results.stream_url) {
                    var scripts = document.querySelectorAll('script[type="application/json"]');
                    var bestUrl = "";
                    var bestBitrate = 0;

                    function isAudioOnlyUrl(url) {
                        // Direct keyword check in URL path
                        if (url.includes('audio') || url.includes('heaac') || url.includes('_a_') || url.includes('dash_a')) return true;
                        // Decode efg param — Facebook encodes stream type there as base64 JSON
                        try {
                            var efgMatch = url.match(/[?&]efg=([^&]+)/);
                            if (efgMatch) {
                                var efgDecoded = atob(decodeURIComponent(efgMatch[1]));
                                var efgJson = JSON.parse(efgDecoded);
                                // Facebook uses "vencode_tag" for the stream type
                                var tag = (efgJson.vencode_tag || efgJson.encode_tag || '').toLowerCase();
                                // audio-only encode tags contain "audio" (e.g. dash_ln_heaac_vbr3_audio)
                                if (tag.includes('audio') && !tag.includes('video')) return true;
                            }
                        } catch(e) {}
                        return false;
                    }

                    for (var sc of scripts) {
                        var text = sc.textContent || '';
                        if (text.length < 500 || !text.includes('.mp4')) continue;

                        // Find all base_url entries that point to mp4 files
                        var re = /"base_url"\s*:\s*"(https?:[^"]+\.mp4[^"]*)"/g;
                        var m;
                        while ((m = re.exec(text)) !== null) {
                            var url = m[1].replace(/\\\//g, '/').replace(/\u0025/g, '%');
                            // Skip audio-only DASH segments (check URL and decoded efg param)
                            if (isAudioOnlyUrl(url)) continue;
                            if (!bestUrl) {
                                bestUrl = url;
                            }
                            // Pick highest bandwidth (= highest quality video)
                            var ctx = text.substring(Math.max(0, m.index - 500), Math.min(text.length, m.index + 200));
                            var bwMatch = ctx.match(/"bandwidth"\s*:\s*(\d+)/);
                            if (bwMatch) {
                                var bw = parseInt(bwMatch[1]);
                                if (bw > bestBitrate) {
                                    bestBitrate = bw;
                                    bestUrl = url;
                                }
                            }
                        }
                    }
                    if (bestUrl) {
                        results.stream_url = bestUrl;
                    }
                }

                // Thumbnail from og:image
                var og = document.querySelector('meta[property="og:image"]');
                results.thumb = og ? og.content : '';

                // Caption from og:description or page text
                var ogDesc = document.querySelector('meta[property="og:description"]');
                results.caption = ogDesc ? ogDesc.content : '';

                return results;
                """


                for i, dr in enumerate(dom_reels):
                    rid = dr["id"]
                    reel_url = dr["post_url"]
                    _progress(
                        50 + int((i / max(total, 1)) * 45),
                        f"Reel {i+1}/{total} ka stream URL nikal rahe hain..."
                    )
                    stream_url = ""
                    caption = ""
                    thumb = dr.get("thumb", "")
                    posted_at = ""
                    audio_url_reel = ""

                    try:
                        driver.get(reel_url)
                        # Wait for JS to execute and video to load
                        time.sleep(4.0)

                        # ── Primary: Always try DASH manifest first — gives both video+audio ──
                        # IMPORTANT: filter DASH results to only the current reel ID to avoid
                        # picking up recommended/autoplay reels that Facebook loads alongside.
                        src_text = driver.page_source
                        dash_found = _extract_dash_from_source(src_text)

                        def _reel_matches_dash(dash_entry: dict, reel_id: str) -> bool:
                            """Check if a DASH entry belongs to a specific reel ID."""
                            # Direct ID match
                            if str(dash_entry.get("id", "")) == str(reel_id):
                                return True
                            # Try extracting numeric video_id from video URL (encoded in efg param)
                            import base64
                            vid_url = dash_entry.get("url", "") or dash_entry.get("video_url", "")
                            try:
                                efg_m = re.search(r'[?&]efg=([^&]+)', vid_url)
                                if efg_m:
                                    efg_bytes = base64.b64decode(unquote(efg_m.group(1)) + "==")
                                    efg_json = json.loads(efg_bytes)
                                    extracted_vid_id = str(efg_json.get("video_id", ""))
                                    if extracted_vid_id and extracted_vid_id == str(reel_id):
                                        return True
                            except Exception:
                                pass
                            return False

                        # Filter: keep only DASH entries whose ID matches this reel
                        dash_for_this = [d for d in dash_found if _reel_matches_dash(d, rid)]
                        # Fallback: if no ID-matched entry, use first entry (page may not embed ID)
                        if not dash_for_this and dash_found:
                            dash_for_this = dash_found[:1]

                        if dash_for_this:
                            best = dash_for_this[0]
                            stream_url = best["url"]
                            audio_url_reel = best.get("audio_url", "")
                            if best.get("thumb"):
                                thumb = best["thumb"]
                            if best.get("caption"):
                                caption = best["caption"]
                            print(f"  Reel {rid}: DASH video={'YES' if stream_url else 'NO'} audio={'YES' if audio_url_reel else 'NO'}")

                        # ── Secondary: JavaScript DOM inspection ──
                        # Used when DASH extraction didn't find a stream (progressive MP4 fallback)
                        if not stream_url:
                            try:
                                js_result = driver.execute_script(_js_get_video) or {}
                                stream_url = (js_result.get("stream_url") or "").strip().replace("\\/", "/")
                                if js_result.get("thumb") and not thumb:
                                    thumb = js_result["thumb"]
                                if js_result.get("caption") and not caption:
                                    caption = js_result["caption"]
                                if stream_url:
                                    print(f"  Reel {rid}: JS stream found url={stream_url[:60]}")
                            except Exception as je:
                                print(f"  JS extraction error for reel {rid}: {je}")

                        # ── Tertiary: legacy pattern regex fallback ──
                        if not stream_url:
                            _video_patterns = [
                                r'"browser_native_hd_url"\s*:\s*"(https:[^"]+)"',
                                r'"browser_native_sd_url"\s*:\s*"(https:[^"]+)"',
                                r'"playable_url_quality_hd"\s*:\s*"(https:[^"]+)"',
                                r'"playable_url"\s*:\s*"(https:[^"]+\.mp4[^"]*)"',
                                r'"hd_stream_url"\s*:\s*"(https:[^"]+)"',
                                r'"sd_stream_url"\s*:\s*"(https:[^"]+)"',
                            ]
                            for pat in _video_patterns:
                                mm = re.search(pat, src_text)
                                if mm:
                                    candidate = mm.group(1).replace("\\/", "/")
                                    if not _is_audio_only_url(candidate):
                                        stream_url = candidate
                                        break

                        # ── Quaternary: wait longer then retry DASH + JS ──
                        if not stream_url:
                            time.sleep(3.0)
                            src_text2 = driver.page_source
                            dash_found2 = _extract_dash_from_source(src_text2)
                            dash_for_this2 = [d for d in dash_found2 if _reel_matches_dash(d, rid)]
                            if not dash_for_this2 and dash_found2:
                                dash_for_this2 = dash_found2[:1]
                            if dash_for_this2:
                                best2 = dash_for_this2[0]
                                stream_url = best2["url"]
                                audio_url_reel = best2.get("audio_url", "")
                                if best2.get("thumb") and not thumb:
                                    thumb = best2["thumb"]
                                if best2.get("caption") and not caption:
                                    caption = best2["caption"]
                            else:
                                try:
                                    js_result2 = driver.execute_script(_js_get_video) or {}
                                    stream_url = (js_result2.get("stream_url") or "").strip().replace("\\/", "/")
                                    if not thumb and js_result2.get("thumb"):
                                        thumb = js_result2["thumb"]
                                    if not caption and js_result2.get("caption"):
                                        caption = js_result2["caption"]
                                except Exception:
                                    pass

                        print(f"  Reel {rid}: stream_url={'YES' if stream_url else 'EMPTY'} audio={'YES' if audio_url_reel else 'NO'} url={stream_url[:60] if stream_url else ''}") 

                    except Exception as exc:
                        print(f"Reel {rid} visit error: {exc}")

                    media_item = {"type": "video", "url": stream_url, "thumb": thumb}
                    if audio_url_reel:
                        media_item["audio_url"] = audio_url_reel

                    valid_reels.append({
                        "id": rid,
                        "caption": caption or (f"Reel ({dr.get('views','')} views)" if dr.get("views") else "Facebook Reel"),
                        "media": [media_item],
                        "likes": parse_count(dr.get("views", 0)),
                        "comments": 0, "shares": 0,
                        "postedAt": posted_at,
                        "postUrl": reel_url,
                    })

            # ── Single reel page path ──
            else:
                valid_reels = []
                # Also try DASH extraction on single reel page
                dash_single = _extract_dash_from_source(driver.page_source)
                for de in dash_single:
                    if de["id"] not in seen_ids:
                        seen_ids.add(de["id"])
                        entries.append(de)

                for entry in entries:
                    media_item = {
                        "type": "video",
                        "url": entry["url"],
                        "thumb": entry.get("thumb", ""),
                    }
                    if entry.get("audio_url"):
                        media_item["audio_url"] = entry["audio_url"]
                    valid_reels.append({
                        "id": entry["id"],
                        "caption": entry["caption"] or "Facebook Reel",
                        "media": [media_item],
                        "likes": 0, "comments": 0, "shares": 0,
                        "postedAt": entry["posted_at"],
                        "postUrl": page_url,
                    })

            _progress(95, f"Results ready: 0 posts, {len(valid_reels)} reels")
            
            page_meta = {}
            try:
                page_meta = get_page_meta(driver)
            except Exception:
                pass

            return {
                "success": True,
                "page_url": page_url,
                "page_meta": page_meta,
                "posts_count": 0,
                "reels_count": len(valid_reels),
                "posts": [],
                "reels": valid_reels[:max_posts],
            }

        # Get page meta
        _progress(18, "Page meta extract ho rahi hai...")
        page_meta = get_page_meta(driver)

        # Visit /about for extra details
        _progress(22, "About page se details le rahe hain...")
        try:
            driver.get(page_url.rstrip("/") + "/about")
            time.sleep(4)
            about_src = driver.page_source

            if not page_meta.get("followers"):
                for pat in [r'"follower_count":(\d+)', r'"fan_count":(\d+)', r'"global_followers_count":(\d+)']:
                    m = re.search(pat, about_src)
                    if m:
                        page_meta["followers"] = int(m.group(1))
                        break

            # DOM fallback for followers text
            if not page_meta.get("followers"):
                try:
                    for el in driver.find_elements(By.CSS_SELECTOR, "span, div")[:400]:
                        t = el.text.strip()
                        m = re.match(r'^([\d,\.]+[KkMm]?)\s+followers?', t, re.IGNORECASE)
                        if m:
                            page_meta["followers"] = parse_count(m.group(1))
                            break
                except Exception:
                    pass

            # About text + contact info from JSON
            if not page_meta.get("about"):
                for pat in [
                    r'"biography":\{"text":"((?:[^"\\]|\\.)+)"',
                    r'"general_info":\{"text":"((?:[^"\\]|\\.)+)"',
                    r'"blurb":"((?:[^"\\]|\\.)+)"',
                ]:
                    m = re.search(pat, about_src)
                    if m:
                        try:
                            page_meta["about"] = m.group(1).encode('raw_unicode_escape').decode('unicode_escape')
                        except Exception:
                            page_meta["about"] = m.group(1)
                        break

            for key, pat in [
                ("phone",    r'"phone":"([^"]+)"'),
                ("website",  r'"website":"([^"]+)"'),
                ("address",  r'"single_line_address":"([^"]+)"'),
                ("email",    r'"email":"([^"]+)"'),
            ]:
                if not page_meta.get(key):
                    m = re.search(pat, about_src, re.DOTALL)
                    if m:
                        page_meta[key] = m.group(1)

            # External links from about page DOM
            try:
                import urllib.parse
                links = driver.find_elements(By.TAG_NAME, "a")
                external_links = []
                for a in links:
                    href = a.get_attribute("href") or ""
                    txt = a.text.strip()
                    if "l.facebook.com/l.php" in href:
                        parsed = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
                        real = parsed.get("u", [""])[0]
                        if real:
                            external_links.append({"text": txt or real, "url": real})
                    elif href.startswith("http") and "facebook.com" not in href:
                        if href not in [x["url"] for x in external_links]:
                            external_links.append({"text": txt or href, "url": href})
                if external_links:
                    page_meta["links"] = external_links
            except Exception:
                pass
        except Exception:
            pass

        # Skip separate /reels page — capture everything from main feed directly
        # Main feed already contains posts, reels, images, videos in order
        reels_video_urls = []  # no pre-seeding from separate page

        # Navigate to main posts page
        _progress(40, "Main posts page load ho rahi hai...")
        driver.get(page_url)
        time.sleep(5)

        all_posts = []
        seen_ids = set()

        # Pre-seed with reels
        for rv in reels_video_urls:
            if rv["id"] not in seen_ids:
                seen_ids.add(rv["id"])
                all_posts.append({
                    "id": rv["id"],
                    "caption": rv["caption"],
                    "media": [{"type": "video", "url": rv["url"], "thumb": rv["thumb"]}],
                    "likes": 0, "comments": 0, "shares": 0,
                    "postedAt": rv["posted_at"],
                    "postUrl": "",
                })

        # Scroll rounds:
        # - User specified scroll_rounds is the minimum
        # - For max_posts >= 9999 (All), scroll_rounds already set to 200 by caller
        # - For date_from, ensure at least 50 rounds
        # - Otherwise: max(scroll_rounds, max_posts // 5) but at least 5
        if max_posts >= 9999:
            actual_scroll_rounds = scroll_rounds  # already 200
        else:
            actual_scroll_rounds = max(scroll_rounds, max(5, max_posts // 5))

        if _date_from:
            actual_scroll_rounds = max(actual_scroll_rounds, 50)

        consecutive_no_new = 0
        total_past_range = 0

        for round_num in range(actual_scroll_rounds):
            pct = 50 + int((round_num / max(actual_scroll_rounds, 1)) * 35)
            src = driver.page_source

            # Source-based JSON extraction
            src_posts = extract_from_source(src)

            # DOM-based extraction
            dom_posts = extract_from_dom(driver)

            # Build ID-based lookup from source posts for accurate date enrichment
            src_by_id = {p["id"]: p for p in src_posts}

            # Enrich DOM posts dates: prefer src_by_id match, then _parse_fb_date
            for p in dom_posts:
                if not p["postedAt"]:
                    # Try matching by ID from source
                    if p["id"] in src_by_id and src_by_id[p["id"]].get("postedAt"):
                        p["postedAt"] = src_by_id[p["id"]]["postedAt"]
                # If postedAt is still a human string (not YYYY-MM-DD), parse it
                if p["postedAt"] and not re.match(r'\d{4}-\d{2}-\d{2}', p["postedAt"]):
                    p["postedAt"] = _parse_fb_date(p["postedAt"])
            reels_by_id = {p["id"]: p for p in all_posts if p.get("media") and any(m.get("type") == "video" for m in p["media"])}

            new_count = 0
            round_past_range = 0  # posts older than date_from this round
            round_future = 0      # posts newer than date_to this round (skip, keep scrolling)

            # Merge DOM posts
            for p in dom_posts:
                if p["id"] not in seen_ids:
                    seen_ids.add(p["id"])
                    # Enrich with source data
                    if p["id"] in src_by_id:
                        sp = src_by_id[p["id"]]
                        if not p["postedAt"] and sp["postedAt"]:
                            p["postedAt"] = sp["postedAt"]
                        if p["likes"] == 0 and sp["likes"]:
                            p["likes"] = sp["likes"]
                        if p["comments"] == 0 and sp["comments"]:
                            p["comments"] = sp["comments"]
                        if not p["postUrl"] and sp["postUrl"]:
                            p["postUrl"] = sp["postUrl"]
                        if not any(m["type"] == "video" for m in p["media"]):
                            for m in sp.get("media", []):
                                if m["type"] == "video" and not any(x["url"] == m["url"] for x in p["media"]):
                                    p["media"].insert(0, m)
                    # Inject reel video if matching
                    if p["id"] in reels_by_id and not any(m["type"] == "video" for m in p["media"]):
                        p["media"] = reels_by_id[p["id"]]["media"] + p["media"]

                    # Date range check
                    if _past_range(p.get("postedAt", "")):
                        round_past_range += 1
                        continue  # too old — skip
                    if _future_of_range(p.get("postedAt", "")):
                        round_future += 1
                        continue  # too new — skip but keep scrolling
                    if not _in_range(p.get("postedAt", "")):
                        continue  # out of range

                    new_count += 1
                    all_posts.append(p)
                else:
                    existing = next((x for x in all_posts if x["id"] == p["id"]), None)
                    if existing:
                        if not existing.get("caption") and p.get("caption"):
                            existing["caption"] = p["caption"]
                        if existing.get("likes", 0) == 0 and p.get("likes", 0) > 0:
                            existing["likes"] = p["likes"]

            # Add source-only posts not in DOM
            for p in src_posts:
                if p["id"] not in seen_ids and (p.get("caption") or p.get("media")):
                    seen_ids.add(p["id"])
                    if _past_range(p.get("postedAt", "")):
                        round_past_range += 1
                        continue
                    if _future_of_range(p.get("postedAt", "")):
                        round_future += 1
                        continue
                    if not _in_range(p.get("postedAt", "")):
                        continue
                    new_count += 1
                    all_posts.append(p)

            total_past_range += round_past_range

            date_range_label = ""
            if _date_from or _date_to:
                date_range_label = f" | range: {len(all_posts)}, old: {total_past_range}"

            _progress(pct, f"Scroll {round_num + 1}/{actual_scroll_rounds} — {len(all_posts)} posts mile{date_range_label}...")

            # Early stop when scrolled past date_from
            if total_past_range >= 5 and _date_from:
                _progress(88, f"Date range boundary reached — {len(all_posts)} posts")
                break

            # Stop if we have enough posts
            if len(all_posts) >= max_posts:
                break

            # Track if no new posts appeared
            if new_count == 0:
                consecutive_no_new += 1
                no_new_limit = 15 if max_posts >= 9999 else 5

                # At 3 stuck rounds: scroll to top and back
                if consecutive_no_new == 3:
                    try:
                        driver.execute_script("window.scrollTo(0, 0)")
                        time.sleep(3)
                        driver.execute_script("window.scrollTo(0, document.body.scrollHeight)")
                        time.sleep(4)
                    except Exception:
                        pass

                # At 5 stuck rounds: try "See more posts" button
                if consecutive_no_new == 5:
                    try:
                        for btn_text in ["See more posts", "See More", "Load more", "More posts", "Show more"]:
                            btns = driver.find_elements(By.XPATH,
                                f"//span[contains(translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'{btn_text.lower()}')]")
                            if btns:
                                driver.execute_script("arguments[0].click()", btns[0])
                                time.sleep(5)
                                break
                    except Exception:
                        pass

                if consecutive_no_new >= no_new_limit:
                    _progress(88, f"Page end reached — {len(all_posts)} posts total")
                    break
            else:
                consecutive_no_new = 0

            # Scroll for more content
            _scroll_page(driver, pause=3.0)
            if round_num == 0:
                time.sleep(2)

        # Also do a final pass with videos page — already handled inside _get_video_urls_from_reels
        # But do a quick DOM video scan on the current page state
        _progress(88, "Video elements check ho rahi hain...")
        try:
            vids = driver.find_elements(By.TAG_NAME, "video")
            for vid in vids:
                src    = vid.get_attribute("src") or ""
                poster = vid.get_attribute("poster") or ""
                if not src or not src.startswith("http"):
                    continue
                # Try to match this video to an existing post
                matched = False
                for post in all_posts:
                    if not any(m.get("type") == "video" for m in post.get("media", [])):
                        # Post has no video yet — attach this one
                        post["media"].insert(0, {"type": "video", "url": src, "thumb": poster})
                        matched = True
                        break
                if not matched:
                    # Create a standalone video post
                    vid_id = hashlib.md5(src.encode()).hexdigest()[:12]
                    if vid_id not in seen_ids:
                        seen_ids.add(vid_id)
                        all_posts.append({
                            "id": vid_id,
                            "caption": "",
                            "media": [{"type": "video", "url": src, "thumb": poster}],
                            "likes": 0, "comments": 0, "shares": 0,
                            "postedAt": "", "postUrl": "",
                        })
        except Exception:
            pass

        # ── Separate posts and reels ─────────────────────────────────────
        # Since we capture everything from main feed:
        # - reel = post whose only/primary media is video (and postUrl has /reel/)
        # - post = everything else (images, text, mixed)
        valid_posts = []
        valid_reels = []

        for p in all_posts:
            if not (p.get("caption") or p.get("media")):
                continue

            post_url_str = p.get("postUrl", "")
            has_video = any(m.get("type") == "video" for m in p.get("media", []))
            has_image = any(m.get("type") == "image" for m in p.get("media", []))
            is_reel_url = "/reel" in post_url_str or "/videos/" in post_url_str

            # Classify as reel if: has video AND (reel URL OR only video, no image)
            is_reel = has_video and (is_reel_url or (not has_image and has_video))

            if is_reel:
                valid_reels.append(p)
            else:
                valid_posts.append(p)

        _progress(95, f"Results ready: {len(valid_posts)} posts, {len(valid_reels)} reels")

        # Sort both by date descending
        def sort_key(p):
            return p.get("postedAt") or ""

        valid_posts.sort(key=sort_key, reverse=True)
        valid_reels.sort(key=sort_key, reverse=True)

        return {
            "success": True,
            "page_url": page_url,
            "page_meta": page_meta,
            "posts_count": len(valid_posts),
            "reels_count": len(valid_reels),
            "posts": valid_posts[:max_posts],
            "reels": valid_reels[:max_posts],
        }

    except Exception as e:
        import traceback
        return {
            "error": "scraper_exception",
            "message": str(e),
            "traceback": traceback.format_exc(),
        }
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
            # Force-kill any leftover chromedriver processes from this session
            try:
                import subprocess, os, signal
                # Get our own PID to avoid killing unrelated processes
                our_pid = os.getpid()
                result = subprocess.run(
                    ["pgrep", "-f", "chromedriver"],
                    capture_output=True, text=True
                )
                for pid_str in result.stdout.strip().split("\n"):
                    pid_str = pid_str.strip()
                    if pid_str and pid_str.isdigit():
                        pid = int(pid_str)
                        if pid != our_pid:
                            try:
                                os.kill(pid, signal.SIGTERM)
                            except Exception:
                                pass
            except Exception:
                pass
