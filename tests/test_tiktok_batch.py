import unittest
import contextlib
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
from clipmac.tiktok_batch import match_new_post


class TikTokBatchMatchTests(unittest.TestCase):
    def row(self, url, caption='#Twitch', privacy='Everyone'):
        return {url: {'url': url, 'caption': caption, 'row': caption+'\n'+privacy}}

    def test_only_new_public_matching_post_is_accepted(self):
        old=self.row('old')
        after={**old, **self.row('new')}
        self.assertEqual(match_new_post(old,after,'#Twitch')['url'],'new')

    def test_existing_same_caption_is_not_new_upload(self):
        old=self.row('old')
        self.assertIsNone(match_new_post(old,old,'#Twitch'))

    def test_private_or_different_caption_is_rejected(self):
        self.assertIsNone(match_new_post({},self.row('new',privacy='Only you'),'#Twitch'))
        self.assertIsNone(match_new_post({},self.row('new',caption='#Other'),'#Twitch'))

    def test_two_matching_posts_are_ambiguous(self):
        self.assertIsNone(match_new_post({}, {**self.row('one'), **self.row('two')}, '#Twitch'))

    def test_review_is_identified_only_when_explicitly_allowed(self):
        row=self.row('new',privacy='Content under review\nOnly me')
        self.assertIsNone(match_new_post({},row,'#Twitch'))
        self.assertEqual(match_new_post({},row,'#Twitch',accept_review=True)['url'],'new')
        self.assertIsNone(match_new_post({},self.row('private',privacy='Only me'),'#Twitch',accept_review=True))

    def test_stop_after_submission_records_result_but_never_starts_next_clip(self):
        from clipmac import tiktok_batch, tiktok
        from clipmac.state import atomic_json
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); stopped=[False]
            plan={'account':'demo.clips','items':[{'clip_id':c,'sha256':'abc','caption':'#Twitch','status':'pending'} for c in ('one','two')]}
            page=MagicMock()
            @contextlib.contextmanager
            def browser():yield None,page
            def publish(account,clip_id,**kwargs):
                atomic_json(root/account/(clip_id+'.json'),{'status':'confirmation_received'})
                stopped[0]=True
            with patch.object(tiktok,'browser',browser), patch.object(tiktok,'RECEIPTS',root), \
                    patch.object(tiktok,'clip_payload',return_value={'sha256':'abc','caption':'#Twitch'}), \
                    patch.object(tiktok,'publish',side_effect=publish) as upload, \
                    patch.object(tiktok_batch,'studio_posts',side_effect=[{},self.row('https://www.tiktok.com/@demo.clips/video/123')]):
                result=tiktok_batch.run(plan,root/'plan.json',should_stop=lambda: stopped[0])
            self.assertFalse(result);self.assertEqual(plan['status'],'paused_by_user')
            self.assertEqual(plan['items'][0]['status'],'verified')
            self.assertEqual(plan['items'][1]['status'],'pending');self.assertEqual(upload.call_count,1)

    def test_stopped_before_run_never_opens_tiktok(self):
        from clipmac import tiktok_batch,tiktok
        with tempfile.TemporaryDirectory() as directory,patch.object(tiktok,'browser') as browser:
            plan={'account':'demo.clips','items':[]}
            self.assertFalse(tiktok_batch.run(plan,Path(directory)/'plan.json',should_stop=lambda:True))
            browser.assert_not_called()
