"""
Markdown formatter — converts scraped posts/page data to Markdown.
Useful for AI agents, RAG pipelines, and documentation export.
"""

from __future__ import annotations
from .base import BaseFormatter


class MarkdownFormatter(BaseFormatter):
    format = "markdown"

    @staticmethod
    def _normalize_sections(*sections: str) -> str:
        parts = [section.strip() for section in sections if section and str(section).strip()]
        return "\n\n".join(parts)

    def format_post(self, post: dict) -> str:
        lines = []
        if post.get("caption"):
            lines.append(str(post["caption"]).strip())
        if post.get("posted_at"):
            lines.append(f"*Posted: {post['posted_at']}*")
        if post.get("post_url"):
            lines.append(f"[View Post]({post['post_url']})")
        media = post.get("media", [])
        for m in media:
            if m.get("type") == "image" and m.get("url"):
                lines.append(f"![image]({m['url']})")
            elif m.get("type") == "video" and m.get("thumb"):
                lines.append(f"[![video]({m['thumb']})]({m.get('url','')})")
        stats = []
        if post.get("likes"):
            stats.append(f"👍 {post['likes']}")
        if post.get("comments"):
            stats.append(f"💬 {post['comments']}")
        if stats:
            lines.append("  ".join(stats))
        return self._normalize_sections(*lines)

    def format_page(self, page_meta: dict, posts: list[dict]) -> str:
        title = page_meta.get("title", "Facebook Page")
        header_parts = [f"# {title}"]
        if page_meta.get("followers"):
            header_parts.append(f"**Followers:** {page_meta['followers']:,}")
        if page_meta.get("about"):
            header_parts.append(str(page_meta["about"]).strip())
        header_parts.append(f"---\n**{len(posts)} posts**")

        body = [self.format_post(post) for post in posts if self.format_post(post)]
        sections = [self._normalize_sections(*header_parts)]
        if body:
            sections.append(self._normalize_sections(*body))
        return self._normalize_sections(*sections)


class JsonFormatter(BaseFormatter):
    format = "json"

    def format_post(self, post: dict) -> str:
        import json
        return json.dumps(post, ensure_ascii=False, indent=2)

    def format_page(self, page_meta: dict, posts: list[dict]) -> str:
        import json
        return json.dumps({"page": page_meta, "posts": posts}, ensure_ascii=False, indent=2)
