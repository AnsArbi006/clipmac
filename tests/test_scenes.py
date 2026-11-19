import unittest

from clipmac.scenes import classify_faces, timeline_from_samples


CORNER = {"cx": .88, "cy": .75, "w": .10, "h": .22, "score": .95}
FULL = {"cx": .49, "cy": .59, "w": .13, "h": .26, "score": .95}


def samples(frames):
    return [{"t": i / 2, "faces": faces} for i, faces in enumerate(frames)]


class SceneTests(unittest.TestCase):
    def test_game_face_does_not_override_corner_camera(self):
        self.assertEqual(classify_faces([FULL, CORNER])[0], "split")

    def test_fullcam_between_gameplay_sections(self):
        seq = samples([[CORNER]] * 8 + [[FULL]] * 8 + [[CORNER]] * 8)
        result = timeline_from_samples(seq, 12)
        self.assertEqual([(s["start"], s["end"], s["mode"]) for s in result],
                         [(0, 4, "split"), (4, 8, "fullcam"), (8, 12, "split")])

    def test_occlusion_and_one_bad_frame_do_not_flicker(self):
        seq = samples([[CORNER]] * 4 + [[]] * 3 + [[FULL]] + [[CORNER]] * 4)
        result = timeline_from_samples(seq, 6)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["mode"], "split")

    def test_large_fullcam_face_not_rejected_as_non_webcam(self):
        huge = {**FULL, "w": .4, "h": .65}
        result = timeline_from_samples(samples([[huge]] * 4), 2)
        self.assertEqual(result[0]["mode"], "fullcam")

    def test_no_detected_faces_uses_main_content(self):
        result = timeline_from_samples(samples([[]] * 8), 4)
        self.assertEqual(result[0]["mode"], "portrait")
        self.assertIsNone(result[0]["face"])

    def test_looking_down_does_not_change_layout(self):
        result = timeline_from_samples(samples([[CORNER]] * 4 + [[]] * 16 + [[CORNER]] * 4), 12)
        self.assertEqual([s["mode"] for s in result], ["split"])
