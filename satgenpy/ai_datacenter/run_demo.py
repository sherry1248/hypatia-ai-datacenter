import csv
import os

from .placement import select_after_failure

from . import (
    AIJob,
    ComputeNode,
    NetworkCost,
    create_demo_job,
    get_compute_nodes,
    load_network_costs,
    select_compute_aware,
    select_completion_time,
    select_compute_only,
    select_network_only,
)


def _build_scenario_rows(
    scenario: str,
    failed_isls: str,
    job: AIJob,
    compute_nodes: dict[int, ComputeNode],
    network_costs: list[NetworkCost],
    time_ns: int,
) -> list[dict[str, object]]:
    compute_only = select_compute_only(compute_nodes)
    reachable = [cost["compute_node"] for cost in network_costs
                 if cost["time_ns"] == time_ns and cost["status"] == "AVAILABLE"
                 and cost["compute_node"] in compute_nodes]
    policy_results = {}
    for policy in ("network_only", "compute_aware", "completion_time"):
        result = select_after_failure(
            policy, reachable, network_costs, time_ns, compute_nodes, job
        )
        # Reuse the existing CSV fields for unsuccessful selections.
        fields = next(row for row in _build_unplaced_rows(scenario, failed_isls, job, time_ns)
                      if row["algorithm"] == policy)
        fields.update(node_id=-1, placement_status="FAILED")
        if result["status"] == "PLACED":
            fields.update(result["placement"], placement_status="PLACED")
        policy_results[policy] = fields
    network_only = policy_results["network_only"]
    compute_aware = policy_results["compute_aware"]
    completion_time = policy_results["completion_time"]

    compute_node_id = compute_only["node_id"]
    compute_network_cost = next(
        (
            cost for cost in network_costs
            if (
                cost["time_ns"] == time_ns
                and cost["status"] == "AVAILABLE"
                and cost["compute_node"] == compute_node_id
            )
        ),
        None,
    )
    common = {
        "time_ns": time_ns,
        "scenario": scenario,
        "job_id": job["job_id"],
        "job_type": job["job_type"],
        "source_node": job["source_node"],
        "placement_status": "PLACED",
    }
    return [
        {
            **common,
            "algorithm": compute_only["algorithm"],
            "selected_node": compute_node_id,
            "route": (
                compute_network_cost["route"] if compute_network_cost else ""
            ),
            "rtt_ns": (
                compute_network_cost["rtt_ns"] if compute_network_cost else ""
            ),
            "hop_count": (
                compute_network_cost["hop_count"] if compute_network_cost else 0
            ),
            "gpu_util_percent": compute_only["gpu_util_percent"],
            "queue_length": compute_only["queue_length"],
            "compute_speed": compute_only["compute_speed"],
            "network_score": "",
            "compute_score": "",
            "total_score": "",
            "network_time_ms": "",
            "queue_wait_time_ms": "",
            "compute_time_ms": "",
            "total_time_ms": "",
            "failed_isls": (
                compute_network_cost["failed_isls"]
                if compute_network_cost else failed_isls
            ),
        },
        {
            **common,
            "placement_status": network_only["placement_status"],
            "algorithm": network_only["algorithm"],
            "selected_node": network_only["node_id"],
            "route": network_only["route"],
            "rtt_ns": network_only["rtt_ns"],
            "hop_count": network_only["hop_count"],
            "gpu_util_percent": "",
            "queue_length": "",
            "compute_speed": "",
            "network_score": "",
            "compute_score": "",
            "total_score": "",
            "network_time_ms": "",
            "queue_wait_time_ms": "",
            "compute_time_ms": "",
            "total_time_ms": "",
            "failed_isls": network_only["failed_isls"],
        },
        {
            **common,
            "placement_status": compute_aware["placement_status"],
            "algorithm": compute_aware["algorithm"],
            "selected_node": compute_aware["node_id"],
            "route": compute_aware["route"],
            "rtt_ns": compute_aware["rtt_ns"],
            "hop_count": compute_aware["hop_count"],
            "gpu_util_percent": compute_aware["gpu_util_percent"],
            "queue_length": compute_aware["queue_length"],
            "compute_speed": compute_aware["compute_speed"],
            "network_score": compute_aware["network_score"],
            "compute_score": compute_aware["compute_score"],
            "total_score": compute_aware["total_score"],
            "network_time_ms": "",
            "queue_wait_time_ms": "",
            "compute_time_ms": "",
            "total_time_ms": "",
            "failed_isls": compute_aware["failed_isls"],
        },
        {
            **common,
            "placement_status": completion_time["placement_status"],
            "algorithm": completion_time["algorithm"],
            "selected_node": completion_time["node_id"],
            "route": completion_time["route"],
            "rtt_ns": completion_time["rtt_ns"],
            "hop_count": completion_time["hop_count"],
            "gpu_util_percent": "",
            "queue_length": "",
            "compute_speed": "",
            "network_score": "",
            "compute_score": "",
            "total_score": "",
            "network_time_ms": completion_time["network_time_ms"],
            "queue_wait_time_ms": completion_time["queue_wait_time_ms"],
            "compute_time_ms": completion_time["compute_time_ms"],
            "total_time_ms": completion_time["total_time_ms"],
            "failed_isls": completion_time["failed_isls"],
        },
    ]


