import tempfile
import unittest
from pathlib import Path

from clipmac.captions import groups, layout, write_subtitles


class CaptionTests(unittest.TestCase):
    def transcript(self, words):
        return {'segments':[{'words':words}]}

    def test_pauses_punctuation_and_long_german_words(self):
        t=self.transcript([{'word':w,'start':a,'end':b} for w,a,b in
            [('Wirklich?',0,.4),('Ja',.5,.8),('Krankenhausverwaltung',2,2.8),('funktioniert',2.9,3.3)]])
        g=groups(t)
        self.assertEqual([len(x) for x in g],[1,1,2])
        for group in g:
            for p in layout(group):
                self.assertGreaterEqual(p['x']-p['width']/2-14,80)
                self.assertLessEqual(p['x']+p['width']/2+14,930)
                self.assertLess(p['y']+48,1550)

    def test_bad_timestamps_overlap_and_ass_injection(self):
        t=self.transcript([{'word':'Hallo','start':0,'end':1},
            {'word':r'{\pos(0,0)}Welt','start':.5,'end':1.3},
            {'word':'invalid','start':float('nan'),'end':2}])
        g=groups(t)
        self.assertEqual(g[0][0]['end'],.5)
        self.assertEqual(sum(map(len,g)),2)
        self.assertNotIn('\\',g[0][1]['word'])

    def test_word_highlights_and_plain_srt_share_real_timing(self):
        t=self.transcript([{'word':'Das','start':1,'end':1.3},{'word':'passt!','start':1.4,'end':2}])
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'captions.ass'; info=write_subtitles(path,t); ass=path.read_text();srt=path.with_suffix('.srt').read_text()
            self.assertIn('Dialogue: 2,0:00:01.00,0:00:01.40',ass)
            self.assertIn('Dialogue: 2,0:00:01.40,0:00:02.00',ass)
            self.assertEqual(info['words'],2)
            self.assertIn('Das passt!',srt)
            self.assertNotIn('\\pos',srt)
            self.assertIn('\\t(0,70,',ass)

    def test_no_fabricated_word_timing_when_words_missing(self):
        self.assertEqual(groups({'segments':[{'text':'Kein Wortzeitpunkt','start':1,'end':4}]}),[])


if __name__ == '__main__':
    unittest.main()
