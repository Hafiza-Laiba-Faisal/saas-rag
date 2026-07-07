"""
Asset extractor to discover media items (images, videos, audio, SVGs)
and documents (PDF, DOCX, XLSX, PPTX, ZIP) in a BeautifulSoup tree.
"""
from __future__ import annotations
from pathlib import Path
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup


class AssetExtractor:
    """
    Extracts media items and documents from HTML parsed tree.
    """

    def __init__(self, base_url: str = ""):
        self.base_url = base_url

    def extract(self, soup: BeautifulSoup) -> dict[str, list[dict]]:
        images = []
        videos = []
        audio = []
        svgs = []
        documents = []

        # 1. Images
        for img in soup.find_all("img"):
            src = img.get("src")
            if src:
                src_abs = urljoin(self.base_url, src)
                alt = img.get("alt", "")
                srcset = img.get("srcset", "")
                images.append({
                    "src": src_abs,
                    "alt": alt,
                    "srcset": srcset,
                    "tag": "img"
                })

        for svg in soup.find_all("svg"):
            svgs.append({
                "tag": "svg",
                "id": svg.get("id", ""),
                "class": " ".join(svg.get("class", [])) if isinstance(svg.get("class"), list) else svg.get("class", "")
            })

        # 2. Videos
        for video in soup.find_all("video"):
            video_src = video.get("src")
            if video_src:
                videos.append({
                    "src": urljoin(self.base_url, video_src),
                    "tag": "video"
                })
            for source in video.find_all("source"):
                src = source.get("src")
                if src:
                    videos.append({
                        "src": urljoin(self.base_url, src),
                        "type": source.get("type", ""),
                        "tag": "source"
                    })

        # 3. Audio
        for audio_tag in soup.find_all("audio"):
            audio_src = audio_tag.get("src")
            if audio_src:
                audio.append({
                    "src": urljoin(self.base_url, audio_src),
                    "tag": "audio"
                })
            for source in audio_tag.find_all("source"):
                src = source.get("src")
                if src:
                    audio.append({
                        "src": urljoin(self.base_url, src),
                        "type": source.get("type", ""),
                        "tag": "source"
                    })

        # 4. Documents/Files
        doc_extensions = (".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt", ".zip")
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if not href or href.startswith(("javascript:", "mailto:", "tel:")):
                continue
            abs_url = urljoin(self.base_url, href)
            path = urlparse(abs_url).path.lower()
            if path.endswith(doc_extensions):
                ext = Path(path).suffix
                documents.append({
                    "url": abs_url,
                    "text": a.get_text(strip=True)[:200],
                    "extension": ext
                })

        return {
            "images": images,
            "videos": videos,
            "audio": audio,
            "svgs": svgs,
            "documents": documents
        }
