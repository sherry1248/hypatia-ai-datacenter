from __future__ import annotations

import re
import unittest

from satgenpy.ai_datacenter.tests.helpers import BackendTestCase


def metric_value(text: str, name: str, labels: str = "") -> float:
    match = re.search(rf"^{re.escape(name)}{re.escape(labels)} ([^\n]+)$", text, re.MULTILINE)
    if match is None:
        raise AssertionError(f"metric not found: {name}{labels}")
    return float(match.group(1))


class PrometheusConsistencyTests(BackendTestCase, unittest.TestCase):
    def test_metrics_and_status_share_one_active_snapshot(self) -> None:
        self.controller.set_scenario("MULTI_FAILED_ISL_0_1_10_11_BURST")
        _, _, status = self.json_request("/api/status")
        _, _, raw_metrics = self.request("/metrics")
        metrics = raw_metrics.decode("utf-8")

        mappings = {
            "jobs_total": "jobs_total",
            "jobs_placed": "jobs_placed_total",
            "jobs_unplaced": "jobs_unplaced_total",
            "placement_success_ratio": "placement_success_ratio",
            "failed_links": "failed_links",
        }
        for api_name, metric_name in mappings.items():
            with self.subTest(metric=metric_name):
                self.assertAlmostEqual(
                    metric_value(metrics, f"space_ai_datacenter_{metric_name}"),
                    float(status[api_name]),
                )
        unavailable = sum(not node["available"] for node in status["nodes"])
        self.assertEqual(metric_value(metrics, "space_ai_datacenter_unavailable_nodes"), unavailable)
        self.assertEqual(metric_value(metrics, "space_ai_datacenter_active_incidents"), status["active_incident_count"])

        severity_values = {
            severity: metric_value(metrics, "space_ai_datacenter_alert_severity", f'{{severity="{severity}"}}')
            for severity in ("normal", "warning", "critical")
        }
        self.assertEqual(sum(value == 1 for value in severity_values.values()), 1)
        self.assertEqual(severity_values[status["severity"]], 1)
        self.assertEqual(sorted(severity_values.values()), [0, 0, 1])


if __name__ == "__main__":
    unittest.main()
