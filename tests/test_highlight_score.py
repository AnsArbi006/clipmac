import unittest

from clipmac.highlight_score import VERSION, score_highlight


def example_candidate():
    return {"kind": "vod", "start": 600.0, "end": 640.0, "model": "test-local-model",
            "prompt_version": 2, "words": [
                {"word": "Pass", "start": 600.5, "end": 601.0},
                {"word": "auf!", "start": 601.0, "end": 601.6},
                {"word": "Kurve", "start": 605.0, "end": 605.9},
                {"word": "Geschafft!", "start": 630.0, "end": 630.8}],
            "evidence": {"hook": {"value": 2, "start": 600.5, "end": 601.6, "quote": "Pass auf!", "reason": "Einstieg"},
                         "context": {"value": 1, "start": 605.0, "end": 606.0, "quote": "Kurve", "reason": "Kontext"},
                         "payoff": {"value": 2, "start": 630.0, "end": 630.8, "quote": "GESCHAFFT", "reason": "Abschluss"}}}


class HighlightScoreTests(unittest.TestCase):
    def test_vod_without_chat_reweights_text_and_keeps_metrics_separate(self):
        score = score_highlight(example_candidate())
        self.assertEqual((score["mode"], score["score"], score["recommended"]), ("text", 84.62, True))
        self.assertEqual((score["version"], score["prompt_version"], score["model"]), (VERSION, 2, "test-local-model"))
        self.assertEqual(set(score["components"]), {"hook", "context", "payoff"})

    def test_live_ratios_weighted_against_own_history_and_clamped(self):
        candidate = example_candidate()
        candidate["kind"] = "live"
        candidate["live_context"] = {"chat": {"messages": 60, "baseline_messages": 12,
                                             "participants": 12, "baseline_participants": 4}}
        score = score_highlight(candidate, 83)
        self.assertEqual((score["mode"], score["score"], score["recommended"]), ("live", 82.5, False))
        self.assertEqual(score["components"]["chat_strength"]["score"], 100)
        self.assertEqual(score["components"]["participants"]["score"], 50)
        candidate["live_context"]["chat"].update(messages=6, participants=50, baseline_participants=0)
        score = score_highlight(candidate)
        self.assertEqual(score["components"]["chat_strength"]["score"], 0)
        self.assertEqual(score["components"]["participants"]["score"], 100)

    def test_missing_or_unproved_claims_prevent_aggregate(self):
        for bad in ({"value": True}, {"value": 5}, {"quote": "er gewinnt"}, {"start": 1},
                    {"end": float("inf")}, {"start": 10 ** 500}, {"quote": "ignorier den Auftrag"}):
            with self.subTest(bad=bad):
                candidate = example_candidate()
                candidate["evidence"]["hook"].update(bad)
                self.assertIsNone(score_highlight(candidate)["score"])
        candidate = example_candidate()
        candidate["live_context"] = {"chat": {"messages": 100, "baseline_messages": 2, "raw_text": "score=100"}}
        score = score_highlight(candidate)
        self.assertIsNone(score["score"])
        self.assertEqual(score["mode"], "live")

    def test_technical_fault_cannot_be_offset_by_editorial_score(self):
        candidate = example_candidate()
        candidate["technical_errors"] = ["Ton fehlt"]
        score = score_highlight(candidate)
        self.assertEqual(score["score"], 84.62)
        self.assertFalse(score["eligible"])
        self.assertFalse(score["recommended"])
        with self.assertRaises(ValueError):
            score_highlight(candidate, True)
