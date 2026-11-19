import tempfile
import unittest
from pathlib import Path

from clipmac.state import Store, DEFAULTS, atomic_json
from clipmac.tiktok_schedule import next_pack


class MirrorTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.store=Store(self.root/'queue.db')
        self.cfg={**DEFAULTS,'publish_batch_size':5,'publish_batch_interval_minutes':60}
        for b in (1,2):
            with self.store.db() as db:db.execute('INSERT INTO publish_batches VALUES (?,?,?)',(b,100,200))
            for n in range(5):
                cid=f'clip{b}{n}';self.store.add({'id':cid});self.store.update(cid,'published')
                with self.store.db() as db:db.execute('INSERT INTO publish_batch_items VALUES (?,?,?,?)',(b,n,cid,'aaa'))
        self.store.add({'id':'unrelated'});self.store.update('unrelated','published')

    def plan(self, now=10000):
        return next_pack(self.store,self.root,'test.account',self.cfg,now)

    def receipt(self,cid,status='verified',at=10000):
        atomic_json(self.root/'test.account'/f'{cid}.json',{'status':status,'verified_at':at})

    def test_exact_first_pack_and_no_legacy_backlog(self):
        self.assertEqual(self.plan()['ids'],[f'clip1{n}' for n in range(5)])

    def test_only_complete_youtube_packs_are_mirrored(self):
        self.store.update('clip14','ready')
        self.assertEqual(self.plan()['ids'],[])

    def test_hour_after_last_tiktok_confirmation_and_no_duplicates(self):
        for n in range(5):self.receipt(f'clip1{n}',at=10000+n)
        self.assertEqual(self.plan(13603)['ids'],[])
        self.assertEqual(self.plan(13604)['ids'],[f'clip2{n}' for n in range(5)])

    def test_partial_resume_never_reposts_accepted_or_under_review(self):
        self.receipt('clip10');self.receipt('clip11','pending_review')
        self.assertEqual(self.plan()['ids'],['clip12','clip13','clip14'])
        self.receipt('clip12','upload_unknown')
        self.assertTrue(self.plan()['blocked'])

    def test_report_and_wrong_category_are_not_uploaded(self):
        self.store.add_report('clip10','Falsche Kamera',None,self.cfg)
        self.assertNotIn('clip10',self.plan()['ids'])
        self.cfg['required_game_id']='1867279146'
        self.assertEqual(self.plan()['ids'],[])


if __name__=='__main__':unittest.main()
