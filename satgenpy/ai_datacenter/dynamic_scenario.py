"""Deterministic timed failure/recovery scenarios for the AI data center."""

from __future__ import annotations

import json
import argparse
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from .compute_model import get_compute_nodes
from .placement import NetworkCost, load_network_costs
from .workload import generate_workload, workload_fingerprint
from .workload_simulator import SUPPORTED_WORKLOAD_POLICIES, simulate_workload


EVENT_TYPES = ("link_failure", "link_recovery", "node_failure", "node_recovery")
EVENT_PRIORITY = {"link_failure": 0, "node_failure": 1, "link_recovery": 2, "node_recovery": 3}
PHASES = ("healthy", "degraded", "rerouting", "recovering")
WORKLOADS = ("demo", "burst")
LINK_TARGET = re.compile(r"^(\d+)-(\d+)$")
NODE_TARGET = re.compile(r"^(?:SAT-)?(\d+)$")


class DynamicScenarioError(ValueError):
    pass


@dataclass(frozen=True)
class TimedEvent:
    event_id: str
    time_seconds: float
    type: str
    target: str
    metadata: Mapping[str, object]


@dataclass(frozen=True)
class DynamicScenario:
    name: str
    duration_seconds: float
    tick_seconds: float
    events: tuple[TimedEvent, ...]


class SimulationClock:
    """Explicit deterministic clock; it never reads wall time."""

    def __init__(self, duration_seconds: float, tick_seconds: float) -> None:
        if duration_seconds <= 0 or tick_seconds <= 0:
            raise DynamicScenarioError("duration_seconds와 tick_seconds는 양수여야 합니다")
        self.duration_seconds = float(duration_seconds)
        self.tick_seconds = float(tick_seconds)
        self.time_seconds = 0.0

    def detection_time(self, occurrence_seconds: float) -> float:
        ticks = math.ceil((occurrence_seconds / self.tick_seconds) - 1e-12)
        return min(self.duration_seconds, ticks * self.tick_seconds)

    def ticks(self) -> list[float]:
        values = []
        index = 0
        while index * self.tick_seconds <= self.duration_seconds + 1e-12:
            values.append(min(self.duration_seconds, index * self.tick_seconds))
            index += 1
        if values[-1] != self.duration_seconds:
            values.append(self.duration_seconds)
        return values


def _canonical_target(event_type: str, target: object) -> str:
    if not isinstance(target, str):
        raise DynamicScenarioError("이벤트 target은 문자열이어야 합니다")
    if event_type.startswith("link_"):
        match = LINK_TARGET.fullmatch(target)
        if not match or match.group(1) == match.group(2):
            raise DynamicScenarioError(f"잘못된 링크 target: {target}")
        first, second = sorted((int(match.group(1)), int(match.group(2))))
        return f"{first}-{second}"
    match = NODE_TARGET.fullmatch(target)
    node = int(match.group(1)) if match else -1
    if node not in get_compute_nodes():
        raise DynamicScenarioError(f"잘못된 노드 target: {target}")
    return str(node)


