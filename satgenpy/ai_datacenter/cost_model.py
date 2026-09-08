from typing import TypedDict

from .compute_model import ComputeNode
from .job_model import AIJob
from .placement import NetworkCost


class CompletionCost(TypedDict):
    node_id: int
    network_time_ms: float
    queue_wait_time_ms: float
    compute_time_ms: float
    total_time_ms: float
    route: str
    hop_count: int
    failed_isls: str


def estimate_completion_cost(
    job: AIJob,
    compute_node_id: int,
    compute_node: ComputeNode,
    network_cost: NetworkCost,
) -> CompletionCost:
    if compute_node["compute_speed"] <= 0:
        raise ValueError("compute_speed must be greater than zero")
    if network_cost["status"] != "AVAILABLE":
        raise ValueError("network cost must be AVAILABLE")
    if network_cost["compute_node"] != compute_node_id:
        raise ValueError("network cost compute_node must match compute_node_id")

    network_time_ms = network_cost["rtt_ns"] / 1_000_000.0
    # compute_speed is a relative simulation factor, not calibrated throughput.
    compute_time_ms = (
        job["required_compute"] / compute_node["compute_speed"]
    )
    queue_wait_time_ms = compute_node["queue_length"] * compute_time_ms
    total_time_ms = network_time_ms + queue_wait_time_ms + compute_time_ms
    return {
        "node_id": compute_node_id,
        "network_time_ms": network_time_ms,
        "queue_wait_time_ms": queue_wait_time_ms,
        "compute_time_ms": compute_time_ms,
        "total_time_ms": total_time_ms,
        "route": network_cost["route"],
        "hop_count": network_cost["hop_count"],
        "failed_isls": network_cost["failed_isls"],
    }
