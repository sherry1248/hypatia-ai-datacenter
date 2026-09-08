from __future__ import annotations

import csv
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from satgenpy.ai_datacenter import experiment_runner as runner
from satgenpy.ai_datacenter.workload import generate_burst_workload, workload_fingerprint


class ExperimentRunnerTests(unittest.TestCase):
    def test_option_discovery(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(runner.main(["--list-options"]), 0)
        text = output.getvalue()
        self.assertIn("scenarios: normal,single,multi", text)
        self.assertIn("completion_time", text)
        self.assertIn("workloads: demo,burst", text)

    def test_invalid_option_rejected_before_output_creation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "results"
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                runner.main(["--scenarios", "imaginary", "--output", str(output)])
            self.assertFalse(output.exists())

    def test_seed_range_parsing(self) -> None:
        self.assertEqual(runner.parse_seeds("0:4,8,10:6:-2"), [0, 1, 2, 3, 4, 8, 10, 6])

    def test_deterministic_repeated_run(self) -> None:
        first = runner.execute_run("normal", "completion_time", "demo", 7)
        second = runner.execute_run("normal", "completion_time", "demo", 7)
        ignored = {"run_duration_seconds"}
        self.assertEqual(
            {key: value for key, value in first.items() if key not in ignored},
            {key: value for key, value in second.items() if key not in ignored},
        )

    def test_nearest_rank_percentile(self) -> None:
        self.assertEqual(runner.nearest_rank([4, 1, 3, 2], 50), 2)
        self.assertEqual(runner.nearest_rank([4, 1, 3, 2], 95), 4)
        self.assertIsNone(runner.nearest_rank([], 95))

    def test_zero_load_handling(self) -> None:
        mean, stddev, ratio = runner.node_load_statistics([0, 0, 0])
        self.assertEqual((mean, stddev), (0.0, 0.0))
        self.assertIsNone(ratio)

    def test_summary_uses_sample_standard_deviation(self) -> None:
        rows = [self._row(0.8, 2), self._row(1.0, 0), {**self._row(0, 0), "status": "failed"}]
        summary = runner.aggregate_summary(rows)[0]
        self.assertEqual(summary["run_count"], 3)
        self.assertEqual(summary["successful_run_count"], 2)
        self.assertAlmostEqual(summary["placement_success_ratio_mean"], 0.9)
        self.assertAlmostEqual(summary["placement_success_ratio_stddev"], 0.1414213562)

    def test_policy_ranking_is_lexicographic(self) -> None:
        summaries = [
            self._summary("a", 1.0, 0.7, 0, 9.0, 0.2),
            self._summary("b", 1.0, 0.8, 1, 12.0, 0.5),
            self._summary("c", 0.9, 1.0, 0, 1.0, 0.0),
        ]
        ranked = runner.rank_policies(summaries)
        self.assertEqual([row["policy"] for row in ranked], ["b", "a", "c"])

    def test_failed_run_is_recorded_and_returns_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, patch.object(
            runner, "execute_run", side_effect=RuntimeError("concise failure")
        ), redirect_stdout(io.StringIO()):
            code = runner.main(self._args(temporary))
            self.assertEqual(code, 1)
            rows = self._read(Path(temporary) / "runs.csv")
            self.assertEqual(rows[0]["status"], "failed")
            self.assertEqual(rows[0]["error"], "concise failure")

    def test_resume_has_no_duplicates_and_retries_failures(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, redirect_stdout(io.StringIO()):
            path = Path(temporary) / "runs.csv"
            failed = runner.failed_row(
                "normal", "completion_time", "demo", 0, RuntimeError("old")
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=runner.RUN_COLUMNS)
                writer.writeheader()
                writer.writerow(failed)
            self.assertEqual(runner.main(self._args(temporary) + ["--resume"]), 0)
            final_rows = self._read(path)
            self.assertEqual(len(final_rows), 1)
            self.assertEqual(final_rows[0]["status"], "success")
            self.assertEqual(runner.main(self._args(temporary) + ["--resume"]), 0)
            self.assertEqual(len(self._read(path)), 1)

    def test_same_seed_produces_same_fingerprint(self) -> None:
        self.assertEqual(
            workload_fingerprint(generate_burst_workload(seed=17)),
            workload_fingerprint(generate_burst_workload(seed=17)),
        )

    def test_different_seeds_produce_different_burst_fingerprints(self) -> None:
        first = workload_fingerprint(generate_burst_workload(seed=1))[0]
        second = workload_fingerprint(generate_burst_workload(seed=2))[0]
        self.assertNotEqual(first, second)

    def test_demo_determinism_is_reported_honestly(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, redirect_stdout(io.StringIO()):
            args = ["--scenarios", "normal", "--policies", "completion_time",
                    "--workloads", "demo", "--seeds", "0:1", "--output", temporary]
            self.assertEqual(runner.main(args), 0)
            metadata = json.loads((Path(temporary) / "metadata.json").read_text())
            rows = self._read(Path(temporary) / "runs.csv")
            self.assertFalse(metadata["seed_effective"])
            self.assertEqual(metadata["distinct_workload_fingerprint_count"], 1)
            self.assertEqual(len({row["workload_fingerprint"] for row in rows}), 1)

    def test_resume_preserves_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, redirect_stdout(io.StringIO()):
            args = self._args(temporary)
            self.assertEqual(runner.main(args), 0)
            before = self._read(Path(temporary) / "runs.csv")[0]["workload_fingerprint"]
            self.assertEqual(runner.main(args + ["--resume"]), 0)
            after = self._read(Path(temporary) / "runs.csv")
            self.assertEqual(len(after), 1)
            self.assertEqual(after[0]["workload_fingerprint"], before)

    def test_warning_for_ineffective_multiple_seeds(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(runner.main([
                    "--scenarios", "normal", "--policies", "completion_time",
                    "--workloads", "demo", "--seeds", "0:1", "--output", temporary,
                ]), 0)
            self.assertIn("every workload fingerprint is identical", output.getvalue())

    @staticmethod
    def _args(output: str) -> list[str]:
        return ["--scenarios", "normal", "--policies", "completion_time",
                "--workloads", "demo", "--seeds", "0", "--output", output]

    @staticmethod
    def _read(path: Path) -> list[dict[str, str]]:
        with path.open(newline="", encoding="utf-8") as handle:
            return list(csv.DictReader(handle))

    @staticmethod
    def _row(success: float, unplaced: int) -> dict[str, object]:
        row = {metric: 1.0 for metric in runner.MAJOR_METRICS}
        row.update({"scenario": "normal", "policy": "p", "workload": "demo",
                    "status": "success", "placement_success_ratio": success,
                    "jobs_unplaced": unplaced})
        return row

    @staticmethod
    def _summary(policy: str, placement: float, deadline: float, unplaced: float,
                 p95: float, imbalance: float) -> dict[str, object]:
        return {"scenario": "normal", "workload": "demo", "policy": policy,
                "successful_run_count": 1,
                "placement_success_ratio_mean": placement,
                "deadline_met_ratio_mean": deadline, "jobs_unplaced_mean": unplaced,
                "p95_total_time_seconds_mean": p95,
                "node_load_imbalance_ratio_mean": imbalance}


if __name__ == "__main__":
    unittest.main()
