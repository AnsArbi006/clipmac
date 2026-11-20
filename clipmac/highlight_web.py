"""Dashboard adapter for editorial review of locally generated highlights."""

from .environment import DEVELOPMENT
from .highlight_review import HighlightReviews
from .highlight_score import DEFAULT_THRESHOLD


class HighlightDashboard:
    def __init__(self, analysis, store):
        self.analysis = analysis
        self.reviews = HighlightReviews(store)

    def state(self, cfg):
        state = self.analysis.snapshot()
        threshold = cfg.get("highlight_recommendation_threshold", DEFAULT_THRESHOLD)
        rows = []
        for row in state["candidates"]:
            candidate = self.analysis.candidate(row["id"])
            capture = candidate.get("live_context") or {}
            candidate["technical_blocked"] = bool(candidate.get("preview_error"))
            score = self.reviews.score(candidate, threshold)
            review = self.reviews.snapshot(candidate)
            can_promote = (not DEVELOPMENT and row["kind"] == "live" and row["preview_ready"]
                           and capture.get("category_review") is False
                           and capture.get("coverage") in {"complete", "exported"}
                           and not review["promoted_clip_id"] and review["rating"] != "bad"
                           and not any(report["status"] == "open" for report in review["reports"]))
            rows.append({**row, "score": score, "review": review, "can_promote": can_promote})
        return {**state, "candidates": rows, "development": DEVELOPMENT, "threshold": threshold}

    def rate(self, body):
        return self.reviews.rate(self.analysis.candidate(body.get("id")), body.get("value"))

    def report(self, body):
        return self.reviews.report(self.analysis.candidate(body.get("id")), body.get("note"), body.get("position"))

    def withdraw(self, body):
        return self.reviews.withdraw(self.analysis.candidate(body.get("id")), body.get("report_id"))

    def promote(self, body, cfg):
        if body.get("confirmed") is not True:
            raise ValueError("Bitte die Übernahme in die Paketwarteschlange bestätigen.")
        return self.reviews.promote(self.analysis.candidate(body.get("id")), cfg)
