export type NodeType = 'SATELLITE' | 'GROUND_STATION';

export interface NodePosition {
  timeNs: number;
  nodeId: number;
  nodeType: NodeType;
  latitudeDeg: number;
  longitudeDeg: number;
  altitudeM: number;
}

export type SelectionSource = 'globe' | 'tree';

export interface EventEntry {
  id: number;
  time: string;
  message: string;
  level: 'info' | 'success';
}

export type Scenario = 'NORMAL' | 'FAILED_ISL_0_1' | 'MULTI_FAILED_ISL_0_1_10_11';
export type BackendScenario = 'NORMAL_BURST' | 'FAILED_ISL_0_1_BURST' | 'MULTI_FAILED_ISL_0_1_10_11_BURST';
export type ScenarioSyncState = 'syncing' | 'complete' | 'failed';
export type AlertSeverity = 'normal' | 'warning' | 'critical';
export type ScenarioDeadlineRatios = Partial<Record<Scenario, number>>;
export type Link = readonly [number, number];

export interface NetworkCost {
  timeNs: number;
  source: number;
  computeNode: number;
  route: number[];
  rttNs: number | null;
  hopCount: number;
  failedIsls: Link[];
  status: 'AVAILABLE' | 'UNREACHABLE';
}

export interface RoutingEvent {
  timeNs: number;
  source: number;
  destination: number;
  route: number[];
  rttNs: number | null;
  hopCount: number;
  failedIsls: Link[];
  status: 'NORMAL' | 'REROUTED' | 'DROPPED';
}

export interface PlacementResult {
  timeNs: number;
  scenario: Scenario;
  sourceNode: number;
  placementStatus: 'PLACED' | 'UNPLACED';
  selectedNode: number | null;
  route: number[];
  rttNs: number | null;
  hopCount: number;
  failedIsls: Link[];
}

export interface ScenarioComparisonResult {
  scenario: Scenario;
  placementStatus: 'PLACED' | 'UNPLACED';
  selectedNode: number | null;
  queueWaitMs: number | null;
  totalTimeMs: number | null;
  failedIsls: Link[];
}

export interface OperationalStatusNode {
  node: number;
  available: boolean;
  jobs: number;
  average_queue_wait_seconds: number | null;
}

export interface OperationalStatus {
  scenario: BackendScenario;
  scenario_label: string;
  jobs_total: number;
  jobs_placed: number;
  jobs_unplaced: number;
  placement_success_ratio: number;
  deadline_met_ratio: number;
  average_queue_wait_seconds: number;
  maximum_queue_wait_seconds: number;
  average_total_time_seconds: number;
  failed_links: number;
  severity: AlertSeverity;
  severity_label: string;
  alert_reasons: string[];
  active_incident_count: number;
  active_incident_ids: string[];
  nodes: OperationalStatusNode[];
  updated_at: string;
  simulation_time_seconds: number;
  operational_phase: 'healthy' | 'degraded' | 'rerouting' | 'recovering';
  active_failures: number;
  current_failure_ids: string[];
  last_failure: FailureRecord | null;
  last_recovery: string | null;
  recovery_metrics: RecoveryMetrics;
}

export interface RecoveryMetrics {
  failure_occurred_at_seconds?: number | null;
  failure_detected_at_seconds?: number | null;
  reroute_started_at_seconds?: number | null;
  reroute_completed_at_seconds?: number | null;
  service_recovered_at_seconds?: number | null;
  detection_time_seconds?: number | null;
  reroute_time_seconds?: number | null;
  service_recovery_time_seconds?: number | null;
  jobs_unplaced_during_failure?: number | null;
  jobs_arrived_during_failure?: number | null;
}

export interface FailureRecord {
  failure_id: string;
  type: 'link_failure' | 'node_failure';
  target: string;
  status: 'active' | 'recovering' | 'resolved';
  occurred_at_seconds: number;
  detected_at_seconds: number | null;
  recovered_at_seconds: number | null;
  affected_nodes: number[];
  affected_jobs: string[];
  related_event_ids: string[];
  recovery_metrics: RecoveryMetrics;
}

export interface ComputeNodeSummary {
  node: number;
  label: string;
  available: boolean;
  jobs: number;
  average_queue_wait_seconds: number | null;
  utilization_ratio: number | null;
  status_label: string;
}

export interface OperationalJob {
  job_id: string;
  status: 'PLACED' | 'UNPLACED';
  assigned_node: number | null;
  queue_wait_seconds: number | null;
  processing_seconds: number | null;
  total_time_seconds: number | null;
  deadline_seconds: number | null;
  deadline_met: boolean | null;
  failure_reason: string | null;
}

export type OperationalEventLevel = 'info' | 'warning' | 'critical';
export type OperationalEventCategory = 'network' | 'node' | 'job' | 'system';

export interface OperationalEvent {
  event_id: string;
  timestamp: string;
  level: OperationalEventLevel;
  category: OperationalEventCategory;
  type: string;
  target: string;
  message: string;
}

export interface ComputeNodeDetail {
  node: ComputeNodeSummary;
  jobs: OperationalJob[];
  events: OperationalEvent[];
  updated_at: string;
}

export type IncidentStatus = 'open' | 'acknowledged' | 'resolved';

export interface OperationalIncident {
  incident_id: string;
  title: string;
  status: IncidentStatus;
  severity: AlertSeverity;
  severity_label: string;
  scenario: BackendScenario;
  started_at: string;
  acknowledged_at: string | null;
  resolved_at: string | null;
  causes: string[];
  impacts: string[];
  actions: string[];
  related_event_ids: string[];
  affected_nodes: string[];
  affected_job_count: number;
}

export interface OperationalIncidentDetail extends OperationalIncident {
  events: OperationalEvent[];
}

export interface DisplayOptions {
  allLinks: boolean;
  selectedRoute: boolean;
  failedLinks: boolean;
  nodeLabels: boolean;
}

export interface FailedLinkSelection { from: number; to: number; }
