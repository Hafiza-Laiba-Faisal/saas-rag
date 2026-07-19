"""
Browser session manager — wraps fb_auth.py as a service.
Provides a clean interface so routes never touch fb_auth._session directly.
Future: replace with a pool-based session manager.
"""

from __future__ import annotations
from typing import Optional


class BrowserSessionService:
    """
    Facade over fb_auth module.
    All auth routes use this instead of importing fb_auth directly.
    """

    # ── Login flows ───────────────────────────────────────────────────────────

    def start_browser_login(self, timeout: int = 300) -> dict:
        from fb_auth import start_login
        return start_login(timeout_seconds=timeout)

    def get_status(self) -> dict:
        from fb_auth import get_login_status
        return get_login_status()

    def cancel_login(self) -> dict:
        from fb_auth import cancel_login
        return cancel_login()

    def logout(self) -> dict:
        from fb_auth import logout
        return logout()

    def set_cookies(self, cookies: dict) -> dict:
        from fb_auth import set_cookies_manually
        return set_cookies_manually(cookies)

    def get_cookies_from_chrome_profile(self, profile: str = "Default") -> dict:
        from fb_auth import get_cookies_from_profile
        return get_cookies_from_profile(profile)

    # ── Session state ─────────────────────────────────────────────────────────

    @property
    def is_logged_in(self) -> bool:
        from fb_auth import _session
        return _session.status == "success" and bool(_session.cookies.get("c_user"))

    @property
    def active_cookies(self) -> dict:
        from fb_auth import _session
        return _session.cookies if self.is_logged_in else {}


# Module-level service instance
browser_session = BrowserSessionService()
