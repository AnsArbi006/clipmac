import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from clipmac.content_policy import ranked_pool, rejection_reason
from clipmac.engine import Engine
from clipmac.state import Store


class ContentPolicyTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.now(timezone.utc)
        self.cfg = {'required_game_id': '1867279146', 'required_game_name': 'Grand Theft Auto VI',
                    'streamers': ['papaplatte', 'trymacs'], 'lookback_hours': 7,
                    'selection_scope': 'global', 'publish_enabled': True, 'channel_id': 'test',
                    'publish_interval_minutes': 0}

    def clip(self, name, views=10, **changes):
        return {'id': name, 'game_id': '1867279146', 'streamer_login': 'papaplatte',
                'created_at': (self.now-timedelta(hours=1)).isoformat(), 'view_count': views,
                'title': 'GTA 6', **changes}

    def test_gta5_with_gta6_title_and_missing_category_are_rejected(self):
        for game in ('32982', '', None):
            self.assertTrue(rejection_reason(self.clip('a', game_id=game), self.cfg, self.now))

    def test_missing_category_configuration_fails_closed(self):
        self.assertTrue(rejection_reason(self.clip('a'), {**self.cfg, 'required_game_id': ''}, self.now))

    def test_channel_and_freshness_guards(self):
        for changes in ({'streamer_login': 'rohat'}, {'created_at': 'invalid'},
                        {'created_at': '2026-11-18T12:00:00'},
                        {'created_at': (self.now-timedelta(hours=8)).isoformat()},
                        {'created_at': (self.now+timedelta(minutes=1)).isoformat()}):
            self.assertTrue(rejection_reason(self.clip('a', **changes), self.cfg, self.now))
        self.assertFalse(rejection_reason(self.clip('a'), self.cfg, self.now))

    def test_global_top_is_filtered_before_ranking(self):
        clips = [self.clip('wrong', 100000, game_id='32982'), self.clip('b', 20),
                 self.clip('c', 40, streamer_login='trymacs'), self.clip('d', 30)]
        self.assertEqual([c['id'] for c in ranked_pool(clips, self.cfg, 2, self.now)], ['c', 'd'])

    def test_per_streamer_ranking(self):
        clips = [self.clip('a', 20), self.clip('b', 10), self.clip('c', 30, streamer_login='trymacs')]
        self.assertEqual([c['id'] for c in ranked_pool(clips, {**self.cfg, 'selection_scope':'per_streamer'}, 1, self.now)], ['c','a'])

    def test_existing_wrong_queue_never_reaches_download_or_upload(self):
        with tempfile.TemporaryDirectory() as temp:
            store = Store(Path(temp)/'queue.db')
            engine = Engine(store)
            store.add(self.clip('wrong', game_id='32982'))
            with patch('clipmac.engine.settings', return_value=self.cfg), patch('clipmac.engine.media.download') as download:
                engine.process_one(store.get('wrong'))
                download.assert_not_called()
            self.assertEqual(store.get('wrong')['status'], 'policy_blocked')
            store.add(self.clip('old', created_at=(self.now-timedelta(hours=8)).isoformat()))
            store.update('old', 'ready')
            engine.active.set()
            with patch('clipmac.engine.settings', return_value=self.cfg), patch('clipmac.engine.publisher.service_for_channel') as auth:
                engine.publish_one()
                auth.assert_not_called()
            self.assertEqual(store.get('old')['status'], 'policy_blocked')

    def test_discovery_does_not_drain_lower_ranked_clips_on_repeat(self):
        from unittest.mock import MagicMock
        cfg = {**self.cfg, 'top_per_streamer': 2}
        clips = [self.clip('first', 40, duration=20), self.clip('second',30,duration=20),
                 self.clip('third',20,duration=20), self.clip('gta5',1000,duration=20,game_id='32982')]
        client = MagicMock()
        client.resolve_broadcasters.return_value = {'papaplatte':'one','trymacs':'two'}
        client.get_clips_for_broadcaster.side_effect = [clips, [], clips, []]
        client._helix_get.return_value = {'data':[{'id':'1867279146','name':'Grand Theft Auto VI'}]}
        with tempfile.TemporaryDirectory() as temp:
            store = Store(Path(temp)/'queue.db');engine=Engine(store);engine.active.set()
            with patch('clipmac.engine.settings',return_value=cfg), patch('clipmac.engine.secrets',return_value={'client_id':'test','client_secret':'test'}), patch('twitch_api.TwitchApiClient',return_value=client):
                self.assertEqual(engine.discover()['added'],2)
                self.assertEqual(engine.discover()['added'],0)
            self.assertEqual({r['id'] for r in store.rows()}, {'first','second'})

    def test_freshness_rechecked_after_authentication(self):
        with tempfile.TemporaryDirectory() as temp:
            store = Store(Path(temp)/'queue.db');engine = Engine(store)
            store.add(self.clip('fresh'));store.update('fresh','ready');engine.active.set()
            changed = {**self.cfg, 'streamers': ['trymacs']}
            with patch('clipmac.engine.settings', side_effect=[self.cfg, changed]), patch('clipmac.engine.publisher.service_for_channel'), patch('clipmac.engine.publisher.upload') as upload:
                engine.publish_one()
                upload.assert_not_called()
            self.assertEqual(store.get('fresh')['status'], 'policy_blocked')

if __name__ == '__main__':
    unittest.main()
