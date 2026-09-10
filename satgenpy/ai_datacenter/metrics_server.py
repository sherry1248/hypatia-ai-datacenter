"""Prometheus exporter for CSV-backed space AI data-center results."""

from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import os
import re
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO, Callable, Iterable, Literal, Mapping, Sequence, cast
from urllib.parse import parse_qs
from wsgiref.simple_server import WSGIRequestHandler, make_server

from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Gauge, generate_latest


LOGGER = logging.getLogger(__name__)
SERVICE_NAME = "space-ai-datacenter-backend"
SUPPORTED_SCENARIOS = (
    "NORMAL_BURST",
    "FAILED_ISL_0_1_BURST",
    "MULTI_FAILED_ISL_0_1_10_11_BURST",
)
COMPUTE_NODES = (0, 3, 7)
BASE_SCENARIOS = {
    "NORMAL_BURST": "NORMAL",
    "FAILED_ISL_0_1_BURST": "FAILED_ISL_0_1",
    "MULTI_FAILED_ISL_0_1_10_11_BURST": "MULTI_FAILED_ISL_0_1_10_11",
}
EXPECTED_FAILED_LINKS = {
    "NORMAL_BURST": "",
    "FAILED_ISL_0_1_BURST": "0-1",
    "MULTI_FAILED_ISL_0_1_10_11_BURST": "0-1;10-11",
}
SCENARIO_LABELS = {
    "NORMAL_BURST": "정상",
    "FAILED_ISL_0_1_BURST": "단일 장애",
    "MULTI_FAILED_ISL_0_1_10_11_BURST": "다중 장애",
}
ALLOWED_FRONTEND_ORIGINS = {
    "http://localhost:5173",
    "http://127.0.0.1:5173",
}


class MetricsDataError(RuntimeError):
    """Raised when a metrics snapshot cannot be read safely."""


class JsonLogFormatter(logging.Formatter):
    """Render operational records as one compact JSON object per line."""

    CONTEXT_FIELDS = (
        "scenario", "node", "job_id", "incident_id", "method", "path",
        "status_code", "duration_ms",
    )

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname.lower(),
            "component": getattr(record, "component", "metrics_server"),
            "event_type": getattr(record, "event_type", "log"),
            "message": record.getMessage(),
        }
        for field in self.CONTEXT_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload["exception"] = record.exc_info[0].__name__
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _log(level: int, event_type: str, message: str, **context: object) -> None:
    LOGGER.log(
        level,
        message,
        extra={"component": "metrics_server", "event_type": event_type, **context},
    )


@dataclass(frozen=True)
class MetricsSnapshot:
    scenario: str
    jobs_total: int
    jobs_placed_total: int
    jobs_unplaced_total: int
    placement_success_ratio: float
    deadline_met_ratio: float
    average_queue_wait_seconds: float
    maximum_queue_wait_seconds: float
    average_total_time_seconds: float
    node_jobs_total: Mapping[int, int]
    node_queue_wait_seconds: Mapping[int, float | None]
    node_available: Mapping[int, int]
    failed_links: int
    jobs: tuple["JobRecord", ...]


@dataclass(frozen=True)
class JobRecord:
    job_id: str
    status: str
    assigned_node: int | None
    queue_wait_seconds: float | None
    processing_seconds: float | None
    total_time_seconds: float | None
    deadline_seconds: float | None
    deadline_met: bool | None
    failure_reason: str | None


EventLevel = Literal["info", "warning", "critical"]
EventCategory = Literal["network", "node", "job", "system"]


@dataclass(frozen=True)
class OperationalEvent:
    event_id: str
    timestamp: str
    level: EventLevel
    category: EventCategory
    type: str
    target: str
    message: str


IncidentStatus = Literal["open", "acknowledged", "resolved"]


@dataclass
class OperationalIncident:
    incident_id: str
    title: str
    status: IncidentStatus
    severity: "AlertSeverity"
    severity_label: str
    scenario: str
    started_at: str
    acknowledged_at: str | None
    resolved_at: str | None
    causes: list[str]
    impacts: list[str]
    actions: list[str]
    related_event_ids: list[str]
    affected_nodes: list[str]
    affected_job_count: int


AlertSeverity = Literal["normal", "warning", "critical"]


@dataclass(frozen=True)
class OperationalAlert:
    severity: AlertSeverity
    severity_label: str
    reasons: tuple[str, ...]
    unavailable_nodes: int


class PrometheusMetrics:
    """Gauge collection registered only after the first valid snapshot."""

    def __init__(self, registry: CollectorRegistry) -> None:
        prefix = "space_ai_datacenter_"
        self.jobs_total = Gauge(prefix + "jobs_total", "스냅샷의 전체 작업 수", registry=registry)
        self.jobs_placed_total = Gauge(prefix + "jobs_placed_total", "스냅샷의 배치 완료 작업 수", registry=registry)
        self.jobs_unplaced_total = Gauge(prefix + "jobs_unplaced_total", "스냅샷의 미배치 작업 수", registry=registry)
        self.placement_success_ratio = Gauge(prefix + "placement_success_ratio", "작업 배치 성공 비율", registry=registry)
        self.deadline_met_ratio = Gauge(prefix + "deadline_met_ratio", "마감시간 준수 비율", registry=registry)
        self.average_queue_wait_seconds = Gauge(prefix + "average_queue_wait_seconds", "평균 큐 대기시간(초)", registry=registry)
        self.maximum_queue_wait_seconds = Gauge(prefix + "maximum_queue_wait_seconds", "최대 큐 대기시간(초)", registry=registry)
        self.average_total_time_seconds = Gauge(prefix + "average_total_time_seconds", "평균 총 처리시간(초)", registry=registry)
        self.node_jobs_total = Gauge(prefix + "node_jobs_total", "연산 노드에 배치된 작업 수", ("node",), registry=registry)
        self.node_queue_wait_seconds = Gauge(prefix + "node_queue_wait_seconds", "연산 노드별 평균 큐 대기시간(초)", ("node",), registry=registry)
        self.node_available = Gauge(prefix + "node_available", "스냅샷에서 성공 배치 대상으로 관측된 노드", ("node",), registry=registry)
        self.failed_links = Gauge(prefix + "failed_links", "시나리오의 장애 링크 수", registry=registry)
        self.scenario_info = Gauge(prefix + "scenario_info", "현재 내보내는 시나리오", ("scenario",), registry=registry)
        self.alert_severity = Gauge(prefix + "alert_severity", "현재 운영 경보 등급", ("severity",), registry=registry)
        self.unavailable_nodes = Gauge(prefix + "unavailable_nodes", "사용 불가 연산 노드 수", registry=registry)
        self.active_incidents = Gauge(prefix + "active_incidents", "현재 활성 인시던트 수", registry=registry)
        self.incidents_total = Gauge(prefix + "incidents_total", "서버 시작 후 생성된 인시던트 수", registry=registry)
        self.incident_acknowledged_total = Gauge(prefix + "incident_acknowledged_total", "서버 시작 후 확인 처리된 인시던트 수", registry=registry)
        self.incident_resolved_total = Gauge(prefix + "incident_resolved_total", "서버 시작 후 종료된 인시던트 수", registry=registry)
        self.recovery_active_failures = Gauge(prefix + "active_failures", "활성 동적 장애 수", registry=registry)
        self.operational_phase = Gauge(prefix + "operational_phase", "동적 운영 단계", ("phase",), registry=registry)
        self.failure_detection_seconds = Gauge(prefix + "failure_detection_seconds", "장애 발생부터 틱 기반 감지까지의 시간", registry=registry)
        self.reroute_seconds = Gauge(prefix + "reroute_seconds", "감지부터 우회 완료까지의 시간", registry=registry)
        self.service_recovery_seconds = Gauge(prefix + "service_recovery_seconds", "최초 장애부터 정상 서비스 복원까지의 시간", registry=registry)
        self.jobs_unplaced_during_failure = Gauge(prefix + "jobs_unplaced_during_failure", "장애 활성 중 최초 배치에 실패한 작업 수", registry=registry)
        self.retry_success_ratio = Gauge(prefix + "retry_success_ratio", "pending 작업 재시도 성공 비율", registry=registry)
        self.active_scenario: str | None = None


