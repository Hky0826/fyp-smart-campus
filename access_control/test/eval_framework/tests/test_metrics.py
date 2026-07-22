import sys
import os
import unittest
import numpy as np

# Ensure eval_framework directory is in sys.path
eval_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if eval_dir not in sys.path:
    sys.path.insert(0, eval_dir)

from metrics import calculate_metrics, calculate_eer, get_tar_at_far

class TestMetrics(unittest.TestCase):
    def setUp(self):
        # 10 samples: 5 genuine, 5 impostor
        self.labels = [1, 1, 1, 1, 1, 0, 0, 0, 0, 0]
        # Perfect separation for testing
        self.scores_perfect = [0.9, 0.85, 0.8, 0.75, 0.7, 0.3, 0.25, 0.2, 0.15, 0.1]
        # Some overlap
        self.scores_overlap = [0.9, 0.8, 0.7, 0.4, 0.2, 0.85, 0.6, 0.3, 0.2, 0.1]
        
    def test_calculate_metrics(self):
        res = calculate_metrics(self.labels, self.scores_perfect, threshold=0.5)
        # Threshold 0.5: All genuine > 0.5, all impostor < 0.5
        self.assertEqual(res["FAR"], 0.0) # 0 FP
        self.assertEqual(res["FRR"], 0.0) # 0 FN
        self.assertEqual(res["TAR"], 1.0)
        self.assertEqual(res["TRR"], 1.0)

    def test_calculate_metrics_overlap(self):
        res = calculate_metrics(self.labels, self.scores_overlap, threshold=0.5)
        # Genuine >= 0.5: 0.9, 0.8, 0.7 -> 3 TP. Genuine < 0.5: 0.4, 0.2 -> 2 FN
        # Impostor >= 0.5: 0.85, 0.6 -> 2 FP. Impostor < 0.5: 0.3, 0.2, 0.1 -> 3 TN
        self.assertAlmostEqual(res["FAR"], 2/5)
        self.assertAlmostEqual(res["FRR"], 2/5)
        self.assertAlmostEqual(res["TAR"], 3/5)
        self.assertAlmostEqual(res["TRR"], 3/5)

    def test_calculate_eer_perfect(self):
        eer, eer_threshold, fpr, tpr, thresholds = calculate_eer(self.labels, self.scores_perfect)
        self.assertAlmostEqual(eer, 0.0)
        self.assertTrue(eer_threshold >= 0.3 and eer_threshold <= 0.7)

    def test_calculate_eer_overlap(self):
        eer, eer_threshold, fpr, tpr, thresholds = calculate_eer(self.labels, self.scores_overlap)
        # Minimum difference between FPR and FNR
        # Let's just ensure it computes a float between 0 and 1
        self.assertGreaterEqual(eer, 0.0)
        self.assertLessEqual(eer, 1.0)
        
    def test_get_tar_at_far(self):
        eer, eer_threshold, fpr, tpr, thresholds = calculate_eer(self.labels, self.scores_perfect)
        res = get_tar_at_far(fpr, tpr, [0.1, 0.01])
        # Perfect separation means TAR should be 1.0 at any FAR > 0
        self.assertAlmostEqual(res["TAR_at_FAR_0.1"], 1.0)
        self.assertAlmostEqual(res["TAR_at_FAR_0.01"], 1.0)

if __name__ == "__main__":
    unittest.main()
