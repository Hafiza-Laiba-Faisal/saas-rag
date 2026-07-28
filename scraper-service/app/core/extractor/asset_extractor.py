# """
# Asset extractor to discover media items (images, videos, audio, SVGs)
# and documents (PDF, DOCX, XLSX, PPTX, ZIP) in a BeautifulSoup tree.
# """
# from __future__ import annotations
# from pathlib import Path
# from urllib.parse import urljoin, urlparse
# from bs4 import BeautifulSoup
#
#
# class AssetExtractor:
#     """
#     Extracts media items and documents from HTML parsed tree.
#     """
#
#     def __init__(self, base_url: str = ""):
#         self.base_url = base_url
#
#     def extract(self, soup: BeautifulSoup) -> dict[str, list[dict]]:
#         images = []
#         videos = []
#         audio = []
#         svgs = []
#         documents = []
#
#         # 1. Images — also handle lazy-loaded images (data-src, data-lazy-src, etc.)
#         _LAZY_ATTRS = ("src", "data-src", "data-lazy-src", "data-original", "data-lazy", "data-img-src")
#         seen_srcs: set[str] = set()
#         for img in soup.find_all("img"):
#             src = None
#             for attr in _LAZY_ATTRS:
#                 val = img.get(attr)
#                 if val and not val.startswith("data:"):
#                     src = urljoin(self.base_url, val.strip())
#                     break
#             if src and src not in seen_srcs:
#                 seen_srcs.add(src)
#                 alt = img.get("alt", "")
#                 srcset = img.get("srcset", "") or img.get("data-srcset", "")
#                 images.append({
#                     "src": src,
#                     "alt": alt,
#                     "srcset": srcset,
#                     "tag": "img"
#                 })
#
#         # Also check picture > source elements (responsive images)
#         for source in soup.find_all("source"):
#             src = source.get("srcset") or source.get("data-srcset")
#             if src:
#                 first_url = src.strip().split(",")[0].strip().split()[0]
#                 abs_url = urljoin(self.base_url, first_url)
#                 if abs_url not in seen_srcs and not abs_url.startswith("data:"):
#                     seen_srcs.add(abs_url)
#                     images.append({"src": abs_url, "alt": "", "srcset": src, "tag": "source"})
#
#         # Also extract CSS background-image URLs from inline style attributes
#         for tag in soup.find_all(style=True):
#             style_val = tag.get("style", "")
#             import re as _re
#             for m in _re.finditer(r'url\(["\']?([^"\')\s]+)["\']?\)', style_val):
#                 bg_url = urljoin(self.base_url, m.group(1))
#                 if bg_url not in seen_srcs and not bg_url.startswith("data:"):
#                     ext = Path(bg_url.split("?")[0]).suffix.lower()
#                     if ext in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"):
#                         seen_srcs.add(bg_url)
#                         images.append({"src": bg_url, "alt": "", "srcset": "", "tag": "css-bg"})
#
#         for svg in soup.find_all("svg"):
#             svgs.append({
#                 "tag": "svg",
#                 "id": svg.get("id", ""),
#                 "class": " ".join(svg.get("class", [])) if isinstance(svg.get("class"), list) else svg.get("class", "")
#             })
#
#         # 2. Videos
#         for video in soup.find_all("video"):
#             video_src = video.get("src")
#             if video_src:
#                 videos.append({
#                     "src": urljoin(self.base_url, video_src),
#                     "tag": "video"
#                 })
#             for source in video.find_all("source"):
#                 src = source.get("src")
#                 if src:
#                     videos.append({
#                         "src": urljoin(self.base_url, src),
#                         "type": source.get("type", ""),
#                         "tag": "source"
#                     })
#
#         # 3. Audio
#         for audio_tag in soup.find_all("audio"):
#             audio_src = audio_tag.get("src")
#             if audio_src:
#                 audio.append({
#                     "src": urljoin(self.base_url, audio_src),
#                     "tag": "audio"
#                 })
#             for source in audio_tag.find_all("source"):
#                 src = source.get("src")
#                 if src:
#                     audio.append({
#                         "src": urljoin(self.base_url, src),
#                         "type": source.get("type", ""),
#                         "tag": "source"
#                     })
#
#         # 4. Documents/Files
#         doc_extensions = (".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt", ".zip")
#         for a in soup.find_all("a", href=True):
#             href = a["href"].strip()
#             if not href or href.startswith(("javascript:", "mailto:", "tel:")):
#                 continue
#             abs_url = urljoin(self.base_url, href)
#             path = urlparse(abs_url).path.lower()
#             if path.endswith(doc_extensions):
#                 ext = Path(path).suffix
#                 documents.append({
#                     "url": abs_url,
#                     "text": a.get_text(strip=True)[:200],
#                     "extension": ext
#                 })
#
#         return {
#             "images": images,
#             "videos": videos,
#             "audio": audio,
#             "svgs": svgs,
#             "documents": documents
#         }



