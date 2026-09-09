import csv
import math
from typing import TypedDict

from .compute_model import ComputeNode
from .job_model import AIJob


class NetworkCost(TypedDict):
    time_ns: int
    source: int
    compute_node: int
    route: str
    rtt_ns: float
    hop_count: int
    failed_isls: str
    status: str


class NetworkPlacementResult(TypedDict):
    node_id: int
    route: str
    rtt_ns: float
    hop_count: int
    failed_isls: str
    algorithm: str


class ComputeAwarePlacementResult(TypedDict):
    node_id: int
    route: str
    rtt_ns: float
    hop_count: int
    gpu_util_percent: float
    queue_length: int
    compute_speed: float
    network_score: float
    compute_score: float
    total_score: float
    failed_isls: str
    algorithm: str


class CompletionTimePlacementResult(TypedDict):
    node_id: int
    route: str
    rtt_ns: float
    hop_count: int
    network_time_ms: float
    queue_wait_time_ms: float
    compute_time_ms: float
    total_time_ms: float
    failed_isls: str
    algorithm: str


class PlacementResult(TypedDict):
    node_id: int
    queue_length: int
    gpu_util_percent: float
    compute_speed: float
    algorithm: str


class FailedPlacementResult(TypedDict):
    status: str
    selected_compute_node: None


def select_after_failure(
    policy: str,
    reachable_compute_nodes: list[int],
    network_costs: list[NetworkCost],
    time_ns: int,
    compute_nodes: dict[int, ComputeNode] | None = None,
    job: AIJob | None = None,
):
    """Filter unreachable nodes, then delegate to an existing policy."""
    reachable = set(reachable_compute_nodes)
    if not reachable:
        print("\n[Placement after failure]")
        print("selected_compute_node: FAILED")
        return {"status": "FAILED", "selected_compute_node": None}

    filtered_costs = [
        cost for cost in network_costs
        if cost["compute_node"] in reachable
        and cost["time_ns"] == time_ns
        and cost["status"] == "AVAILABLE"
        and math.isfinite(cost["rtt_ns"]) and cost["rtt_ns"] > 0
        and cost["route"].split("-")[0] == str(cost["source"])
        and cost["route"].split("-")[-1] == str(cost["compute_node"])
        and (policy == "network_only" or cost["compute_node"] in (compute_nodes or {}))
    ]
    filtered_nodes = {
        node_id: node for node_id, node in (compute_nodes or {}).items()
        if node_id in reachable
    }

    if not filtered_costs:
        return {"status": "FAILED", "selected_compute_node": None}

    if policy == "network_only":
        result = select_network_only(filtered_costs, time_ns)
    elif policy == "compute_aware":
        result = select_compute_aware(filtered_nodes, filtered_costs, time_ns)
    elif policy == "completion_time":
        if job is None:
            raise ValueError("job is required for completion_time")
        result = select_completion_time(
            job, filtered_nodes, filtered_costs, time_ns
        )
    else:
        raise ValueError("unknown placement policy: %s" % policy)

    print("\n[Placement after failure]")
    print("selected_compute_node: SAT-%d" % result["node_id"])
    return {
        "status": "PLACED",
        "selected_compute_node": result["node_id"],
        "placement": result,
    }


def _normalize(value: float, minimum: float, maximum: float) -> float:
    if minimum == maximum:
        return 0.0
    return (value - minimum) / (maximum - minimum)


def select_compute_only(
    compute_nodes: dict[int, ComputeNode],
) -> PlacementResult:
    if not compute_nodes:
        raise ValueError("compute_nodes must not be empty")

    node_id, node = min(
        compute_nodes.items(),
        key=lambda item: (
            item[1]["queue_length"],
            item[1]["gpu_util_percent"],
            -item[1]["compute_speed"],
            item[0],
        ),
    )
    return {
        "node_id": node_id,
        "queue_length": node["queue_length"],
        "gpu_util_percent": node["gpu_util_percent"],
        "compute_speed": node["compute_speed"],
        "algorithm": "compute_only",
    }


def load_network_costs(csv_path: str) -> list[NetworkCost]:
    network_costs: list[NetworkCost] = []
    with open(csv_path, newline="") as f_in:
        for row in csv.DictReader(f_in):
            network_costs.append({
                "time_ns": int(row["time_ns"]),
                "source": int(row["source"]),
                "compute_node": int(row["compute_node"]),
                "route": (
                    row["route"] if row["status"] == "AVAILABLE" else ""
                ),
                "rtt_ns": (
                    float(row["rtt_ns"])
                    if row["status"] == "AVAILABLE" else 0.0
                ),
                "hop_count": (
                    int(row["hop_count"])
                    if row["status"] == "AVAILABLE" else 0
                ),
                "failed_isls": row["failed_isls"],
                "status": row["status"],
            })
    return network_costs


