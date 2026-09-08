import { useMemo } from 'react';
import type { NetworkCost, Scenario, ScenarioComparisonResult, ScenarioDeadlineRatios } from '../types';

interface Props {
  results: ScenarioComparisonResult[];
  networkCosts: NetworkCost[];
  loading: boolean;
  warning: string | null;
  currentScenario: Scenario;
  onViewScenario: (scenario: Scenario) => void;
  deadlineRatios: ScenarioDeadlineRatios;
}

interface ComparisonRow {
  scenario: Scenario;
  total: number;
  placed: number;
  unplaced: number;
  successRatio: number;
  deadlineRatio: number | null;
  averageQueueMs: number | null;
  averageTotalMs: number | null;
  failedLinks: number;
  unavailableNodes: number[];
  selectedNodeCounts: Map<number, number>;
}

const SCENARIOS: Scenario[] = ['NORMAL', 'FAILED_ISL_0_1', 'MULTI_FAILED_ISL_0_1_10_11'];
const LABELS: Record<Scenario, string> = { NORMAL: '정상', FAILED_ISL_0_1: '단일 장애', MULTI_FAILED_ISL_0_1_10_11: '다중 장애' };
const FAILURE_KEYS: Record<Scenario, string> = { NORMAL: '', FAILED_ISL_0_1: '0-1', MULTI_FAILED_ISL_0_1_10_11: '0-1;10-11' };
const average = (values: Array<number | null>): number | null => { const present = values.filter((value): value is number => value !== null); return present.length ? present.reduce((sum, value) => sum + value, 0) / present.length : null; };
const linkKey = ([from, to]: readonly [number, number]) => `${Math.min(from, to)}-${Math.max(from, to)}`;

function buildRows(results: ScenarioComparisonResult[], costs: NetworkCost[], deadlineRatios: ScenarioDeadlineRatios): ComparisonRow[] {
  return SCENARIOS.map((scenario) => {
    const scenarioResults = results.filter((result) => result.scenario === scenario);
    const placedResults = scenarioResults.filter((result) => result.placementStatus === 'PLACED');
    const selectedNodeCounts = new Map<number, number>();
    placedResults.forEach((result) => { if (result.selectedNode !== null) selectedNodeCounts.set(result.selectedNode, (selectedNodeCounts.get(result.selectedNode) ?? 0) + 1); });
    const scenarioCosts = costs.filter((cost) => cost.failedIsls.map(linkKey).join(';') === FAILURE_KEYS[scenario]);
    const nodeStatuses = new Map<number, NetworkCost['status'][]>();
    scenarioCosts.forEach((cost) => nodeStatuses.set(cost.computeNode, [...(nodeStatuses.get(cost.computeNode) ?? []), cost.status]));
    const unavailableNodes = [...nodeStatuses.entries()].filter(([, statuses]) => statuses.length > 0 && statuses.every((status) => status === 'UNREACHABLE')).map(([node]) => node).sort((a, b) => a - b);
    const failedLinks = new Set(scenarioResults.flatMap((result) => result.failedIsls.map(linkKey))).size;
    return { scenario, total: scenarioResults.length, placed: placedResults.length, unplaced: scenarioResults.length - placedResults.length, successRatio: scenarioResults.length ? placedResults.length / scenarioResults.length : 0, deadlineRatio: deadlineRatios[scenario] ?? null, averageQueueMs: average(scenarioResults.map((result) => result.queueWaitMs)), averageTotalMs: average(scenarioResults.map((result) => result.totalTimeMs)), failedLinks, unavailableNodes, selectedNodeCounts };
  });
}

const formatRatio = (value: number | null) => value === null ? '데이터 없음' : `${(value * 100).toFixed(1)}%`;
const formatTime = (value: number | null) => value === null ? '데이터 없음' : `${(value / 1000).toFixed(2)}초`;
const extrema = (rows: ComparisonRow[], key: 'successRatio' | 'deadlineRatio' | 'averageQueueMs' | 'averageTotalMs' | 'unplaced', mode: 'min' | 'max') => {
  const values = rows.map((row) => row[key]).filter((value): value is number => value !== null);
  return values.length ? (mode === 'max' ? Math.max(...values) : Math.min(...values)) : null;
};

function interpretation(rows: ComparisonRow[]): string {
  const normal = rows.find((row) => row.scenario === 'NORMAL'); const multi = rows.find((row) => row.scenario === 'MULTI_FAILED_ISL_0_1_10_11');
  if (!normal || !multi || !multi.total) return '비교 해석에 필요한 다중 장애 데이터가 없습니다.';
  const sentences: string[] = [];
  if (multi.unavailableNodes.length) sentences.push(`다중 장애에서 ${multi.unavailableNodes.map((node) => `SAT-${node}`).join(', ')}이(가) 전체 관측 시점에 걸쳐 접근 불가였습니다.`);
  const destinations = [...multi.selectedNodeCounts.entries()].sort((a, b) => b[1] - a[1]);
  if (destinations.length) sentences.push(`배치된 ${multi.placed}개 결과는 ${destinations.map(([node, count]) => `SAT-${node} ${count}개`).join(', ')}로 분포했습니다.`);
  if (normal.averageQueueMs !== null && multi.averageQueueMs !== null && multi.averageQueueMs > normal.averageQueueMs) sentences.push(`평균 큐 대기시간은 정상 ${(normal.averageQueueMs / 1000).toFixed(2)}초에서 다중 장애 ${(multi.averageQueueMs / 1000).toFixed(2)}초로 증가했습니다.`);
  if (multi.unplaced > normal.unplaced) sentences.push(`미배치 결과는 정상 ${normal.unplaced}개에서 다중 장애 ${multi.unplaced}개로 증가했습니다.`);
  return sentences.length ? sentences.join(' ') : '현재 CSV에서는 다중 장애의 추가 성능 저하가 관측되지 않았습니다.';
}

