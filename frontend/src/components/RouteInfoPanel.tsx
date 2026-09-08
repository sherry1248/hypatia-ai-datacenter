import type { FailedLinkSelection, PlacementResult, Scenario } from '../types';
import { SCENARIO_LABELS } from './LayerControls';

interface Props { route: PlacementResult | null; failedLink: FailedLinkSelection | null; scenario: Scenario; timeNs: number; }
export function RouteInfoPanel({ route, failedLink, scenario, timeNs }: Props) {
  return <section className="route-info">
    <div className="panel-title"><span>{failedLink ? '장애 링크 상세' : '활성 경로'}</span><small>{SCENARIO_LABELS[scenario]}</small></div>
    {failedLink ? <dl className="telemetry compact">
      <div><dt>링크 종단점</dt><dd>SAT-{failedLink.from} ↔ SAT-{failedLink.to}</dd></div><div><dt>장애 상태</dt><dd className="danger">통신 불가</dd></div><div><dt>시나리오</dt><dd>{SCENARIO_LABELS[scenario]}</dd></div><div><dt>현재 시점</dt><dd>T + {(timeNs / 1e9).toFixed(1)}초</dd></div>
    </dl> : route ? <dl className="telemetry compact">
      <div><dt>소스 노드</dt><dd>NODE-{route.sourceNode}</dd></div><div><dt>목적 연산 노드</dt><dd>{route.selectedNode === null ? '—' : `SAT-${route.selectedNode}`}</dd></div><div className="route-sequence"><dt>경로 노드 순서</dt><dd>{route.route.length ? route.route.join(' → ') : '경로 없음'}</dd></div><div><dt>홉 수</dt><dd>{route.hopCount}</dd></div><div><dt>네트워크 지연</dt><dd>{route.rttNs === null ? '—' : `${(route.rttNs / 1e6).toFixed(2)} ms`}</dd></div><div><dt>배치 상태</dt><dd className={route.placementStatus === 'PLACED' ? 'healthy' : 'danger'}>{route.placementStatus === 'PLACED' ? '배치 완료' : '배치 불가'}</dd></div>
    </dl> : <div className="empty-state">표시할 경로 정보가 없습니다.</div>}
  </section>;
}
