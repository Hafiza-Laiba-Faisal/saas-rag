"""
Markdown formatter — converts scraped posts/page data to Markdown.
Useful for AI agents, RAG pipelines, and documentation export.
"""

from __future__ import annotations
from .base import BaseFormatter


class MarkdownFormatter(BaseFormatter):
    format = "markdown"

    def format_post(self, post: dict) -> str:
        lines = []
        if post.get("caption"):
            lines.append(post["caption"])
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
        if post.get("likes"):  stats.append(f"👍 {post['likes']}")
        if post.get("comments"): stats.append(f"💬 {post['comments']}")
        if stats:
            lines.append("  ".join(stats))
        return "\n\n".join(lines)

    def format_page(self, page_meta: dict, posts: list[dict]) -> str:
        header = [f"# {page_meta.get('title', 'Facebook Page')}"]
        if page_meta.get("followers"):
            header.append(f"**Followers:** {page_meta['followers']:,}")
        if page_meta.get("about"):
            header.append(f"\n{page_meta['about']}")
        header.append(f"\n---\n**{len(posts)} posts**\n")
        body = ["\n\n---\n\n".join(self.format_post(p) for p in posts)]
        return "\n".join(header) + "\n\n" + "\n".join(body)


class JsonFormatter(BaseFormatter):
    format = "json"

    def format_post(self, post: dict) -> str:
        import json
        return json.dumps(post, ensure_ascii=False, indent=2)

    def format_page(self, page_meta: dict, posts: list[dict]) -> str:
        import json
        return json.dumps({"page": page_meta, "posts": posts}, ensure_ascii=False, indent=2)
