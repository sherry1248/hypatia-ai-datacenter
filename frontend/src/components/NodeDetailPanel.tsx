import type { ComputeNodeDetail, NodePosition } from '../types';

export function NodeDetailPanel({ node, unavailable = false, detail, detailStale = false }: { node: NodePosition | null; unavailable?: boolean; detail: ComputeNodeDetail | null; detailStale?: boolean }) {
  const name = node ? `${node.nodeType === 'SATELLITE' ? 'SAT' : 'GS'}-${node.nodeId}` : '선택 없음';
  const compute = Boolean(node && node.nodeType === 'SATELLITE' && [0, 3, 7].includes(node.nodeId)); const activeDetail = compute && detail?.node.node === node?.nodeId ? detail : null;
  return (
    <aside className="panel detail-panel">
      <div className="panel-title"><span>노드 상세</span><small>실시간</small></div>
      {node ? <>
        <div className="node-identity"><span className={node.nodeType === 'SATELLITE' ? 'satellite-glyph' : 'station-glyph'}>◆</span><div><h2>{name}</h2><p>{compute ? 'AI 연산 위성' : node.nodeType === 'SATELLITE' ? '궤도 위성' : '지상국'}</p></div></div>
        <dl className="telemetry">
          <div><dt>노드 유형</dt><dd>{node.nodeType === 'SATELLITE' ? '위성' : '지상국'}</dd></div>
          <div><dt>위도</dt><dd>{node.latitudeDeg.toFixed(5)}°</dd></div>
          <div><dt>경도</dt><dd>{node.longitudeDeg.toFixed(5)}°</dd></div>
          <div><dt>고도</dt><dd>{node.altitudeM >= 1000 ? `${(node.altitudeM / 1000).toFixed(2)} km` : `${node.altitudeM.toFixed(1)} m`}</dd></div>
          <div><dt>운영 상태</dt><dd className={unavailable ? 'danger' : 'healthy'}><span /> {unavailable ? '사용 불가' : '정상'}</dd></div>
        </dl>
        {compute && <div className={`compute-drilldown ${detailStale ? 'stale' : ''}`}>{detailStale && <p className="drilldown-warning">노드 상세 API 연결 끊김{activeDetail ? ' · 마지막 값 표시 중' : ''}</p>}{activeDetail ? <><dl className="telemetry compact"><div><dt>API 가용 상태</dt><dd className={activeDetail.node.available ? 'healthy' : 'danger'}>{activeDetail.node.status_label}</dd></div><div><dt>배치 작업 수</dt><dd>{activeDetail.node.jobs}</dd></div><div><dt>평균 큐 대기</dt><dd>{activeDetail.node.average_queue_wait_seconds === null ? '—' : `${activeDetail.node.average_queue_wait_seconds.toFixed(2)}초`}</dd></div><div><dt>활용률</dt><dd>{activeDetail.node.utilization_ratio === null ? '데이터 없음' : `${(activeDetail.node.utilization_ratio * 100).toFixed(1)}%`}</dd></div></dl><div className="node-related-events"><strong>최근 관련 이벤트</strong>{activeDetail.events.length ? activeDetail.events.map((event) => <p key={event.event_id}>{event.message}</p>) : <p>관련 이벤트 없음</p>}</div></> : !detailStale && <p className="drilldown-empty">노드 상세를 불러오는 중입니다.</p>}</div>}
      </> : <div className="empty-state">글로브 또는 객체 탐색기에서<br />노드를 선택하세요.</div>}
    </aside>
  );
}
