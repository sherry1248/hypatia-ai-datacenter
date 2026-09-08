import type { AlertSeverity, BackendScenario, OperationalStatus, OperationalStatusNode } from '../types';

const STATUS_API_URL = '/api/status';
const BACKEND_SCENARIOS = new Set<BackendScenario>(['NORMAL_BURST', 'FAILED_ISL_0_1_BURST', 'MULTI_FAILED_ISL_0_1_10_11_BURST']);
const ALERT_SEVERITIES = new Set<AlertSeverity>(['normal', 'warning', 'critical']);
const isRecord = (value: unknown): value is Record<string, unknown> => typeof value === 'object' && value !== null;
const isFiniteNumber = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);

function parseNode(value: unknown): OperationalStatusNode | null {
  if (!isRecord(value) || !isFiniteNumber(value.node) || typeof value.available !== 'boolean' || !isFiniteNumber(value.jobs) || !(value.average_queue_wait_seconds === null || isFiniteNumber(value.average_queue_wait_seconds))) return null;
  return { node: value.node, available: value.available, jobs: value.jobs, average_queue_wait_seconds: value.average_queue_wait_seconds };
}

function parseStatus(value: unknown): OperationalStatus {
  if (!isRecord(value) || typeof value.scenario !== 'string' || !BACKEND_SCENARIOS.has(value.scenario as BackendScenario) || typeof value.scenario_label !== 'string' || typeof value.updated_at !== 'string' || !Array.isArray(value.nodes) || typeof value.severity !== 'string' || !ALERT_SEVERITIES.has(value.severity as AlertSeverity) || typeof value.severity_label !== 'string' || !Array.isArray(value.alert_reasons) || !value.alert_reasons.every((reason) => typeof reason === 'string') || !isFiniteNumber(value.active_incident_count) || !Array.isArray(value.active_incident_ids) || !value.active_incident_ids.every((id) => typeof id === 'string')) throw new Error('운영 상태 응답이 올바르지 않습니다.');
  const numericKeys = ['jobs_total', 'jobs_placed', 'jobs_unplaced', 'placement_success_ratio', 'deadline_met_ratio', 'average_queue_wait_seconds', 'maximum_queue_wait_seconds', 'average_total_time_seconds', 'failed_links'] as const;
  if (numericKeys.some((key) => !isFiniteNumber(value[key]))) throw new Error('운영 상태 수치가 올바르지 않습니다.');
  const successRatio = value.placement_success_ratio as number; const deadlineRatio = value.deadline_met_ratio as number;
  if (successRatio < 0 || successRatio > 1 || deadlineRatio < 0 || deadlineRatio > 1) throw new Error('운영 상태 비율이 올바르지 않습니다.');
  const nodes = value.nodes.map(parseNode);
  if (nodes.some((node) => node === null)) throw new Error('운영 노드 상태가 올바르지 않습니다.');
  return {
    scenario: value.scenario as BackendScenario,
    scenario_label: value.scenario_label,
    jobs_total: value.jobs_total as number,
    jobs_placed: value.jobs_placed as number,
    jobs_unplaced: value.jobs_unplaced as number,
    placement_success_ratio: successRatio,
    deadline_met_ratio: deadlineRatio,
    average_queue_wait_seconds: value.average_queue_wait_seconds as number,
    maximum_queue_wait_seconds: value.maximum_queue_wait_seconds as number,
    average_total_time_seconds: value.average_total_time_seconds as number,
    failed_links: value.failed_links as number,
    severity: value.severity as AlertSeverity,
    severity_label: value.severity_label,
    alert_reasons: value.alert_reasons as string[],
    active_incident_count: value.active_incident_count,
    active_incident_ids: value.active_incident_ids as string[],
    nodes: nodes as OperationalStatusNode[],
    updated_at: value.updated_at,
    simulation_time_seconds: isFiniteNumber(value.simulation_time_seconds) ? value.simulation_time_seconds : 0,
    operational_phase: ['healthy', 'degraded', 'rerouting', 'recovering'].includes(String(value.operational_phase)) ? value.operational_phase as OperationalStatus['operational_phase'] : 'healthy',
    active_failures: isFiniteNumber(value.active_failures) ? value.active_failures : 0,
    current_failure_ids: Array.isArray(value.current_failure_ids) ? value.current_failure_ids.filter((id): id is string => typeof id === 'string') : [],
    last_failure: isRecord(value.last_failure) ? value.last_failure as unknown as OperationalStatus['last_failure'] : null,
    last_recovery: typeof value.last_recovery === 'string' ? value.last_recovery : null,
    recovery_metrics: isRecord(value.recovery_metrics) ? value.recovery_metrics as OperationalStatus['recovery_metrics'] : {},
  };
}

export async function getOperationalStatus(): Promise<OperationalStatus> {
  const response = await fetch(STATUS_API_URL);
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) throw new Error(isRecord(payload) && typeof payload.error === 'string' ? payload.error : `HTTP ${response.status}`);
  return parseStatus(payload);
}
