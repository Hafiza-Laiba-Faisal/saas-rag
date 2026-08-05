"""
Lightweight readability parser that cleans HTML by stripping boilerplate tags
(header, footer, nav, aside, script, style, form, iframe, etc.) and formats
the remainder into HTML, Markdown, and clean plain text.
"""
from __future__ import annotations
import re
from urllib.parse import urljoin
from bs4 import BeautifulSoup, Comment


class ReadabilityExtractor:
    """
    Cleans up HTML documents to extract the main readable content.
    Provides output in clean HTML, Markdown, and plain text formats.
    """

    def __init__(self, base_url: str = ""):
        self.base_url = base_url

    @staticmethod
    def _safe_remove(element) -> None:
        """Remove a UI-chrome element only if it is NOT a container holding
        the main page content. Substring class selectors (e.g. `[class*=overlay]`)
        can match the root body/wrapper on templated sites (Squarespace puts
        tweaks like `tweak-show-page-title-overlay-always` on <body>), so we
        must never extract an element that contains an <article>/<main> content
        root, and only remove relatively small leaf-ish nodes."""
        if element is None:
            return
        if element.name in ("html", "body"):
            return
        # Never remove a container that itself holds article/main content.
        if element.find(["article", "main", "[role='main']", "#content", "#main"]):
            return
        # Popups / cookie banners / overlays are small; skip big content wrappers.
        if len(element.get_text()) > 2000:
            return
        element.extract()

    def extract(self, html_content: str) -> dict[str, str]:
        """
        Extract readable content.
        Returns:
            {"html": str, "markdown": str, "clean_text": str, "text_length": int, "word_count": int}
        """
        if not html_content:
            return {"html": "", "markdown": "", "clean_text": "", "text_length": 0, "word_count": 0}

        soup = BeautifulSoup(html_content, "html.parser")

        # 1. Remove comments
        for comment in soup.find_all(text=lambda text: isinstance(text, Comment)):
            comment.extract()

        # 2. Strip non-content / boilerplate tags
        boilerplate_tags = [
            "header", "footer", "nav", "aside", "script", "style", "form",
            "iframe", "noscript", "svg", "button", "select", "textarea", "dialog"  # Added dialog
        ]
        for tag in soup.find_all(boilerplate_tags):
            tag.extract()
        
        # 3. Selector-based removal (cookie banners, modals, chat widgets, etc.)
        ui_chrome_selectors = [
            "[id*=cookie]", "[class*=cookie]",
            "[id*=gdpr]", "[class*=gdpr]",
            "[class*=consent]",
            ".newsletter", "[class*=newsletter]",
            "[class*=popup]",
            "[id*=modal]", "[class*=modal]",
            ".overlay", "[class*=overlay]",
            "[class*=livechat]",
            "[class*=crisp]",
            "[id*=intercom]",
            "[id*=chat-widget]",
            "[class*=support-widget]",
            "[class*=floating-chat]",
            # Specific IDs only (not class*= to avoid over-stripping WP sites)
            "#chat-widget", "#crisp-chatbox", "#intercom-container",
        ]
        # Guarded removal (never nuke main-content containers)
        for selector in ui_chrome_selectors:
            try:
                for element in soup.select(selector):
                    self._safe_remove(element)
            except Exception:
                continue

        # Try to find main content areas if they exist, to focus extraction
        # Use minimum length threshold to avoid selecting tiny divs
        main_content = None
        MIN_CONTENT_LENGTH = 500  # at least 500 chars to be considered main content
        
        for selector in ["main", "article", "[role='main']", "#content", "#main", ".main-content", ".entry-content", ".page-content"]:
            found = soup.select_one(selector)
            if found and len(str(found)) >= MIN_CONTENT_LENGTH:
                main_content = found
                break
        
        # Fallback: find the largest div/section that looks like content
        if not main_content:
            candidates = soup.find_all(["div", "section"], recursive=False)
            if not candidates:
                candidates = soup.find("body").find_all(["div", "section"], recursive=False) if soup.find("body") else []
            if candidates:
                largest = max(candidates, key=lambda el: len(el.get_text()), default=None)
                if largest and len(largest.get_text()) > 100:
                    main_content = largest

        content_root = main_content if main_content else soup

        # Extract clean html
        clean_html = str(content_root)

        _BLOCK_TAGS = {
            "p", "div", "section", "article", "h1", "h2", "h3", "h4", "h5", "h6",
            "ul", "ol", "li", "blockquote", "table", "pre", "br"
        }

        def has_block_child(node) -> bool:
            if hasattr(node, "children"):
                for child in node.children:
                    if child.name and child.name.lower() in _BLOCK_TAGS:
                        return True
            return False

        def traverse(node) -> tuple[str, str]:
            if node.name is None:
                # Text node
                text = node.string
                if text:
                    cleaned_text = re.sub(r"\s+", " ", text)
                    if cleaned_text.strip():
                        return cleaned_text, cleaned_text
                return "", ""

            tag_name = node.name.lower()

            child_mds = []
            child_txts = []
            for child in node.children:
                md, txt = traverse(child)
                if md:
                    child_mds.append(md)
                if txt:
                    child_txts.append(txt)

            inner_md = "".join(child_mds).strip()
            inner_txt = "".join(child_txts).strip()

            if not inner_md and tag_name not in ["img"]:
                return "", ""

            if tag_name in ["h1", "h2", "h3", "h4", "h5", "h6"]:
                level = int(tag_name[1])
                return f"\n\n{'#' * level} {inner_md}\n\n", f"\n\n{inner_txt}\n\n"

            elif tag_name == "p":
                return f"\n\n{inner_md}\n\n", f"\n\n{inner_txt}\n\n"

            elif tag_name in ["div", "section", "article"]:
                if has_block_child(node):
                    return inner_md, inner_txt
                else:
                    return f"\n\n{inner_md}\n\n", f"\n\n{inner_txt}\n\n"

            elif tag_name == "br":
                return "\n", "\n"

            elif tag_name in ["strong", "b"]:
                return f"**{inner_md}**", inner_txt

            elif tag_name in ["em", "i"]:
                return f"*{inner_md}*", inner_txt

            elif tag_name == "a":
                href = node.get("href", "")
                if href and self.base_url:
                    href = urljoin(self.base_url, href)
                if inner_md and href:
                    return f"[{inner_md}]({href})", inner_txt
                return inner_md, inner_txt

            elif tag_name == "img":
                src = node.get("src", "")
                alt = node.get("alt", "image").strip() or "image"
                if src and self.base_url:
                    src = urljoin(self.base_url, src)
                if src:
                    return f"![{alt}]({src})", f"[{alt}]"
                return "", ""

            elif tag_name in ["ul", "ol"]:
                return f"\n\n{inner_md}\n\n", f"\n\n{inner_txt}\n\n"

            elif tag_name == "li":
                return f"\n- {inner_md}", f"\n- {inner_txt}"

            elif tag_name == "pre":
                return f"\n\n```\n{inner_txt}\n```\n\n", f"\n\n{inner_txt}\n\n"

            elif tag_name == "code":
                return f"`{inner_txt}`", inner_txt

            elif tag_name == "blockquote":
                return f"\n\n> {inner_md}\n\n", f"\n\n{inner_txt}\n\n"

            return inner_md, inner_txt

        markdown_content, clean_text_content = traverse(content_root)

        # Assemble markdown & clean text with cleanups
        markdown_content = re.sub(r"\n{3,}", "\n\n", markdown_content).strip()
        clean_text_content = re.sub(r"\n{3,}", "\n\n", clean_text_content).strip()

        # If empty text or markdown, fallback to basic text representation
        if not clean_text_content:
            clean_text_content = content_root.get_text(separator="\n").strip()
            clean_text_content = re.sub(r"\n{3,}", "\n\n", clean_text_content)

        if not markdown_content and clean_text_content:
            markdown_content = clean_text_content

        # Deduplicate repeated paragraphs (WP sites often repeat footer/nav content)
        markdown_content = self._dedup_paragraphs(markdown_content)
        clean_text_content = self._dedup_paragraphs(clean_text_content)

        return {
            "html": clean_html,
            "markdown": markdown_content,
            "clean_text": clean_text_content,
            "text_length": len(clean_text_content),
            "word_count": len(clean_text_content.split())
        }

    def _dedup_paragraphs(self, text: str) -> str:
        """Remove duplicate paragraphs/blocks that appear multiple times (WP footer repeating)."""
        if not text:
            return text
        lines = text.split("\n")
        seen = set()
        deduped = []
        for line in lines:
            stripped = line.strip()
            # Keep empty lines for spacing, deduplicate non-empty
            if not stripped:
                deduped.append(line)
            elif stripped not in seen:
                seen.add(stripped)
                deduped.append(line)
        result = "\n".join(deduped)
        return re.sub(r"\n{3,}", "\n\n", result).strip()
