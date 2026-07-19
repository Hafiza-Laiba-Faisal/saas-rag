"""
Proxy routes — media streaming and DASH video download.
No scraping logic. Pure HTTP proxying.
"""
from __future__ import annotations
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from config.settings import FB_ALLOWED_CDN_DOMAINS, STREAM_CHUNK_SIZE
from utils.media import detect_content_type, sanitize_filename
from session.browser_session import browser_session

router = APIRouter(tags=["proxy"])


# ── Media stream proxy ────────────────────────────────────────────────────────

@router.get("/proxy/media")
def proxy_media(url: str = Query(...)):
    import requests
    url = url.replace("\\/", "/").replace("\\u002F", "/")
    if not url.startswith(("http://", "https://")):
        raise HTTPException(400, "Invalid URL")
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 Chrome/124.0.0.0 Safari/537.36",
            "Referer":    "https://www.facebook.com/",
            "Accept":     "*/*",
        }
        cookies = browser_session.active_cookies
        if cookies:
            from cookies.cookie_store import CookieStore
            headers["Cookie"] = CookieStore.export_cookie_string(cookies)

        r = requests.get(url, headers=headers, stream=True, timeout=60)
        r.raise_for_status()
        ct = detect_content_type(url, r.headers.get("Content-Type", ""))
        resp_headers = {"Access-Control-Allow-Origin": "*", "Cache-Control": "public, max-age=3600"}
        if "Content-Length" in r.headers:
            resp_headers["Content-Length"] = r.headers["Content-Length"]
        return StreamingResponse(r.iter_content(STREAM_CHUNK_SIZE), media_type=ct, headers=resp_headers)
    except Exception as e:
        raise HTTPException(502, f"Proxy error: {e}")


# ── Download with optional DASH merge ────────────────────────────────────────

@router.get("/proxy-download")
async def proxy_download(
    url:       str = Query(...),
    audio_url: str = Query(""),
    filename:  str = Query("media"),
):
    import httpx
    from urllib.parse import urlparse
    if not url.startswith("http"):
        raise HTTPException(400, "Invalid URL")
    domain = urlparse(url).netloc.lower()
    if not any(domain.endswith(d) for d in FB_ALLOWED_CDN_DOMAINS):
        raise HTTPException(403, "Only Facebook CDN URLs allowed")

    cookies = browser_session.active_cookies
    from cookies.cookie_store import CookieStore
    req_headers = {
        "User-Agent": "Mozilla/5.0 Chrome/124.0.0.0 Safari/537.36",
        "Referer":    "https://www.facebook.com/",
        "Accept":     "*/*",
    }
    if cookies:
        req_headers["Cookie"] = CookieStore.export_cookie_string(cookies)

    safe_fn = sanitize_filename(filename, "reel") + ".mp4"

    # DASH merge mode
    if audio_url and audio_url.startswith("http"):
        import subprocess, tempfile, os, concurrent.futures, requests as req_lib

        def fetch_tmp(src, suf):
            r = req_lib.get(src, headers=req_headers, timeout=60, stream=True)
            r.raise_for_status()
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suf)
            for chunk in r.iter_content(65536):
                tmp.write(chunk)
            tmp.close()
            return tmp.name

        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
                v_tmp = ex.submit(fetch_tmp, url, "_v.mp4").result()
                a_tmp = ex.submit(fetch_tmp, audio_url, "_a.mp4").result()
            out_tmp = tempfile.NamedTemporaryFile(delete=False, suffix="_merged.mp4")
            out_tmp.close()
            res = subprocess.run(
                ["ffmpeg", "-y", "-i", v_tmp, "-i", a_tmp,
                 "-c:v", "copy", "-c:a", "aac", "-movflags", "+faststart", out_tmp.name],
                capture_output=True, timeout=120,
            )
            os.unlink(v_tmp); os.unlink(a_tmp)
            if res.returncode != 0:
                raise HTTPException(500, f"ffmpeg failed: {res.stderr.decode()[-300:]}")
            fsize = os.path.getsize(out_tmp.name)

            def iter_merged():
                try:
                    with open(out_tmp.name, "rb") as f:
                        while chunk := f.read(65536):
                            yield chunk
                finally:
                    try: os.unlink(out_tmp.name)
                    except Exception: pass

            return StreamingResponse(iter_merged(), media_type="video/mp4", headers={
                "Content-Disposition": f'attachment; filename="{safe_fn}"',
                "Content-Length": str(fsize), "Access-Control-Allow-Origin": "*",
            })
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(502, f"DASH merge error: {e}")

    # Simple stream
    ct = detect_content_type(url)

    async def stream():
        async with httpx.AsyncClient(follow_redirects=True, timeout=60.0) as client:
            async with client.stream("GET", url, headers=req_headers) as resp:
                if resp.status_code < 400:
                    async for chunk in resp.aiter_bytes(65536):
                        yield chunk

    return StreamingResponse(stream(), media_type=ct, headers={
        "Content-Disposition": f'attachment; filename="{safe_fn}"',
        "Access-Control-Allow-Origin": "*",
    })