def _read_csv(path: Path, required_columns: Iterable[str]) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            columns = set(reader.fieldnames or ())
            missing = set(required_columns) - columns
            if missing:
                raise MetricsDataError(
                    f"{path.name} 필수 열 누락: {', '.join(sorted(missing))}"
                )
            parsed_rows: list[dict[str, str]] = []
            for row_number, row in enumerate(reader, start=2):
                if None in row or any(value is None for value in row.values()):
                    raise MetricsDataError(
                        f"{path.name} {row_number}행의 열 개수가 올바르지 않습니다"
                    )
                parsed_rows.append({key: value.strip() for key, value in row.items()})
            return parsed_rows
    except MetricsDataError:
        raise
    except (OSError, csv.Error) as error:
        raise MetricsDataError(f"{path.name} 읽기 실패: {error}") from error


def _number(row: Mapping[str, str], column: str, file_name: str) -> float:
    try:
        value = float(row[column])
    except (KeyError, TypeError, ValueError) as error:
        raise MetricsDataError(f"{file_name}의 {column} 값이 올바르지 않습니다") from error
    if not math.isfinite(value):
        raise MetricsDataError(f"{file_name}의 {column} 값이 유한수가 아닙니다")
    return value


def _integer(row: Mapping[str, str], column: str, file_name: str) -> int:
    value = _number(row, column, file_name)
    if not value.is_integer():
        raise MetricsDataError(f"{file_name}의 {column} 값이 정수가 아닙니다")
    return int(value)


def _optional_seconds(row: Mapping[str, str], column: str, file_name: str) -> float | None:
    if not row.get(column, ""):
        return None
    return _number(row, column, file_name) / 1000.0


def _optional_boolean(row: Mapping[str, str], column: str, file_name: str) -> bool | None:
    value = row.get(column, "").lower()
    if not value:
        return None
    if value not in {"true", "false"}:
        raise MetricsDataError(f"{file_name}의 {column} 값이 올바르지 않습니다")
    return value == "true"


def _failed_edges(value: str) -> set[tuple[int, int]]:
    edges: set[tuple[int, int]] = set()
    if not value:
        return edges
    for raw_edge in value.split(";"):
        parts = raw_edge.split("-")
        if len(parts) != 2:
            raise MetricsDataError(f"failed_isls 형식이 올바르지 않습니다: {value}")
        try:
            first, second = (int(part) for part in parts)
        except ValueError as error:
            raise MetricsDataError(f"failed_isls 형식이 올바르지 않습니다: {value}") from error
        edges.add(tuple(sorted((first, second))))
    return edges


def load_metrics_snapshot(
    scenario: str,
    data_directory: Path | None = None,
) -> MetricsSnapshot:
    """Load and validate one deterministic scenario snapshot from CSV files."""
    if scenario not in SUPPORTED_SCENARIOS:
        raise ValueError(f"지원하지 않는 시나리오: {scenario}")
    data_dir = data_directory or Path(__file__).resolve().parents[1] / "demo_data"
    summary_rows = _read_csv(
        data_dir / "workload_experiment_summary.csv",
        (
            "scenario", "total_jobs", "placed_jobs", "unplaced_jobs",
            "placement_success_rate_percent", "deadline_met_rate_percent",
            "average_queue_wait_ms", "maximum_queue_wait_ms",
            "average_total_time_ms",
        ),
    )
    result_rows = _read_csv(
        data_dir / "workload_experiment_results.csv",
        (
            "job_id", "scenario", "placement_status", "selected_node",
            "queue_wait_time_ms", "compute_time_ms", "total_time_ms",
            "deadline_ms", "deadline_met", "failed_isls",
        ),
    )
    placement_rows = _read_csv(
        data_dir / "placement_results.csv",
        ("scenario", "placement_status", "selected_node", "failed_isls"),
    )
    routing_rows = _read_csv(
        data_dir / "routing_events.csv",
        ("time_ns", "source", "destination", "failed_isls", "status"),
    )

    matching_summaries = [row for row in summary_rows if row["scenario"] == scenario]
    matching_results = [row for row in result_rows if row["scenario"] == scenario]
    matching_placements = [row for row in placement_rows if row["scenario"] == BASE_SCENARIOS[scenario]]
    failure_marker = EXPECTED_FAILED_LINKS[scenario]
    matching_routing = [row for row in routing_rows if row["failed_isls"] == failure_marker]
    if len(matching_summaries) != 1:
        raise MetricsDataError(f"{scenario} 요약 행은 정확히 하나여야 합니다")
    if not matching_results or not matching_placements or not matching_routing:
        raise MetricsDataError(f"{scenario}에 필요한 결과 행이 없습니다")

    summary = matching_summaries[0]
    for row in matching_results:
        if row["placement_status"] not in {"PLACED", "UNPLACED"}:
            raise MetricsDataError("workload_experiment_results.csv의 placement_status 값이 올바르지 않습니다")
    for row in matching_placements:
        if row["placement_status"] not in {"PLACED", "UNPLACED", "FAILED"}:
            raise MetricsDataError("placement_results.csv의 placement_status 값이 올바르지 않습니다")
        if row["placement_status"] == "PLACED":
            _integer(row, "selected_node", "placement_results.csv")
    for row in matching_routing:
        _integer(row, "time_ns", "routing_events.csv")
        _integer(row, "source", "routing_events.csv")
        _integer(row, "destination", "routing_events.csv")
        if row["status"] not in {"NORMAL", "REROUTED", "DROPPED"}:
            raise MetricsDataError("routing_events.csv의 status 값이 올바르지 않습니다")

    placed_rows = [row for row in matching_results if row["placement_status"] == "PLACED"]
    job_records: list[JobRecord] = []
    for row in matching_results:
        placed = row["placement_status"] == "PLACED"
        assigned_node = _integer(row, "selected_node", "workload_experiment_results.csv") if placed else None
        job_records.append(
            JobRecord(
                job_id=row["job_id"],
                status=row["placement_status"],
                assigned_node=assigned_node,
                queue_wait_seconds=_optional_seconds(row, "queue_wait_time_ms", "workload_experiment_results.csv"),
                processing_seconds=_optional_seconds(row, "compute_time_ms", "workload_experiment_results.csv"),
                total_time_seconds=_optional_seconds(row, "total_time_ms", "workload_experiment_results.csv"),
                deadline_seconds=_optional_seconds(row, "deadline_ms", "workload_experiment_results.csv"),
                deadline_met=_optional_boolean(row, "deadline_met", "workload_experiment_results.csv"),
                failure_reason=None,
            )
        )
    node_counts = {node: 0 for node in COMPUTE_NODES}
    node_queue_ms: dict[int, list[float]] = {node: [] for node in COMPUTE_NODES}
    for row in placed_rows:
        node = _integer(row, "selected_node", "workload_experiment_results.csv")
        if node not in node_counts:
            raise MetricsDataError(f"지원하지 않는 연산 노드가 선택되었습니다: {node}")
        node_counts[node] += 1
        node_queue_ms[node].append(
            _number(row, "queue_wait_time_ms", "workload_experiment_results.csv")
        )

    failed_edges: set[tuple[int, int]] = set()
    for row in (*matching_results, *matching_placements, *matching_routing):
        failed_edges.update(_failed_edges(row["failed_isls"]))

    placement_ratio = _number(summary, "placement_success_rate_percent", "workload_experiment_summary.csv") / 100.0
    deadline_ratio = _number(summary, "deadline_met_rate_percent", "workload_experiment_summary.csv") / 100.0
    if not 0.0 <= placement_ratio <= 1.0 or not 0.0 <= deadline_ratio <= 1.0:
        raise MetricsDataError("비율 지표가 0.0~1.0 범위를 벗어났습니다")

    return MetricsSnapshot(
        scenario=scenario,
        jobs_total=_integer(summary, "total_jobs", "workload_experiment_summary.csv"),
        jobs_placed_total=_integer(summary, "placed_jobs", "workload_experiment_summary.csv"),
        jobs_unplaced_total=_integer(summary, "unplaced_jobs", "workload_experiment_summary.csv"),
        placement_success_ratio=placement_ratio,
        deadline_met_ratio=deadline_ratio,
        average_queue_wait_seconds=_number(summary, "average_queue_wait_ms", "workload_experiment_summary.csv") / 1000.0,
        maximum_queue_wait_seconds=_number(summary, "maximum_queue_wait_ms", "workload_experiment_summary.csv") / 1000.0,
        average_total_time_seconds=_number(summary, "average_total_time_ms", "workload_experiment_summary.csv") / 1000.0,
        node_jobs_total=node_counts,
        node_queue_wait_seconds={node: (sum(values) / len(values) / 1000.0 if values else None) for node, values in node_queue_ms.items()},
        node_available={node: int(node_counts[node] > 0) for node in COMPUTE_NODES},
        failed_links=len(failed_edges),
        jobs=tuple(job_records),
    )


