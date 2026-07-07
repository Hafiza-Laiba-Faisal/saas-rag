class QualityScorer:
    RULES = [
        ("title_found", lambda e: bool(e.get("title")), 10),
        ("main_content_found", lambda e: e.get("html_length", 0) > 1000, 30),
        ("links_found", lambda e: e.get("links_count", 0) > 0, 10),
        ("metadata_found", lambda e: bool(e.get("description")), 10),
        ("html_size_reasonable", lambda e: 1000 < e.get("html_length", 0) < 5_000_000, 10),
        ("empty_page", lambda e: e.get("html_length", 0) < 200, -40),
        ("cloudflare_detected", lambda e: e.get("detectors", {}).get("cloudflare", False), -50),
        ("javascript_required", lambda e: e.get("detectors", {}).get("javascript_required", False), -30),
        ("login_required", lambda e: e.get("detectors", {}).get("login_required", False), -20),
        ("status_not_200", lambda e: e.get("status_code") != 200, -20),
    ]

    def score(self, extraction: dict) -> dict:
        breakdown = []
        raw = 0
        for rule, check, points in self.RULES:
            if check(extraction):
                raw += points
                breakdown.append({"rule": rule, "points": points})

        score = max(0, min(100, raw))

        if score >= 70:
            quality = "high"
        elif score >= 40:
            quality = "medium"
        elif score >= 20:
            quality = "low"
        else:
            quality = "failed"

        return {"score": score, "breakdown": breakdown, "quality": quality}
