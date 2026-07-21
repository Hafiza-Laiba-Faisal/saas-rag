from __future__ import annotations
import logging
from collections import deque
from datetime import datetime, timezone
from typing import Any


class InMemoryLogHandler(logging.Handler):
    _records: deque[dict[str, Any]]

    def __init__(self, maxlen: int = 1000):
        super().__init__()
        self._records = deque(maxlen=maxlen)

    def emit(self, record: logging.LogRecord):
        self._records.append({
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level":     record.levelname,
            "name":      record.name,
            "message":   record.getMessage(),
        })

    def get_logs(self, n: int = 50) -> list[dict[str, Any]]:
        return list(self._records)[-n:]


in_memory_handler = InMemoryLogHandler(maxlen=1000)