def update_prometheus_metrics(
    snapshot: MetricsSnapshot,
    metrics: PrometheusMetrics,
    alert: OperationalAlert,
) -> None:
    """Atomically apply a validated CSV snapshot to registered gauges."""
    metrics.jobs_total.set(snapshot.jobs_total)
    metrics.jobs_placed_total.set(snapshot.jobs_placed_total)
    metrics.jobs_unplaced_total.set(snapshot.jobs_unplaced_total)
    metrics.placement_success_ratio.set(snapshot.placement_success_ratio)
    metrics.deadline_met_ratio.set(snapshot.deadline_met_ratio)
    metrics.average_queue_wait_seconds.set(snapshot.average_queue_wait_seconds)
    metrics.maximum_queue_wait_seconds.set(snapshot.maximum_queue_wait_seconds)
    metrics.average_total_time_seconds.set(snapshot.average_total_time_seconds)
    metrics.failed_links.set(snapshot.failed_links)
    metrics.unavailable_nodes.set(alert.unavailable_nodes)
    for severity in ("normal", "warning", "critical"):
        metrics.alert_severity.labels(severity=severity).set(int(severity == alert.severity))
    for node in COMPUTE_NODES:
        label = str(node)
        metrics.node_jobs_total.labels(node=label).set(snapshot.node_jobs_total[node])
        metrics.node_available.labels(node=label).set(snapshot.node_available[node])
        queue_wait = snapshot.node_queue_wait_seconds[node]
        metrics.node_queue_wait_seconds.labels(node=label).set(0 if queue_wait is None else queue_wait)
    if metrics.active_scenario and metrics.active_scenario != snapshot.scenario:
        try:
            metrics.scenario_info.remove(metrics.active_scenario)
        except KeyError:
            pass
    metrics.scenario_info.labels(scenario=snapshot.scenario).set(1)
    metrics.active_scenario = snapshot.scenario


def evaluate_operational_alert(snapshot: MetricsSnapshot) -> OperationalAlert:
    """Apply deterministic operational thresholds to one loaded snapshot."""
    critical_reasons: list[str] = []
    warning_reasons: list[str] = []
    unavailable_node_ids = [node for node in COMPUTE_NODES if not snapshot.node_available[node]]

    if snapshot.jobs_unplaced_total > 0:
        critical_reasons.append(f"미배치 작업 {snapshot.jobs_unplaced_total}개 발생")
    if snapshot.placement_success_ratio < 0.95:
        critical_reasons.append(f"배치 성공률 {snapshot.placement_success_ratio * 100:.2f}%로 임계값 미만")
    if snapshot.average_queue_wait_seconds >= 60:
        critical_reasons.append(f"평균 큐 대기시간 {snapshot.average_queue_wait_seconds:.2f}초로 심각 임계값 도달")

    warning_reasons.extend(f"연산 노드 SAT-{node} 사용 불가" for node in unavailable_node_ids)
    if 30 <= snapshot.average_queue_wait_seconds < 60:
        warning_reasons.append(f"평균 큐 대기시간 {snapshot.average_queue_wait_seconds:.2f}초로 주의 임계값 도달")
    if snapshot.failed_links > 0:
        warning_reasons.append(f"장애 링크 {snapshot.failed_links}개 감지")

    severity: AlertSeverity = "critical" if critical_reasons else "warning" if warning_reasons else "normal"
    labels: Mapping[AlertSeverity, str] = {"normal": "정상", "warning": "주의", "critical": "심각"}
    return OperationalAlert(
        severity=severity,
        severity_label=labels[severity],
        reasons=tuple((*critical_reasons, *warning_reasons)),
        unavailable_nodes=len(unavailable_node_ids),
    )


def _iso_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


