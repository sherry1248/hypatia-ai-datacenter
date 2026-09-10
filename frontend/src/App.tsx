import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { CesiumGlobe } from './components/CesiumGlobe';
import { EventLog } from './components/EventLog';
import { EventCenter } from './components/EventCenter';
import { JobExplorer } from './components/JobExplorer';
import { IncidentCenter } from './components/IncidentCenter';
import { LayerControls, SCENARIO_LABELS } from './components/LayerControls';
import { MonitoringStatus } from './components/MonitoringStatus';
import { NodeDetailPanel } from './components/NodeDetailPanel';
import { ObjectTree } from './components/ObjectTree';
import { OperationsHeader } from './components/OperationsHeader';
import { RouteInfoPanel } from './components/RouteInfoPanel';
import { RecoveryPanel } from './components/RecoveryPanel';
import { ScenarioComparisonPanel } from './components/ScenarioComparisonPanel';
import { loadNetworkCosts, loadNodePositions, loadPlacements, loadRoutingEvents, loadScenarioComparisonResults, loadScenarioDeadlineRatios } from './lib/csv';
import { FRONTEND_SCENARIO_BY_BACKEND, getBackendScenario, setBackendScenario } from './lib/scenarioApi';
import { getOperationalStatus } from './lib/statusApi';
import { getNodeDetail } from './lib/drilldownApi';
import type { AlertSeverity, ComputeNodeDetail, DisplayOptions, EventEntry, FailedLinkSelection, Link, NetworkCost, NodePosition, OperationalIncident, OperationalStatus, PlacementResult, RoutingEvent, Scenario, ScenarioComparisonResult, ScenarioDeadlineRatios, ScenarioSyncState, SelectionSource } from './types';

const timestampLabel = (timeNs: number) => `${(timeNs / 1e9).toFixed(1)}초`;
const nodeName = (node: NodePosition) => `${node.nodeType === 'SATELLITE' ? 'SAT' : 'GS'}-${node.nodeId}`;
const scenarioFailureKey: Record<Scenario, string> = { NORMAL: '', FAILED_ISL_0_1: '0-1', MULTI_FAILED_ISL_0_1_10_11: '0-1;10-11' };
const failureKey = (links: Link[]) => [...new Set(links.map(([a, b]) => `${Math.min(a, b)}-${Math.max(a, b)}`))].sort().join(';');
const edgesOf = (paths: number[][], failed: Link[]): Link[] => {
  const failedKeys = new Set(failed.map(([a, b]) => `${Math.min(a, b)}-${Math.max(a, b)}`)); const found = new Map<string, Link>();
  paths.forEach((path) => path.slice(0, -1).forEach((from, index) => { const to = path[index + 1]; const key = `${Math.min(from, to)}-${Math.max(from, to)}`; if (!failedKeys.has(key)) found.set(key, [from, to]); }));
  return [...found.values()];
};

