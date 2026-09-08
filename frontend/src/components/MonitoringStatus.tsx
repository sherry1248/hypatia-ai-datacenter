import type { OperationalIncident, OperationalStatus, Scenario, ScenarioSyncState } from '../types';
import { SCENARIO_LABELS } from './LayerControls';

interface MonitoringStatusProps {
  scenario: Scenario;
  status: OperationalStatus | null;
  disconnected: boolean;
  syncState: ScenarioSyncState;
  syncWarning: string | null;
  incidents: OperationalIncident[];
  incidentsStale: boolean;
}

const SYNC_LABELS: Record<ScenarioSyncState, string> = { syncing: '동기화 중', complete: '동기화 완료', failed: '동기화 실패' };
const ratio = (value: number) => `${(value * 100).toFixed(1)}%`;
const seconds = (value: number | null) => value === null ? '데이터 없음' : `${value.toFixed(2)}초`;
const freshness = (updatedAt: string) => {
  const date = new Date(updatedAt);
  return Number.isNaN(date.getTime()) ? '확인 불가' : date.toLocaleTimeString('ko-KR', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
};

export function MonitoringStatus({ scenario, status, disconnected, syncState, syncWarning, incidents, incidentsStale }: MonitoringStatusProps) {
  const unavailableNodes = status?.nodes.filter((node) => !node.available) ?? [];
  const activeIncidents = incidents.filter((incident) => incident.status !== 'resolved');
  const highestSeverity = activeIncidents.some((incident) => incident.severity === 'critical') ? '심각' : activeIncidents.some((incident) => incident.severity === 'warning') ? '주의' : '정상';
  const oldestStartedAt = activeIncidents.length ? activeIncidents.reduce((oldest, incident) => incident.started_at < oldest ? incident.started_at : oldest, activeIncidents[0].started_at) : null;
  return (
    <section className={`monitoring-status ${disconnected ? 'stale' : ''}`}>
      <div className="panel-title"><span>현재 운영 상태</span><small className={`sync-state ${syncState}`}>{SYNC_LABELS[syncState]}</small></div>
      <p className="status-source">backend /api/status</p>
      {disconnected && <p className="status-disconnected">운영 지표 연결 끊김{status ? ' · 마지막 정상 값 표시 중' : ''}</p>}
      {status ? <>
        <div className={`severity-badge ${status.severity}`} role="status" aria-label={`현재 운영 등급 ${status.severity_label}`}><span aria-hidden="true">{status.severity === 'normal' ? '●' : status.severity === 'warning' ? '▲' : '!'}</span><small>현재 운영 등급</small><strong>{status.severity_label}</strong></div>
        <div className="alert-reasons"><strong>경보 사유</strong>{status.alert_reasons.length ? <ul>{status.alert_reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul> : <p>활성 경보 없음</p>}</div>
        <div className="incident-summary"><strong>활성 인시던트</strong><span>{status.active_incident_count}건</span><small>최고 등급 {highestSeverity} · 최초 시작 {oldestStartedAt ? freshness(oldestStartedAt) : '없음'}{incidentsStale ? ' · 목록 stale' : ''}</small></div>
        <dl className="telemetry compact operational-metrics">
          <div><dt>Cesium 선택 시나리오</dt><dd>{SCENARIO_LABELS[scenario]}</dd></div>
          <div><dt>Grafana 메트릭 시나리오</dt><dd>{status.scenario_label}</dd></div>
          <div><dt>전체 작업 수</dt><dd>{status.jobs_total}</dd></div>
          <div><dt>배치 성공 작업</dt><dd>{status.jobs_placed}</dd></div>
          <div className={status.jobs_unplaced ? 'metric-alert' : ''}><dt>미배치 작업</dt><dd className={status.jobs_unplaced ? 'danger' : ''}>{status.jobs_unplaced}</dd></div>
          <div><dt>배치 성공률</dt><dd>{ratio(status.placement_success_ratio)}</dd></div>
          <div><dt>마감 준수율</dt><dd>{ratio(status.deadline_met_ratio)}</dd></div>
          <div><dt>평균 큐 대기시간</dt><dd>{seconds(status.average_queue_wait_seconds)}</dd></div>
          <div><dt>최대 큐 대기시간</dt><dd>{seconds(status.maximum_queue_wait_seconds)}</dd></div>
          <div><dt>평균 전체 처리시간</dt><dd>{seconds(status.average_total_time_seconds)}</dd></div>
          <div><dt>장애 링크 수</dt><dd>{status.failed_links}</dd></div>
          <div><dt>사용 불가 연산 노드</dt><dd className={unavailableNodes.length ? 'danger' : ''}>{unavailableNodes.length ? unavailableNodes.map((node) => `SAT-${node.node}`).join(', ') : '없음'}</dd></div>
          <div><dt>최근 갱신</dt><dd>{freshness(status.updated_at)}</dd></div>
        </dl>
        <div className="operational-nodes">{status.nodes.map((node) => <div key={node.node} className={node.available ? '' : 'unavailable'}><strong>SAT-{node.node}</strong><span>{node.available ? '사용 가능' : '사용 불가'}</span><span>작업 {node.jobs}</span><span>평균 대기 {seconds(node.average_queue_wait_seconds)}</span></div>)}</div>
      </> : <p className="status-empty">표시할 운영 스냅샷이 없습니다.</p>}
      {syncWarning && <p className="sync-warning">{syncWarning}</p>}
    </section>
  );
}
