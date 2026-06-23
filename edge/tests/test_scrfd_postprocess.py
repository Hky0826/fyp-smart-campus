import unittest

import numpy as np

from edge.src.hailo.postprocess_scrfd import postprocess_scrfd
from edge.src.hailo.preprocess import preprocess_arcface, preprocess_scrfd


class SCRFDPostprocessTests(unittest.TestCase):
    def test_preprocess_keeps_scrfd_pixels_in_hailo_range(self):
        frame = np.array([[[10, 20, 30]]], dtype=np.uint8)

        tensor = preprocess_scrfd(frame, input_size=(1, 1))

        self.assertEqual(tensor.dtype, np.float32)
        self.assertEqual(tensor.shape, (1, 1, 1, 3))
        np.testing.assert_allclose(tensor[0, 0, 0], [30.0, 20.0, 10.0])

    def test_preprocess_keeps_arcface_pixels_in_hailo_range(self):
        crop = np.array([[[10, 20, 30]]], dtype=np.uint8)

        tensor = preprocess_arcface(crop, input_size=(1, 1))

        self.assertEqual(tensor.dtype, np.float32)
        self.assertEqual(tensor.shape, (1, 1, 1, 3))
        np.testing.assert_allclose(tensor[0, 0, 0], [30.0, 20.0, 10.0])

    def test_parses_hailo_detection_outputs(self):
        outputs = {
            "scrfd/detection_boxes": np.array([[[0.10, 0.20, 0.40, 0.60]]], dtype=np.float32),
            "scrfd/detection_scores": np.array([[0.90]], dtype=np.float32),
            "scrfd/num_detections": np.array([1], dtype=np.float32),
        }

        faces = postprocess_scrfd(outputs, original_shape=(100, 200), confidence_threshold=0.6)

        self.assertEqual(len(faces), 1)
        np.testing.assert_allclose(faces[0].bbox, [40.0, 10.0, 120.0, 40.0])
        self.assertAlmostEqual(faces[0].confidence, 0.9, places=5)

    def test_decodes_raw_hwc_scrfd_heads(self):
        scores = np.zeros((80, 80, 2), dtype=np.float32)
        boxes = np.zeros((80, 80, 8), dtype=np.float32)
        landmarks = np.zeros((80, 80, 20), dtype=np.float32)
        scores[20, 30, 0] = 0.95
        boxes[20, 30, 0:4] = [5.0, 6.0, 7.0, 8.0]
        landmarks[20, 30, 0:10] = [-2.0, -2.0, 2.0, -2.0, 0.0, 0.0, -1.5, 2.0, 1.5, 2.0]
        outputs = {
            "scrfd/stride8/bbox": boxes,
            "scrfd/stride8/class": scores,
            "scrfd/stride8/landmark": landmarks,
        }

        faces = postprocess_scrfd(outputs, original_shape=(480, 640), input_size=(640, 640), confidence_threshold=0.6)

        self.assertEqual(len(faces), 1)
        np.testing.assert_allclose(faces[0].bbox, [200.0, 84.0, 296.0, 168.0])
        self.assertAlmostEqual(faces[0].confidence, 0.95, places=5)
        self.assertEqual(faces[0].landmarks.shape, (5, 2))

    def test_decodes_raw_flat_scrfd_heads(self):
        scores = np.zeros((12800, 1), dtype=np.float32)
        boxes = np.zeros((12800, 4), dtype=np.float32)
        scores[100, 0] = 0.91
        boxes[100] = [2.0, 3.0, 4.0, 5.0]
        outputs = {
            "score_8": scores,
            "bbox_8": boxes,
        }

        faces = postprocess_scrfd(outputs, original_shape=(640, 640), input_size=(640, 640), confidence_threshold=0.6)

        self.assertEqual(len(faces), 1)
        self.assertAlmostEqual(faces[0].confidence, 0.91, places=5)
        self.assertEqual(faces[0].xyxy_int(), [384, 0, 432, 40])


if __name__ == "__main__":
    unittest.main()
