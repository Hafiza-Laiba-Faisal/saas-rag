"""Request logging middleware."""
from __future__ import annotations
import time
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from utils.logger import get_logger
from utils.request_id import generate_request_id

logger = get_logger(__name__)

class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("X-Request-ID") or generate_request_id()
        start = time.monotonic()
        logger.info(
            "Request started",
            extra={"request_id": request_id, "method": request.method, "path": request.url.path},
        )
        response = await call_next(request)
        processing_time_ms = (time.monotonic() - start) * 1000
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "Request completed",
            extra={"request_id": request_id, "status_code": response.status_code, "processing_time_ms": round(processing_time_ms, 2)},
        )
        return response