def _build_unplaced_rows(
    scenario: str,
    failed_isls: str,
    job: AIJob,
    time_ns: int,
) -> list[dict[str, object]]:
    return [
        {
            "time_ns": time_ns,
            "scenario": scenario,
            "job_id": job["job_id"],
            "job_type": job["job_type"],
            "source_node": job["source_node"],
            "placement_status": "UNPLACED",
            "algorithm": algorithm,
            "selected_node": -1,
            "route": "",
            "rtt_ns": "",
            "hop_count": 0,
            "gpu_util_percent": "",
            "queue_length": "",
            "compute_speed": "",
            "network_score": "",
            "compute_score": "",
            "total_score": "",
            "network_time_ms": "",
            "queue_wait_time_ms": "",
            "compute_time_ms": "",
            "total_time_ms": "",
            "failed_isls": failed_isls,
        }
        for algorithm in (
            "compute_only",
            "network_only",
            "compute_aware",
            "completion_time",
        )
    ]


def main() -> None:
    demo_data_dir = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "demo_data"
    )
    network_costs_path = os.path.join(demo_data_dir, "network_costs.csv")
    output_path = os.path.join(demo_data_dir, "placement_results.csv")

    job = create_demo_job()
    compute_nodes = get_compute_nodes()
    network_costs = load_network_costs(network_costs_path)
    high_load_compute_nodes = {
        node_id: node.copy() for node_id, node in compute_nodes.items()
    }
    high_load_compute_nodes[7]["gpu_util_percent"] = 95.0
    high_load_compute_nodes[7]["queue_length"] = 10
    scenarios = [
        ("NORMAL", "", "normal"),
        ("FAILED_ISL_0_1", "0-1", "normal"),
        ("MULTI_FAILED_ISL_0_1_10_11", "0-1;10-11", "normal"),
        ("HIGH_LOAD_NODE_7", "", "high"),
        ("DYNAMIC_LOAD_NODE_7", "", "dynamic"),
    ]
    known_failures = {failed for _, failed, _ in scenarios}
    scenarios.extend(
        ("FAILED_ISL_" + failed.replace(";", "_").replace("-", "_"), failed, "normal")
        for failed in sorted({cost["failed_isls"] for cost in network_costs} - known_failures)
    )
    rows: list[dict[str, object]] = []
    scenario_summaries: list[tuple[str, list[int], int]] = []
    for scenario, failed_isls, compute_state in scenarios:
        scenario_costs = [
            cost
            for cost in network_costs
            if cost["failed_isls"] == failed_isls
        ]
        time_values = sorted({
            cost["time_ns"] for cost in scenario_costs
        })
        processed_times = []
        scenario_row_count = 0
        for time_ns in time_values:
            timestamp_costs = [
                cost for cost in scenario_costs
                if cost["time_ns"] == time_ns
                and cost["status"] == "AVAILABLE"
                and cost["compute_node"] in compute_nodes
            ]
            dynamic_high_load = (
                compute_state == "dynamic"
                and 60_000_000_000 <= time_ns < 120_000_000_000
            )
            scenario_compute_nodes = (
                high_load_compute_nodes
                if compute_state == "high" or dynamic_high_load
                else compute_nodes
            )
            scenario_rows = _build_scenario_rows(
                scenario, failed_isls, job, scenario_compute_nodes,
                timestamp_costs, time_ns,
            )
            if not timestamp_costs:
                scenario_rows[0] = _build_unplaced_rows(scenario, failed_isls, job, time_ns)[0]
            rows.extend(scenario_rows)
            processed_times.append(time_ns)
            scenario_row_count += len(scenario_rows)
        scenario_summaries.append(
            (scenario, processed_times, scenario_row_count)
        )

    fieldnames = [
        "time_ns",
        "scenario",
        "job_id",
        "job_type",
        "source_node",
        "placement_status",
        "algorithm",
        "selected_node",
        "route",
        "rtt_ns",
        "hop_count",
        "gpu_util_percent",
        "queue_length",
        "compute_speed",
        "network_score",
        "compute_score",
        "total_score",
        "network_time_ms",
        "queue_wait_time_ms",
        "compute_time_ms",
        "total_time_ms",
        "failed_isls",
    ]
    with open(output_path, "w", newline="") as f_out:
        writer = csv.DictWriter(f_out, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    for scenario, processed_times, row_count in scenario_summaries:
        print(
            "%s: timestamps=%d, rows=%d, first_time_ns=%s, last_time_ns=%s"
            % (
                scenario,
                len(processed_times),
                row_count,
                processed_times[0] if processed_times else "",
                processed_times[-1] if processed_times else "",
            )
        )


if __name__ == "__main__":
    main()
