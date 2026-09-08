from __future__ import annotations

import unittest

from satgenpy.ai_datacenter.tests.helpers import BackendTestCase


class ApiEndpointTests(BackendTestCase, unittest.TestCase):
    def assert_json_ok(self, path: str, required: set[str]) -> dict[str, object]:
        status, headers, payload = self.json_request(path)
        self.assertEqual(status, 200)
        self.assertTrue(headers["Content-Type"].startswith("application/json"))
        self.assertTrue(required.issubset(payload))
        return payload

    def test_status_nodes_node_and_jobs_endpoints(self) -> None:
        self.assert_json_ok("/api/status", {"scenario", "jobs_total", "jobs_placed", "jobs_unplaced", "severity", "nodes", "updated_at"})
        nodes = self.assert_json_ok("/api/nodes", {"nodes", "updated_at"})
        self.assertEqual({item["node"] for item in nodes["nodes"]}, {0, 3, 7})
        detail = self.assert_json_ok("/api/nodes/0", {"node", "jobs", "events", "updated_at"})
        self.assertTrue({"node", "label", "available", "jobs", "status_label"}.issubset(detail["node"]))
        jobs = self.assert_json_ok("/api/jobs", {"jobs", "total", "limit", "updated_at"})
        self.assertTrue({"job_id", "status", "assigned_node", "deadline_met"}.issubset(jobs["jobs"][0]))

    def test_events_incidents_detail_acknowledge_and_metrics_endpoints(self) -> None:
        self.controller.set_scenario("MULTI_FAILED_ISL_0_1_10_11_BURST")
        events = self.assert_json_ok("/api/events", {"events", "total", "limit"})
        self.assertTrue({"event_id", "timestamp", "level", "category", "message"}.issubset(events["events"][0]))
        incidents = self.assert_json_ok("/api/incidents", {"incidents", "total", "limit"})
        incident_id = incidents["incidents"][0]["incident_id"]
        detail = self.assert_json_ok(f"/api/incidents/{incident_id}", {"incident_id", "status", "severity", "causes", "events"})
        self.assertEqual(detail["incident_id"], incident_id)
        status, headers, acknowledged = self.json_request(f"/api/incidents/{incident_id}/acknowledge", method="POST")
        self.assertEqual((status, acknowledged["status"]), (200, "acknowledged"))
        self.assertTrue(headers["Content-Type"].startswith("application/json"))

        status, headers, metrics = self.request("/metrics")
        self.assertEqual(status, 200)
        self.assertTrue(headers["Content-Type"].startswith("text/plain"))
        self.assertIn(b"space_ai_datacenter_jobs_total", metrics)

    def test_unknown_node_returns_korean_json_error(self) -> None:
        status, headers, payload = self.json_request("/api/nodes/99")
        self.assertEqual(status, 404)
        self.assertTrue(headers["Content-Type"].startswith("application/json"))
        self.assertEqual(payload, {"error": "알 수 없는 연산 노드입니다: SAT-99"})

    def test_job_status_node_and_limit_filters(self) -> None:
        self.controller.set_scenario("MULTI_FAILED_ISL_0_1_10_11_BURST")
        expected_status = {"placed": "PLACED", "unplaced": "UNPLACED"}
        for requested, stored in expected_status.items():
            _, _, payload = self.json_request("/api/jobs", query={"status": requested})
            self.assertTrue(payload["jobs"])
            self.assertTrue(all(job["status"] == stored for job in payload["jobs"]))
        _, _, missed = self.json_request("/api/jobs", query={"status": "deadline_missed"})
        self.assertTrue(missed["jobs"])
        self.assertTrue(all(job["deadline_met"] is False for job in missed["jobs"]))
        _, _, by_node = self.json_request("/api/jobs", query={"node": 3, "limit": 7})
        self.assertEqual(len(by_node["jobs"]), 7)
        self.assertTrue(all(job["assigned_node"] == 3 for job in by_node["jobs"]))

    def test_job_default_and_maximum_limits(self) -> None:
        _, _, default = self.json_request("/api/jobs")
        self.assertEqual((default["limit"], len(default["jobs"])), (50, 50))
        _, _, maximum = self.json_request("/api/jobs", query={"limit": 500})
        self.assertEqual((maximum["limit"], len(maximum["jobs"])), (500, 300))
        self.assertEqual(self.json_request("/api/jobs", query={"limit": 501})[0], 400)


if __name__ == "__main__":
    unittest.main()
