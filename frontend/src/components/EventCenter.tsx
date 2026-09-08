import { useEffect, useState } from 'react';
import { getOperationalEvents } from '../lib/drilldownApi';
import type { OperationalEvent, OperationalEventCategory, OperationalEventLevel } from '../types';

const CATEGORY_LABELS: Record<OperationalEventCategory, string> = { network: '네트워크', node: '노드', job: '작업', system: '시스템' };
const LEVEL_LABELS: Record<OperationalEventLevel, string> = { info: '정보', warning: '주의', critical: '심각' };

export function EventCenter() {
  const [level, setLevel] = useState<'all' | OperationalEventLevel>('all'); const [category, setCategory] = useState<'all' | OperationalEventCategory>('all'); const [events, setEvents] = useState<OperationalEvent[]>([]); const [total, setTotal] = useState(0); const [stale, setStale] = useState(false);
  useEffect(() => {
    let active = true;
    const refresh = () => getOperationalEvents({ level: level === 'all' ? undefined : level, category: category === 'all' ? undefined : category, limit: 100 }).then((payload) => { if (!active) return; setEvents([...new Map(payload.events.map((event) => [event.event_id, event])).values()]); setTotal(payload.total); setStale(false); }).catch(() => { if (active) setStale(true); });
    void refresh(); const timer = window.setInterval(() => { void refresh(); }, 5000); return () => { active = false; window.clearInterval(timer); };
  }, [level, category]);
  return <details className={`rail-drilldown event-center ${stale ? 'stale' : ''}`}>
    <summary>이벤트 센터 <span>{total}건</span></summary>
    <div className="drilldown-body">
      {stale && <p className="drilldown-warning">이벤트 API 연결 끊김 · 마지막 기록 표시 중</p>}
      <div className="drilldown-filters"><select aria-label="이벤트 등급" value={level} onChange={(event) => setLevel(event.target.value as 'all' | OperationalEventLevel)}><option value="all">전체 등급</option><option value="info">정보</option><option value="warning">주의</option><option value="critical">심각</option></select><select aria-label="이벤트 분류" value={category} onChange={(event) => setCategory(event.target.value as 'all' | OperationalEventCategory)}><option value="all">전체 분류</option><option value="network">네트워크</option><option value="node">노드</option><option value="job">작업</option><option value="system">시스템</option></select></div>
      <div className="center-events">{events.map((event) => <article key={event.event_id} className={event.level}><div><time>{new Date(event.timestamp).toLocaleTimeString('ko-KR', { hour12: false })}</time><strong>{LEVEL_LABELS[event.level]}</strong><span>{CATEGORY_LABELS[event.category]}</span></div><p>{event.message}</p><small>{event.target}</small></article>)}</div>
      {!events.length && <p className="drilldown-empty">표시할 이벤트가 없습니다.</p>}
    </div>
  </details>;
}