class MetricsController:
    """Own the active scenario and serialize snapshot/Gauge updates."""

    def __init__(self, registry: CollectorRegistry, scenario: str) -> None:
        self.registry = registry
        self.lock = threading.RLock()
        self.metrics: PrometheusMetrics | None = None
        event_labels = ("scenario", "algorithm", "source")
        self.csv_selected_node = Gauge("space_ai_datacenter_csv_selected_node", "선택한 CSV 이벤트의 노드, 실패는 -1", event_labels, registry=registry)
        self.csv_placement_status = Gauge("space_ai_datacenter_csv_placement_status", "선택한 CSV 이벤트의 배치 상태", event_labels + ("placement_status",), registry=registry)
        self.csv_active_failures = Gauge("space_ai_datacenter_csv_active_failure_count", "선택한 CSV 이벤트의 활성 장애 링크 수", event_labels, registry=registry)
        self.csv_event_time = Gauge("space_ai_datacenter_csv_event_time_ns", "선택한 CSV 이벤트 timestamp", event_labels, registry=registry)
        self.csv_routing_status = Gauge("space_ai_datacenter_csv_routing_status", "동일 timestamp의 라우팅 상태", event_labels + ("routing_status",), registry=registry)
        self.current_snapshot: MetricsSnapshot | None = None
        self.current_alert: OperationalAlert | None = None
        self.snapshot_available = False
        self.active_scenario = scenario
        self.updated_at = _iso_timestamp()
        self.events: list[OperationalEvent] = []
        self.event_sequence = 1
        self.incidents: list[OperationalIncident] = []
        self.incident_sequence = 1
        self.incident_acknowledged_count = 0
        self.incident_resolved_count = 0
        self.started_monotonic = time.monotonic()
        self.dynamic_state: dict[str, object] = {
            "simulation_time_seconds": 0.0,
            "operational_phase": "healthy",
            "active_failures": 0,
            "current_failure_ids": [],
            "last_failure": None,
            "last_recovery": None,
            "recovery_metrics": {},
        }
        self.failure_history: list[dict[str, object]] = []

    def placement_event_response(self, time_ns: int, scenario: str, source: int,
                                 data_directory: Path | None = None) -> dict[str, object]:
        data_dir = data_directory or Path(__file__).resolve().parents[1] / "demo_data"
        placements = _read_csv(data_dir / "placement_results.csv",
                               ("time_ns", "scenario", "source_node", "algorithm", "selected_node", "placement_status", "failed_isls"))
        routing = _read_csv(data_dir / "routing_events.csv",
                            ("time_ns", "source", "failed_isls", "status"))
        events = []
        for row in placements:
            if (int(row["time_ns"]) != time_ns or row["scenario"] != scenario
                    or int(row["source_node"]) != source
                    or row["algorithm"] not in {"network_only", "compute_aware", "completion_time"}):
                continue
            failures = _failed_edges(row["failed_isls"])
            statuses = sorted({route["status"] for route in routing
                               if int(route["time_ns"]) == time_ns and int(route["source"]) == source
                               and _failed_edges(route["failed_isls"]) == failures})
            placed = row["placement_status"] == "PLACED" and int(row["selected_node"]) >= 0
            events.append({"time_ns": time_ns, "scenario": scenario, "source": source,
                           "algorithm": row["algorithm"], "failed_isls": ";".join("%d-%d" % edge for edge in sorted(failures)),
                           "routing_status": statuses, "placement_status": "PLACED" if placed else "FAILED",
                           "selected_node": int(row["selected_node"]) if placed else -1,
                           "active_failure_count": len(failures)})
        if not events:
            raise ValueError("해당 timestamp와 시나리오의 placement가 없습니다")
        with self.lock:
            # A cursor represents one displayed event; clear previous cursor labels.
            for gauge in (self.csv_selected_node, self.csv_placement_status, self.csv_active_failures,
                          self.csv_event_time, self.csv_routing_status):
                gauge.clear()
            for event in events:
                labels = (scenario, event["algorithm"], str(source))
                self.csv_selected_node.labels(*labels).set(event["selected_node"])
                self.csv_placement_status.labels(*labels, event["placement_status"]).set(1)
                self.csv_active_failures.labels(*labels).set(event["active_failure_count"])
                self.csv_event_time.labels(*labels).set(time_ns)
                for status in event["routing_status"] or ["NO_DATA"]:
                    self.csv_routing_status.labels(*labels, status).set(1)
        return {"time_ns": time_ns, "scenario": scenario, "events": events}

    def _append_event(
        self,
        timestamp: str,
        level: EventLevel,
        category: EventCategory,
        event_type: str,
        target: str,
        message: str,
    ) -> None:
        self.events.append(
            OperationalEvent(
                event_id=f"event-{self.event_sequence:06d}",
                timestamp=timestamp,
                level=level,
                category=category,
                type=event_type,
                target=target,
                message=message,
            )
        )
        self.event_sequence += 1
        if len(self.events) > 500:
            del self.events[:-500]

    @staticmethod
    def _unavailable_node_ids(snapshot: MetricsSnapshot) -> tuple[int, ...]:
        return tuple(node for node in COMPUTE_NODES if not snapshot.node_available[node])

    def _record_snapshot_events(
        self,
        previous_snapshot: MetricsSnapshot | None,
        previous_alert: OperationalAlert | None,
        snapshot: MetricsSnapshot,
        alert: OperationalAlert,
        timestamp: str,
    ) -> None:
        scenario_changed = previous_snapshot is None or previous_snapshot.scenario != snapshot.scenario
        if scenario_changed:
            message = f"운영 시나리오 시작: {SCENARIO_LABELS[snapshot.scenario]}" if previous_snapshot is None else f"운영 시나리오 변경: {SCENARIO_LABELS[previous_snapshot.scenario]} → {SCENARIO_LABELS[snapshot.scenario]}"
            self._append_event(timestamp, "info", "system", "scenario_changed", snapshot.scenario, message)

        if previous_alert is not None and previous_alert.severity != alert.severity:
            level: EventLevel = "critical" if alert.severity == "critical" else "warning" if alert.severity == "warning" else "info"
            self._append_event(timestamp, level, "system", "severity_changed", alert.severity, f"운영 등급 변경: {previous_alert.severity_label} → {alert.severity_label}")
            _log(logging.WARNING if alert.severity != "normal" else logging.INFO, "severity_changed", "운영 등급이 변경되었습니다.", scenario=snapshot.scenario)

        previous_failed_links = previous_snapshot.failed_links if previous_snapshot and not scenario_changed else -1
        if snapshot.failed_links > 0 and snapshot.failed_links != previous_failed_links:
            self._append_event(timestamp, "warning", "network", "failed_link_detected", snapshot.scenario, f"장애 링크 {snapshot.failed_links}개 감지")

        previous_unavailable = set(self._unavailable_node_ids(previous_snapshot)) if previous_snapshot and not scenario_changed else set()
        for node in self._unavailable_node_ids(snapshot):
            if node not in previous_unavailable:
                self._append_event(timestamp, "warning", "node", "node_unavailable", f"SAT-{node}", f"연산 노드 SAT-{node} 사용 불가 감지")

        previous_unplaced = previous_snapshot.jobs_unplaced_total if previous_snapshot and not scenario_changed else -1
        if snapshot.jobs_unplaced_total > 0 and snapshot.jobs_unplaced_total != previous_unplaced:
            self._append_event(timestamp, "critical", "job", "jobs_unplaced", snapshot.scenario, f"미배치 작업 {snapshot.jobs_unplaced_total}개 발생")

    @staticmethod
    def _incident_details(snapshot: MetricsSnapshot, alert: OperationalAlert) -> tuple[list[str], list[str], list[str], list[str]]:
        unavailable = [f"SAT-{node}" for node in COMPUTE_NODES if not snapshot.node_available[node]]
        causes: list[str] = []
        impacts: list[str] = []
        actions: list[str] = []
        if snapshot.failed_links:
            causes.append(f"장애 링크 {snapshot.failed_links}개 활성")
            actions.append("장애 링크와 우회 경로 상태 확인")
        if unavailable:
            causes.append(f"연산 노드 {', '.join(unavailable)} 사용 불가")
            actions.append(f"{', '.join(unavailable)} 접근성과 연결 상태 확인")
        if snapshot.jobs_unplaced_total:
            impacts.append(f"미배치 작업 {snapshot.jobs_unplaced_total}개 발생")
            actions.append("미배치 작업과 가용 연산 자원 확인")
        if snapshot.placement_success_ratio < 0.95:
            impacts.append(f"배치 성공률 {snapshot.placement_success_ratio * 100:.2f}%")
        if snapshot.average_queue_wait_seconds >= 30:
            impacts.append(f"평균 큐 대기시간 {snapshot.average_queue_wait_seconds:.2f}초")
            actions.append("연산 노드별 작업 집중도와 큐 대기시간 확인")
        if not causes:
            causes.extend(alert.reasons)
        return causes, impacts, actions, unavailable

    def _sync_incident_metrics(self) -> None:
        if self.metrics is None:
            return
        self.metrics.active_incidents.set(sum(incident.status != "resolved" for incident in self.incidents))
        self.metrics.incidents_total.set(self.incident_sequence - 1)
        self.metrics.incident_acknowledged_total.set(self.incident_acknowledged_count)
        self.metrics.incident_resolved_total.set(self.incident_resolved_count)

    def _update_incidents(
        self,
        snapshot: MetricsSnapshot,
        alert: OperationalAlert,
        timestamp: str,
        transition_event_ids: list[str],
    ) -> None:
        active = next((incident for incident in reversed(self.incidents) if incident.status != "resolved"), None)
        is_clear = (
            snapshot.failed_links == 0
            and not self._unavailable_node_ids(snapshot)
            and snapshot.jobs_unplaced_total == 0
            and alert.severity == "normal"
        )
        if is_clear:
            if active is not None:
                active.status = "resolved"
                active.resolved_at = timestamp
                active.related_event_ids.extend(event_id for event_id in transition_event_ids if event_id not in active.related_event_ids)
                self.incident_resolved_count += 1
                _log(logging.INFO, "incident_resolved", "인시던트가 종료되었습니다.", scenario=snapshot.scenario, incident_id=active.incident_id)
            self._sync_incident_metrics()
            return

        causes, impacts, actions, affected_nodes = self._incident_details(snapshot, alert)
        if active is None:
            incident_id = f"INC-{self.incident_sequence:04d}"
            self.incident_sequence += 1
            active = OperationalIncident(
                incident_id=incident_id,
                title=f"{SCENARIO_LABELS[snapshot.scenario]} 운영 이상",
                status="open",
                severity=alert.severity,
                severity_label=alert.severity_label,
                scenario=snapshot.scenario,
                started_at=timestamp,
                acknowledged_at=None,
                resolved_at=None,
                causes=causes,
                impacts=impacts,
                actions=actions,
                related_event_ids=list(dict.fromkeys(transition_event_ids)),
                affected_nodes=affected_nodes,
                affected_job_count=snapshot.jobs_unplaced_total,
            )
            self.incidents.append(active)
            _log(logging.WARNING, "incident_created", "인시던트가 생성되었습니다.", scenario=snapshot.scenario, incident_id=incident_id)
            if len(self.incidents) > 100:
                del self.incidents[:-100]
        else:
            active.title = f"{SCENARIO_LABELS[snapshot.scenario]} 운영 이상"
            active.scenario = snapshot.scenario
            active.severity = alert.severity
            active.severity_label = alert.severity_label
            active.causes = causes
            active.impacts = impacts
            active.actions = actions
            active.affected_nodes = affected_nodes
            active.affected_job_count = snapshot.jobs_unplaced_total
            active.related_event_ids.extend(event_id for event_id in transition_event_ids if event_id not in active.related_event_ids)
        self._sync_incident_metrics()

    def _apply_scenario_locked(self, scenario: str) -> None:
        snapshot = load_metrics_snapshot(scenario)
        alert = evaluate_operational_alert(snapshot)
        previous_snapshot = self.current_snapshot
        previous_alert = self.current_alert
        if self.metrics is None:
            self.metrics = PrometheusMetrics(self.registry)
        update_prometheus_metrics(snapshot, self.metrics, alert)
        updated_at = _iso_timestamp()
        self.current_snapshot = snapshot
        self.current_alert = alert
        self.snapshot_available = True
        self.active_scenario = scenario
        self.updated_at = updated_at
        event_sequence_start = self.event_sequence
        self._record_snapshot_events(previous_snapshot, previous_alert, snapshot, alert, updated_at)
        transition_event_ids = [
            event.event_id
            for event in self.events
            if int(event.event_id.removeprefix("event-")) >= event_sequence_start
        ]
        self._update_incidents(snapshot, alert, updated_at, transition_event_ids)
        self.dynamic_state = {
            "simulation_time_seconds": 0.0, "operational_phase": "healthy",
            "active_failures": 0, "current_failure_ids": [],
            "last_failure": None, "last_recovery": None,
            "recovery_metrics": {},
        }
        self._update_recovery_metrics()

    def _update_recovery_metrics(self) -> None:
        if self.metrics is None:
            return
        state = self.dynamic_state
        recovery = state.get("recovery_metrics")
        recovery = recovery if isinstance(recovery, dict) else {}
        self.metrics.recovery_active_failures.set(float(state.get("active_failures", 0)))
        phase = str(state.get("operational_phase", "healthy"))
        for candidate in ("healthy", "degraded", "rerouting", "recovering"):
            self.metrics.operational_phase.labels(phase=candidate).set(int(candidate == phase))
        gauges = (
            (self.metrics.failure_detection_seconds, "detection_time_seconds"),
            (self.metrics.reroute_seconds, "reroute_time_seconds"),
            (self.metrics.service_recovery_seconds, "service_recovery_time_seconds"),
            (self.metrics.jobs_unplaced_during_failure, "jobs_unplaced_during_failure"),
            (self.metrics.retry_success_ratio, "retry_success_ratio"),
        )
        for gauge, name in gauges:
            value = recovery.get(name)
            gauge.set(0 if value is None else float(value))

    def apply_dynamic_result(self, result: Mapping[str, object]) -> None:
        """Publish one deterministic simulation result without changing static CSV behavior."""
        with self.lock:
            phase = result.get("operational_phase")
            if phase not in {"healthy", "degraded", "rerouting", "recovering"}:
                raise ValueError("지원하지 않는 operational_phase입니다")
            self.dynamic_state = {
                key: result.get(key)
                for key in (
                    "simulation_time_seconds", "operational_phase", "active_failures",
                    "current_failure_ids", "last_failure", "last_recovery", "recovery_metrics",
                )
            }
            failures = result.get("failures")
            if not isinstance(failures, list) or any(not isinstance(item, dict) for item in failures):
                raise ValueError("동적 failure 기록이 올바르지 않습니다")
            known = {str(item.get("failure_id")): item for item in self.failure_history}
            for item in failures:
                known[str(item["failure_id"])] = dict(item)
            self.failure_history = list(known.values())[-100:]
            self.updated_at = _iso_timestamp()
            self._update_recovery_metrics()

    def refresh(self) -> None:
        with self.lock:
            scenario = self.active_scenario
            try:
                self._apply_scenario_locked(scenario)
            except (MetricsDataError, OSError, ValueError):
                self.snapshot_available = False
                _log(logging.ERROR, "snapshot_load_failed", "운영 스냅샷을 불러오지 못했습니다.", scenario=scenario)
                raise
        _log(logging.INFO, "snapshot_loaded", "운영 스냅샷을 불러왔습니다.", scenario=scenario)

    def set_scenario(self, scenario: str) -> None:
        if scenario not in SUPPORTED_SCENARIOS:
            _log(logging.ERROR, "scenario_change_failed", "지원하지 않는 메트릭 시나리오입니다.", scenario=scenario)
            raise ValueError(f"지원하지 않는 시나리오입니다: {scenario}")
        try:
            with self.lock:
                self._apply_scenario_locked(scenario)
        except (MetricsDataError, OSError, ValueError):
            _log(logging.ERROR, "scenario_change_failed", "메트릭 시나리오를 변경하지 못했습니다.", scenario=scenario)
            raise
        _log(logging.INFO, "scenario_changed", "메트릭 시나리오를 변경했습니다.", scenario=scenario)

    def scenario_response(self) -> dict[str, str]:
        with self.lock:
            return {
                "scenario": self.active_scenario,
                "updated_at": self.updated_at,
            }

    @staticmethod
    def _failure_response(record: Mapping[str, object]) -> dict[str, object]:
        return {key: record.get(key) for key in (
            "failure_id", "type", "target", "status", "occurred_at_seconds",
            "detected_at_seconds", "recovered_at_seconds", "affected_nodes",
            "affected_jobs", "related_event_ids", "recovery_metrics",
        )}

    def failures_response(self) -> dict[str, object]:
        with self.lock:
            records = list(reversed(self.failure_history))
            return {"failures": [self._failure_response(item) for item in records], "total": len(records)}

    def failure_detail_response(self, failure_id: str) -> dict[str, object] | None:
        with self.lock:
            record = next((item for item in self.failure_history if item.get("failure_id") == failure_id), None)
            return None if record is None else self._failure_response(record)

    def status_response(self) -> dict[str, object] | None:
        with self.lock:
            snapshot = self.current_snapshot
            alert = self.current_alert
            if snapshot is None or alert is None or not self.snapshot_available:
                return None
            active_incidents = [incident for incident in self.incidents if incident.status != "resolved"]
            return {
                "scenario": snapshot.scenario,
                "scenario_label": SCENARIO_LABELS[snapshot.scenario],
                "jobs_total": snapshot.jobs_total,
                "jobs_placed": snapshot.jobs_placed_total,
                "jobs_unplaced": snapshot.jobs_unplaced_total,
                "placement_success_ratio": snapshot.placement_success_ratio,
                "deadline_met_ratio": snapshot.deadline_met_ratio,
                "average_queue_wait_seconds": snapshot.average_queue_wait_seconds,
                "maximum_queue_wait_seconds": snapshot.maximum_queue_wait_seconds,
                "average_total_time_seconds": snapshot.average_total_time_seconds,
                "failed_links": snapshot.failed_links,
                "severity": alert.severity,
                "severity_label": alert.severity_label,
                "alert_reasons": list(alert.reasons),
                "active_incident_count": len(active_incidents),
                "active_incident_ids": [incident.incident_id for incident in active_incidents],
                "nodes": [
                    {
                        "node": node,
                        "available": bool(snapshot.node_available[node]),
                        "jobs": snapshot.node_jobs_total[node],
                        "average_queue_wait_seconds": snapshot.node_queue_wait_seconds[node],
                    }
                    for node in COMPUTE_NODES
                ],
                "updated_at": self.updated_at,
                **self.dynamic_state,
            }

    @staticmethod
    def _job_response(job: JobRecord) -> dict[str, object]:
        return {
            "job_id": job.job_id,
            "status": job.status,
            "assigned_node": job.assigned_node,
            "queue_wait_seconds": job.queue_wait_seconds,
            "processing_seconds": job.processing_seconds,
            "total_time_seconds": job.total_time_seconds,
            "deadline_seconds": job.deadline_seconds,
            "deadline_met": job.deadline_met,
            "failure_reason": job.failure_reason,
        }

    @staticmethod
    def _event_response(event: OperationalEvent) -> dict[str, str]:
        return {
            "event_id": event.event_id,
            "timestamp": event.timestamp,
            "level": event.level,
            "category": event.category,
            "type": event.type,
            "target": event.target,
            "message": event.message,
        }

    def _node_response(self, snapshot: MetricsSnapshot, node: int) -> dict[str, object]:
        return {
            "node": node,
            "label": f"SAT-{node}",
            "available": bool(snapshot.node_available[node]),
            "jobs": snapshot.node_jobs_total[node],
            "average_queue_wait_seconds": snapshot.node_queue_wait_seconds[node],
            "utilization_ratio": None,
            "status_label": "사용 가능" if snapshot.node_available[node] else "사용 불가",
        }

    def nodes_response(self) -> dict[str, object] | None:
        with self.lock:
            snapshot = self.current_snapshot
            if snapshot is None or not self.snapshot_available:
                return None
            return {"nodes": [self._node_response(snapshot, node) for node in COMPUTE_NODES], "updated_at": self.updated_at}

    def node_detail_response(self, node: int) -> dict[str, object] | None:
        with self.lock:
            snapshot = self.current_snapshot
            if snapshot is None or not self.snapshot_available:
                return None
            jobs = [self._job_response(job) for job in snapshot.jobs if job.assigned_node == node]
            events = [self._event_response(event) for event in reversed(self.events) if event.target == f"SAT-{node}"][:20]
            return {"node": self._node_response(snapshot, node), "jobs": jobs, "events": events, "updated_at": self.updated_at}

    def jobs_response(self, status: str | None, node: int | None, limit: int) -> dict[str, object] | None:
        with self.lock:
            snapshot = self.current_snapshot
            if snapshot is None or not self.snapshot_available:
                return None
            jobs = list(snapshot.jobs)
            if status == "placed":
                jobs = [job for job in jobs if job.status == "PLACED"]
            elif status == "unplaced":
                jobs = [job for job in jobs if job.status == "UNPLACED"]
            elif status == "deadline_missed":
                jobs = [job for job in jobs if job.deadline_met is False]
            if node is not None:
                jobs = [job for job in jobs if job.assigned_node == node]
            return {"jobs": [self._job_response(job) for job in jobs[:limit]], "total": len(jobs), "limit": limit, "updated_at": self.updated_at}

    def events_response(self, level: str | None, category: str | None, limit: int) -> dict[str, object] | None:
        with self.lock:
            if self.current_snapshot is None or not self.snapshot_available:
                return None
            events = list(reversed(self.events))
            if level:
                events = [event for event in events if event.level == level]
            if category:
                events = [event for event in events if event.category == category]
            return {"events": [self._event_response(event) for event in events[:limit]], "total": len(events), "limit": limit}

    @staticmethod
    def _incident_response(incident: OperationalIncident) -> dict[str, object]:
        return {
            "incident_id": incident.incident_id,
            "title": incident.title,
            "status": incident.status,
            "severity": incident.severity,
            "severity_label": incident.severity_label,
            "scenario": incident.scenario,
            "started_at": incident.started_at,
            "acknowledged_at": incident.acknowledged_at,
            "resolved_at": incident.resolved_at,
            "causes": list(incident.causes),
            "impacts": list(incident.impacts),
            "actions": list(incident.actions),
            "related_event_ids": list(incident.related_event_ids),
            "affected_nodes": list(incident.affected_nodes),
            "affected_job_count": incident.affected_job_count,
        }

    def incidents_response(self, status: str | None, severity: str | None, limit: int) -> dict[str, object]:
        with self.lock:
            incidents = list(reversed(self.incidents))
            if status:
                incidents = [incident for incident in incidents if incident.status == status]
            if severity:
                incidents = [incident for incident in incidents if incident.severity == severity]
            return {"incidents": [self._incident_response(incident) for incident in incidents[:limit]], "total": len(incidents), "limit": limit}

    def incident_detail_response(self, incident_id: str) -> dict[str, object] | None:
        with self.lock:
            incident = next((item for item in self.incidents if item.incident_id == incident_id), None)
            if incident is None:
                return None
            event_ids = set(incident.related_event_ids)
            payload = self._incident_response(incident)
            payload["events"] = [self._event_response(event) for event in self.events if event.event_id in event_ids]
            return payload

    def acknowledge_incident(self, incident_id: str) -> dict[str, object] | None:
        with self.lock:
            incident = next((item for item in self.incidents if item.incident_id == incident_id), None)
            if incident is None:
                return None
            if incident.status == "open":
                incident.status = "acknowledged"
                incident.acknowledged_at = _iso_timestamp()
                self.incident_acknowledged_count += 1
                self._sync_incident_metrics()
                _log(logging.INFO, "incident_acknowledged", "인시던트를 확인 처리했습니다.", scenario=incident.scenario, incident_id=incident.incident_id)
            return self._incident_response(incident)

    def health_response(self) -> dict[str, object]:
        return {
            "status": "ok",
            "service": SERVICE_NAME,
            "uptime_seconds": max(0.0, time.monotonic() - self.started_monotonic),
            "timestamp": _iso_timestamp(),
        }

    def readiness_response(self) -> tuple[bool, dict[str, object]]:
        with self.lock:
            status_available = self.status_response() is not None
            snapshot_loaded = self.snapshot_available and self.current_snapshot is not None
            metrics_ready = (
                self.metrics is not None
                and self.metrics.active_scenario == self.active_scenario
            )
            ready = snapshot_loaded and status_available and metrics_ready
            return ready, {
                "status": "ready" if ready else "not_ready",
                "service": SERVICE_NAME,
                "snapshot_loaded": snapshot_loaded,
                "metrics_ready": metrics_ready,
                "current_scenario": self.active_scenario,
                "timestamp": _iso_timestamp(),
            }

    def render_metrics(self) -> bytes:
        with self.lock:
            return generate_latest(self.registry)


