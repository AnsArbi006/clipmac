import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from clipmac.state import Store
from clipmac.learning import collect_performance, dashboard_learning, learning_export, performance_comparison, video_statistics, sample_ratios


class LearningTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = Store(self.root / "queue.sqlite")
        self.video = self.root / "final.mp4"
        self.video.write_bytes(b"test-video-version-one")
        self.store.add({"id": "clip1", "broadcaster_name": "Streamer"})
        self.store.update("clip1", "published", result={"file": str(self.video), "render": {"layout_version": 3}}, youtube_id="testvideo01", published=1000)
        self.job = self.store.get("clip1")
        self.stats = {"availability": "public", "views": 100, "likes": 5, "comments": 0}

    def test_rating_edits_and_reset_keep_history_without_upload_side_effects(self):
        self.store.rate("clip1", "good")
        self.store.rate("clip1", "good")
        self.store.rate("clip1", "bad")
        self.store.rate("clip1", None)
        self.assertEqual([r["value"] for r in self.store.rating_rows(history=True)], ["good", "bad", None])
        self.assertEqual(self.store.get("clip1")["status"], "published")
        self.assertEqual(dashboard_learning(Store(self.store.path))["rated_count"], 0)

    def test_rating_rejects_unknown_clip_unrendered_and_invalid_value(self):
        for clip, rating in (("clip1", "great"), ("missing", "good")):
            with self.assertRaises(ValueError): self.store.rate(clip, rating)
        self.store.add({"id": "empty"})
        with self.assertRaises(ValueError): self.store.rate("empty", "medium")

    def test_new_render_does_not_inherit_old_rating(self):
        self.store.rate("clip1", "good")
        self.video.write_bytes(b"different-render-version-two")
        data = dashboard_learning(self.store)
        self.assertFalse(data["ratings"][0]["current_revision"])
        self.assertEqual(data["rated_count"], 0)

    def test_late_first_read_never_fabricates_one_or_two_hour_values(self):
        self.store.record_performance(self.job, self.stats, 1000 + 3*3600, 1000)
        self.assertEqual([c["state"] for c in self.store.checkpoint_rows()], ["missed", "missed"])
        self.assertTrue(all(c["sample_id"] is None for c in self.store.checkpoint_rows()))
        self.assertEqual(self.store.performance_rows()[0]["age_seconds"], 10800)

    def test_checkpoints_persist_actual_age_and_are_not_overwritten(self):
        self.store.record_performance(self.job, self.stats, 4660, 1000)
        sample_id = self.store.checkpoint_rows()[0]["sample_id"]
        self.store.record_performance(self.job, {**self.stats, "views": 200}, 4800, 1000)
        self.assertEqual(self.store.checkpoint_rows()[0]["sample_id"], sample_id)
        self.assertEqual(self.store.performance_rows()[0]["age_seconds"], 3660)
        self.assertEqual(Store(self.store.path).performance_sync_rows()[0]["next_check"], 8200)

    def test_missing_metrics_not_zero_and_retry_within_window(self):
        values = video_statistics({"snippet": {"channelId": "mine"}, "status": {"privacyStatus": "public"}, "statistics": {}}, "mine")
        self.assertIsNone(values["views"])
        self.store.record_performance(self.job, values, 4660, 1000)
        self.assertEqual(self.store.checkpoint_rows(), [])
        self.assertEqual(self.store.performance_sync_rows()[0]["next_check"], 4960)

    def test_no_false_stats_for_other_channel_or_missing_video(self):
        self.assertEqual(video_statistics(None, "mine"), {"availability": "unavailable"})
        self.assertEqual(video_statistics({"snippet": {"channelId": "other"}, "statistics": {"viewCount": "100"}}, "mine"), {"availability": "unavailable"})

    def test_collect_uses_batch_and_official_publication_time(self):
        service = MagicMock()
        service.videos.return_value.list.return_value.execute.return_value = {"items": [{"id": "testvideo01", "snippet": {"channelId": "mine", "publishedAt": "1970-01-01T00:20:00Z"}, "status": {"privacyStatus": "public"}, "statistics": {"viewCount": "100", "likeCount": "2"}}]}
        self.assertEqual(collect_performance(self.store, service, "mine", 4800), 1)
        sample = self.store.performance_rows()[0]
        self.assertEqual(sample["published_at"], 1200)
        self.assertEqual(sample["age_seconds"], 3600)
        self.assertIsNone(sample["comments"])
        self.assertEqual(collect_performance(self.store, service, "mine", 4900), 0)

    def test_failed_api_read_backoffs_without_zero_snapshot(self):
        service = MagicMock()
        service.videos.return_value.list.return_value.execute.side_effect = TimeoutError()
        with self.assertRaises(TimeoutError): collect_performance(self.store, service, "mine", 4800)
        self.assertEqual(self.store.performance_rows(), [])
        self.assertEqual(self.store.performance_sync_rows()[0]["next_check"], 5700)

    def test_comparison_only_same_age_with_enough_peers(self):
        samples = [{"id": i, "views": 100 if i else 10} for i in range(7)]
        checkpoints = [{"clip_id": str(i), "sample_id": i, "state": "recorded", "hour": 1} for i in range(7)]
        result = performance_comparison("0", checkpoints, samples)
        self.assertEqual(result["state"], "below")
        self.assertEqual(result["signal"], "audience_reach_not_edit_quality")
        for c in checkpoints[2:]: c["hour"] = 2
        self.assertEqual(performance_comparison("0", checkpoints, samples)["state"], "insufficient")

    def test_export_retains_subjective_and_observed_sources_separately(self):
        self.store.rate("clip1", "good")
        self.store.record_performance(self.job, {**self.stats, "views": 0}, 4660, 1000)
        result = learning_export(self.store)
        self.assertFalse(result["model_trained"])
        self.assertEqual(result["ratings_history"][0]["snapshot"]["label_source"], "user_subjective")
        self.assertEqual(result["ratings_history"][0]["value"], "good")
        self.assertEqual(result["performance_samples"][0]["views"], 0)

    def test_ratios_preserve_missing_values_and_zero_denominator(self):
        ratios = sample_ratios({**self.stats, "views": 3, "likes": 1})
        self.assertEqual(ratios["likes_per_100_views"], 33.3333)
        self.assertEqual(ratios["denominator_views"], 3)
        self.assertIsNone(sample_ratios({**self.stats, "views": 0})["likes_per_100_views"])
        self.assertIsNone(sample_ratios({**self.stats, "likes": None})["likes_per_100_views"])
        self.assertIsNone(sample_ratios({**self.stats, "availability": "unavailable"})["likes_per_100_views"])
        self.assertEqual(sample_ratios(self.stats)["comments_per_100_views"], 0)

    def test_context_survives_files_being_removed_without_inventing_missing_artifacts(self):
        caption = self.root / 'captions.ass'
        caption.write_text('Style: Caption,Arial,64\nDialogue: example')
        self.store.capture_learning_context(self.job)
        caption.unlink()
        self.store.capture_learning_context(self.job)
        contexts = Store(self.store.path).learning_context_rows()
        self.assertEqual(len(contexts), 1)
        context = contexts[0]['context']
        self.assertIn('Style: Caption', context['artifacts']['captions.ass'])
        self.assertIn('transcript.json', context['missing_artifacts'])
        self.assertEqual(context['matches_published_video'], 'not_verified')

    def test_description_feedback_is_general_not_a_rating_or_edit(self):
        self.store.add_learning_note('description-note', 'youtube_description', 'Beschreibung gefällt mir nicht.')
        self.store.add_learning_note('description-note', 'youtube_description', 'Beschreibung gefällt mir nicht.')
        data = learning_export(self.store)
        self.assertEqual(len(data['collection_feedback']), 1)
        self.assertEqual(data['ratings_history'], [])
        self.assertEqual(data['phase'], 'data_collection_only')
        self.assertFalse(data['automatic_model_or_edit_changes'])
        self.assertEqual(self.store.get('clip1')['result'], self.job['result'])

    def test_actual_youtube_description_is_linked_to_its_observation(self):
        values = video_statistics({'snippet': {'channelId': 'mine', 'title': 'Actual title',
            'description': 'Actual description'}, 'status': {'privacyStatus': 'public'},
            'statistics': {'viewCount': '100', 'likeCount': '5'}}, 'mine')
        self.store.record_performance(self.job, values, 4660, 1000)
        data = learning_export(self.store)
        metadata = data['youtube_metadata_observations'][0]
        self.assertEqual(metadata['sample_id'], data['performance_samples'][0]['id'])
        self.assertEqual(metadata['metadata']['description'], 'Actual description')
        self.assertEqual(data['performance_checkpoints'][0]['sample_id'], metadata['sample_id'])
        self.assertEqual(data['performance_samples'][0]['ratios']['likes_per_100_views'], 5)


if __name__ == "__main__": unittest.main()
