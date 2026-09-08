import { useEffect, useState } from 'react';
import { getFailureDetail, getFailures } from '../lib/drilldownApi';
import type { FailureRecord, OperationalStatus } from '../types';

const PHASE_LABELS = { healthy: '정상', degraded: '성능 저하', rerouting: '우회 중', recovering: '복구 중' } as const;
const seconds = (value: number | null | undefined) => value == null ? '계산 불가' : `${value.toFixed(2)}초`;

export function RecoveryPanel({ status, stale }: { status: OperationalStatus | null; stale: boolean }) {
  const [failures, setFailures] = useState<FailureRecord[]>([]);
  const [selected, setSelected] = useState<FailureRecord | null>(null);
  const [historyStale, setHistoryStale] = useState(false);
  useEffect(() => {
    let active = true;
    getFailures().then((payload) => { if (active) { setFailures(payload.failures); setHistoryStale(false); } }).catch(() => { if (active) setHistoryStale(true); });
    return () => { active = false; };
  }, [status?.updated_at]);
  const choose = (failure: FailureRecord) => getFailureDetail(failure.failure_id).then(setSelected).catch(() => { setSelected(failure); setHistoryStale(true); });
  const metrics = status?.recovery_metrics ?? {};
  return <section className={`recovery-panel panel ${stale || historyStale ? 'stale' : ''}`}>
    <div className="panel-title"><strong>복구 상태</strong><small>{status ? PHASE_LABELS[status.operational_phase] : '대기'}</small></div>
    {(stale || historyStale) && <p className="status-disconnected">연결 끊김 · 마지막 복구 데이터를 유지합니다.</p>}
    <dl className="telemetry compact">
      <div><dt>장애 시작</dt><dd>{seconds(metrics.failure_occurred_at_seconds)}</dd></div>
      <div><dt>감지 시간</dt><dd>{seconds(metrics.detection_time_seconds)}</dd></div>
      <div><dt>우회 시간</dt><dd>{seconds(metrics.reroute_time_seconds)}</dd></div>
      <div><dt>서비스 복구</dt><dd>{seconds(metrics.service_recovery_time_seconds)}</dd></div>
      <div><dt>영향 작업</dt><dd>{status?.last_failure?.affected_jobs.length ?? 0}</dd></div>
      <div><dt>장애 중 미배치</dt><dd>{metrics.jobs_unplaced_during_failure ?? '계산 불가'}</dd></div>
    </dl>
    <details className="failure-history"><summary>장애 이력 <span>{failures.length}</span></summary>
      <div className="failure-list">{failures.map((failure) => <button type="button" key={failure.failure_id} onClick={() => void choose(failure)}><strong>{failure.failure_id}</strong><span>{failure.target} · {failure.status}</span></button>)}</div>
      {selected && <article className="failure-detail"><strong>{selected.failure_id}</strong><p>관련 이벤트: {selected.related_event_ids.join(', ') || '없음'}</p><p>영향 노드: {selected.affected_nodes.join(', ') || '없음'}</p><p>영향 작업: {selected.affected_jobs.join(', ') || '없음'}</p></article>}
    </details>
  </section>;
}
