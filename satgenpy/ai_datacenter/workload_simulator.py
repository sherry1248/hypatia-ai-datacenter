import csv
from collections.abc import Iterable
from os import PathLike
from typing import TypedDict

from .compute_model import ComputeNode
from .cost_model import estimate_completion_cost
from .job_model import AIJob
from .placement import (
    NetworkCost,
    select_compute_aware,
    select_compute_only,
    select_network_only,
)


SUPPORTED_WORKLOAD_POLICIES = (
    "compute_only",
    "network_only",
    "compute_aware",
    "completion_time",
)


class NodeQueueState(TypedDict):
    next_available_time_ms: float
    queued_job_count: int
    completed_job_count: int


class WorkloadSimulationResult(TypedDict):
    job_id: str
    job_type: str
    arrival_time_ns: int
    scenario: str
    algorithm: str
    placement_status: str
    selected_node: int
    route: str
    rtt_ns: float | str
    network_time_ms: float | str
    queue_wait_time_ms: float | str
    compute_time_ms: float | str
    start_time_ms: float | str
    finish_time_ms: float | str
    total_time_ms: float | str
    deadline_ms: float
    deadline_met: bool
    failed_isls: str


RESULT_COLUMNS = (
    "job_id",
    "job_type",
    "arrival_time_ns",
    "scenario",
    "algorithm",
    "placement_status",
    "selected_node",
    "route",
    "rtt_ns",
    "network_time_ms",
    "queue_wait_time_ms",
    "compute_time_ms",
    "start_time_ms",
    "finish_time_ms",
    "total_time_ms",
    "deadline_ms",
    "deadline_met",
    "failed_isls",
)


def simulate_workload_completion_time(
    jobs: list[AIJob],
    compute_nodes: dict[int, ComputeNode],
    network_costs: list[NetworkCost],
    scenario: str,
    failed_isls: str,
) -> list[dict[str, object]]:
    return simulate_workload(
        jobs, compute_nodes, network_costs, scenario, failed_isls,
        "completion_time",
    )


