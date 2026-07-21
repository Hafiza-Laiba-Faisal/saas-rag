from fastapi import APIRouter, Query
from core.logs import in_memory_handler

router = APIRouter(tags=["logs"])


@router.get("/logs", summary="Return last N log lines from in-memory buffer")
def get_logs(lines: int = Query(default=50, ge=1, le=500)):
    return {"logs": in_memory_handler.get_logs(n=lines)}
