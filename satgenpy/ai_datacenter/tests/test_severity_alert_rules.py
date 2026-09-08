from __future__ import annotations

import unittest

from satgenpy.ai_datacenter.metrics_server import evaluate_operational_alert, load_metrics_snapshot

from satgenpy.ai_datacenter.tests.helpers import snapshot_with


class SeverityAlertRuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.normal = load_metrics_snapshot("NORMAL_BURST")

    def test_normal_conditions_and_korean_label(self) -> None:
        alert = evaluate_operational_alert(self.normal)
        self.assertEqual((alert.severity, alert.severity_label, alert.reasons), ("normal", "정상", ()))

    def test_warning_rules_and_deterministic_reason_order(self) -> None:
        snapshot = snapshot_with(
            self.normal,
            node_available={0: 1, 3: 0, 7: 1},
            average_queue_wait_seconds=30.0,
            failed_links=2,
        )
        alert = evaluate_operational_alert(snapshot)
        self.assertEqual(alert.severity, "warning")
        self.assertEqual(alert.severity_label, "주의")
        self.assertEqual(
            alert.reasons,
            (
                "연산 노드 SAT-3 사용 불가",
                "평균 큐 대기시간 30.00초로 주의 임계값 도달",
                "장애 링크 2개 감지",
            ),
        )

    def test_each_warning_condition(self) -> None:
        cases = (
            {"node_available": {0: 0, 3: 1, 7: 1}},
            {"average_queue_wait_seconds": 59.99},
            {"failed_links": 1},
        )
        for changes in cases:
            with self.subTest(changes=changes):
                self.assertEqual(evaluate_operational_alert(snapshot_with(self.normal, **changes)).severity, "warning")

    def test_each_critical_condition(self) -> None:
        cases = (
            {"jobs_unplaced_total": 1},
            {"placement_success_ratio": 0.949},
            {"average_queue_wait_seconds": 60.0},
        )
        for changes in cases:
            with self.subTest(changes=changes):
                alert = evaluate_operational_alert(snapshot_with(self.normal, **changes))
                self.assertEqual((alert.severity, alert.severity_label), ("critical", "심각"))

    def test_critical_reasons_precede_warning_reasons_deterministically(self) -> None:
        snapshot = snapshot_with(
            self.normal,
            jobs_unplaced_total=2,
            placement_success_ratio=0.90,
            average_queue_wait_seconds=60.0,
            node_available={0: 1, 3: 1, 7: 0},
            failed_links=1,
        )
        self.assertEqual(
            evaluate_operational_alert(snapshot).reasons,
            (
                "미배치 작업 2개 발생",
                "배치 성공률 90.00%로 임계값 미만",
                "평균 큐 대기시간 60.00초로 심각 임계값 도달",
                "연산 노드 SAT-7 사용 불가",
                "장애 링크 1개 감지",
            ),
        )


if __name__ == "__main__":
    unittest.main()