def select_network_only(
    network_costs: list[NetworkCost],
    time_ns: int,
) -> NetworkPlacementResult:
    candidates = [
        cost for cost in network_costs
        if cost["time_ns"] == time_ns and cost["status"] == "AVAILABLE"
    ]
    if not candidates:
        raise ValueError(
            "no AVAILABLE network cost for time_ns %d" % time_ns
        )

    best = min(
        candidates,
        key=lambda cost: (
            cost["rtt_ns"],
            cost["hop_count"],
            cost["compute_node"],
        ),
    )
    return {
        "node_id": best["compute_node"],
        "route": best["route"],
        "rtt_ns": best["rtt_ns"],
        "hop_count": best["hop_count"],
        "failed_isls": best["failed_isls"],
        "algorithm": "network_only",
    }


def select_compute_aware(
    compute_nodes: dict[int, ComputeNode],
    network_costs: list[NetworkCost],
    time_ns: int,
    network_weight: float = 0.5,
    compute_weight: float = 0.5,
) -> ComputeAwarePlacementResult:
    if not compute_nodes:
        raise ValueError("compute_nodes must not be empty")
    if network_weight < 0 or compute_weight < 0:
        raise ValueError("placement weights must be non-negative")

    weight_total = network_weight + compute_weight
    if weight_total <= 0:
        raise ValueError("placement weights must have a positive sum")

    candidates = [
        cost for cost in network_costs
        if (
            cost["time_ns"] == time_ns
            and cost["status"] == "AVAILABLE"
            and cost["compute_node"] in compute_nodes
        )
    ]
    if not candidates:
        raise ValueError(
            "no AVAILABLE compute-aware candidate for time_ns %d" % time_ns
        )

    rtts = [cost["rtt_ns"] for cost in candidates]
    nodes = [compute_nodes[cost["compute_node"]] for cost in candidates]
    gpu_utils = [node["gpu_util_percent"] for node in nodes]
    queue_lengths = [node["queue_length"] for node in nodes]
    compute_speeds = [node["compute_speed"] for node in nodes]
    normalized_network_weight = network_weight / weight_total
    normalized_compute_weight = compute_weight / weight_total

    scored = []
    for cost in candidates:
        node = compute_nodes[cost["compute_node"]]
        network_score = _normalize(cost["rtt_ns"], min(rtts), max(rtts))
        compute_score = (
            _normalize(
                node["gpu_util_percent"], min(gpu_utils), max(gpu_utils)
            )
            + _normalize(
                node["queue_length"], min(queue_lengths), max(queue_lengths)
            )
            + 1.0 - _normalize(
                node["compute_speed"], min(compute_speeds), max(compute_speeds)
            )
        ) / 3.0
        total_score = (
            normalized_network_weight * network_score
            + normalized_compute_weight * compute_score
        )
        scored.append((cost, node, network_score, compute_score, total_score))

    best, node, network_score, compute_score, total_score = min(
        scored,
        key=lambda item: (
            item[4],
            item[0]["rtt_ns"],
            item[1]["queue_length"],
            item[0]["compute_node"],
        ),
    )
    return {
        "node_id": best["compute_node"],
        "route": best["route"],
        "rtt_ns": best["rtt_ns"],
        "hop_count": best["hop_count"],
        "gpu_util_percent": node["gpu_util_percent"],
        "queue_length": node["queue_length"],
        "compute_speed": node["compute_speed"],
        "network_score": network_score,
        "compute_score": compute_score,
        "total_score": total_score,
        "failed_isls": best["failed_isls"],
        "algorithm": "compute_aware",
    }


def select_completion_time(
    job: AIJob,
    compute_nodes: dict[int, ComputeNode],
    network_costs: list[NetworkCost],
    time_ns: int,
) -> CompletionTimePlacementResult:
    from .cost_model import CompletionCost, estimate_completion_cost

    if not compute_nodes:
        raise ValueError("compute_nodes must not be empty")

    candidates = [
        cost for cost in network_costs
        if (
            cost["time_ns"] == time_ns
            and cost["status"] == "AVAILABLE"
            and cost["compute_node"] in compute_nodes
        )
    ]
    if not candidates:
        raise ValueError(
            "no AVAILABLE completion-time candidate for time_ns %d" % time_ns
        )

    scored: list[tuple[NetworkCost, CompletionCost]] = []
    for cost in candidates:
        node_id = cost["compute_node"]
        scored.append((
            cost,
            estimate_completion_cost(
                job, node_id, compute_nodes[node_id], cost
            ),
        ))

    best, completion = min(
        scored,
        key=lambda item: (
            item[1]["total_time_ms"],
            item[1]["network_time_ms"],
            item[1]["queue_wait_time_ms"],
            item[0]["compute_node"],
        ),
    )
    return {
        "node_id": best["compute_node"],
        "route": completion["route"],
        "rtt_ns": best["rtt_ns"],
        "hop_count": completion["hop_count"],
        "network_time_ms": completion["network_time_ms"],
        "queue_wait_time_ms": completion["queue_wait_time_ms"],
        "compute_time_ms": completion["compute_time_ms"],
        "total_time_ms": completion["total_time_ms"],
        "failed_isls": completion["failed_isls"],
        "algorithm": "completion_time",
    }
