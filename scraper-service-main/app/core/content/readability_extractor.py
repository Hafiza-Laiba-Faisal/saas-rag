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

        # Generate markdown and clean text
        markdown_lines = []
        text_lines = []

        def traverse(node):
            if node.name is None:
                # Text node
                text = node.string
                if text:
                    cleaned_text = re.sub(r"\s+", " ", text)
                    if cleaned_text.strip():
                        return cleaned_text
                return ""

            # Check block elements or formatters
            tag_name = node.name.lower()
            
            # Sub-elements processing
            child_contents = []
            for child in node.children:
                res = traverse(child)
                if res:
                    child_contents.append(res)
            
            inner_text = " ".join(child_contents).strip()
            if not inner_text and tag_name not in ["img"]:
                return ""

            if tag_name in ["h1", "h2", "h3", "h4", "h5", "h6"]:
                level = int(tag_name[1])
                markdown_lines.append(f"\n\n{'#' * level} {inner_text}\n")
                text_lines.append(inner_text)
                return inner_text

            elif tag_name in ["p", "div", "section", "article"]:
                if inner_text:
                    markdown_lines.append(f"\n\n{inner_text}\n")
                    text_lines.append(inner_text)
                return inner_text

            elif tag_name == "br":
                markdown_lines.append("\n")
                return "\n"

            elif tag_name in ["strong", "b"]:
                return f"**{inner_text}**"

            elif tag_name in ["em", "i"]:
                return f"*{inner_text}*"

            elif tag_name == "a":
                href = node.get("href", "")
                if href and self.base_url:
                    href = urljoin(self.base_url, href)
                if inner_text and href:
                    return f"[{inner_text}]({href})"
                return inner_text

            elif tag_name == "img":
                src = node.get("src", "")
                alt = node.get("alt", "image").strip() or "image"
                if src and self.base_url:
                    src = urljoin(self.base_url, src)
                if src:
                    img_md = f"![{alt}]({src})"
                    markdown_lines.append(f"\n{img_md}\n")
                    return img_md
                return ""

            elif tag_name in ["ul", "ol"]:
                # Container tag, children are li. Just return cumulative text.
                return inner_text

            elif tag_name == "li":
                if inner_text:
                    markdown_lines.append(f"\n- {inner_text}")
                    text_lines.append(inner_text)
                return inner_text

            return inner_text

        # Start traversal from root
        traverse(content_root)

        # Assemble markdown
        markdown_content = "".join(markdown_lines).strip()
        # Clean up double newlines
        markdown_content = re.sub(r"\n{3,}", "\n\n", markdown_content)

        # Assemble plain text
        clean_text_content = "\n".join(text_lines).strip()
        clean_text_content = re.sub(r"\n{3,}", "\n\n", clean_text_content)

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
