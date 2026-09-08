from __future__ import annotations

import csv
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from prometheus_client import CollectorRegistry, generate_latest

from satgenpy.ai_datacenter.dynamic_scenario import (
    DynamicScenarioError,
    SimulationClock,
    parse_scenario,
    simulate_dynamic_scenario,
)
from satgenpy.ai_datacenter.experiment_runner import (
    aggregate_recovery_summary,
    execute_run,
    main as runner_main,
)
from satgenpy.ai_datacenter.metrics_server import MetricsController, make_wsgi_application
from satgenpy.ai_datacenter.tests.helpers import BackendTestCase


class DynamicScenarioTests(unittest.TestCase):
    def setUp(self) -> None:
        self.payload = {
            "name": "test_recovery", "duration_seconds": 30, "tick_seconds": 1,
            "events": [
                {"event_id": "failure", "time_seconds": 10, "type": "link_failure", "target": "0-1"},
                {"event_id": "recovery", "time_seconds": 20, "type": "link_recovery", "target": "0-1"},
            ],
        }

    def test_dynamic_scenario_validation(self) -> None:
        for change, message in (
            ({"events": [{"event_id": "x", "time_seconds": -1, "type": "link_failure", "target": "0-1"}]}, "범위를"),
            ({"events": [{"event_id": "x", "time_seconds": 31, "type": "link_failure", "target": "0-1"}]}, "범위를"),
            ({"events": [{"event_id": "x", "time_seconds": 1, "type": "unknown", "target": "0-1"}]}, "지원하지"),
            ({"events": [{"event_id": "x", "time_seconds": 1, "type": "link_failure", "target": "bad"}]}, "target"),
        ):
            with self.subTest(message=message), self.assertRaisesRegex(DynamicScenarioError, message):
                parse_scenario({**self.payload, **change})

    def test_duplicate_ids_and_failure_before_recovery(self) -> None:
        duplicate = {**self.payload, "events": [self.payload["events"][0], {**self.payload["events"][1], "event_id": "failure"}]}
        with self.assertRaisesRegex(DynamicScenarioError, "중복"):
            parse_scenario(duplicate)
        recovery_first = {**self.payload, "events": [{"event_id": "r", "time_seconds": 1, "type": "node_recovery", "target": "7"}]}
        with self.assertRaisesRegex(DynamicScenarioError, "matching failure"):
            parse_scenario(recovery_first)

    def test_deterministic_event_ordering(self) -> None:
        payload = {**self.payload, "events": [
            {"event_id": "z", "time_seconds": 10, "type": "link_failure", "target": "0-1"},
            {"event_id": "a", "time_seconds": 10, "type": "node_failure", "target": "7"},
            {"event_id": "rz", "time_seconds": 20, "type": "link_recovery", "target": "0-1"},
            {"event_id": "ra", "time_seconds": 20, "type": "node_recovery", "target": "7"},
        ]}
        self.assertEqual([event.event_id for event in parse_scenario(payload).events], ["z", "a", "rz", "ra"])

    def test_clock_is_independent_of_wall_time(self) -> None:
        with patch("time.time", return_value=999999999):
            clock = SimulationClock(5, 2)
            self.assertEqual(clock.ticks(), [0.0, 2.0, 4.0, 5.0])
            self.assertEqual(clock.detection_time(2.1), 4.0)

    def test_phase_transitions_recovery_and_job_classification(self) -> None:
        result = simulate_dynamic_scenario(parse_scenario(self.payload), "completion_time", "demo", 3)
        phases = {row["phase"] for row in result["timeline"]}
        self.assertEqual(phases, {"healthy", "degraded", "rerouting", "recovering"})
        self.assertEqual(result["operational_phase"], "healthy")
        self.assertEqual(result["failures"][0]["status"], "resolved")
        periods = {row["failure_period"] for row in result["jobs"]}
        self.assertEqual(periods, {"before", "during", "after"})

    def test_static_scenario_backward_compatibility(self) -> None:
        row = execute_run("normal", "completion_time", "demo", 0)
        self.assertEqual(row["dynamic_scenario"], False)
        self.assertEqual(row["failure_event_count"], 0)
        self.assertEqual(row["jobs_total"], 100)

    def test_experiment_runner_dynamic_output_and_recovery_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, redirect_stdout(io.StringIO()):
            root = Path(temporary)
            scenario_path = root / "scenario.json"
            scenario_path.write_text(json.dumps(self.payload), encoding="utf-8")
            output = root / "output"
            code = runner_main(["--dynamic-scenario", str(scenario_path), "--policies", "completion_time", "--workloads", "demo", "--seeds", "0", "--output", str(output)])
            self.assertEqual(code, 0)
            with (output / "runs.csv").open(newline="") as handle:
                row = next(csv.DictReader(handle))
            self.assertEqual(row["dynamic_scenario"], "True")
            self.assertEqual(row["failure_event_count"], "1")
            self.assertTrue((output / "recovery_summary.csv").is_file())

    def test_recovery_summary_aggregation(self) -> None:
        rows = [
            {"scenario": "d", "policy": "p", "workload": "w", "status": "success", "dynamic_scenario": True,
             "detection_time_seconds": value, "reroute_time_seconds": 1, "service_recovery_time_seconds": 10,
             "jobs_unplaced_during_failure": 0, "retry_success_ratio": ""}
            for value in (1, 3)
        ]
        summary = aggregate_recovery_summary(rows)[0]
        self.assertEqual(summary["detection_time_seconds_mean"], 2)
        self.assertEqual(summary["detection_time_seconds_p95"], 3)


class DynamicBackendTests(BackendTestCase, unittest.TestCase):
    def setUp(self) -> None:
        BackendTestCase.setUp(self)
        payload = {
            "name": "api_dynamic", "duration_seconds": 30, "tick_seconds": 1,
            "events": [
                {"event_id": "failure", "time_seconds": 10, "type": "link_failure", "target": "0-1"},
                {"event_id": "recovery", "time_seconds": 20, "type": "link_recovery", "target": "0-1"},
            ],
        }
        self.result = simulate_dynamic_scenario(parse_scenario(payload), "completion_time", "demo", 0)
        self.controller.apply_dynamic_result(self.result)

    def test_dynamic_api_fields_and_failure_history(self) -> None:
        status, _, payload = self.json_request("/api/status")
        self.assertEqual(status, 200)
        for key in ("simulation_time_seconds", "operational_phase", "active_failures", "current_failure_ids", "last_failure", "last_recovery", "recovery_metrics"):
            self.assertIn(key, payload)
        status, _, failures = self.json_request("/api/failures")
        self.assertEqual(status, 200)
        self.assertEqual(failures["total"], 1)
        failure_id = failures["failures"][0]["failure_id"]
        status, _, detail = self.json_request(f"/api/failures/{failure_id}")
        self.assertEqual((status, detail["status"]), (200, "resolved"))

    def test_prometheus_recovery_metrics(self) -> None:
        metrics = self.controller.render_metrics().decode()
        for name in (
            "space_ai_datacenter_active_failures", "space_ai_datacenter_operational_phase",
            "space_ai_datacenter_failure_detection_seconds", "space_ai_datacenter_reroute_seconds",
            "space_ai_datacenter_service_recovery_seconds", "space_ai_datacenter_jobs_unplaced_during_failure",
            "space_ai_datacenter_retry_success_ratio",
        ):
            self.assertIn(name, metrics)


if __name__ == "__main__":
    unittest.main()
