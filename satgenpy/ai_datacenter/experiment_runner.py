"""Deterministic batch experiments and standard-library statistical analysis."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import platform
import statistics
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from .compute_model import get_compute_nodes
from .dynamic_scenario import DynamicScenario, load_scenario, simulate_dynamic_scenario
from .placement import load_network_costs
from .workload import generate_workload, workload_fingerprint
from .workload_experiment import WORKLOAD_SCENARIOS
from .workload_simulator import SUPPORTED_WORKLOAD_POLICIES, simulate_workload


SCENARIOS = dict(zip(
    ("normal", "single", "multi"),
    (failed_isls for _name, failed_isls in WORKLOAD_SCENARIOS),
))
WORKLOADS = ("demo", "burst")
POLICIES = SUPPORTED_WORKLOAD_POLICIES
PERCENTILE_METHOD = "nearest-rank (ceil(p*n), minimum rank 1)"
STDDEV_METHOD = "sample standard deviation (n-1); null for fewer than 2 values"
MAJOR_METRICS = (
    "placement_success_ratio", "jobs_unplaced", "deadline_met_ratio",
    "average_queue_wait_seconds", "p95_queue_wait_seconds",
    "average_total_time_seconds", "p95_total_time_seconds",
    "node_load_imbalance_ratio",
)
RUN_COLUMNS = (
    "run_id", "scenario", "policy", "workload", "seed", "jobs_total",
    "jobs_placed", "jobs_unplaced", "placement_success_ratio",
    "deadline_met_ratio", "average_queue_wait_seconds",
    "p50_queue_wait_seconds", "p95_queue_wait_seconds",
    "maximum_queue_wait_seconds", "average_total_time_seconds",
    "p50_total_time_seconds", "p95_total_time_seconds", "failed_links",
    "unavailable_nodes", "node_load_mean", "node_load_stddev",
    "node_load_imbalance_ratio", "run_duration_seconds", "status", "error",
    "dynamic_scenario", "failure_event_count", "recovery_event_count",
    "detection_time_seconds", "reroute_time_seconds",
    "service_recovery_time_seconds", "jobs_unplaced_during_failure",
    "retry_success_ratio",
    "workload_fingerprint", "workload_job_count",
)
SUMMARY_COLUMNS = (
    "scenario", "policy", "workload", "run_count", "successful_run_count",
    "failed_run_count",
) + tuple(
    f"{metric}_{stat}"
    for metric in MAJOR_METRICS
    for stat in ("mean", "stddev", "minimum", "maximum")
)
RANKING_COLUMNS = (
    "scenario", "workload", "rank", "policy", "successful_run_count",
    "placement_success_ratio", "deadline_met_ratio", "jobs_unplaced",
    "p95_total_time_seconds", "node_load_imbalance_ratio",
)
RECOVERY_METRICS = (
    "detection_time_seconds", "reroute_time_seconds",
    "service_recovery_time_seconds", "jobs_unplaced_during_failure",
    "retry_success_ratio",
)
RECOVERY_SUMMARY_COLUMNS = (
    "scenario", "policy", "workload", "run_count",
) + tuple(
    f"{metric}_{stat}"
    for metric in RECOVERY_METRICS
    for stat in ("mean", "stddev", "minimum", "maximum", "p95")
)


def parse_csv_values(value: str) -> list[str]:
    values = [item.strip() for item in value.split(",") if item.strip()]
    if not values:
        raise argparse.ArgumentTypeError("value list must not be empty")
    return values


def parse_seeds(value: str) -> list[int]:
    seeds: list[int] = []
    try:
        for part in parse_csv_values(value):
            if ":" in part:
                pieces = part.split(":")
                if len(pieces) not in (2, 3):
                    raise ValueError
                start, stop = int(pieces[0]), int(pieces[1])
                step = int(pieces[2]) if len(pieces) == 3 else 1
                if step == 0 or (stop - start) * step < 0:
                    raise ValueError
                seeds.extend(range(start, stop + (1 if step > 0 else -1), step))
            else:
                seeds.append(int(part))
    except (ValueError, argparse.ArgumentTypeError) as error:
        raise argparse.ArgumentTypeError(
            "seeds must be comma-separated integers or inclusive ranges (for example 0:4)"
        ) from error
    if not seeds:
        raise argparse.ArgumentTypeError("at least one seed is required")
    return list(dict.fromkeys(seeds))


def nearest_rank(values: Sequence[float], percentile: float) -> float | None:
    if not values:
        return None
    if not 0 < percentile <= 100:
        raise ValueError("percentile must be greater than 0 and at most 100")
    ordered = sorted(values)
    return ordered[max(0, math.ceil(percentile / 100 * len(ordered)) - 1)]


def node_load_statistics(loads: Sequence[float]) -> tuple[float | None, float | None, float | None]:
    if not loads:
        return None, None, None
    mean = statistics.fmean(loads)
    stddev = statistics.pstdev(loads)
    return mean, stddev, stddev / mean if mean else None


def _mean(values: Sequence[float]) -> float | None:
    return statistics.fmean(values) if values else None


def _run_id(scenario: str, policy: str, workload: str, seed: int) -> str:
    identity = f"{scenario}\0{policy}\0{workload}\0{seed}".encode()
    return hashlib.sha256(identity).hexdigest()[:16]


def _demo_data_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "demo_data"


def execute_run(scenario: str, policy: str, workload: str, seed: int) -> dict[str, object]:
    """Execute one validated combination; seed is explicit configuration."""
    started = time.perf_counter()
    failed_isls = SCENARIOS[scenario]
    network_costs = [
        cost for cost in load_network_costs(str(_demo_data_dir() / "network_costs.csv"))
        if cost["failed_isls"] == failed_isls
    ]
    compute_nodes = get_compute_nodes()
    jobs = generate_workload(workload, seed)
    fingerprint, workload_job_count = workload_fingerprint(jobs)
    results = simulate_workload(
        jobs, compute_nodes, network_costs, scenario, failed_isls, policy
    )
    placed = [row for row in results if row["placement_status"] == "PLACED"]
    queue_waits = [float(row["queue_wait_time_ms"]) / 1000 for row in placed]
    total_times = [float(row["total_time_ms"]) / 1000 for row in placed]
    node_counts = [
        sum(int(row["selected_node"]) == node for row in placed)
        for node in sorted(compute_nodes)
    ]
    # All configured compute nodes are included, including unavailable zero-load nodes.
    load_mean, load_stddev, imbalance = node_load_statistics(node_counts)
    observed_nodes = {int(row["selected_node"]) for row in placed}
    return {
        "run_id": _run_id(scenario, policy, workload, seed),
        "scenario": scenario, "policy": policy, "workload": workload,
        "seed": seed, "jobs_total": len(results), "jobs_placed": len(placed),
        "jobs_unplaced": len(results) - len(placed),
        "placement_success_ratio": len(placed) / len(results) if results else None,
        "deadline_met_ratio": (
            sum(bool(row["deadline_met"]) for row in placed) / len(placed)
            if placed else None
        ),
        "average_queue_wait_seconds": _mean(queue_waits),
        "p50_queue_wait_seconds": nearest_rank(queue_waits, 50),
        "p95_queue_wait_seconds": nearest_rank(queue_waits, 95),
        "maximum_queue_wait_seconds": max(queue_waits) if queue_waits else None,
        "average_total_time_seconds": _mean(total_times),
        "p50_total_time_seconds": nearest_rank(total_times, 50),
        "p95_total_time_seconds": nearest_rank(total_times, 95),
        "failed_links": len([edge for edge in failed_isls.split(";") if edge]),
        "unavailable_nodes": len(compute_nodes) - len(observed_nodes),
        "node_load_mean": load_mean, "node_load_stddev": load_stddev,
        "node_load_imbalance_ratio": imbalance,
        "run_duration_seconds": time.perf_counter() - started,
        "status": "success", "error": "",
        "dynamic_scenario": False, "failure_event_count": 0,
        "recovery_event_count": 0, "detection_time_seconds": None,
        "reroute_time_seconds": None, "service_recovery_time_seconds": None,
        "jobs_unplaced_during_failure": None, "retry_success_ratio": None,
        "workload_fingerprint": fingerprint,
        "workload_job_count": workload_job_count,
    }


def execute_dynamic_run(scenario: DynamicScenario, policy: str, workload: str, seed: int) -> dict[str, object]:
    started = time.perf_counter()
    dynamic = simulate_dynamic_scenario(scenario, policy, workload, seed)
    jobs = dynamic["jobs"]
    assert isinstance(jobs, list)
    placed = [row for row in jobs if row["placement_status"] == "PLACED"]
    node_counts = [sum(row["final_assigned_node"] == node for row in placed) for node in sorted(get_compute_nodes())]
    load_mean, load_stddev, imbalance = node_load_statistics(node_counts)
    queue_waits = [float(row["queue_wait_time_ms"]) / 1000 for row in placed if row["queue_wait_time_ms"] != ""]
    total_times = [float(row["total_time_ms"]) / 1000 for row in placed if row["total_time_ms"] != ""]
    recovery = dynamic["recovery_metrics"]
    assert isinstance(recovery, dict)
    return {
        "run_id": _run_id(scenario.name, policy, workload, seed),
        "scenario": scenario.name, "policy": policy, "workload": workload,
        "seed": seed, "jobs_total": len(jobs), "jobs_placed": len(placed),
        "jobs_unplaced": len(jobs) - len(placed),
        "placement_success_ratio": len(placed) / len(jobs) if jobs else None,
        "deadline_met_ratio": sum(bool(row["deadline_met"]) for row in placed) / len(placed) if placed else None,
        "average_queue_wait_seconds": _mean(queue_waits),
        "p50_queue_wait_seconds": nearest_rank(queue_waits, 50),
        "p95_queue_wait_seconds": nearest_rank(queue_waits, 95),
        "maximum_queue_wait_seconds": max(queue_waits) if queue_waits else None,
        "average_total_time_seconds": _mean(total_times),
        "p50_total_time_seconds": nearest_rank(total_times, 50),
        "p95_total_time_seconds": nearest_rank(total_times, 95),
        "failed_links": 0, "unavailable_nodes": 0,
        "node_load_mean": load_mean, "node_load_stddev": load_stddev,
        "node_load_imbalance_ratio": imbalance,
        "run_duration_seconds": time.perf_counter() - started,
        "status": "success", "error": "", "dynamic_scenario": True,
        "failure_event_count": dynamic["failure_event_count"],
        "recovery_event_count": dynamic["recovery_event_count"],
        **{metric: recovery.get(metric) for metric in RECOVERY_METRICS},
        "workload_fingerprint": dynamic["workload_fingerprint"],
        "workload_job_count": dynamic["workload_job_count"],
    }


def failed_row(scenario: str, policy: str, workload: str, seed: int, error: Exception) -> dict[str, object]:
    row = {column: None for column in RUN_COLUMNS}
    row.update({
        "run_id": _run_id(scenario, policy, workload, seed),
        "scenario": scenario, "policy": policy, "workload": workload,
        "seed": seed, "status": "failed",
        "error": str(error).replace("\n", " ")[:240],
    })
    return row


def aggregate_summary(rows: Iterable[Mapping[str, object]]) -> list[dict[str, object]]:
    groups: dict[tuple[str, str, str], list[Mapping[str, object]]] = defaultdict(list)
    for row in rows:
        groups[(str(row["scenario"]), str(row["policy"]), str(row["workload"]))].append(row)
    summaries = []
    for key in sorted(groups):
        group = groups[key]
        successes = [row for row in group if row["status"] == "success"]
        summary: dict[str, object] = {
            "scenario": key[0], "policy": key[1], "workload": key[2],
            "run_count": len(group), "successful_run_count": len(successes),
            "failed_run_count": len(group) - len(successes),
        }
        for metric in MAJOR_METRICS:
            values = [float(row[metric]) for row in successes if row.get(metric) not in (None, "")]
            summary[f"{metric}_mean"] = _mean(values)
            summary[f"{metric}_stddev"] = statistics.stdev(values) if len(values) >= 2 else None
            summary[f"{metric}_minimum"] = min(values) if values else None
            summary[f"{metric}_maximum"] = max(values) if values else None
        summaries.append(summary)
    return summaries


def rank_policies(summaries: Iterable[Mapping[str, object]]) -> list[dict[str, object]]:
    groups: dict[tuple[str, str], list[Mapping[str, object]]] = defaultdict(list)
    for row in summaries:
        groups[(str(row["scenario"]), str(row["workload"]))].append(row)
    ranked_rows = []
    for key in sorted(groups):
        eligible = [row for row in groups[key] if int(row["successful_run_count"]) > 0]
        def value(row: Mapping[str, object], metric: str, fallback: float) -> float:
            raw = row.get(f"{metric}_mean")
            return float(raw) if raw not in (None, "") else fallback
        eligible.sort(key=lambda row: (
            -value(row, "placement_success_ratio", -math.inf),
            -value(row, "deadline_met_ratio", -math.inf),
            value(row, "jobs_unplaced", math.inf),
            value(row, "p95_total_time_seconds", math.inf),
            value(row, "node_load_imbalance_ratio", math.inf),
            str(row["policy"]),
        ))
        for rank, row in enumerate(eligible, 1):
            ranked_rows.append({
                "scenario": key[0], "workload": key[1], "rank": rank,
                "policy": row["policy"],
                "successful_run_count": row["successful_run_count"],
                **{metric: row.get(f"{metric}_mean") for metric in (
                    "placement_success_ratio", "deadline_met_ratio", "jobs_unplaced",
                    "p95_total_time_seconds", "node_load_imbalance_ratio",
                )},
            })
    return ranked_rows


def aggregate_recovery_summary(rows: Iterable[Mapping[str, object]]) -> list[dict[str, object]]:
    groups: dict[tuple[str, str, str], list[Mapping[str, object]]] = defaultdict(list)
    for row in rows:
        if str(row.get("dynamic_scenario", "")).lower() in {"true", "1"}:
            groups[(str(row["scenario"]), str(row["policy"]), str(row["workload"]))].append(row)
    output = []
    for key in sorted(groups):
        group = [row for row in groups[key] if row["status"] == "success"]
        summary: dict[str, object] = {"scenario": key[0], "policy": key[1], "workload": key[2], "run_count": len(group)}
        for metric in RECOVERY_METRICS:
            values = [float(row[metric]) for row in group if row.get(metric) not in (None, "")]
            summary[f"{metric}_mean"] = _mean(values)
            summary[f"{metric}_stddev"] = statistics.stdev(values) if len(values) >= 2 else None
            summary[f"{metric}_minimum"] = min(values) if values else None
            summary[f"{metric}_maximum"] = max(values) if values else None
            summary[f"{metric}_p95"] = nearest_rank(values, 95)
        output.append(summary)
    return output


def _write_csv(path: Path, columns: Sequence[str], rows: Iterable[Mapping[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows({column: row.get(column) for column in columns} for row in rows)


def _read_runs(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _revision() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parent,
            check=True, capture_output=True, text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenarios", type=parse_csv_values, default=["normal", "single", "multi"])
    parser.add_argument("--policies", type=parse_csv_values, default=list(POLICIES))
    parser.add_argument("--workloads", type=parse_csv_values, default=["burst"])
    parser.add_argument("--seeds", type=parse_seeds, default=[0])
    parser.add_argument("--output", type=Path, default=Path("experiments/results"))
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--list-options", action="store_true")
    parser.add_argument("--dynamic-scenario", type=Path)
    return parser


def _validate(parser: argparse.ArgumentParser, requested: Sequence[str], supported: Iterable[str], name: str) -> None:
    invalid = sorted(set(requested) - set(supported))
    if invalid:
        parser.error("unsupported %s: %s" % (name, ", ".join(invalid)))


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.list_options:
        print("scenarios: " + ",".join(SCENARIOS))
        print("policies: " + ",".join(POLICIES))
        print("workloads: " + ",".join(WORKLOADS))
        return 0
    dynamic_scenario = None
    if args.dynamic_scenario is not None:
        try:
            dynamic_scenario = load_scenario(args.dynamic_scenario)
        except ValueError as error:
            parser.error(str(error))
    else:
        _validate(parser, args.scenarios, SCENARIOS, "scenarios")
    _validate(parser, args.policies, POLICIES, "policies")
    _validate(parser, args.workloads, WORKLOADS, "workloads")
    selected_scenarios = [dynamic_scenario.name] if dynamic_scenario else args.scenarios
    matrix = [
        (scenario, policy, workload, seed)
        for scenario in selected_scenarios for policy in args.policies
        for workload in args.workloads for seed in args.seeds
    ]
    args.output.mkdir(parents=True, exist_ok=True)
    runs_path = args.output / "runs.csv"
    existing = _read_runs(runs_path) if args.resume else []
    by_identity: dict[tuple[str, str, str, int], dict[str, object]] = {}
    for row in existing:
        identity = (row["scenario"], row["policy"], row["workload"], int(row["seed"]))
        if identity not in by_identity or row["status"] == "success":
            by_identity[identity] = row
    rows: list[dict[str, object]] = []
    skipped = failed = completed = 0
    for index, identity in enumerate(matrix, 1):
        scenario, policy, workload, seed = identity
        previous = by_identity.get(identity)
        if previous and previous["status"] == "success" and previous.get("workload_fingerprint"):
            rows.append(previous)
            skipped += 1
            continue
        print(f"[{index}/{len(matrix)}] scenario={scenario} policy={policy} workload={workload} seed={seed}")
        try:
            row = execute_dynamic_run(dynamic_scenario, policy, workload, seed) if dynamic_scenario else execute_run(*identity)
            completed += 1
        except Exception as error:  # one bad run must not stop the matrix
            row = failed_row(*identity, error)
            if dynamic_scenario:
                row["dynamic_scenario"] = True
            failed += 1
        if not row.get("workload_fingerprint"):
            identity_jobs = generate_workload(workload, seed)
            if dynamic_scenario:
                identity_jobs = [job for job in identity_jobs if job["arrival_time_ns"] / 1e9 <= dynamic_scenario.duration_seconds]
            fingerprint, job_count = workload_fingerprint(identity_jobs)
            row["workload_fingerprint"] = fingerprint
            row["workload_job_count"] = job_count
        rows.append(row)
    # Exact requested identities only; each is emitted once, replacing prior failures.
    _write_csv(runs_path, RUN_COLUMNS, rows)
    summaries = aggregate_summary(rows)
    summary_path = args.output / "summary.csv"
    ranking_path = args.output / "policy_ranking.csv"
    metadata_path = args.output / "metadata.json"
    _write_csv(summary_path, SUMMARY_COLUMNS, summaries)
    _write_csv(ranking_path, RANKING_COLUMNS, rank_policies(summaries))
    recovery_path = args.output / "recovery_summary.csv"
    if dynamic_scenario:
        _write_csv(recovery_path, RECOVERY_SUMMARY_COLUMNS, aggregate_recovery_summary(rows))
    fingerprints = {str(row["workload_fingerprint"]) for row in rows if row.get("workload_fingerprint")}
    fingerprint_groups: dict[tuple[str, str, str], dict[int, str]] = defaultdict(dict)
    for row in rows:
        if row.get("workload_fingerprint"):
            fingerprint_groups[(str(row["scenario"]), str(row["policy"]), str(row["workload"]))][int(row["seed"])] = str(row["workload_fingerprint"])
    seed_effective = any(
        len(by_seed) >= 2 and len(set(by_seed.values())) >= 2
        for by_seed in fingerprint_groups.values()
    )
    if len(args.seeds) >= 2 and len(fingerprints) == 1:
        print("warning: multiple seeds requested, but every workload fingerprint is identical; seed is ineffective for this matrix")
    metadata = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "requested_matrix": {
            "scenarios": selected_scenarios, "policies": args.policies,
            "workloads": args.workloads, "seeds": args.seeds,
        },
        "supported_options": {
            "scenarios": list(SCENARIOS), "policies": list(POLICIES),
            "workloads": list(WORKLOADS),
        },
        "completed_run_count": sum(row["status"] == "success" for row in rows),
        "failed_run_count": sum(row["status"] == "failed" for row in rows),
        "percentile_method": PERCENTILE_METHOD,
        "standard_deviation_method": STDDEV_METHOD,
        "node_load_method": "population stddev across all configured compute nodes, including unavailable zero-load nodes",
        "repository_revision": _revision(), "python_version": platform.python_version(),
        "dynamic_scenario": dynamic_scenario.name if dynamic_scenario else None,
        "distinct_workload_fingerprint_count": len(fingerprints),
        "seed_effective": seed_effective,
    }
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(f"total requested: {len(matrix)}; completed: {completed}; skipped: {skipped}; failed: {failed}")
    paths = [runs_path, summary_path, ranking_path, metadata_path]
    if dynamic_scenario:
        paths.append(recovery_path)
    print("outputs: " + ", ".join(str(path) for path in paths))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
