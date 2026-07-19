"""
Detects Facebook login wall — does NOT attempt to bypass it.
"""

from __future__ import annotations
from .base import BaseDetector


class LoginRequiredDetector(BaseDetector):
    name = "login_required"

    def detect(self, html: str, url: str = "") -> bool:
        url_lower = url.lower()
        if "login" in url_lower:
            return True
        html_lower = html.lower()
        has_login_form = 'id="email"' in html_lower
        has_signup     = "create new account" in html_lower
        is_short       = len(html) < 30_000
        return (has_login_form and has_signup) or (is_short and "log in" in html_lower and has_signup)


class CloudflareDetector(BaseDetector):
    name = "cloudflare"

    def detect(self, html: str, url: str = "") -> bool:
        markers = [
            "cf-browser-verification",
            "cloudflare ray id",
            "checking your browser",
            "just a moment",
            "_cf_chl_opt",
        ]
        lower = html.lower()
        return any(m in lower for m in markers)


class CaptchaDetector(BaseDetector):
    name = "captcha"

    def detect(self, html: str, url: str = "") -> bool:
        markers = [
            "recaptcha",
            "g-recaptcha",
            "hcaptcha",
            "captcha-box",
            "security check",
        ]
        lower = html.lower()
        return any(m in lower for m in markers)


class JavaScriptRequiredDetector(BaseDetector):
    name = "javascript_required"

    def detect(self, html: str, url: str = "") -> bool:
        markers = [
            "enable javascript",
            "javascript is disabled",
            "noscript",
        ]
        lower = html.lower()
        return any(m in lower for m in markers) and len(html) < 5_000
