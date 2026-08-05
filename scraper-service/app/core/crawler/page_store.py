"""
PageStore — Structured storage manager for crawled content.

Provides consistent page ID generation and organized storage:
- raw_html/{page_id}.html
- clean_text/{page_id}.md
- metadata/{page_id}.metadata.json

Single source of truth for output manifest (index.json).
"""
from __future__ import annotations
import json
import hashlib
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from core.crawler.url_normalizer import URLNormalizer


class PageStore:
    """
    Manages structured storage of crawled pages.
    """
    
    def __init__(self, output_dir: Path):
        """
        Initialize PageStore.
        
        Args:
            output_dir: Base directory for crawl output (e.g., crawl_output/example_com/)
        """
        self.output_dir = Path(output_dir)
        self.normalizer = URLNormalizer()
        
        # Create directory structure
        self.raw_html_dir = self.output_dir / "raw_html"
        self.clean_text_dir = self.output_dir / "clean_text"
        self.metadata_dir = self.output_dir / "metadata"
        
        self.raw_html_dir.mkdir(parents=True, exist_ok=True)
        self.clean_text_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_dir.mkdir(parents=True, exist_ok=True)
        
        # In-memory manifest accumulator
        self._manifest_entries: list[dict] = []
    
    def page_id(self, url: str) -> str:
        """
        Generate consistent page ID from URL.
        
        Args:
            url: Page URL
            
        Returns:
            8-character SHA1 hash of normalized URL
        """
        normalized = self.normalizer.normalize(
            url,
            remove_fragments=True,
            remove_query_params=["utm_source", "utm_medium", "utm_campaign", "fbclid", "gclid"]
        )
        hash_obj = hashlib.sha1(normalized.encode("utf-8"))
        return hash_obj.hexdigest()[:8]
    
    def save_raw_html(self, page_id: str, html: str) -> Path:
        """
        Save raw HTML content.
        
        Args:
            page_id: Page identifier
            html: Raw HTML content
            
        Returns:
            Path to saved file
        """
        file_path = self.raw_html_dir / f"{page_id}.html"
        file_path.write_text(html, encoding="utf-8")
        return file_path
    
    def save_clean_text(self, page_id: str, markdown: str) -> Path:
        """
        Save clean markdown text.
        
        Args:
            page_id: Page identifier
            markdown: Cleaned markdown content
            
        Returns:
            Path to saved file
        """
        file_path = self.clean_text_dir / f"{page_id}.md"
        file_path.write_text(markdown, encoding="utf-8")
        return file_path
    
    def save_metadata(self, page_id: str, meta: dict) -> Path:
        """
        Save page metadata as JSON.
        
        Args:
            page_id: Page identifier
            meta: Metadata dictionary
            
        Returns:
            Path to saved file
        """
        file_path = self.metadata_dir / f"{page_id}.metadata.json"
        file_path.write_text(
            json.dumps(meta, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8"
        )
        return file_path
    
    def manifest_entry(
        self,
        page_id: str,
        url: str,
        title: str = "",
        language: str = "default",
        section: str = "General",
        changed: bool = True,
        **kwargs
    ) -> dict:
        """
        Create manifest entry for a page.
        
        Args:
            page_id: Page identifier
            url: Page URL
            title: Page title
            language: Language code
            section: Content section
            changed: Whether page changed since last crawl
            **kwargs: Additional fields
            
        Returns:
            Manifest entry dictionary
        """
        entry = {
            "page_id": page_id,
            "url": url,
            "title": title,
            "language": language,
            "section": section,
            "changed": changed,
            "raw_html": f"raw_html/{page_id}.html",
            "clean_text": f"clean_text/{page_id}.md",
            "metadata": f"metadata/{page_id}.metadata.json",
        }
        entry.update(kwargs)
        return entry
    
    def append_manifest(self, entry: dict) -> None:
        """
        Add entry to manifest (accumulated in memory).
        
        Args:
            entry: Manifest entry dictionary
        """
        self._manifest_entries.append(entry)
    
    def write_manifest(
        self,
        site: str,
        strategy: str = "recursive",
        stats: Optional[dict] = None,
        pages_by_language: Optional[dict] = None,
        **kwargs
    ) -> Path:
        """
        Write index.json manifest to disk.
        
        Args:
            site: Site URL
            strategy: Crawl strategy used
            stats: Crawl statistics
            pages_by_language: Pages grouped by language
            **kwargs: Additional manifest fields
            
        Returns:
            Path to index.json
        """
        from datetime import datetime
        
        manifest = {
            "site": site,
            "crawled_at": datetime.utcnow().isoformat() + "Z",
            "strategy": strategy,
            "pages": self._manifest_entries,
            "stats": stats or {},
        }
        
        # Add pages_by_language if provided
        if pages_by_language:
            manifest["pages_by_language"] = pages_by_language
        
        # Add any additional fields
        manifest.update(kwargs)
        
        # Derive changed/unchanged lists
        changed_pages = [e["url"] for e in self._manifest_entries if e.get("changed", True)]
        unchanged_pages = [e["url"] for e in self._manifest_entries if not e.get("changed", True)]
        
        manifest["changed_pages"] = changed_pages
        manifest["unchanged_pages"] = unchanged_pages
        
        # Write to disk
        index_path = self.output_dir / "index.json"
        index_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8"
        )
        
        return index_path
    
    def get_manifest_entries(self) -> list[dict]:
        """Get all accumulated manifest entries."""
        return self._manifest_entries.copy()
    
    def clear_manifest(self) -> None:
        """Clear accumulated manifest entries."""
        self._manifest_entries.clear()
