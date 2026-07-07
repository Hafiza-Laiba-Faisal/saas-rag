"""
Auth routes — Facebook login, cookie management.
No scraping logic here.
"""
from fastapi import APIRouter, HTTPException
from schemas.scraper import SetCookiesRequest
from session.browser_session import browser_session
from cookies.cookie_store import CookieStore

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/set-cookies")
def set_cookies(req: SetCookiesRequest):
    cookies = CookieStore.parse_cookie_string(req.cookies)
    c_user = cookies.get("c_user", "")
    xs     = cookies.get("xs", "")
    if not c_user or not xs:
        raise HTTPException(400, "c_user ya xs cookie nahi mili — Facebook pe logged in ho?")
    result = browser_session.set_cookies({
        "c_user": c_user, "xs": xs,
        "datr": cookies.get("datr", ""),
        "sb":   cookies.get("sb", ""),
        "fr":   cookies.get("fr", ""),
    })
    return {"message": "Cookies set aur save ho gayi!", "c_user": c_user[:6] + "***"}


@router.post("/fb-login")
def fb_login(timeout: int = 300):
    return browser_session.start_browser_login(timeout)


@router.get("/fb-status")
def fb_status():
    return browser_session.get_status()


@router.post("/fb-cancel")
def fb_cancel():
    return browser_session.cancel_login()


@router.post("/fb-logout")
def fb_logout():
    return browser_session.logout()


@router.get("/fb-cookies-from-profile")
def fb_cookies_from_profile(profile: str = "Default"):
    result = browser_session.get_cookies_from_chrome_profile(profile)
    if "error" in result:
        raise HTTPException(400, result["error"])
    return {"cookies": result}
