import { useCallback, useEffect, useRef, useState } from 'react';
import { acknowledgeIncident, getIncidentDetail, getIncidents } from '../lib/drilldownApi';
import type { IncidentStatus, OperationalIncident, OperationalIncidentDetail } from '../types';

const STATUS_LABELS: Record<IncidentStatus, string> = { open: '진행 중', acknowledged: '확인됨', resolved: '종료' };
const dateTime = (value: string | null) => value ? new Date(value).toLocaleString('ko-KR', { hour12: false }) : '없음';

interface Props { onData: (incidents: OperationalIncident[], stale: boolean) => void; }

export function IncidentCenter({ onData }: Props) {
  const [filter, setFilter] = useState<'all' | IncidentStatus>('all');
  const [incidents, setIncidents] = useState<OperationalIncident[]>([]);
  const [total, setTotal] = useState(0);
  const [selected, setSelected] = useState<OperationalIncidentDetail | null>(null);
  const [stale, setStale] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const lastIncidents = useRef<OperationalIncident[]>([]);

  const refresh = useCallback(async () => {
    try {
      const payload = await getIncidents();
      lastIncidents.current = payload.incidents; setIncidents(payload.incidents); setTotal(payload.total); setStale(false); onData(payload.incidents, false);
      if (selected) setSelected(await getIncidentDetail(selected.incident_id));
    } catch { setStale(true); onData(lastIncidents.current, true); }
  }, [onData, selected]);

  useEffect(() => {
    let active = true;
    const poll = async () => {
      try {
        const payload = await getIncidents();
        if (!active) return;
        lastIncidents.current = payload.incidents; setIncidents(payload.incidents); setTotal(payload.total); setStale(false); onData(payload.incidents, false);
      } catch { if (active) { setStale(true); onData(lastIncidents.current, true); } }
    };
    void poll(); const timer = window.setInterval(() => { void poll(); }, 5000);
    return () => { active = false; window.clearInterval(timer); };
  }, [onData]);

  const visibleIncidents = filter === 'all' ? incidents : incidents.filter((incident) => incident.status === filter);

  const selectIncident = async (incidentId: string) => {
    setActionError(null);
    try { setSelected(await getIncidentDetail(incidentId)); } catch { setActionError('인시던트 상세 연결 끊김'); }
  };
  const acknowledge = async () => {
    if (!selected) return;
    setActionError(null);
    try { await acknowledgeIncident(selected.incident_id); await refresh(); } catch { setActionError('확인 처리에 실패했습니다.'); }
  };

  return <details className={`rail-drilldown incident-center ${stale ? 'stale' : ''}`}>
    <summary>인시던트 센터 <span>{total}건</span></summary>
    <div className="drilldown-body">
      <p className="incident-guide"><strong>경보</strong>는 현재 조건, <strong>이벤트</strong>는 개별 기록, <strong>인시던트</strong>는 관련 이벤트를 묶은 운영 문제입니다.</p>
      {stale && <p className="drilldown-warning">인시던트 API 연결 끊김 · 마지막 목록 표시 중</p>}
      <div className="incident-filters">{(['all', 'open', 'acknowledged', 'resolved'] as const).map((value) => <button key={value} className={filter === value ? 'selected' : ''} onClick={() => setFilter(value)}>{value === 'all' ? '전체' : STATUS_LABELS[value]}</button>)}</div>
      <div className="incident-list">{visibleIncidents.map((incident) => <button key={incident.incident_id} className={`${incident.severity} ${selected?.incident_id === incident.incident_id ? 'selected' : ''}`} onClick={() => void selectIncident(incident.incident_id)}><span><strong>{incident.incident_id}</strong><em>{incident.severity_label} · {STATUS_LABELS[incident.status]}</em></span><b>{incident.title}</b><small>{dateTime(incident.started_at)} · 노드 {incident.affected_nodes.length} · 작업 {incident.affected_job_count}</small></button>)}</div>
      {!visibleIncidents.length && <p className="drilldown-empty">표시할 인시던트가 없습니다.</p>}
      {actionError && <p className="drilldown-warning">{actionError}</p>}
      {selected && <section className="incident-detail">
        <header><strong>{selected.incident_id} 상세</strong>{selected.status === 'open' && <button onClick={() => void acknowledge()}>확인 처리</button>}</header>
        <dl><div><dt>확인 시각</dt><dd>{dateTime(selected.acknowledged_at)}</dd></div><div><dt>종료 시각</dt><dd>{dateTime(selected.resolved_at)}</dd></div><div><dt>영향 노드</dt><dd>{selected.affected_nodes.join(', ') || '없음'}</dd></div></dl>
        {([['원인', selected.causes], ['영향', selected.impacts], ['조치', selected.actions]] as const).map(([label, values]) => <div className="incident-section" key={label}><strong>{label}</strong>{values.length ? <ul>{values.map((value) => <li key={value}>{value}</li>)}</ul> : <p>기록 없음</p>}</div>)}
        <div className="incident-section"><strong>관련 이벤트 타임라인</strong>{selected.events.length ? selected.events.map((event) => <p key={event.event_id}><time>{dateTime(event.timestamp)}</time> {event.message}</p>) : <p>관련 이벤트 없음</p>}</div>
      </section>}
    </div>
  </details>;
}