def parse_scenario(payload: object) -> DynamicScenario:
    if not isinstance(payload, dict):
        raise DynamicScenarioError("시나리오 최상위 값은 객체여야 합니다")
    name = payload.get("name")
    if not isinstance(name, str) or not name.strip():
        raise DynamicScenarioError("시나리오 name이 필요합니다")
    try:
        duration = float(payload["duration_seconds"])
        tick = float(payload["tick_seconds"])
    except (KeyError, TypeError, ValueError) as error:
        raise DynamicScenarioError("duration_seconds와 tick_seconds가 올바르지 않습니다") from error
    if not math.isfinite(duration) or not math.isfinite(tick) or duration <= 0 or tick <= 0:
        raise DynamicScenarioError("duration_seconds와 tick_seconds는 유한한 양수여야 합니다")
    raw_events = payload.get("events")
    if not isinstance(raw_events, list):
        raise DynamicScenarioError("events는 배열이어야 합니다")
    ids: set[str] = set()
    events = []
    for raw in raw_events:
        if not isinstance(raw, dict):
            raise DynamicScenarioError("각 이벤트는 객체여야 합니다")
        event_id = raw.get("event_id")
        event_type = raw.get("type")
        if not isinstance(event_id, str) or not event_id:
            raise DynamicScenarioError("event_id가 필요합니다")
        if event_id in ids:
            raise DynamicScenarioError(f"중복 event_id: {event_id}")
        ids.add(event_id)
        if event_type not in EVENT_TYPES:
            raise DynamicScenarioError(f"지원하지 않는 이벤트 type: {event_type}")
        try:
            event_time = float(raw["time_seconds"])
        except (KeyError, TypeError, ValueError) as error:
            raise DynamicScenarioError(f"이벤트 시간이 올바르지 않습니다: {event_id}") from error
        if not math.isfinite(event_time) or event_time < 0 or event_time > duration:
            raise DynamicScenarioError(f"이벤트 시간이 시나리오 범위를 벗어났습니다: {event_id}")
        metadata = raw.get("metadata", {})
        if not isinstance(metadata, dict):
            raise DynamicScenarioError(f"metadata는 객체여야 합니다: {event_id}")
        events.append(TimedEvent(event_id, event_time, event_type, _canonical_target(event_type, raw.get("target")), metadata))
    ordered = tuple(sorted(events, key=lambda event: (event.time_seconds, EVENT_PRIORITY[event.type], event.event_id)))
    active: set[tuple[str, str]] = set()
    for event in ordered:
        kind = "link" if event.type.startswith("link_") else "node"
        key = (kind, event.target)
        if event.type.endswith("failure"):
            if key in active:
                raise DynamicScenarioError(f"이미 활성인 장애의 중복 failure: {event.event_id}")
            active.add(key)
        elif key not in active:
            raise DynamicScenarioError(f"matching failure 이전의 recovery: {event.event_id}")
        else:
            active.remove(key)
    return DynamicScenario(name.strip(), duration, tick, ordered)


def load_scenario(path: Path) -> DynamicScenario:
    try:
        return parse_scenario(json.loads(path.read_text(encoding="utf-8")))
    except DynamicScenarioError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise DynamicScenarioError(f"시나리오 파일 읽기 실패: {error}") from error


def _failed_key(links: set[str]) -> str:
    return ";".join(sorted(links, key=lambda value: tuple(map(int, value.split("-")))))


def _state_at(events: Sequence[TimedEvent], time_seconds: float) -> tuple[set[str], set[int]]:
    links: set[str] = set()
    nodes: set[int] = set()
    for event in events:
        if event.time_seconds > time_seconds:
            break
        collection = links if event.type.startswith("link_") else nodes
        target: str | int = event.target if event.type.startswith("link_") else int(event.target)
        if event.type.endswith("failure"):
            collection.add(target)  # type: ignore[arg-type]
        else:
            collection.discard(target)  # type: ignore[arg-type]
    return links, nodes


def _available_costs(all_costs: Sequence[NetworkCost], links: set[str], failed_nodes: set[int]) -> list[NetworkCost]:
    key = _failed_key(links)
    costs = [cost for cost in all_costs if cost["failed_isls"] == key and cost["compute_node"] not in failed_nodes]
    if not costs:
        raise DynamicScenarioError(f"저장 네트워크 데이터가 장애 조합을 지원하지 않습니다: {key or 'normal'}")
    return costs


def _affected_routes(all_costs: Sequence[NetworkCost], event: TimedEvent) -> tuple[int, list[int]]:
    if event.type != "link_failure":
        return 0, [int(event.target)]
    first, second = map(int, event.target.split("-"))
    routes = set()
    nodes = set()
    for cost in all_costs:
        if cost["failed_isls"] or cost["status"] != "AVAILABLE":
            continue
        route = [int(value) for value in cost["route"].split("-") if value]
        if any({route[index], route[index + 1]} == {first, second} for index in range(len(route) - 1)):
            routes.add(cost["route"])
            nodes.add(cost["compute_node"])
    return len(routes), sorted(nodes)


