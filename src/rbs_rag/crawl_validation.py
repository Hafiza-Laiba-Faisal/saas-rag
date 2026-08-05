"""
Automated validation for crawl output quality.

Checks:
- Missing titles/metadata
- Broken image URLs
- Duplicate chunks in Qdrant
"""
from __future__ import annotations
import asyncio
import json
import logging
from pathlib import Path
from typing import Any
from datetime import datetime

logger = logging.getLogger(__name__)


async def validate_crawl(
    output_dir: Path,
    qdrant_client: Any | None = None,
    tenant_id: str | None = None,
    collection_name: str = "rag_chunks",
    sample_images: int = 20
) -> dict:
    """
    Validate crawl output quality.
    
    Args:
        output_dir: Crawl output directory
        qdrant_client: Optional Qdrant client for chunk validation
        tenant_id: Optional tenant ID for filtering chunks
        collection_name: Qdrant collection name
        sample_images: Percentage of images to check (0-100)
        
    Returns:
        Validation report dictionary
    """
    report = {
        "validation_date": datetime.utcnow().isoformat() + "Z",
        "crawl_output_dir": str(output_dir),
        "issues": {
            "missing_titles": [],
            "missing_metadata": [],
            "broken_images": [],
            "duplicate_chunks": []
        },
        "stats": {
            "total_pages": 0,
            "total_chunks": 0,
            "images_checked": 0,
            "issues_found": 0
        },
        "status": "passed"
    }
    
    if not output_dir.exists():
        report["status"] = "error"
        report["error"] = f"Output directory not found: {output_dir}"
        return report
    
    # Load index.json
    index_path = output_dir / "index.json"
    if not index_path.exists():
        report["status"] = "error"
        report["error"] = "index.json not found"
        return report
    
    try:
        with open(index_path, "r", encoding="utf-8") as f:
            index_data = json.load(f)
    except Exception as e:
        report["status"] = "error"
        report["error"] = f"Failed to load index.json: {e}"
        return report
    
    pages = index_data.get("pages", [])
    report["stats"]["total_pages"] = len(pages)
    
    # Check 1: Missing titles and metadata
    metadata_dir = output_dir / "metadata"
    for page in pages:
        page_id = page.get("page_id", "")
        url = page.get("url", "")
        title = page.get("title", "")
        
        if not title or title.strip() == "":
            report["issues"]["missing_titles"].append({
                "page_id": page_id,
                "url": url
            })
        
        # Check if metadata file exists
        meta_path = metadata_dir / f"{page_id}.metadata.json"
        if not meta_path.exists():
            report["issues"]["missing_metadata"].append({
                "page_id": page_id,
                "url": url,
                "reason": "metadata file not found"
            })
        else:
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                if not meta or len(meta) == 0:
                    report["issues"]["missing_metadata"].append({
                        "page_id": page_id,
                        "url": url,
                        "reason": "metadata file empty"
                    })
            except Exception as e:
                report["issues"]["missing_metadata"].append({
                    "page_id": page_id,
                    "url": url,
                    "reason": f"invalid JSON: {e}"
                })
    
    # Check 2: Broken images (sample check)
    images_json_path = output_dir / "images.json"
    if images_json_path.exists():
        try:
            with open(images_json_path, "r", encoding="utf-8") as f:
                images = json.load(f)
            
            # Sample images
            import random
            sample_count = max(1, int(len(images) * sample_images / 100))
            sampled_images = random.sample(images, min(sample_count, len(images)))
            
            broken = await _check_images(sampled_images)
            report["issues"]["broken_images"] = broken
            report["stats"]["images_checked"] = len(sampled_images)
            
        except Exception as e:
            logger.error(f"Failed to check images: {e}")
    
    # Check 3: Duplicate chunks in Qdrant
    if qdrant_client and tenant_id:
        try:
            duplicates = await _check_duplicate_chunks(
                qdrant_client,
                collection_name,
                tenant_id
            )
            report["issues"]["duplicate_chunks"] = duplicates
            report["stats"]["total_chunks"] = duplicates.get("total_checked", 0)
        except Exception as e:
            logger.error(f"Failed to check duplicate chunks: {e}")
    
    # Calculate total issues
    total_issues = (
        len(report["issues"]["missing_titles"]) +
        len(report["issues"]["missing_metadata"]) +
        len(report["issues"]["broken_images"]) +
        len(report["issues"]["duplicate_chunks"])
    )
    report["stats"]["issues_found"] = total_issues
    
    if total_issues > 0:
        report["status"] = "failed"
    
    return report


async def _check_images(images: list[dict]) -> list[dict]:
    """Check if image URLs are accessible (sample check with rate limiting)."""
    import httpx
    
    broken = []
    semaphore = asyncio.Semaphore(5)  # Max 5 concurrent checks
    
    async def check_image(img: dict):
        url = img.get("url", "") or img.get("src", "")
        if not url or url.startswith("data:"):
            return
        
        async with semaphore:
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.head(url, follow_redirects=True)
                    if response.status_code >= 400:
                        broken.append({
                            "url": url,
                            "status": response.status_code,
                            "page_url": img.get("page_url", "")
                        })
            except Exception as e:
                broken.append({
                    "url": url,
                    "status": 0,
                    "error": str(e),
                    "page_url": img.get("page_url", "")
                })
            
            # Rate limiting: small delay between requests
            await asyncio.sleep(0.1)
    
    tasks = [check_image(img) for img in images]
    await asyncio.gather(*tasks, return_exceptions=True)
    
    return broken


async def _check_duplicate_chunks(
    qdrant_client: Any,
    collection_name: str,
    tenant_id: str
) -> list[dict]:
    """Check for duplicate chunks in Qdrant."""
    try:
        # Query all chunks for tenant
        from qdrant_client.models import Filter, FieldCondition, MatchValue
        
        scroll_result = qdrant_client.scroll(
            collection_name=collection_name,
            scroll_filter=Filter(
                must=[
                    FieldCondition(
                        key="tenant_id",
                        match=MatchValue(value=tenant_id)
                    )
                ]
            ),
            limit=10000,  # Adjust based on expected size
            with_payload=True,
            with_vectors=False
        )
        
        points = scroll_result[0] if scroll_result else []
        
        # Check for duplicate chunk_ids or content_hashes
        seen_ids = {}
        seen_hashes = {}
        duplicates = []
        
        for point in points:
            chunk_id = point.payload.get("chunk_id", "")
            content_hash = point.payload.get("content_hash", "")
            
            if chunk_id:
                if chunk_id in seen_ids:
                    duplicates.append({
                        "type": "duplicate_chunk_id",
                        "chunk_id": chunk_id,
                        "point_ids": [seen_ids[chunk_id], point.id]
                    })
                else:
                    seen_ids[chunk_id] = point.id
            
            if content_hash:
                if content_hash in seen_hashes:
                    duplicates.append({
                        "type": "duplicate_content_hash",
                        "content_hash": content_hash[:16] + "...",
                        "point_ids": [seen_hashes[content_hash], point.id]
                    })
                else:
                    seen_hashes[content_hash] = point.id
        
        return {
            "duplicates": duplicates,
            "total_checked": len(points)
        }
        
    except Exception as e:
        logger.error(f"Failed to check duplicate chunks: {e}")
        return {
            "error": str(e),
            "total_checked": 0
        }
