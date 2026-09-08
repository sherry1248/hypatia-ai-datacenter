import { useEffect, useState } from 'react';
import { getJobs } from '../lib/drilldownApi';
import type { OperationalJob } from '../types';

interface Props { nodes: number[]; refreshKey: string | undefined; }
type JobView = 'all' | 'placed' | 'unplaced' | 'deadline_missed';
const seconds = (value: number | null) => value === null ? '—' : `${value.toFixed(2)}초`;

export function JobExplorer({ nodes, refreshKey }: Props) {
  const [view, setView] = useState<JobView>('all'); const [node, setNode] = useState('all'); const [jobs, setJobs] = useState<OperationalJob[]>([]); const [total, setTotal] = useState(0); const [stale, setStale] = useState(false);
  useEffect(() => {
    let active = true;
    getJobs({ status: view === 'all' ? undefined : view, node: node === 'all' ? undefined : Number(node), limit: 50 }).then((payload) => { if (!active) return; setJobs(payload.jobs); setTotal(payload.total); setStale(false); }).catch(() => { if (active) setStale(true); });
    return () => { active = false; };
  }, [view, node, refreshKey]);
  return <details className={`rail-drilldown job-explorer ${stale ? 'stale' : ''}`}>
    <summary>작업 탐색기 <span>{total}개</span></summary>
    <div className="drilldown-body">
      {stale && <p className="drilldown-warning">작업 API 연결 끊김 · 마지막 목록 표시 중</p>}
      <div className="drilldown-filters"><select aria-label="작업 상태" value={view} onChange={(event) => setView(event.target.value as JobView)}><option value="all">전체 작업</option><option value="placed">배치 작업</option><option value="unplaced">미배치 작업</option><option value="deadline_missed">마감 실패 작업</option></select><select aria-label="연산 노드" value={node} onChange={(event) => setNode(event.target.value)}><option value="all">전체 노드</option>{nodes.map((id) => <option key={id} value={id}>SAT-{id}</option>)}</select></div>
      <div className="drilldown-table-wrap"><table><thead><tr><th>작업 ID</th><th>상태</th><th>배치 노드</th><th>큐 대기</th><th>전체 시간</th><th>마감 결과</th></tr></thead><tbody>{jobs.map((job) => <tr key={job.job_id} className={job.status === 'UNPLACED' ? 'unplaced' : job.deadline_met === false ? 'deadline-missed' : ''}><td>{job.job_id}</td><td>{job.status === 'PLACED' ? '배치' : '미배치'}</td><td>{job.assigned_node === null ? '—' : `SAT-${job.assigned_node}`}</td><td>{seconds(job.queue_wait_seconds)}</td><td>{seconds(job.total_time_seconds)}</td><td>{job.deadline_met === null ? '—' : job.deadline_met ? '준수' : '미준수'}</td></tr>)}</tbody></table></div>
      {!jobs.length && <p className="drilldown-empty">조건에 맞는 작업이 없습니다.</p>}<small className="drilldown-limit">최대 50행 표시</small>
    </div>
  </details>;
}
