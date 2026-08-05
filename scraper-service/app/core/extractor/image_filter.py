"""
ImageFilter — Two-phase image classification (extract all, filter decorative vs content).

Extraction NEVER discards — all images kept in page metadata.
Filtering applied at download/storage stage.
"""
from __future__ import annotations
import json
import re
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse


class ImageFilter:
    """
    Classifies images as 'content' or 'decorative' based on:
    - URL pattern matching
    - File extension
    - Dimensions (if available)
    """
    
    def __init__(self, config_path: Path | None = None):
        """
        Initialize ImageFilter with config.
        
        Args:
            config_path: Path to config JSON. If None, uses default.
        """
        self.config = self._load_default_config()
        if config_path and config_path.exists():
            self.load_config(config_path)
    
    def _load_default_config(self) -> dict:
        """Load default configuration."""
        return {
            "decorative_patterns": [
                "logo", "favicon", "icon", "facebook", "instagram",
                "twitter", "social", "footer", "button", "badge"
            ],
            "blocked_extensions": ["svg", "ico"],
            "min_width": 80,
            "min_height": 80,
            "content_keywords": []
        }
    
    def load_config(self, config_path: Path, domain: str | None = None) -> None:
        """
        Load configuration from file, optionally merging domain-specific overrides.
        
        Args:
            config_path: Path to base config JSON
            domain: Domain name for domain-specific config (e.g., 'grandhoteldelaville.com')
        """
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                base_config = json.load(f)
                self.config.update(base_config)
        except Exception as e:
            print(f"Warning: Could not load config from {config_path}: {e}")
        
        # Try domain-specific override
        if domain:
            domain_config_path = config_path.parent / f"{domain}.json"
            if domain_config_path.exists():
                try:
                    with open(domain_config_path, "r", encoding="utf-8") as f:
                        domain_config = json.load(f)
                        # Merge patterns
                        if "decorative_patterns" in domain_config:
                            self.config["decorative_patterns"].extend(domain_config["decorative_patterns"])
                        if "content_keywords" in domain_config:
                            self.config["content_keywords"].extend(domain_config["content_keywords"])
                        # Override scalars
                        for key in ["min_width", "min_height", "blocked_extensions"]:
                            if key in domain_config:
                                self.config[key] = domain_config[key]
                except Exception as e:
                    print(f"Warning: Could not load domain config from {domain_config_path}: {e}")
    
    def classify(self, image_meta: dict) -> Literal["content", "decorative"]:
        """
        Classify a single image.
        
        Args:
            image_meta: Dictionary with keys: url, alt (optional), width (optional), height (optional)
            
        Returns:
            "content" or "decorative"
        """
        url = image_meta.get("url", "") or image_meta.get("src", "")
        if not url:
            return "decorative"
        
        url_lower = url.lower()
        
        # 1. Check file extension
        parsed = urlparse(url_lower)
        path = parsed.path
        extension = Path(path).suffix.lstrip(".")
        if extension in self.config.get("blocked_extensions", []):
            return "decorative"
        
        # 2. Check decorative patterns in URL
        decorative_patterns = self.config.get("decorative_patterns", [])
        for pattern in decorative_patterns:
            if pattern.lower() in url_lower:
                return "decorative"
        
        # 3. Check dimensions if available
        width = image_meta.get("width")
        height = image_meta.get("height")
        min_width = self.config.get("min_width", 80)
        min_height = self.config.get("min_height", 80)
        
        if width and height:
            try:
                w = int(width)
                h = int(height)
                if w < min_width or h < min_height:
                    return "decorative"
            except (ValueError, TypeError):
                pass
        
        # 4. Check content keywords (positive signal)
        content_keywords = self.config.get("content_keywords", [])
        if content_keywords:
            for keyword in content_keywords:
                if keyword.lower() in url_lower:
                    return "content"  # Strong signal for content
        
        # 5. Check alt text quality (longer alt = likely content)
        alt = image_meta.get("alt", "")
        if alt and len(alt) > 20:
            return "content"
        
        # Default to content (conservative approach - don't over-filter)
        return "content"
    
    def filter_content(self, images: list[dict]) -> list[dict]:
        """
        Filter list of images, returning only content images.
        
        Args:
            images: List of image metadata dicts
            
        Returns:
            List of content images with 'category' field added
        """
        content_images = []
        for img in images:
            category = self.classify(img)
            img_copy = img.copy()
            img_copy["category"] = category
            if category == "content":
                content_images.append(img_copy)
        return content_images
    
    def classify_all(self, images: list[dict]) -> list[dict]:
        """
        Classify all images and add 'category' field without filtering.
        
        Args:
            images: List of image metadata dicts
            
        Returns:
            Same list with 'category' field added to each image
        """
        classified = []
        for img in images:
            img_copy = img.copy()
            img_copy["category"] = self.classify(img)
            classified.append(img_copy)
        return classified
