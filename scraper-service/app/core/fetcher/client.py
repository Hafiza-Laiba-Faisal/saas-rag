import httpx

async_client: httpx.AsyncClient | None = None

def get_async_client() -> httpx.AsyncClient:
    global async_client
    if async_client is None:
        async_client = httpx.AsyncClient(http2=False, follow_redirects=True)
    return async_client
