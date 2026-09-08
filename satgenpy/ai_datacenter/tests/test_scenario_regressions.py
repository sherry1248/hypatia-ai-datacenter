from __future__ import annotations

import unittest

from satgenpy.ai_datacenter.metrics_server import evaluate_operational_alert, load_metrics_snapshot


class SavedScenarioRegressionTests(unittest.TestCase):
    def test_normal_saved_snapshot(self) -> None:
        snapshot = load_metrics_snapshot("NORMAL_BURST")
        self.assertEqual(snapshot.jobs_total, 300)
        self.assertEqual(snapshot.jobs_placed_total, 300)
        self.assertEqual(snapshot.jobs_unplaced_total, 0)
        self.assertEqual(snapshot.failed_links, 0)
        self.assertAlmostEqual(snapshot.placement_success_ratio, 1.0)
        self.assertEqual(evaluate_operational_alert(snapshot).severity, "normal")

    def test_multi_failure_saved_snapshot_counts_and_node_state(self) -> None:
        snapshot = load_metrics_snapshot("MULTI_FAILED_ISL_0_1_10_11_BURST")
        self.assertEqual(snapshot.jobs_total, 300)
        self.assertEqual(snapshot.jobs_placed_total, 289)
        self.assertEqual(snapshot.jobs_unplaced_total, 11)
        self.assertEqual(snapshot.failed_links, 2)
        self.assertAlmostEqual(snapshot.placement_success_ratio, 289 / 300)
        self.assertEqual(snapshot.node_available[7], 0)
        self.assertEqual(snapshot.node_jobs_total[7], 0)
        self.assertEqual(evaluate_operational_alert(snapshot).severity, "critical")

    def test_multi_failure_timing_metrics_with_tolerances(self) -> None:
        snapshot = load_metrics_snapshot("MULTI_FAILED_ISL_0_1_10_11_BURST")
        self.assertAlmostEqual(snapshot.average_queue_wait_seconds, 55.29, delta=0.01)
        self.assertAlmostEqual(snapshot.maximum_queue_wait_seconds, 109.33, delta=0.01)
        self.assertAlmostEqual(snapshot.average_total_time_seconds, 57.05, delta=0.01)


if __name__ == "__main__":
    unittest.main()
