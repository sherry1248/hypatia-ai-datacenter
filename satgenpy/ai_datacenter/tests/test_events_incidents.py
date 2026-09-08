from __future__ import annotations

import unittest

from satgenpy.ai_datacenter.tests.helpers import BackendTestCase


class EventTests(BackendTestCase, unittest.TestCase):
    def test_repeated_reads_and_refresh_do_not_duplicate_events(self) -> None:
        initial_ids = [event.event_id for event in self.controller.events]
        self.json_request("/api/status")
        self.json_request("/api/events")
        self.controller.refresh()
        self.assertEqual([event.event_id for event in self.controller.events], initial_ids)

    def test_event_filters_and_limit(self) -> None:
        self.controller.set_scenario("MULTI_FAILED_ISL_0_1_10_11_BURST")
        for key, value in (("level", "critical"), ("category", "network")):
            status, _, payload = self.json_request("/api/events", query={key: value})
            self.assertEqual(status, 200)
            self.assertTrue(payload["events"])
            self.assertTrue(all(event[key] == value for event in payload["events"]))
        _, _, limited = self.json_request("/api/events", query={"limit": 2})
        self.assertEqual(len(limited["events"]), 2)
        self.assertEqual(limited["limit"], 2)

    def test_invalid_event_filters_and_limits_return_400(self) -> None:
        for query in ({"level": "bad"}, {"category": "bad"}, {"limit": 0}, {"limit": 501}, {"limit": "x"}):
            with self.subTest(query=query):
                self.assertEqual(self.json_request("/api/events", query=query)[0], 400)


class IncidentLifecycleTests(BackendTestCase, unittest.TestCase):
    def create_incident(self) -> str:
        self.controller.set_scenario("MULTI_FAILED_ISL_0_1_10_11_BURST")
        return self.controller.incidents[0].incident_id

    def test_one_transition_groups_related_problems_into_one_incident(self) -> None:
        incident_id = self.create_incident()
        self.assertEqual(len(self.controller.incidents), 1)
        incident = self.controller.incident_detail_response(incident_id)
        assert incident is not None
        self.assertIn("장애 링크 2개 활성", incident["causes"])
        self.assertIn("연산 노드 SAT-7 사용 불가", incident["causes"])
        self.assertEqual(incident["affected_job_count"], 11)
        self.assertGreaterEqual(len(incident["related_event_ids"]), 3)

    def test_repeated_polling_and_refresh_do_not_duplicate_incidents(self) -> None:
        incident_id = self.create_incident()
        self.json_request("/api/incidents")
        self.json_request(f"/api/incidents/{incident_id}")
        self.controller.refresh()
        self.assertEqual([item.incident_id for item in self.controller.incidents], [incident_id])

    def test_open_acknowledged_resolved_lifecycle_and_history(self) -> None:
        incident_id = self.create_incident()
        self.assertEqual(self.controller.incidents[0].status, "open")
        status, _, acknowledged = self.json_request(f"/api/incidents/{incident_id}/acknowledge", method="POST")
        self.assertEqual((status, acknowledged["status"]), (200, "acknowledged"))
        self.assertIsNone(acknowledged["resolved_at"])
        acknowledged_at = acknowledged["acknowledged_at"]

        _, _, second = self.json_request(f"/api/incidents/{incident_id}/acknowledge", method="POST")
        self.assertEqual(second["acknowledged_at"], acknowledged_at)
        self.assertEqual(self.controller.incident_acknowledged_count, 1)

        self.controller.set_scenario("NORMAL_BURST")
        _, _, resolved = self.json_request(f"/api/incidents/{incident_id}")
        self.assertEqual(resolved["status"], "resolved")
        self.assertIsNotNone(resolved["resolved_at"])
        _, _, history = self.json_request("/api/incidents", query={"status": "resolved"})
        self.assertEqual([item["incident_id"] for item in history["incidents"]], [incident_id])

    def test_unknown_incident_get_and_acknowledge_return_404(self) -> None:
        for method, path in (("GET", "/api/incidents/INC-9999"), ("POST", "/api/incidents/INC-9999/acknowledge")):
            with self.subTest(method=method):
                status, _, payload = self.json_request(path, method=method)
                self.assertEqual(status, 404)
                self.assertEqual(payload, {"error": "알 수 없는 인시던트입니다."})


if __name__ == "__main__":
    unittest.main()
