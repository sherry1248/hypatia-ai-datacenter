from __future__ import annotations

import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from satgenpy.ai_datacenter import experiment_report as report


class ExperimentReportTests(unittest.TestCase):
    def test_required_file_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, self.assertRaisesRegex(report.ReportError, "필수 입력 파일 누락"):
            report.load_inputs(Path(temporary))

    def test_required_column_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = self._fixture(Path(temporary))
            (source / "summary.csv").write_text("scenario,policy\nnormal,p\n", encoding="utf-8")
            with self.assertRaisesRegex(report.ReportError, "필수 열 누락"):
                report.load_inputs(source)

    def test_percentage_points_and_percentage_change(self) -> None:
        ratio = report.calculate_change("placement_success_ratio", 0.8, 0.7)
        duration = report.calculate_change("p95_total_time_seconds", 10, 12)
        self.assertAlmostEqual(ratio["absolute_change"], -0.1)
        self.assertIsNone(ratio["relative_change_percent"])
        self.assertEqual(duration["relative_change_percent"], 20)

    def test_zero_baseline_preserves_absolute_change(self) -> None:
        change = report.calculate_change("jobs_unplaced", 0, 3)
        self.assertEqual(change["absolute_change"], 3)
        self.assertIsNone(change["relative_change_percent"])

    def test_incomplete_matrix_detection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = self._fixture(Path(temporary), scenarios=("normal", "single"), requested=("normal", "single", "multi"))
            data = report.load_inputs(source)
            self.assertEqual(data["missing_combinations"], [{"scenario": "multi", "policy": "completion_time", "workload": "demo", "seed": 0}])

    def test_failed_run_is_rendered(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = self._fixture(Path(temporary), failed=True)
            data = report.load_inputs(source)
            text = report.generate_markdown("제목", "time", data, report.build_degradations(data["summaries"]), [], [])
            self.assertIn("의도된 실패", text)
            self.assertEqual(data["failed_count"], 1)

    def test_ranking_consistency(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = self._fixture(Path(temporary))
            rows = self._read(source / "policy_ranking.csv")
            rows[0]["policy"] = "missing_policy"
            self._write(source / "policy_ranking.csv", rows, report.RANKING_REQUIRED)
            with self.assertRaisesRegex(report.ReportError, "실제 요약 조합"):
                report.load_inputs(source)

    def test_finding_order_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data = report.load_inputs(self._fixture(Path(temporary)))
            degradations = report.build_degradations(data["summaries"])
            self.assertEqual(report.build_findings(degradations), report.build_findings(degradations))
            self.assertEqual(report.build_findings(degradations)[0]["finding_id"], "F0001")

    def test_markdown_generation_uses_relative_figures(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data = report.load_inputs(self._fixture(Path(temporary)))
            text = report.generate_markdown("제목", "time", data, report.build_degradations(data["summaries"]), [], ["figures/test.svg"])
            self.assertIn("![test](figures/test.svg)", text)
            self.assertIn("## 한계", text)

    def test_html_escapes_result_text(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data = report.load_inputs(self._fixture(Path(temporary), failed=True, error="<script>alert(1)</script>"))
            text = report.generate_html("<제목>", "time", data, report.build_degradations(data["summaries"]), [], [])
            self.assertNotIn("<script>alert", text)
            self.assertIn("&lt;script&gt;", text)
            self.assertIn("&lt;제목&gt;", text)

    def test_report_metadata_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = self._fixture(Path(temporary) / "source")
            output = Path(temporary) / "report"
            report.generate_report(source, output, "제목", ["markdown"])
            metadata = json.loads((output / "report_metadata.json").read_text())
            expected = hashlib.sha256((source / "runs.csv").read_bytes()).hexdigest()
            self.assertEqual(metadata["source_file_hashes"]["runs.csv"], expected)

    def test_svg_figure_generation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = self._fixture(Path(temporary) / "source")
            output = Path(temporary) / "report"
            data = report.load_inputs(source)
            figures = report.generate_figures(data["summaries"], report.build_degradations(data["summaries"]), output)
            self.assertEqual(len(figures), 7)
            self.assertTrue((output / figures[0]).read_text(encoding="utf-8").lstrip().startswith("<?xml"))

    def _fixture(self, root: Path, *, scenarios=("normal", "single", "multi"), requested=None, failed=False, error="의도된 실패") -> Path:
        root.mkdir(parents=True, exist_ok=True)
        requested = requested or scenarios
        runs = []
        summaries = []
        rankings = []
        for index, scenario in enumerate(scenarios):
            success = 1.0 - index * 0.05
            metric_values = {
                "placement_success_ratio": success, "jobs_unplaced": index * 5.0,
                "deadline_met_ratio": 0.8 - index * 0.1,
                "average_queue_wait_seconds": 10.0 + index * 2,
                "p95_queue_wait_seconds": 15.0 + index * 3,
                "average_total_time_seconds": 12.0 + index * 2,
                "p95_total_time_seconds": 18.0 + index * 3,
                "node_load_imbalance_ratio": 0.2 + index * 0.1,
            }
            run = {column: "" for column in report.RUN_REQUIRED}
            run.update({"scenario": scenario, "policy": "completion_time", "workload": "demo", "seed": "0", "status": "success", "error": ""})
            runs.append(run)
            summary = {column: "" for column in report.SUMMARY_REQUIRED}
            summary.update({"scenario": scenario, "policy": "completion_time", "workload": "demo", "successful_run_count": "1", "failed_run_count": "0"})
            summary.update({f"{metric}_mean": str(value) for metric, value in metric_values.items()})
            summaries.append(summary)
            rankings.append({"scenario": scenario, "workload": "demo", "rank": "1", "policy": "completion_time"})
        if failed:
            runs.append({"scenario": scenarios[0], "policy": "completion_time", "workload": "demo", "seed": "1", "status": "failed", "error": error})
        self._write(root / "runs.csv", runs, report.RUN_REQUIRED)
        self._write(root / "summary.csv", summaries, report.SUMMARY_REQUIRED)
        self._write(root / "policy_ranking.csv", rankings, report.RANKING_REQUIRED)
        metadata = {
            "requested_matrix": {"scenarios": list(requested), "policies": ["completion_time"], "workloads": ["demo"], "seeds": [0] + ([1] if failed else [])},
            "completed_run_count": len(scenarios), "failed_run_count": int(failed),
            "percentile_method": "nearest-rank", "standard_deviation_method": "sample",
            "repository_revision": "abc", "python_version": "3.x",
        }
        (root / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
        return root

    @staticmethod
    def _write(path: Path, rows: list[dict[str, str]], columns) -> None:
        fields = sorted(columns)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    @staticmethod
    def _read(path: Path) -> list[dict[str, str]]:
        with path.open(encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))


if __name__ == "__main__":
    unittest.main()