WSGIStartResponse = Callable[[str, list[tuple[str, str]]], object]
WSGIApplication = Callable[[dict[str, object], WSGIStartResponse], list[bytes]]


def make_wsgi_application(controller: MetricsController) -> WSGIApplication:
    """Route Prometheus and scenario-control requests in one WSGI app."""

    def application(
        environ: dict[str, object],
        start_response: WSGIStartResponse,
    ) -> list[bytes]:
        method = str(environ.get("REQUEST_METHOD", "GET")).upper()
        path = str(environ.get("PATH_INFO", ""))
        query = parse_qs(str(environ.get("QUERY_STRING", "")), keep_blank_values=True)
        origin_value = environ.get("HTTP_ORIGIN")
        origin = origin_value if isinstance(origin_value, str) else None
        request_started = time.monotonic()

        def respond(
            status: str,
            body: bytes,
            content_type: str = "application/json; charset=utf-8",
        ) -> list[bytes]:
            headers = [
                ("Content-Type", content_type),
                ("Content-Length", str(len(body))),
            ]
            if origin in ALLOWED_FRONTEND_ORIGINS and path not in {"/health", "/ready"}:
                headers.extend(
                    (
                        ("Access-Control-Allow-Origin", origin),
                        ("Access-Control-Allow-Methods", "GET,POST,OPTIONS"),
                        ("Access-Control-Allow-Headers", "Content-Type"),
                        ("Vary", "Origin"),
                    )
                )
            start_response(status, headers)
            status_code = int(status.split()[0])
            if status_code >= 400:
                _log(
                    logging.WARNING if status_code < 500 else logging.ERROR,
                    "api_error",
                    "API 요청이 오류 응답으로 완료되었습니다.",
                    method=method,
                    path=path,
                    status_code=status_code,
                    duration_ms=round((time.monotonic() - request_started) * 1000, 3),
                )
            return [body]

        def json_response(status: str, payload: Mapping[str, object]) -> list[bytes]:
            return respond(
                status,
                json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            )

        def query_value(name: str) -> str | None:
            values = query.get(name)
            return values[0] if values else None

        def query_limit() -> int:
            raw_limit = query_value("limit")
            limit = 50 if raw_limit is None else int(raw_limit)
            if not 1 <= limit <= 500:
                raise ValueError
            return limit

        if method == "GET" and path == "/health":
            return json_response("200 OK", controller.health_response())

        if method == "GET" and path == "/ready":
            ready, payload = controller.readiness_response()
            return json_response("200 OK" if ready else "503 Service Unavailable", payload)

        if method == "GET" and path == "/metrics":
            return respond("200 OK", controller.render_metrics(), CONTENT_TYPE_LATEST)

        if method == "GET" and path == "/api/placement-event":
            try:
                return json_response("200 OK", controller.placement_event_response(
                    int(query_value("time_ns") or "-1"), query_value("scenario") or "",
                    int(query_value("source") or "12"),
                ))
            except (ValueError, MetricsDataError, OSError) as error:
                return json_response("400 Bad Request", {"error": str(error)})

        if method == "GET" and path == "/api/scenario":
            return json_response("200 OK", controller.scenario_response())

        if method == "GET" and path == "/api/status":
            status_payload = controller.status_response()
            if status_payload is None:
                return json_response(
                    "503 Service Unavailable",
                    {"error": "현재 운영 스냅샷을 불러올 수 없습니다."},
                )
            return json_response("200 OK", status_payload)

        if method == "GET" and path == "/api/failures":
            return json_response("200 OK", controller.failures_response())

        failure_match = re.fullmatch(r"/api/failures/([A-Za-z0-9._-]+)", path)
        if method == "GET" and failure_match:
            failure_payload = controller.failure_detail_response(failure_match.group(1))
            if failure_payload is None:
                return json_response("404 Not Found", {"error": "알 수 없는 장애 기록입니다."})
            return json_response("200 OK", failure_payload)

        if method == "GET" and path == "/api/nodes":
            nodes_payload = controller.nodes_response()
            if nodes_payload is None:
                return json_response("503 Service Unavailable", {"error": "현재 노드 상태를 불러올 수 없습니다."})
            return json_response("200 OK", nodes_payload)

        node_match = re.fullmatch(r"/api/nodes/(\d+)", path)
        if method == "GET" and node_match:
            node = int(node_match.group(1))
            if node not in COMPUTE_NODES:
                return json_response("404 Not Found", {"error": f"알 수 없는 연산 노드입니다: SAT-{node}"})
            node_payload = controller.node_detail_response(node)
            if node_payload is None:
                return json_response("503 Service Unavailable", {"error": "현재 노드 상세를 불러올 수 없습니다."})
            return json_response("200 OK", node_payload)

        if method == "GET" and path == "/api/jobs":
            try:
                status_filter = query_value("status")
                if status_filter not in {None, "placed", "unplaced", "deadline_missed"}:
                    raise ValueError
                node_filter_raw = query_value("node")
                node_filter = None if node_filter_raw is None else int(node_filter_raw)
                if node_filter is not None and node_filter not in COMPUTE_NODES:
                    raise ValueError
                limit = query_limit()
            except ValueError:
                return json_response("400 Bad Request", {"error": "작업 조회 필터가 올바르지 않습니다."})
            jobs_payload = controller.jobs_response(status_filter, node_filter, limit)
            if jobs_payload is None:
                return json_response("503 Service Unavailable", {"error": "현재 작업 데이터를 불러올 수 없습니다."})
            return json_response("200 OK", jobs_payload)

        if method == "GET" and path == "/api/events":
            try:
                level_filter = query_value("level")
                category_filter = query_value("category")
                if level_filter not in {None, "info", "warning", "critical"} or category_filter not in {None, "network", "node", "job", "system"}:
                    raise ValueError
                limit = query_limit()
            except ValueError:
                return json_response("400 Bad Request", {"error": "이벤트 조회 필터가 올바르지 않습니다."})
            events_payload = controller.events_response(level_filter, category_filter, limit)
            if events_payload is None:
                return json_response("503 Service Unavailable", {"error": "현재 이벤트 데이터를 불러올 수 없습니다."})
            return json_response("200 OK", events_payload)

        if method == "GET" and path == "/api/incidents":
            try:
                status_filter = query_value("status")
                severity_filter = query_value("severity")
                if status_filter not in {None, "open", "acknowledged", "resolved"}:
                    raise ValueError
                if severity_filter not in {None, "normal", "warning", "critical"}:
                    raise ValueError
                raw_limit = query_value("limit")
                limit = 20 if raw_limit is None else int(raw_limit)
                if not 1 <= limit <= 100:
                    raise ValueError
            except ValueError:
                return json_response("400 Bad Request", {"error": "인시던트 조회 필터가 올바르지 않습니다."})
            return json_response("200 OK", controller.incidents_response(status_filter, severity_filter, limit))

        incident_match = re.fullmatch(r"/api/incidents/(INC-\d{4,})", path)
        if method == "GET" and incident_match:
            incident_payload = controller.incident_detail_response(incident_match.group(1))
            if incident_payload is None:
                return json_response("404 Not Found", {"error": "알 수 없는 인시던트입니다."})
            return json_response("200 OK", incident_payload)

        acknowledge_match = re.fullmatch(r"/api/incidents/(INC-\d{4,})/acknowledge", path)
        if method == "POST" and acknowledge_match:
            incident_payload = controller.acknowledge_incident(acknowledge_match.group(1))
            if incident_payload is None:
                return json_response("404 Not Found", {"error": "알 수 없는 인시던트입니다."})
            return json_response("200 OK", incident_payload)

        if method == "OPTIONS" and (path == "/api/scenario" or acknowledge_match):
            return respond("204 No Content", b"")

        if method == "POST" and path == "/api/scenario":
            try:
                content_length = int(str(environ.get("CONTENT_LENGTH", "0")))
                if content_length <= 0 or content_length > 4096:
                    raise ValueError
                request_stream = cast(BinaryIO, environ["wsgi.input"])
                payload = json.loads(request_stream.read(content_length).decode("utf-8"))
                scenario = payload.get("scenario") if isinstance(payload, dict) else None
                if not isinstance(scenario, str):
                    raise ValueError
            except (KeyError, ValueError, json.JSONDecodeError, UnicodeDecodeError):
                return json_response(
                    "400 Bad Request",
                    {"error": "시나리오 요청 JSON이 올바르지 않습니다."},
                )

            if scenario not in SUPPORTED_SCENARIOS:
                return json_response(
                    "400 Bad Request",
                    {"error": f"지원하지 않는 시나리오입니다: {scenario}"},
                )
            try:
                controller.set_scenario(scenario)
            except (MetricsDataError, OSError, ValueError):
                return json_response(
                    "500 Internal Server Error",
                    {"error": "시나리오 메트릭을 갱신할 수 없습니다."},
                )
            return json_response("200 OK", controller.scenario_response())

        return json_response(
            "404 Not Found",
            {"error": "요청 경로를 찾을 수 없습니다."},
        )

    def guarded_application(
        environ: dict[str, object],
        start_response: WSGIStartResponse,
    ) -> list[bytes]:
        try:
            return application(environ, start_response)
        except Exception:
            method = str(environ.get("REQUEST_METHOD", "GET")).upper()
            path = str(environ.get("PATH_INFO", ""))
            LOGGER.exception(
                "요청 처리 중 예기치 않은 오류가 발생했습니다.",
                extra={
                    "component": "metrics_server",
                    "event_type": "request_exception",
                    "method": method,
                    "path": path,
                    "status_code": 500,
                },
            )
            body = json.dumps({"error": "요청을 처리할 수 없습니다."}, ensure_ascii=False).encode("utf-8")
            start_response("500 Internal Server Error", [("Content-Type", "application/json; charset=utf-8"), ("Content-Length", str(len(body)))])
            return [body]

    return guarded_application


