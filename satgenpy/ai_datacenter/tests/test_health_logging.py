from __future__ import annotations

import io
import json
import logging
import unittest
from datetime import datetime

from prometheus_client import CollectorRegistry

from satgenpy.ai_datacenter import metrics_server
from satgenpy.ai_datacenter.metrics_server import JsonLogFormatter, MetricsController, make_wsgi_application
from satgenpy.ai_datacenter.tests.helpers import BackendTestCase


class HealthEndpointTests(BackendTestCase, unittest.TestCase):
    def test_health_returns_200_and_required_fields(self) -> None:
        status, headers, payload = self.json_request("/health")
        self.assertEqual(status, 200)
        self.assertTrue(headers["Content-Type"].startswith("application/json"))
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["service"], metrics_server.SERVICE_NAME)
        self.assertGreaterEqual(payload["uptime_seconds"], 0)
        datetime.fromisoformat(payload["timestamp"])

    def test_ready_returns_200_when_snapshot_and_metrics_are_loaded(self) -> None:
        status, _, payload = self.json_request("/ready")
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "ready")
        self.assertTrue(payload["snapshot_loaded"])
        self.assertTrue(payload["metrics_ready"])
        self.assertEqual(payload["current_scenario"], "NORMAL_BURST")
        self.assertIn("timestamp", payload)

    def test_ready_returns_503_without_snapshot(self) -> None:
        controller = MetricsController(CollectorRegistry(), "NORMAL_BURST")
        self.app = make_wsgi_application(controller)
        status, _, payload = self.json_request("/ready")
        self.assertEqual(status, 503)
        self.assertEqual(payload["status"], "not_ready")
        self.assertFalse(payload["snapshot_loaded"])
        self.assertFalse(payload["metrics_ready"])

    def test_health_polling_does_not_create_events_or_incidents(self) -> None:
        before = ([event.event_id for event in self.controller.events], [item.incident_id for item in self.controller.incidents])
        for _ in range(3):
            self.json_request("/health")
            self.json_request("/ready")
        after = ([event.event_id for event in self.controller.events], [item.incident_id for item in self.controller.incidents])
        self.assertEqual(after, before)


class StructuredLoggingTests(BackendTestCase, unittest.TestCase):
    def setUp(self) -> None:
        self.stream = io.StringIO()
        self.handler = logging.StreamHandler(self.stream)
        self.handler.setFormatter(JsonLogFormatter())
        self.logger = metrics_server.LOGGER
        self.old_handlers = list(self.logger.handlers)
        self.old_level = self.logger.level
        self.old_propagate = self.logger.propagate
        self.logger.handlers = [self.handler]
        self.logger.setLevel(logging.DEBUG)
        self.logger.propagate = False
        super().setUp()
        self.stream.seek(0)
        self.stream.truncate(0)

    def tearDown(self) -> None:
        self.logger.handlers = self.old_handlers
        self.logger.setLevel(self.old_level)
        self.logger.propagate = self.old_propagate

    def records(self) -> list[dict[str, object]]:
        return [json.loads(line) for line in self.stream.getvalue().splitlines() if line]

    def test_json_log_shape(self) -> None:
        metrics_server._log(logging.INFO, "test_event", "테스트", scenario="NORMAL_BURST")
        record = self.records()[0]
        self.assertTrue({"timestamp", "level", "component", "event_type", "message"}.issubset(record))
        self.assertEqual(record["event_type"], "test_event")
        self.assertEqual(record["scenario"], "NORMAL_BURST")
        datetime.fromisoformat(record["timestamp"])

    def test_scenario_change_log_emission(self) -> None:
        self.controller.set_scenario("MULTI_FAILED_ISL_0_1_10_11_BURST")
        records = self.records()
        self.assertTrue(any(item["event_type"] == "scenario_changed" and item["scenario"] == "MULTI_FAILED_ISL_0_1_10_11_BURST" for item in records))

    def test_incident_lifecycle_log_emission(self) -> None:
        self.controller.set_scenario("MULTI_FAILED_ISL_0_1_10_11_BURST")
        incident_id = self.controller.incidents[0].incident_id
        self.controller.acknowledge_incident(incident_id)
        self.controller.set_scenario("NORMAL_BURST")
        event_types = [item["event_type"] for item in self.records()]
        self.assertIn("incident_created", event_types)
        self.assertIn("incident_acknowledged", event_types)
        self.assertIn("incident_resolved", event_types)

    def test_api_error_log_does_not_include_request_body(self) -> None:
        secret = "do-not-log-this-secret"
        status, _, _ = self.request("/api/scenario", method="POST", body=json.dumps({"secret": secret}).encode())
        self.assertEqual(status, 400)
        output = self.stream.getvalue()
        self.assertNotIn(secret, output)
        record = self.records()[-1]
        self.assertEqual(record["event_type"], "api_error")
        self.assertEqual(record["status_code"], 400)
        self.assertEqual(record["method"], "POST")
        self.assertEqual(record["path"], "/api/scenario")


if __name__ == "__main__":
    unittest.main()