def simulate_dynamic_scenario(
    scenario: DynamicScenario,
    policy: str,
    workload: str,
    seed: int,
    network_costs_path: Path | None = None,
) -> dict[str, object]:
    if policy not in SUPPORTED_WORKLOAD_POLICIES:
        raise DynamicScenarioError(f"지원하지 않는 policy: {policy}")
    if workload not in WORKLOADS:
        raise DynamicScenarioError(f"지원하지 않는 workload: {workload}")
    if not isinstance(seed, int):
        raise DynamicScenarioError("seed는 명시적 정수여야 합니다")
    clock = SimulationClock(scenario.duration_seconds, scenario.tick_seconds)
    data_path = network_costs_path or Path(__file__).resolve().parent.parent / "demo_data" / "network_costs.csv"
    all_costs = load_network_costs(str(data_path))
    jobs = [job for job in generate_workload(workload, seed) if job["arrival_time_ns"] / 1e9 <= scenario.duration_seconds]
    fingerprint, workload_job_count = workload_fingerprint(jobs)
    results: list[dict[str, object]] = []
    retry_candidates: list[tuple[dict[str, object], float]] = []
    for job in jobs:
        arrival = job["arrival_time_ns"] / 1e9
        failed_links, failed_nodes = _state_at(scenario.events, arrival)
        costs = _available_costs(all_costs, failed_links, failed_nodes)
        nodes = {node: value for node, value in get_compute_nodes().items() if node not in failed_nodes}
        simulated = simulate_workload([job], nodes, costs, scenario.name, _failed_key(failed_links), policy)[0]
        during = bool(failed_links or failed_nodes)
        placed = simulated["placement_status"] == "PLACED"
        total = float(simulated["total_time_ms"]) / 1000 if placed else None
        result = {
            **simulated,
            "arrival_time_seconds": arrival,
            "placement_time_seconds": arrival + (float(simulated["network_time_ms"]) + float(simulated["queue_wait_time_ms"])) / 1000 if placed else None,
            "completion_time_seconds": arrival + total if total is not None else None,
            "failure_affected": during,
            "failure_period": "during" if during else "before" if not any(event.type.endswith("failure") and event.time_seconds <= arrival for event in scenario.events) else "after",
            "retry_count": 0,
            "original_assigned_node": int(simulated["selected_node"]) if placed else None,
            "final_assigned_node": int(simulated["selected_node"]) if placed else None,
        }
        results.append(result)
        if during and not placed:
            next_recovery = next((event.time_seconds for event in scenario.events if event.type.endswith("recovery") and event.time_seconds > arrival), None)
            if next_recovery is not None:
                retry_candidates.append((result, next_recovery))

    retry_successes = 0
    for result, retry_time in retry_candidates:
        failed_links, failed_nodes = _state_at(scenario.events, retry_time)
        retry_job = next(job for job in jobs if job["job_id"] == result["job_id"]).copy()
        retry_job["arrival_time_ns"] = round(retry_time * 1e9)
        retry = simulate_workload(
            [retry_job],
            {node: value for node, value in get_compute_nodes().items() if node not in failed_nodes},
            _available_costs(all_costs, failed_links, failed_nodes),
            scenario.name, _failed_key(failed_links), policy,
        )[0]
        result["retry_count"] = 1
        if retry["placement_status"] == "PLACED":
            retry_successes += 1
            result["placement_status"] = "PLACED"
            result["final_assigned_node"] = int(retry["selected_node"])
            result["placement_time_seconds"] = retry_time + (float(retry["network_time_ms"]) + float(retry["queue_wait_time_ms"])) / 1000
            result["completion_time_seconds"] = retry_time + float(retry["total_time_ms"]) / 1000

    failures = [event for event in scenario.events if event.type.endswith("failure")]
    recoveries = [event for event in scenario.events if event.type.endswith("recovery")]
    first_failure = failures[0] if failures else None
    first_detection = clock.detection_time(first_failure.time_seconds) if first_failure else None
    reroute_complete = min(first_detection + clock.tick_seconds, scenario.duration_seconds) if first_detection is not None else None
    last_recovery_time = max((event.time_seconds for event in recoveries), default=None)
    unresolved_jobs = [row for row in results if row["placement_status"] == "UNPLACED"]
    final_links, final_nodes = _state_at(scenario.events, scenario.duration_seconds)
    service_recovered = None
    if first_failure and last_recovery_time is not None and not final_links and not final_nodes and not unresolved_jobs:
        service_recovered = min(last_recovery_time + clock.tick_seconds, scenario.duration_seconds)
    timeline: list[dict[str, object]] = [{"time_seconds": 0.0, "phase": "healthy", "event_id": None}]
    for event in scenario.events:
        timeline.append({"time_seconds": event.time_seconds, "phase": "degraded" if event.type.endswith("failure") else "recovering", "event_id": event.event_id})
        if event.type.endswith("failure"):
            detected = clock.detection_time(event.time_seconds)
            timeline.append({"time_seconds": detected, "phase": "rerouting", "event_id": event.event_id})
    if service_recovered is not None:
        timeline.append({"time_seconds": service_recovered, "phase": "healthy", "event_id": None})
    timeline.sort(key=lambda row: (float(row["time_seconds"]), PHASES.index(str(row["phase"])), str(row["event_id"] or "")))
    affected_route_count = 0
    affected_nodes: set[int] = set()
    records = []
    for failure in failures:
        route_count, nodes = _affected_routes(all_costs, failure)
        affected_route_count += route_count
        affected_nodes.update(nodes)
        matching_type = failure.type.replace("failure", "recovery")
        recovery = next((event for event in recoveries if event.type == matching_type and event.target == failure.target and event.time_seconds >= failure.time_seconds), None)
        affected_jobs = [str(row["job_id"]) for row in results if row["failure_affected"]]
        records.append({
            "failure_id": failure.event_id, "type": failure.type, "target": failure.target,
            "status": "resolved" if recovery and service_recovered is not None else "recovering" if recovery else "active",
            "occurred_at_seconds": failure.time_seconds,
            "detected_at_seconds": clock.detection_time(failure.time_seconds),
            "recovered_at_seconds": recovery.time_seconds if recovery else None,
            "affected_nodes": nodes, "affected_jobs": affected_jobs,
            "related_event_ids": [failure.event_id] + ([recovery.event_id] if recovery else []),
            "recovery_metrics": {},
        })
    during_rows = [row for row in results if row["failure_period"] == "during"]
    metrics = {
        "failure_occurred_at_seconds": first_failure.time_seconds if first_failure else None,
        "failure_detected_at_seconds": first_detection,
        "reroute_started_at_seconds": first_detection,
        "reroute_completed_at_seconds": reroute_complete,
        "service_recovered_at_seconds": service_recovered,
        "detection_time_seconds": first_detection - first_failure.time_seconds if first_failure and first_detection is not None else None,
        "reroute_time_seconds": reroute_complete - first_detection if reroute_complete is not None and first_detection is not None else None,
        "service_recovery_time_seconds": service_recovered - first_failure.time_seconds if service_recovered is not None and first_failure else None,
        "jobs_arrived_during_failure": len(during_rows),
        "jobs_placed_during_failure": sum(row["original_assigned_node"] is not None for row in during_rows),
        "jobs_unplaced_during_failure": sum(row["original_assigned_node"] is None for row in during_rows),
        "jobs_retried": len(retry_candidates),
        "retry_success_ratio": retry_successes / len(retry_candidates) if retry_candidates else None,
        "affected_node_count": len(affected_nodes), "affected_route_count": affected_route_count,
    }
    for record in records:
        record["recovery_metrics"] = dict(metrics)
    active = [record for record in records if record["status"] != "resolved"]
    phase = "healthy" if service_recovered is not None or not failures else "degraded" if active else "recovering"
    return {
        "scenario": scenario.name, "dynamic_scenario": True, "policy": policy,
        "workload": workload, "seed": seed, "duration_seconds": scenario.duration_seconds,
        "tick_seconds": scenario.tick_seconds, "simulation_time_seconds": scenario.duration_seconds,
        "operational_phase": phase, "active_failures": len(active),
        "current_failure_ids": [record["failure_id"] for record in active],
        "last_failure": records[-1] if records else None,
        "last_recovery": recoveries[-1].event_id if recoveries else None,
        "recovery_metrics": metrics, "failures": records, "timeline": timeline,
        "jobs": results, "failure_event_count": len(failures),
        "recovery_event_count": len(recoveries),
        "workload_fingerprint": fingerprint,
        "workload_job_count": workload_job_count,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", type=Path, required=True)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        scenario = load_scenario(args.scenario)
    except DynamicScenarioError as error:
        parser.error(str(error))
    print(
        f"시나리오 검증 완료: {scenario.name} "
        f"duration={scenario.duration_seconds:g}s tick={scenario.tick_seconds:g}s "
        f"events={len(scenario.events)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
