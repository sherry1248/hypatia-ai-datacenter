import type { Link, NetworkCost, NodePosition, NodeType, PlacementResult, RoutingEvent, Scenario, ScenarioComparisonResult, ScenarioDeadlineRatios } from '../types';

function rows(csv: string, expected: readonly string[]): Record<string, string>[] {
  const lines = csv.trim().split(/\r?\n/);
  if (lines.length < 2) throw new Error('CSV에 데이터가 없습니다.');
  const header = lines[0].split(',').map((value) => value.trim());
  for (const column of expected) if (!header.includes(column)) throw new Error(`CSV 필수 열이 없습니다: ${column}`);
  return lines.slice(1).map((line, rowIndex) => {
    const values = line.split(',').map((value) => value.trim());
    if (values.length !== header.length) throw new Error(`CSV ${rowIndex + 2}행의 열 개수가 올바르지 않습니다.`);
    return Object.fromEntries(header.map((column, index) => [column, values[index]]));
  });
}

function number(value: string, name: string): number {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) throw new Error(`${name} 값이 숫자가 아닙니다: ${value}`);
  return parsed;
}
const nullableNumber = (value: string): number | null => value === '' ? null : number(value, '숫자');
const route = (value: string): number[] => value === '' ? [] : value.split('-').map((part) => number(part, '경로 노드'));
const links = (value: string): Link[] => value === '' ? [] : value.split(';').map((edge) => {
  const pair = edge.split('-').map((part) => number(part, '링크 노드'));
  if (pair.length !== 2) throw new Error(`장애 링크 형식이 올바르지 않습니다: ${edge}`);
  return [pair[0], pair[1]] as const;
});

async function load(url: string): Promise<string> {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${url} 데이터를 불러오지 못했습니다 (${response.status}).`);
  return response.text();
}

export async function loadNodePositions(): Promise<NodePosition[]> {
  return rows(await load('/data/node_positions.csv'), ['time_ns', 'node_id', 'node_type', 'latitude_deg', 'longitude_deg', 'altitude_m']).map((row) => {
    const nodeType = row.node_type as NodeType;
    if (!['SATELLITE', 'GROUND_STATION'].includes(nodeType)) throw new Error(`알 수 없는 노드 유형: ${nodeType}`);
    return { timeNs: number(row.time_ns, 'time_ns'), nodeId: number(row.node_id, 'node_id'), nodeType, latitudeDeg: number(row.latitude_deg, 'latitude_deg'), longitudeDeg: number(row.longitude_deg, 'longitude_deg'), altitudeM: number(row.altitude_m, 'altitude_m') };
  });
}

export async function loadNetworkCosts(): Promise<NetworkCost[]> {
  return rows(await load('/data/network_costs.csv'), ['time_ns', 'source', 'compute_node', 'route', 'rtt_ns', 'hop_count', 'failed_isls', 'status']).map((row) => ({ timeNs: number(row.time_ns, 'time_ns'), source: number(row.source, 'source'), computeNode: number(row.compute_node, 'compute_node'), route: route(row.route), rttNs: nullableNumber(row.rtt_ns), hopCount: number(row.hop_count, 'hop_count'), failedIsls: links(row.failed_isls), status: row.status as NetworkCost['status'] }));
}

export async function loadRoutingEvents(): Promise<RoutingEvent[]> {
  return rows(await load('/data/routing_events.csv'), ['time_ns', 'source', 'destination', 'route', 'rtt_ns', 'hop_count', 'failed_isls', 'status']).map((row) => ({ timeNs: number(row.time_ns, 'time_ns'), source: number(row.source, 'source'), destination: number(row.destination, 'destination'), route: route(row.route), rttNs: nullableNumber(row.rtt_ns), hopCount: number(row.hop_count, 'hop_count'), failedIsls: links(row.failed_isls), status: row.status as RoutingEvent['status'] }));
}

export async function loadPlacements(): Promise<PlacementResult[]> {
  return rows(await load('/data/placement_results.csv'), ['time_ns', 'scenario', 'source_node', 'placement_status', 'algorithm', 'selected_node', 'route', 'rtt_ns', 'hop_count', 'failed_isls'])
    .filter((row) => row.algorithm === 'completion_time' && ['NORMAL', 'FAILED_ISL_0_1', 'MULTI_FAILED_ISL_0_1_10_11'].includes(row.scenario))
    .map((row) => ({ timeNs: number(row.time_ns, 'time_ns'), scenario: row.scenario as Scenario, sourceNode: number(row.source_node, 'source_node'), placementStatus: row.placement_status as PlacementResult['placementStatus'], selectedNode: row.selected_node === '-1' || row.selected_node === '' ? null : number(row.selected_node, 'selected_node'), route: route(row.route), rttNs: nullableNumber(row.rtt_ns), hopCount: number(row.hop_count, 'hop_count'), failedIsls: links(row.failed_isls) }));
}

export async function loadScenarioComparisonResults(): Promise<ScenarioComparisonResult[]> {
  return rows(await load('/data/placement_results.csv'), ['scenario', 'placement_status', 'algorithm', 'selected_node', 'queue_wait_time_ms', 'total_time_ms', 'failed_isls'])
    .filter((row) => row.algorithm === 'completion_time' && ['NORMAL', 'FAILED_ISL_0_1', 'MULTI_FAILED_ISL_0_1_10_11'].includes(row.scenario))
    .map((row) => ({ scenario: row.scenario as Scenario, placementStatus: row.placement_status as ScenarioComparisonResult['placementStatus'], selectedNode: row.selected_node === '-1' || row.selected_node === '' ? null : number(row.selected_node, 'selected_node'), queueWaitMs: nullableNumber(row.queue_wait_time_ms), totalTimeMs: nullableNumber(row.total_time_ms), failedIsls: links(row.failed_isls) }));
}

export async function loadScenarioDeadlineRatios(): Promise<ScenarioDeadlineRatios> {
  const scenarioMap: Record<string, Scenario> = { NORMAL_BURST: 'NORMAL', FAILED_ISL_0_1_BURST: 'FAILED_ISL_0_1', MULTI_FAILED_ISL_0_1_10_11_BURST: 'MULTI_FAILED_ISL_0_1_10_11' };
  const deadlineRatios: ScenarioDeadlineRatios = {};
  rows(await load('/data/workload_experiment_summary.csv'), ['scenario', 'deadline_met_rate_percent']).forEach((row) => {
    const scenario = scenarioMap[row.scenario]; if (!scenario) return;
    const percent = number(row.deadline_met_rate_percent, 'deadline_met_rate_percent');
    if (percent < 0 || percent > 100) throw new Error(`마감 준수율 범위가 올바르지 않습니다: ${percent}`);
    deadlineRatios[scenario] = percent / 100;
  });
  return deadlineRatios;
}

export function nearestTime<T extends { timeNs: number }>(items: T[], target: number): number | null {
  const times = [...new Set(items.map((item) => item.timeNs))];
  return times.length ? times.reduce((best, value) => Math.abs(value - target) < Math.abs(best - target) ? value : best) : null;
}
