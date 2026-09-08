import csv
import os
from collections.abc import Iterable
from os import PathLike
from typing import TypedDict

from .compute_model import get_compute_nodes
from .placement import load_network_costs
from .workload import generate_burst_workload
from .workload_simulator import (
    export_workload_results_csv,
    simulate_workload_completion_time,
)


class WorkloadExperimentSummary(TypedDict):
    scenario: str
    total_jobs: int
    placed_jobs: int
    unplaced_jobs: int
    placement_success_rate_percent: float
    deadline_met_rate_percent: float
    average_queue_wait_ms: float
    maximum_queue_wait_ms: float
    average_total_time_ms: float


SUMMARY_COLUMNS = (
    "scenario",
    "total_jobs",
    "placed_jobs",
    "unplaced_jobs",
    "placement_success_rate_percent",
    "deadline_met_rate_percent",
    "average_queue_wait_ms",
    "maximum_queue_wait_ms",
    "average_total_time_ms",
)

WORKLOAD_SCENARIOS = (
    ("NORMAL_BURST", ""),
    ("FAILED_ISL_0_1_BURST", "0-1"),
    ("MULTI_FAILED_ISL_0_1_10_11_BURST", "0-1;10-11"),
)


def export_experiment_results_csv(
    results: Iterable[dict[str, object]],
    output_path: str | PathLike[str],
) -> None:
    export_workload_results_csv(results, output_path)


def export_experiment_summary_csv(
    summaries: Iterable[dict[str, object]],
    output_path: str | PathLike[str],
) -> None:
    with open(output_path, "w", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=SUMMARY_COLUMNS)
        writer.writeheader()
        for summary in summaries:
            writer.writerow({
                column: summary[column] for column in SUMMARY_COLUMNS
            })


def _summarize(
    scenario: str,
    results: list[dict[str, object]],
) -> WorkloadExperimentSummary:
    placed = [
        result
        for result in results
        if result["placement_status"] == "PLACED"
    ]
    total_jobs = len(results)
    placed_jobs = len(placed)
    queue_waits = [float(result["queue_wait_time_ms"]) for result in placed]
    total_times = [float(result["total_time_ms"]) for result in placed]
    deadline_met_jobs = sum(bool(result["deadline_met"]) for result in placed)
    return {
        "scenario": scenario,
        "total_jobs": total_jobs,
        "placed_jobs": placed_jobs,
        "unplaced_jobs": total_jobs - placed_jobs,
        "placement_success_rate_percent": (
            placed_jobs / total_jobs * 100.0 if total_jobs else 0.0
        ),
        "deadline_met_rate_percent": (
            deadline_met_jobs / placed_jobs * 100.0 if placed_jobs else 0.0
        ),
        "average_queue_wait_ms": (
            sum(queue_waits) / placed_jobs if placed_jobs else 0.0
        ),
        "maximum_queue_wait_ms": max(queue_waits, default=0.0),
        "average_total_time_ms": (
            sum(total_times) / placed_jobs if placed_jobs else 0.0
        ),
    }


def run_burst_experiment() -> tuple[
    list[dict[str, object]],
    list[dict[str, object]],
]:
    demo_data_dir = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "demo_data"
    )
    network_costs = load_network_costs(
        os.path.join(demo_data_dir, "network_costs.csv")
    )
    jobs = generate_burst_workload()
    all_results: list[dict[str, object]] = []
    all_summaries: list[dict[str, object]] = []
    for scenario, failed_isls in WORKLOAD_SCENARIOS:
        scenario_costs = [
            cost
            for cost in network_costs
            if cost["failed_isls"] == failed_isls
        ]
        results = simulate_workload_completion_time(
            jobs,
            get_compute_nodes(),
            scenario_costs,
            scenario,
            failed_isls,
        )
        all_results.extend(results)
        all_summaries.append(dict(_summarize(scenario, results)))

    export_experiment_results_csv(
        all_results,
        os.path.join(demo_data_dir, "workload_experiment_results.csv"),
    )
    export_experiment_summary_csv(
        all_summaries,
        os.path.join(demo_data_dir, "workload_experiment_summary.csv"),
    )
    return all_results, all_summaries
