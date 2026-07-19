from .base import BaseDetector
from .login_detector import (
    LoginRequiredDetector,
    CloudflareDetector,
    CaptchaDetector,
    JavaScriptRequiredDetector,
)
from .wordpress_detector import WordPressDetector
