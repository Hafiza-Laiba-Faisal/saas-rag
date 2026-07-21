import asyncio
import httpx

_async_client: httpx.AsyncClient | None = None
_loop_id: int | None = None

def get_async_client() -> httpx.AsyncClient:
    global _async_client, _loop_id
    try:
        current_loop = asyncio.get_running_loop()
        current_id = id(current_loop)
    except RuntimeError:
        current_loop = None
        current_id = None
    if _async_client is None or current_id != _loop_id:
        _async_client = httpx.AsyncClient(http2=False, follow_redirects=True, timeout=httpx.Timeout(30.0))
        _loop_id = current_id
    return _async_client
