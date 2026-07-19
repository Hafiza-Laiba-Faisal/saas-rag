"""
URL normalization and deduplication.
Ensures:
  - example.com/page
  - example.com/page/
  - example.com/page#section
  - example.com/page?utm=test
All map to same canonical URL.
"""
from __future__ import annotations
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode


class URLNormalizer:
    """Canonical URL normalization for deduplication."""

    def normalize(self, url: str, remove_fragments: bool = True, 
                  remove_query_params: list[str] | None = None) -> str:
        """
        Normalize URL to canonical form.
        
        Args:
            url: Raw URL
            remove_fragments: Remove #section anchors (default: True)
            remove_query_params: List of query params to strip (e.g., ['utm_source', 'fbclid'])
        
        Returns:
            Canonical URL string
        """
        parsed = urlparse(url.strip())
        
        # Lowercase scheme and netloc
        scheme = parsed.scheme.lower() if parsed.scheme else "https"
        netloc = parsed.netloc.lower()
        
        # Remove trailing slash from path (except root)
        path = parsed.path.rstrip("/") if parsed.path != "/" else "/"
        
        # Sort and filter query params
        query = ""
        if parsed.query:
            params = parse_qs(parsed.query, keep_blank_values=True)
            if remove_query_params:
                for key in remove_query_params:
                    params.pop(key, None)
            # Sort for consistency
            sorted_params = sorted(params.items())
            query = urlencode(sorted_params, doseq=True) if sorted_params else ""
        
        # Remove fragment if requested
        fragment = "" if remove_fragments else parsed.fragment
        
        normalized = urlunparse((scheme, netloc, path, "", query, fragment))
        return normalized

    def get_domain(self, url: str) -> str:
        """Extract domain from URL."""
        parsed = urlparse(url)
        return parsed.netloc.lower()

    def is_same_domain(self, url1: str, url2: str) -> bool:
        """Check if two URLs belong to same domain."""
        return self.get_domain(url1) == self.get_domain(url2)