"""
Asset extractor to discover media items (images, videos, audio, SVGs)
and documents (PDF, DOCX, XLSX, PPTX, ZIP) in a BeautifulSoup tree.
"""
from __future__ import annotations
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup

_VIDEO_EMBED_DOMAINS = ("youtube.com", "youtube-nocookie.com", "youtu.be", "vimeo.com", "dailymotion.com", "wistia.com", "wistia.net")


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

        # Respect <base href> if present — overrides self.base_url for relative resolution
        base_tag = soup.find("base", href=True)
        effective_base = urljoin(self.base_url, base_tag["href"]) if base_tag else self.base_url

        # 1. Images — also handle lazy-loaded images (data-src, data-lazy-src, etc.)
        _LAZY_ATTRS = ("src", "data-src", "data-lazy-src", "data-original", "data-lazy", "data-img-src")
        seen_srcs: set[str] = set()
        for img in soup.find_all("img"):
            src = None
            for attr in _LAZY_ATTRS:
                val = img.get(attr)
                if val and not val.startswith("data:"):
                    src = urljoin(effective_base, val.strip())
                    break
            if src and src not in seen_srcs:
                seen_srcs.add(src)
                alt = img.get("alt", "")
                srcset = img.get("srcset", "") or img.get("data-srcset", "")
                images.append({
                    "src": src,
                    "alt": alt,
                    "srcset": srcset,
                    "tag": "img"
                })

        # Only <picture> > <source> — not video/audio <source> tags
        for source in soup.select("picture > source"):
            src = source.get("srcset") or source.get("data-srcset")
            if src:
                first_url = src.strip().split(",")[0].strip().split()[0]
                abs_url = urljoin(effective_base, first_url)
                if abs_url not in seen_srcs and not abs_url.startswith("data:"):
                    seen_srcs.add(abs_url)
                    images.append({"src": abs_url, "alt": "", "srcset": src, "tag": "source"})

        # og:image / twitter:image meta tags — page's canonical preview image
        for meta_name in ("og:image", "og:image:url", "twitter:image", "twitter:image:src"):
            tag = soup.find("meta", attrs={"property": meta_name}) or soup.find("meta", attrs={"name": meta_name})
            if tag and tag.get("content"):
                abs_url = urljoin(effective_base, tag["content"].strip())
                if abs_url not in seen_srcs:
                    seen_srcs.add(abs_url)
                    images.append({"src": abs_url, "alt": "", "srcset": "", "tag": "meta"})

        # Also extract CSS background-image URLs from inline style attributes
        for tag in soup.find_all(style=True):
            style_val = tag.get("style", "")
            for m in re.finditer(r'url\(["\']?([^"\')\s]+)["\']?\)', style_val):
                bg_url = urljoin(effective_base, m.group(1))
                if bg_url not in seen_srcs and not bg_url.startswith("data:"):
                    ext = Path(bg_url.split("?")[0]).suffix.lower()
                    if ext in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"):
                        seen_srcs.add(bg_url)
                        images.append({"src": bg_url, "alt": "", "srcset": "", "tag": "css-bg"})

        for svg in soup.find_all("svg"):
            svgs.append({
                "tag": "svg",
                "id": svg.get("id", ""),
                "class": " ".join(svg.get("class", [])) if isinstance(svg.get("class"), list) else svg.get("class", "")
            })

        # 2. Videos — native <video> tags
        for video in soup.find_all("video"):
            video_src = video.get("src")
            if video_src:
                videos.append({
                    "src": urljoin(effective_base, video_src),
                    "tag": "video"
                })
            for source in video.find_all("source"):
                src = source.get("src")
                if src:
                    videos.append({
                        "src": urljoin(effective_base, src),
                        "type": source.get("type", ""),
                        "tag": "source"
                    })

        # Embedded videos — YouTube/Vimeo/Dailymotion/Wistia iframes
        for iframe in soup.find_all("iframe", src=True):
            src = urljoin(effective_base, iframe["src"].strip())
            domain = urlparse(src).netloc.lower()
            if any(d in domain for d in _VIDEO_EMBED_DOMAINS):
                videos.append({
                    "src": src,
                    "type": "embed",
                    "tag": "iframe"
                })

        # 3. Audio
        for audio_tag in soup.find_all("audio"):
            audio_src = audio_tag.get("src")
            if audio_src:
                audio.append({
                    "src": urljoin(effective_base, audio_src),
                    "tag": "audio"
                })
            for source in audio_tag.find_all("source"):
                src = source.get("src")
                if src:
                    audio.append({
                        "src": urljoin(effective_base, src),
                        "type": source.get("type", ""),
                        "tag": "source"
                    })

        # 4. Documents/Files
        doc_extensions = (".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt", ".zip")
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if not href or href.startswith(("javascript:", "mailto:", "tel:")):
                continue
            abs_url = urljoin(effective_base, href)
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
