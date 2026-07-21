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

    def extract(self, html_content: str) -> dict[str, str]:
        """
        Extract readable content.
        Returns:
            {"html": str, "markdown": str, "clean_text": str}
        """
        if not html_content:
            return {"html": "", "markdown": "", "clean_text": ""}

        soup = BeautifulSoup(html_content, "html.parser")

        # 1. Remove comments
        for comment in soup.find_all(text=lambda text: isinstance(text, Comment)):
            comment.extract()

        # 2. Strip non-content / boilerplate tags
        boilerplate_tags = [
            "header", "footer", "nav", "aside", "script", "style", "form",
            "iframe", "noscript", "svg", "button", "select", "textarea"
        ]
        for tag in soup.find_all(boilerplate_tags):
            tag.extract()

        # Try to find main content areas if they exist, to focus extraction
        main_content = None
        for selector in ["main", "article", "[role='main']", "#content", ".content", "#main"]:
            found = soup.select_one(selector)
            if found:
                main_content = found
                break

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

        return {
            "html": clean_html,
            "markdown": markdown_content,
            "clean_text": clean_text_content
        }