class MetricsWSGIRequestHandler(WSGIRequestHandler):
    def log_message(self, format_string: str, *args: object) -> None:
        LOGGER.debug("HTTP 요청: " + format_string, *args)


def _positive_number(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("0보다 큰 숫자여야 합니다")
    return parsed


def _port_number(value: str) -> int:
    parsed = int(value)
    if not 1 <= parsed <= 65535:
        raise argparse.ArgumentTypeError("포트는 1~65535 범위여야 합니다")
    return parsed


def main() -> None:
    parser = argparse.ArgumentParser(description="우주 AI 데이터센터 Prometheus 메트릭 서버")
    parser.add_argument("--host", default=os.environ.get("HOST", "0.0.0.0"))
    parser.add_argument("--port", type=_port_number, default=os.environ.get("PORT", "8000"))
    parser.add_argument("--scenario", choices=SUPPORTED_SCENARIOS, default=os.environ.get("SCENARIO", "NORMAL_BURST"))
    parser.add_argument("--refresh-seconds", type=_positive_number, default=30.0)
    parser.add_argument("--dynamic-scenario", type=Path)
    parser.add_argument("--dynamic-policy", choices=("compute_only", "network_only", "compute_aware", "completion_time"), default="completion_time")
    parser.add_argument("--dynamic-workload", choices=("demo", "burst"), default="demo")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    dynamic_result = None
    if args.dynamic_scenario is not None:
        from .dynamic_scenario import DynamicScenarioError, load_scenario, simulate_dynamic_scenario
        try:
            dynamic_result = simulate_dynamic_scenario(
                load_scenario(args.dynamic_scenario), args.dynamic_policy,
                args.dynamic_workload, args.seed,
            )
        except DynamicScenarioError as error:
            parser.error(str(error))

    log_level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_name, None)
    if not isinstance(log_level, int):
        parser.error(f"지원하지 않는 LOG_LEVEL입니다: {log_level_name}")
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonLogFormatter())
    logging.basicConfig(level=log_level, handlers=[handler], force=True)
    registry = CollectorRegistry()
    controller = MetricsController(registry, args.scenario)

    def refresh() -> None:
        try:
            controller.refresh()
            if dynamic_result is not None:
                controller.apply_dynamic_result(dynamic_result)
        except (MetricsDataError, OSError, ValueError):
            pass

    refresh()
    stop_refresh = threading.Event()

    def refresh_periodically() -> None:
        while not stop_refresh.wait(args.refresh_seconds):
            refresh()

    refresh_thread = threading.Thread(
        target=refresh_periodically,
        name="metrics-refresh",
        daemon=True,
    )
    refresh_thread.start()
    server = make_server(
        args.host,
        args.port,
        make_wsgi_application(controller),
        handler_class=MetricsWSGIRequestHandler,
    )
    _log(logging.INFO, "service_startup", "메트릭 서버가 요청을 받을 준비가 되었습니다.", scenario=args.scenario)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        _log(logging.INFO, "service_shutdown", "메트릭 서버를 종료합니다.", scenario=controller.active_scenario)
    finally:
        stop_refresh.set()
        server.server_close()


if __name__ == "__main__":
    main()
