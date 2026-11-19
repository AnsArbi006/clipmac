import unittest

from clipmac.layout import portrait_layout


class PortraitLayoutTests(unittest.TestCase):
    def test_corner_faces_stay_inside_source_without_squashing(self):
        for face in ({"x": .01, "y": .74, "w": .09, "h": .21},
                     {"x": .78, "y": .52, "w": .21, "h": .48}):
            for share in (1 / 3, .5):
                plan = portrait_layout(1920, 1080, face, share)
                self.assertEqual(plan["mode"], "split")
                self.assertEqual(plan["camera_height"], 640 if share == 1 / 3 else 960)
                for key, height in (("camera", plan["camera_height"]), ("content", 1920-plan["camera_height"])):
                    c = plan[key]
                    self.assertGreaterEqual(c["x"], 0)
                    self.assertGreaterEqual(c["y"], 0)
                    self.assertLessEqual(c["x"] + c["w"], 1920)
                    self.assertLessEqual(c["y"] + c["h"], 1080)
                    self.assertAlmostEqual(c["w"] / c["h"], 1080 / height, delta=.015)
                camera = plan["camera"]
                self.assertGreaterEqual(camera["h"], int(face["h"] * 1080) - 2)

    def test_full_camera_is_not_duplicated(self):
        plan = portrait_layout(1920, 1080, {"x": .40, "y": .41, "w": .18, "h": .38})
        self.assertEqual(plan["mode"], "portrait")
        self.assertIsNone(plan["camera"])

    def test_no_face_still_fills_portrait_frame(self):
        plan = portrait_layout(1920, 1080, None)
        self.assertEqual(plan["mode"], "portrait")
        self.assertAlmostEqual(plan["content"]["w"] / plan["content"]["h"], 1080 / 1920, delta=.002)