def simulate_workload(
    jobs: list[AIJob],
    compute_nodes: dict[int, ComputeNode],
    network_costs: list[NetworkCost],
    scenario: str,
    failed_isls: str,
    policy: str,
) -> list[dict[str, object]]:
    """Run the existing deterministic single-server queue with a real policy."""
    if policy not in SUPPORTED_WORKLOAD_POLICIES:
        raise ValueError("unsupported workload policy: %s" % policy)
    queue_states: dict[int, NodeQueueState] = {
        node_id: {
            "next_available_time_ms": 0.0,
            "queued_job_count": 0,
            "completed_job_count": 0,
        }
        for node_id in compute_nodes
    }
    pending_finishes: dict[int, list[float]] = {
        node_id: [] for node_id in compute_nodes
    }
    results: list[dict[str, object]] = []

    for job in sorted(
        jobs,
        key=lambda item: (item["arrival_time_ns"], item["job_id"]),
    ):
        arrival_time_ns = job["arrival_time_ns"]
        arrival_time_ms = arrival_time_ns / 1_000_000.0
        for node_id, finishes in pending_finishes.items():
            completed = sum(finish <= arrival_time_ms for finish in finishes)
            if completed:
                pending_finishes[node_id] = [
                    finish for finish in finishes if finish > arrival_time_ms
                ]
                queue_states[node_id]["completed_job_count"] += completed
            queue_states[node_id]["queued_job_count"] = len(
                pending_finishes[node_id]
            )

        eligible_times = [
            cost["time_ns"]
            for cost in network_costs
            if (
                cost["source"] == job["source_node"]
                and cost["time_ns"] <= arrival_time_ns
            )
        ]
        selected_time_ns = max(eligible_times) if eligible_times else None
        candidates = [
            cost
            for cost in network_costs
            if (
                selected_time_ns is not None
                and cost["time_ns"] == selected_time_ns
                and cost["source"] == job["source_node"]
                and cost["status"] == "AVAILABLE"
                and cost["compute_node"] in compute_nodes
            )
        ]
        deadline_ms = float(job["deadline_ms"])
        if not candidates:
            unplaced: WorkloadSimulationResult = {
                "job_id": job["job_id"],
                "job_type": job["job_type"],
                "arrival_time_ns": arrival_time_ns,
                "scenario": scenario,
                "algorithm": policy,
                "placement_status": "UNPLACED",
                "selected_node": -1,
                "route": "",
                "rtt_ns": "",
                "network_time_ms": "",
                "queue_wait_time_ms": "",
                "compute_time_ms": "",
                "start_time_ms": "",
                "finish_time_ms": "",
                "total_time_ms": "",
                "deadline_ms": deadline_ms,
                "deadline_met": False,
                "failed_isls": failed_isls,
            }
            results.append(dict(unplaced))
            continue

        candidate_nodes = {
            node_id: compute_nodes[node_id].copy()
            for node_id in {cost["compute_node"] for cost in candidates}
        }
        for node_id, node in candidate_nodes.items():
            node["queue_length"] = queue_states[node_id]["queued_job_count"]

        scored = []
        for cost in candidates:
            node_id = cost["compute_node"]
            calculation_node = candidate_nodes[node_id].copy()
            calculation_node["queue_length"] = 0
            completion = estimate_completion_cost(
                job, node_id, calculation_node, cost
            )
            network_ready_ms = arrival_time_ms + completion["network_time_ms"]
            start_time_ms = max(
                network_ready_ms,
                queue_states[node_id]["next_available_time_ms"],
            )
            queue_wait_time_ms = start_time_ms - network_ready_ms
            finish_time_ms = start_time_ms + completion["compute_time_ms"]
            total_time_ms = finish_time_ms - arrival_time_ms
            scored.append((
                total_time_ms, completion["network_time_ms"],
                queue_wait_time_ms, node_id, cost,
                completion["compute_time_ms"], start_time_ms, finish_time_ms,
            ))

        if policy == "completion_time":
            selected = min(scored, key=lambda item: item[:4])
        else:
            selected_time_costs = [
                cost for cost in candidates if cost["time_ns"] == selected_time_ns
            ]
            if policy == "compute_only":
                selected_node_id = select_compute_only(candidate_nodes)["node_id"]
            elif policy == "network_only":
                selected_node_id = select_network_only(
                    selected_time_costs, selected_time_ns
                )["node_id"]
            else:
                selected_node_id = select_compute_aware(
                    candidate_nodes, selected_time_costs, selected_time_ns
                )["node_id"]
            selected = next(item for item in scored if item[3] == selected_node_id)

        (
            total_time_ms, network_time_ms, queue_wait_time_ms,
            selected_node, selected_cost, compute_time_ms,
            start_time_ms, finish_time_ms,
        ) = selected
        queue_states[selected_node]["next_available_time_ms"] = finish_time_ms
        pending_finishes[selected_node].append(finish_time_ms)
        queue_states[selected_node]["queued_job_count"] = len(
            pending_finishes[selected_node]
        )

        placed: WorkloadSimulationResult = {
            "job_id": job["job_id"],
            "job_type": job["job_type"],
            "arrival_time_ns": arrival_time_ns,
            "scenario": scenario,
            "algorithm": policy,
            "placement_status": "PLACED",
            "selected_node": selected_node,
            "route": selected_cost["route"],
            "rtt_ns": selected_cost["rtt_ns"],
            "network_time_ms": network_time_ms,
            "queue_wait_time_ms": queue_wait_time_ms,
            "compute_time_ms": compute_time_ms,
            "start_time_ms": start_time_ms,
            "finish_time_ms": finish_time_ms,
            "total_time_ms": total_time_ms,
            "deadline_ms": deadline_ms,
            "deadline_met": total_time_ms <= deadline_ms,
            "failed_isls": failed_isls,
        }
        results.append(dict(placed))

    return results


def export_workload_results_csv(
    results: Iterable[dict[str, object]],
    output_path: str | PathLike[str],
) -> None:
    with open(output_path, "w", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=RESULT_COLUMNS)
        writer.writeheader()
        for result in results:
            writer.writerow({column: result[column] for column in RESULT_COLUMNS})