export default function App() {
  const [allNodes, setAllNodes] = useState<NodePosition[]>([]); const [networkCosts, setNetworkCosts] = useState<NetworkCost[]>([]); const [routingEvents, setRoutingEvents] = useState<RoutingEvent[]>([]); const [placements, setPlacements] = useState<PlacementResult[]>([]);
  const [timeIndex, setTimeIndex] = useState(0); const [scenario, setScenario] = useState<Scenario>('NORMAL'); const [selectedKey, setSelectedKey] = useState<string | null>(null); const [failedSelection, setFailedSelection] = useState<FailedLinkSelection | null>(null);
  const [csvSelectorSlot, setCsvSelectorSlot] = useState<HTMLDivElement | null>(null);
  const [csvScenario, setCsvScenario] = useState<string | null>(null);
  const [csvSyncWarning, setCsvSyncWarning] = useState<string | null>(null);
  const [playing, setPlaying] = useState(false); const [error, setError] = useState<string | null>(null); const [options, setOptions] = useState<DisplayOptions>({ allLinks: true, selectedRoute: true, failedLinks: true, nodeLabels: false });
  const [syncState, setSyncState] = useState<ScenarioSyncState>('syncing'); const [syncWarning, setSyncWarning] = useState<string | null>(null); const [operationalStatus, setOperationalStatus] = useState<OperationalStatus | null>(null); const [statusDisconnected, setStatusDisconnected] = useState(false);
  const [comparisonResults, setComparisonResults] = useState<ScenarioComparisonResult[]>([]); const [comparisonLoading, setComparisonLoading] = useState(true); const [comparisonWarning, setComparisonWarning] = useState<string | null>(null);
  const [deadlineRatios, setDeadlineRatios] = useState<ScenarioDeadlineRatios>({});
  const [nodeDetail, setNodeDetail] = useState<ComputeNodeDetail | null>(null); const [nodeDetailStale, setNodeDetailStale] = useState(false);
  const [incidents, setIncidents] = useState<OperationalIncident[]>([]); const [incidentsStale, setIncidentsStale] = useState(false);
  const [events, setEvents] = useState<EventEntry[]>([{ id: 1, time: 'SYSTEM', message: '운영 콘솔 초기화 중', level: 'info' }]); const eventId = useRef(2);
  const addEvent = useCallback((message: string, level: EventEntry['level'] = 'info', time = 'SYSTEM') => setEvents((current) => [{ id: eventId.current++, time, message, level }, ...current].slice(0, 7)), []);
  const syncRequestId = useRef(0); const syncQueue = useRef<Promise<void>>(Promise.resolve()); const statusRequestId = useRef(0); const previousSeverity = useRef<AlertSeverity | null>(null); const nodeDetailRequestId = useRef(0);
  const refreshOperationalStatus = useCallback(() => { const requestId = ++statusRequestId.current; return getOperationalStatus().then((status) => { if (requestId !== statusRequestId.current) return; setOperationalStatus(status); setStatusDisconnected(false); }).catch(() => { if (requestId === statusRequestId.current) setStatusDisconnected(true); }); }, []);
  const refreshNodeDetail = useCallback((nodeId: number) => { const requestId = ++nodeDetailRequestId.current; return getNodeDetail(nodeId).then((detail) => { if (requestId !== nodeDetailRequestId.current) return; setNodeDetail(detail); setNodeDetailStale(false); }).catch(() => { if (requestId === nodeDetailRequestId.current) setNodeDetailStale(true); }); }, []);
  const handleIncidentData = useCallback((nextIncidents: OperationalIncident[], stale: boolean) => { setIncidents(nextIncidents); setIncidentsStale(stale); }, []);

  useEffect(() => { Promise.all([loadNodePositions(), loadNetworkCosts(), loadRoutingEvents(), loadPlacements()]).then(([nodeRows, costs, routing, placementRows]) => { setAllNodes(nodeRows); setNetworkCosts(costs); setRoutingEvents(routing); setPlacements(placementRows); setEvents([{ id: eventId.current++, time: 'DATA', message: '위치·네트워크·경로·배치 데이터 로드 완료', level: 'success' }]); }).catch((reason: unknown) => setError(reason instanceof Error ? reason.message : String(reason))); }, []);
  useEffect(() => { loadScenarioComparisonResults().then(setComparisonResults).catch((reason: unknown) => setComparisonWarning(`시나리오 비교 데이터를 표시할 수 없습니다: ${reason instanceof Error ? reason.message : String(reason)}`)).finally(() => setComparisonLoading(false)); }, []);
  useEffect(() => { loadScenarioDeadlineRatios().then(setDeadlineRatios).catch(() => setDeadlineRatios({})); }, []);
  useEffect(() => { void refreshOperationalStatus(); const timer = window.setInterval(() => { void refreshOperationalStatus(); }, 5000); return () => window.clearInterval(timer); }, [refreshOperationalStatus]);
  useEffect(() => { if (!operationalStatus) return; if (previousSeverity.current !== null && previousSeverity.current !== operationalStatus.severity) { const reason = operationalStatus.alert_reasons.length ? ` · ${operationalStatus.alert_reasons.join(' · ')}` : ''; addEvent(`운영 등급 변경 · ${operationalStatus.severity_label}${reason}`, operationalStatus.severity === 'normal' ? 'success' : 'info', 'ALERT'); } previousSeverity.current = operationalStatus.severity; }, [operationalStatus, addEvent]);
  useEffect(() => { if (selectedKey?.startsWith('SATELLITE-')) { const nodeId = Number(selectedKey.slice('SATELLITE-'.length)); if ([0, 3, 7].includes(nodeId)) { void refreshNodeDetail(nodeId); return; } } nodeDetailRequestId.current += 1; setNodeDetailStale(false); }, [operationalStatus?.updated_at, selectedKey, refreshNodeDetail]);
  useEffect(() => {
    let active = true; const requestId = ++syncRequestId.current;
    getBackendScenario().then((backendScenario) => {
      if (!active || requestId !== syncRequestId.current) return;
      const frontendScenario = FRONTEND_SCENARIO_BY_BACKEND[backendScenario];
      setScenario(frontendScenario); setSyncState('complete'); setSyncWarning(null); void refreshOperationalStatus();
      addEvent(`메트릭 시나리오 동기화 완료 · ${SCENARIO_LABELS[frontendScenario]}`, 'success', 'MONITOR');
    }).catch(() => {
      if (!active || requestId !== syncRequestId.current) return;
      setSyncState('failed'); setSyncWarning('메트릭 서버에 연결할 수 없습니다. CSV 화면은 계속 사용할 수 있습니다.');
      addEvent('메트릭 서버 연결 실패 · CSV 화면 유지', 'info', 'MONITOR');
    });
    return () => { active = false; };
  }, [addEvent, refreshOperationalStatus]);

  useEffect(() => {
    const scenarioLabel = document.querySelector('.globe-panel .layer-controls .scenario-select');
    if (!scenarioLabel) return;
    const slot = document.createElement('div');
    scenarioLabel.after(slot);
    setCsvSelectorSlot(slot);
    return () => slot.remove();
  }, []);

  const timestamps = useMemo(() => [...new Set(allNodes.map((node) => node.timeNs))].sort((a, b) => a - b), [allNodes]); const currentTime = timestamps[timeIndex] ?? 0;
  const nodes = useMemo(() => allNodes.filter((node) => node.timeNs === currentTime), [allNodes, currentTime]);
  const csvScenarios = useMemo(() => [...new Set(placements.map((row) => String(row.scenario)))].filter((name) => !(name in scenarioFailureKey)), [placements]);
  const eventScenario = csvScenario ?? scenario;
  const activePlacement = useMemo(() => placements.find((row) => row.scenario === eventScenario && row.timeNs === currentTime) ?? null, [placements, eventScenario, currentTime]);
  const failedLinks = activePlacement?.failedIsls ?? [];
  const eventFailureKey = failureKey(failedLinks);
  const currentCosts = useMemo(() => activePlacement ? networkCosts.filter((row) => row.timeNs === currentTime && row.source === activePlacement.sourceNode && failureKey(row.failedIsls) === eventFailureKey) : [], [networkCosts, currentTime, activePlacement, eventFailureKey]);
  const currentRouting = useMemo(() => activePlacement ? routingEvents.filter((row) => row.timeNs === currentTime && row.source === activePlacement.sourceNode && failureKey(row.failedIsls) === eventFailureKey) : [], [routingEvents, currentTime, activePlacement, eventFailureKey]);
  const visualFailedLinks = failedLinks;
  const recoveredLinks = useMemo<Link[]>(() => {
    const failure = operationalStatus?.last_failure;
    if (operationalStatus?.simulation_time_seconds !== currentTime / 1e9 || failure?.status !== 'resolved' || failure.type !== 'link_failure') return [];
    const parts = failure.target.split('-').map(Number);
    return parts.length === 2 && parts.every(Number.isFinite) ? [[parts[0], parts[1]]] : [];
  }, [operationalStatus, currentTime]);
  const normalLinks = useMemo(() => edgesOf([...currentCosts.map((row) => row.route), ...currentRouting.map((row) => row.route)], failedLinks), [currentCosts, currentRouting, eventFailureKey]);
  const unavailableNodeIds = useMemo(() => new Set(currentCosts.filter((row) => row.status !== 'AVAILABLE').map((row) => row.computeNode)), [currentCosts]);
  useEffect(() => {
    const controller = new AbortController();
    if (!activePlacement) { setCsvSyncWarning(null); return; }
    const query = new URLSearchParams({ time_ns: String(currentTime), scenario: eventScenario, source: String(activePlacement.sourceNode) });
    fetch(`/api/placement-event?${query}`, { signal: controller.signal }).then((response) => {
      if (!response.ok) throw new Error('CSV 이벤트 동기화 실패');
      return response.json();
    }).then((payload) => {
      if (controller.signal.aborted) return;
      const event = payload.events?.find((row: { algorithm: string }) => row.algorithm === 'completion_time');
      const expectedStatus = activePlacement.placementStatus === 'PLACED' ? 'PLACED' : 'FAILED';
      if (!event || event.time_ns !== currentTime || event.selected_node !== (activePlacement.selectedNode ?? -1) || event.placement_status !== expectedStatus || event.failed_isls.split(';').filter(Boolean).sort().join(';') !== eventFailureKey) throw new Error('CSV 사본 불일치');
      setCsvSyncWarning(null);
    }).catch(() => { if (!controller.signal.aborted) setCsvSyncWarning('현재 CSV 이벤트의 메트릭 동기화 실패'); });
    return () => controller.abort();
  }, [currentTime, eventScenario, activePlacement]);
  const selected = useMemo(() => selectedKey ? nodes.find((node) => `${node.nodeType}-${node.nodeId}` === selectedKey) ?? null : null, [nodes, selectedKey]);

  useEffect(() => { if (!playing || timestamps.length < 2) return; const timer = window.setInterval(() => setTimeIndex((index) => (index + 1) % timestamps.length), 500); return () => window.clearInterval(timer); }, [playing, timestamps.length]);
  const previousTime = useRef<number | null>(null); useEffect(() => { if (previousTime.current !== null && previousTime.current !== currentTime) addEvent(`시점 변경 · T + ${timestampLabel(currentTime)}`, 'info', 'TIME'); previousTime.current = currentTime; setFailedSelection(null); }, [currentTime, addEvent]);
  const previousRoute = useRef<string | null>(null); useEffect(() => { const key = activePlacement?.route.join('-') ?? ''; if (previousRoute.current !== null && key !== previousRoute.current) addEvent(key ? `활성 경로 변경 · ${key}` : '활성 경로 도달 불가', 'info', 'ROUTE'); previousRoute.current = key; }, [activePlacement, addEvent]);
  const previousUnreachable = useRef(false); useEffect(() => { const unreachable = activePlacement?.placementStatus === 'UNPLACED' || currentRouting.some((row) => row.status === 'DROPPED'); if (unreachable && !previousUnreachable.current) addEvent('경로 도달 불가 · 배치 또는 라우팅 실패', 'info', 'ALERT'); previousUnreachable.current = unreachable; }, [activePlacement, currentRouting, addEvent]);

  const changeScenario = (value: Scenario) => {
    setCsvScenario(null); setScenario(value); setFailedSelection(null); setSyncState('syncing'); setSyncWarning(null); addEvent(`시나리오 변경 · ${SCENARIO_LABELS[value]}`, 'info', 'SCENARIO');
    const failures = value === 'NORMAL' ? '' : value === 'FAILED_ISL_0_1' ? 'SAT-0 ↔ SAT-1' : 'SAT-0 ↔ SAT-1, SAT-10 ↔ SAT-11'; if (failures) addEvent(`장애 링크 감지 · ${failures}`, 'info', 'ALERT');
    const requestId = ++syncRequestId.current;
    const synchronization = syncQueue.current.catch(() => undefined).then(() => setBackendScenario(value)).then((backendScenario) => {
      if (requestId !== syncRequestId.current) return;
      const synchronizedScenario = FRONTEND_SCENARIO_BY_BACKEND[backendScenario]; setSyncState('complete'); setSyncWarning(null); void refreshOperationalStatus();
      addEvent(`메트릭 시나리오 동기화 완료 · ${SCENARIO_LABELS[synchronizedScenario]}`, 'success', 'MONITOR');
    }).catch(() => {
      if (requestId !== syncRequestId.current) return;
      setSyncState('failed'); setSyncWarning('메트릭 시나리오 동기화에 실패했습니다. CSV 화면은 계속 사용할 수 있습니다.');
      addEvent('메트릭 시나리오 동기화 실패 · CSV 화면 유지', 'info', 'MONITOR');
    });
    syncQueue.current = synchronization;
  };
  const selectNode = useCallback((node: NodePosition, source: SelectionSource) => { setSelectedKey(`${node.nodeType}-${node.nodeId}`); setFailedSelection(null); addEvent(`${nodeName(node)} 선택 · ${source === 'globe' ? '글로브' : '객체 탐색기'}`, 'info', timestampLabel(node.timeNs)); }, [addEvent]);

  if (error) return <main className="fatal"><h1>데이터를 표시할 수 없습니다</h1><p>{error}</p><code>npm run copy:data</code>를 먼저 실행해 주세요.</main>;
  return <main className="app-shell">
    <OperationsHeader timeNs={currentTime} playing={playing} onTogglePlayback={() => setPlaying((value) => !value)} />
    <div className="workspace"><ObjectTree nodes={nodes} selected={selected} onSelect={(node) => selectNode(node, 'tree')} />
      <section className="globe-panel">{csvSelectorSlot && createPortal(<label className="scenario-select csv-scenario-select">CSV 장애 시나리오 <select value={csvScenario ?? ''} onChange={(event) => setCsvScenario(event.target.value || null)}><option value="">기존 시나리오 선택 사용</option>{csvScenarios.map((name) => <option key={name} value={name}>{name}</option>)}</select></label>, csvSelectorSlot)}<output aria-live="polite">T + {timestampLabel(currentTime)} · {currentRouting.map((row) => row.status).join(', ') || '라우팅 데이터 없음'} · {activePlacement ? (activePlacement.placementStatus === 'PLACED' && activePlacement.selectedNode !== null ? `PLACED · SAT-${activePlacement.selectedNode}` : 'FAILED · selected_node=-1') : '배치 데이터 없음'}{csvSyncWarning ? ` · ${csvSyncWarning}` : ''}</output><LayerControls scenario={scenario} options={options} onScenarioChange={changeScenario} onOptionsChange={setOptions} /><ScenarioComparisonPanel results={comparisonResults} networkCosts={networkCosts} loading={comparisonLoading} warning={comparisonWarning} currentScenario={scenario} onViewScenario={changeScenario} deadlineRatios={deadlineRatios} /><CesiumGlobe computeNodeId={activePlacement?.selectedNode ?? null} nodes={nodes} selected={selected} normalLinks={normalLinks} route={activePlacement?.route ?? []} failedLinks={visualFailedLinks} recoveredLinks={recoveredLinks} unavailableNodeIds={unavailableNodeIds} options={options} onSelect={(node) => selectNode(node, 'globe')} onFailedLinkSelect={(link) => { setFailedSelection(link); addEvent(`장애 링크 선택 · SAT-${link.from} ↔ SAT-${link.to}`, 'info', 'ALERT'); }} />
        <div className="timeline-control"><div><strong>시뮬레이션 타임라인</strong><span>{timestamps.length ? `${timeIndex + 1} / ${timestamps.length}` : '데이터 로드 중'} · {operationalStatus ? ({ healthy: '정상', degraded: '성능 저하', rerouting: '우회 중', recovering: '복구 중' } as const)[operationalStatus.operational_phase] : '상태 대기'}</span></div><input aria-label="시뮬레이션 시점" type="range" min="0" max={Math.max(timestamps.length - 1, 0)} value={timeIndex} disabled={!timestamps.length} onChange={(event) => { setPlaying(false); setTimeIndex(Number(event.target.value)); }} /><output>T + {timestampLabel(currentTime)}</output><div className="timeline-events">{operationalStatus && operationalStatus.simulation_time_seconds > 0 && ([['failure', operationalStatus.recovery_metrics.failure_occurred_at_seconds, '장애 발생'], ['detection', operationalStatus.recovery_metrics.failure_detected_at_seconds, '감지'], ['reroute', operationalStatus.recovery_metrics.reroute_completed_at_seconds, '우회 완료'], ['recovery', operationalStatus.last_failure?.recovered_at_seconds, '복구'], ['healthy', operationalStatus.recovery_metrics.service_recovered_at_seconds, '정상 복원']] as const).map(([kind, value, label]) => value == null ? null : <i key={kind} className={kind} title={`${label} · ${value}초`} style={{ left: `${Math.min(100, Math.max(0, value / operationalStatus.simulation_time_seconds * 100))}%` }} />)}</div></div>
      </section><div className="right-rail"><NodeDetailPanel node={selected} unavailable={selected ? unavailableNodeIds.has(selected.nodeId) : false} detail={nodeDetail} detailStale={nodeDetailStale} /><RecoveryPanel status={operationalStatus} stale={statusDisconnected} /><MonitoringStatus scenario={scenario} status={operationalStatus} disconnected={statusDisconnected} syncState={syncState} syncWarning={syncWarning} incidents={incidents} incidentsStale={incidentsStale} /><IncidentCenter onData={handleIncidentData} /><JobExplorer nodes={operationalStatus?.nodes.map((node) => node.node) ?? [0, 3, 7]} refreshKey={operationalStatus?.updated_at} /><EventCenter /><RouteInfoPanel route={activePlacement} failedLink={failedSelection} scenario={scenario} timeNs={currentTime} /></div>
    </div><EventLog events={events} />
  </main>;
}