export function ScenarioComparisonPanel({ results, networkCosts, loading, warning, currentScenario, onViewScenario, deadlineRatios }: Props) {
  const rows = useMemo(() => buildRows(results, networkCosts, deadlineRatios), [results, networkCosts, deadlineRatios]);
  const bestSuccess = extrema(rows, 'successRatio', 'max'); const bestDeadline = extrema(rows, 'deadlineRatio', 'max');
  const worstUnplaced = extrema(rows, 'unplaced', 'max'); const worstQueue = extrema(rows, 'averageQueueMs', 'max'); const worstTotal = extrema(rows, 'averageTotalMs', 'max');
  const normal = rows[0];
  const cellClass = (kind: 'success' | 'deadline' | 'unplaced' | 'queue' | 'total', row: ComparisonRow) => {
    const value = kind === 'success' ? row.successRatio : kind === 'deadline' ? row.deadlineRatio : kind === 'unplaced' ? row.unplaced : kind === 'queue' ? row.averageQueueMs : row.averageTotalMs;
    const target = kind === 'success' ? bestSuccess : kind === 'deadline' ? bestDeadline : kind === 'unplaced' ? worstUnplaced : kind === 'queue' ? worstQueue : worstTotal;
    const classes = value !== null && target !== null && value === target ? (kind === 'success' || kind === 'deadline' ? ['best'] : ['worst']) : [];
    if (row.scenario === 'MULTI_FAILED_ISL_0_1_10_11' && value !== null) {
      const baseline = kind === 'success' ? normal.successRatio : kind === 'deadline' ? normal.deadlineRatio : kind === 'unplaced' ? normal.unplaced : kind === 'queue' ? normal.averageQueueMs : normal.averageTotalMs;
      if (baseline !== null && (kind === 'success' || kind === 'deadline' ? value < baseline : value > baseline)) classes.push('degraded');
    }
    return classes.join(' ');
  };

  return <details className="scenario-comparison">
    <summary>시나리오 성능 비교 <span>saved experiment CSV</span></summary>
    <div className="comparison-body">
      {loading ? <p className="comparison-warning">비교 데이터를 불러오는 중입니다.</p> : warning ? <p className="comparison-warning">{warning}</p> : rows.some((row) => !row.total) ? <p className="comparison-warning">일부 시나리오의 비교 CSV 데이터가 없습니다.</p> : <>
        <div className="comparison-table-wrap"><table><thead><tr><th>시나리오</th><th>전체 작업 수</th><th>배치 성공 작업</th><th>미배치 작업</th><th>배치 성공률</th><th>마감 준수율</th><th>평균 큐 대기시간</th><th>평균 전체 처리시간</th><th>장애 링크 수</th><th>사용 불가 연산 노드</th><th>선택</th></tr></thead><tbody>{rows.map((row) => <tr key={row.scenario} className={row.scenario === 'MULTI_FAILED_ISL_0_1_10_11' && (row.unplaced > normal.unplaced || row.successRatio < normal.successRatio) ? 'multi-degraded' : ''}><th>{LABELS[row.scenario]}</th><td>{row.total}</td><td>{row.placed}</td><td className={cellClass('unplaced', row)}>{row.unplaced}</td><td className={cellClass('success', row)}>{formatRatio(row.successRatio)}</td><td className={cellClass('deadline', row)}>{formatRatio(row.deadlineRatio)}</td><td className={cellClass('queue', row)}>{formatTime(row.averageQueueMs)}</td><td className={cellClass('total', row)}>{formatTime(row.averageTotalMs)}</td><td>{row.failedLinks}</td><td>{row.unavailableNodes.length ? row.unavailableNodes.map((node) => `SAT-${node}`).join(', ') : '없음'}</td><td><button type="button" disabled={currentScenario === row.scenario} onClick={() => onViewScenario(row.scenario)}>{currentScenario === row.scenario ? '현재 시나리오' : '이 시나리오 보기'}</button></td></tr>)}</tbody></table></div>
        {rows.some((row) => row.deadlineRatio === null) && <p className="comparison-schema-note">저장된 workload 요약 CSV가 없으면 마감 준수율은 데이터 없음으로 표시됩니다.</p>}
        <p className="comparison-interpretation">{interpretation(rows)}</p>
      </>}
    </div>
  </details>;
}
