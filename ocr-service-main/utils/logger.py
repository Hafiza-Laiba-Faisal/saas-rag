"""Structured JSON logging factory for the OCR service.

Usage::

    from utils.logger import get_logger

    logger = get_logger(__name__)
    logger.info("Processing started", extra={"request_id": "abc-123"})
"""

from __future__ import annotations

import logging

from pythonjsonlogger.jsonlogger import JsonFormatter

from config.settings import get_settings


class _OCRJsonFormatter(JsonFormatter):
    """JsonFormatter subclass that renames the standard fields to the
    canonical names required by the OCR service log schema.

    Output fields (order is advisory for readability):
        timestamp  – ISO-8601 wall-clock time of the log record
        level      – uppercased severity (INFO, ERROR, …)
        logger     – dotted logger name
        request_id – optional correlation ID (forwarded via ``extra``)
        message    – the rendered log message
    """

    def add_fields(
        self,
        log_record: dict,
        record: logging.LogRecord,
        message_dict: dict,
    ) -> None:
        super().add_fields(log_record, record, message_dict)

        # Normalise field names to the OCR service schema
        log_record["timestamp"] = log_record.pop("asctime", None) or self.formatTime(record)
        log_record["level"] = log_record.pop("levelname", record.levelname)
        log_record["logger"] = log_record.pop("name", record.name)

        # request_id is optional — keep empty string rather than omitting
        log_record.setdefault("request_id", "")


def get_logger(name: str) -> logging.Logger:
    """Return a named :class:`logging.Logger` configured with JSON output.

    The log level is read from :func:`config.settings.get_settings` so
    that the same environment variable / .env override controls all
    loggers created by this factory.

    Calling this function multiple times with the same *name* is safe:
    handlers are not added twice.

    Args:
        name: Dotted logger name, typically ``__name__``.

    Returns:
        A configured :class:`logging.Logger` instance.
    """
    settings = get_settings()
    level = settings.log_level

    logger = logging.getLogger(name)

    # Avoid duplicate handlers if get_logger is called more than once
    # with the same name (e.g. during tests or module re-imports).
    if logger.handlers:
        logger.setLevel(level)
        return logger

    handler = logging.StreamHandler()
    formatter = _OCRJsonFormatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(level)

    # Prevent log records from propagating to the root logger's handlers
    # (avoids duplicate output when the root logger also has handlers).
    logger.propagate = False

    return logger
