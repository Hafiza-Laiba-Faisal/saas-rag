import httpx

async_client: httpx.AsyncClient | None = None

def get_async_client() -> httpx.AsyncClient:
    global async_client
    if async_client is None:
        raise RuntimeError("AsyncClient not initialized. Check app lifespan.")
    return async_client
