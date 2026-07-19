"""
Central retry strategy.
Supports: exponential backoff, configurable count, jitter.
"""

from __future__ import annotations
import time
import random
import logging
from typing import Callable, TypeVar

log = logging.getLogger(__name__)
T = TypeVar("T")


class RetryPolicy:
    def __init__(
        self,
        max_attempts: int = 3,
        base_delay:   float = 1.0,
        max_delay:    float = 30.0,
        backoff:      float = 2.0,
        jitter:       bool  = True,
        exceptions:   tuple = (Exception,),
    ):
        self.max_attempts = max_attempts
        self.base_delay   = base_delay
        self.max_delay    = max_delay
        self.backoff      = backoff
        self.jitter       = jitter
        self.exceptions   = exceptions

    def execute(self, fn: Callable[[], T], label: str = "") -> T:
        last_exc: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                return fn()
            except self.exceptions as exc:
                last_exc = exc
                if attempt == self.max_attempts:
                    break
                delay = min(self.base_delay * (self.backoff ** (attempt - 1)), self.max_delay)
                if self.jitter:
                    delay *= (0.5 + random.random() * 0.5)
                log.warning(
                    "Retry %d/%d for %s after %.1fs — %s",
                    attempt, self.max_attempts, label or fn.__name__, delay, exc,
                )
                time.sleep(delay)
        raise last_exc  # type: ignore[misc]


# Default policies
DEFAULT_RETRY   = RetryPolicy(max_attempts=3, base_delay=1.0)
AGGRESSIVE_RETRY = RetryPolicy(max_attempts=5, base_delay=2.0, max_delay=60.0)
NO_RETRY        = RetryPolicy(max_attempts=1)
