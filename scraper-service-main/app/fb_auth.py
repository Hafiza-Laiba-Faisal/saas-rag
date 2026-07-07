"""
Facebook Auth — session cookies management.

Flow:
1. On startup, load saved cookies from DB (persistent login).
2. User can trigger a visible Chrome window to log in fresh.
3. On success, cookies are saved to DB — survive server restarts.
4. /auth/fb-status returns saved cookies immediately if already logged in.
"""

import time
import threading
from typing import Optional

from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager


# ── Global login session state ────────────────────────────────────────────────

class LoginSession:
    def __init__(self):
        self.driver: Optional[webdriver.Chrome] = None
        self.status: str = "idle"   # idle | waiting | success | timeout | error
        self.cookies: dict = {}
        self.error: str = ""
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None

    def is_active(self) -> bool:
        return self.status in ("waiting",)


_session = LoginSession()


def _load_saved_cookies():
    """Load cookies from DB on startup so user stays logged in."""
    try:
        from database import load_fb_cookies
        saved = load_fb_cookies()
        if saved.get("c_user") and saved.get("xs"):
            _session.cookies = saved
            _session.status = "success"
    except Exception:
        pass


# Load on module import
_load_saved_cookies()


def _save_cookies(cookies: dict):
    """Persist cookies to DB."""
    try:
        from database import save_fb_cookies
        save_fb_cookies(cookies)
    except Exception:
        pass


def start_login(timeout_seconds: int = 900) -> dict:
    """
    Open a real visible Chrome window to facebook.com.
    Returns immediately. Poll /auth/fb-status to check progress.
    If already logged in (saved cookies), returns success immediately.
    """
    global _session

    # Already logged in — no need to open browser
    if _session.status == "success" and _session.cookies.get("c_user"):
        return {
            "status": "already_logged_in",
            "message": "Aap pehle se logged in hain — koi action nahi chahiye",
            "c_user": _session.cookies["c_user"][:6] + "***",
        }

    with _session._lock:
        if _session.is_active():
            return {"status": "already_active", "message": "Login window already open"}
        _session.status = "waiting"
        _session.cookies = {}
        _session.error = ""

    def _run():
        driver = None
        try:
            opts = ChromeOptions()
            opts.add_argument("--window-size=1280,800")
            opts.add_argument("--disable-blink-features=AutomationControlled")
            opts.add_experimental_option("excludeSwitches", ["enable-automation"])
            opts.add_experimental_option("useAutomationExtension", False)
            opts.add_argument(
                "user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
            service = ChromeService(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=opts)
            driver.execute_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
            _session.driver = driver
            driver.get("https://www.facebook.com/")

            deadline = time.time() + timeout_seconds
            logged_in = False

            while time.time() < deadline:
                time.sleep(2)
                try:
                    _ = driver.current_url  # check browser still open
                except Exception:
                    _session.status = "error"
                    _session.error = "Browser band ho gaya — dobara try karo"
                    return

                try:
                    raw_cookies = driver.get_cookies()
                    cookie_dict = {c["name"]: c["value"] for c in raw_cookies}
                    current_url = driver.current_url

                    if "c_user" in cookie_dict and cookie_dict["c_user"]:
                        new_cookies = {
                            "c_user": cookie_dict.get("c_user", ""),
                            "xs":     cookie_dict.get("xs", ""),
                            "datr":   cookie_dict.get("datr", ""),
                            "sb":     cookie_dict.get("sb", ""),
                            "fr":     cookie_dict.get("fr", ""),
                        }
                        _session.cookies = new_cookies
                        _session.status = "success"
                        _save_cookies(new_cookies)  # persist to DB
                        logged_in = True
                        break

                    # Fallback: on feed but c_user not set yet
                    on_feed = (
                        "facebook.com" in current_url and
                        "login" not in current_url and
                        "checkpoint" not in current_url and
                        current_url != "https://www.facebook.com/"
                    )
                    if on_feed and "xs" in cookie_dict:
                        time.sleep(4)
                        raw_cookies = driver.get_cookies()
                        cookie_dict = {c["name"]: c["value"] for c in raw_cookies}
                        if "c_user" in cookie_dict and cookie_dict["c_user"]:
                            new_cookies = {
                                "c_user": cookie_dict.get("c_user", ""),
                                "xs":     cookie_dict.get("xs", ""),
                                "datr":   cookie_dict.get("datr", ""),
                                "sb":     cookie_dict.get("sb", ""),
                                "fr":     cookie_dict.get("fr", ""),
                            }
                            _session.cookies = new_cookies
                            _session.status = "success"
                            _save_cookies(new_cookies)
                            logged_in = True
                            break
                except Exception:
                    pass

            if not logged_in and _session.status != "error":
                _session.status = "timeout"
                _session.error = f"Login timeout after {timeout_seconds}s"

        except Exception as e:
            _session.status = "error"
            _session.error = str(e)
        finally:
            if driver:
                try:
                    time.sleep(2)
                    driver.quit()
                except Exception:
                    pass
            _session.driver = None

    _session._thread = threading.Thread(target=_run, daemon=True)
    _session._thread.start()
    return {"status": "waiting", "message": "Chrome window khul raha hai — Facebook pe login karo"}


def get_cookies_from_profile(profile_dir: str = "Default") -> dict:
    """
    Extract cookies from an existing Chrome profile (Chrome must be closed first).
    On success, cookies are saved to DB.
    """
    import os
    chrome_user_data = os.path.expanduser("~/.config/google-chrome")

    opts = ChromeOptions()
    opts.add_argument(f"--user-data-dir={chrome_user_data}")
    opts.add_argument(f"--profile-directory={profile_dir}")
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)

    driver = None
    try:
        service = ChromeService(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=opts)
        driver.execute_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        driver.get("https://www.facebook.com/")
        time.sleep(4)

        raw_cookies = driver.get_cookies()
        cookie_dict = {c["name"]: c["value"] for c in raw_cookies}

        if "c_user" not in cookie_dict or not cookie_dict["c_user"]:
            return {"error": f"Profile '{profile_dir}' mein Facebook login nahi mila. Chrome band karke try karo."}

        new_cookies = {
            "c_user": cookie_dict.get("c_user", ""),
            "xs":     cookie_dict.get("xs", ""),
            "datr":   cookie_dict.get("datr", ""),
            "sb":     cookie_dict.get("sb", ""),
            "fr":     cookie_dict.get("fr", ""),
        }
        _session.cookies = new_cookies
        _session.status = "success"
        _save_cookies(new_cookies)  # persist to DB
        return new_cookies

    except Exception as e:
        err = str(e)
        if "user data directory is already in use" in err or "DevToolsActivePort" in err:
            return {"error": "Chrome pehle se open hai — band karo phir try karo, ya 'Login' button use karo"}
        return {"error": err}
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


def get_login_status() -> dict:
    """Poll to check login progress. Returns saved cookies immediately if already logged in."""
    return {
        "status":  _session.status,
        "cookies": _session.cookies if _session.status == "success" else {},
        "error":   _session.error,
    }


def set_cookies_manually(cookies: dict) -> dict:
    """Set cookies manually (from console snippet) and persist them."""
    if not cookies.get("c_user") or not cookies.get("xs"):
        return {"error": "c_user ya xs nahi mili"}
    _session.cookies = cookies
    _session.status = "success"
    _save_cookies(cookies)
    return {"ok": True}


def logout() -> dict:
    """Clear saved cookies and reset session."""
    global _session
    try:
        if _session.driver:
            _session.driver.quit()
    except Exception:
        pass
    _session.status = "idle"
    _session.cookies = {}
    _session.error = ""
    try:
        from database import clear_fb_cookies
        clear_fb_cookies()
    except Exception:
        pass
    return {"status": "logged_out"}


def cancel_login() -> dict:
    """Close the login browser window without clearing saved cookies."""
    global _session
    try:
        if _session.driver:
            _session.driver.quit()
    except Exception:
        pass
    # Only reset if we were in 'waiting' state (not if already logged in)
    if _session.status == "waiting":
        _session.status = "idle"
        _session.error = ""
    return {"status": "cancelled"}
