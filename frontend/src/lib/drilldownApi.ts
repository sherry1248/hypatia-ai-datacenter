import type { ComputeNodeDetail, FailureRecord, IncidentStatus, OperationalEvent, OperationalEventCategory, OperationalEventLevel, OperationalIncident, OperationalIncidentDetail, OperationalJob } from '../types';

const API_ROOT = '/api';

async function request<T>(path: string): Promise<T> {
  const response = await fetch(`${API_ROOT}${path}`);
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const message = payload && typeof payload === 'object' && 'error' in payload && typeof payload.error === 'string' ? payload.error : `HTTP ${response.status}`;
    throw new Error(message);
  }
  return payload as T;
}

export async function getNodeDetail(node: number): Promise<ComputeNodeDetail> {
  const payload = await request<ComputeNodeDetail>(`/nodes/${node}`);
  if (!payload?.node || payload.node.node !== node || !Array.isArray(payload.jobs) || !Array.isArray(payload.events)) throw new Error('노드 상세 응답이 올바르지 않습니다.');
  return payload;
}

export interface JobFilters { status?: 'placed' | 'unplaced' | 'deadline_missed'; node?: number; limit?: number; }
export async function getJobs(filters: JobFilters): Promise<{ jobs: OperationalJob[]; total: number }> {
  const query = new URLSearchParams(); if (filters.status) query.set('status', filters.status); if (filters.node !== undefined) query.set('node', String(filters.node)); query.set('limit', String(filters.limit ?? 50));
  const payload = await request<{ jobs: OperationalJob[]; total: number }>(`/jobs?${query}`);
  if (!Array.isArray(payload?.jobs) || typeof payload.total !== 'number') throw new Error('작업 목록 응답이 올바르지 않습니다.');
  return payload;
}

export interface EventFilters { level?: OperationalEventLevel; category?: OperationalEventCategory; limit?: number; }
export async function getOperationalEvents(filters: EventFilters): Promise<{ events: OperationalEvent[]; total: number }> {
  const query = new URLSearchParams(); if (filters.level) query.set('level', filters.level); if (filters.category) query.set('category', filters.category); query.set('limit', String(filters.limit ?? 100));
  const payload = await request<{ events: OperationalEvent[]; total: number }>(`/events?${query}`);
  if (!Array.isArray(payload?.events) || typeof payload.total !== 'number') throw new Error('이벤트 목록 응답이 올바르지 않습니다.');
  return payload;
}

export async function getIncidents(status?: IncidentStatus): Promise<{ incidents: OperationalIncident[]; total: number }> {
  const query = new URLSearchParams({ limit: '100' }); if (status) query.set('status', status);
  const payload = await request<{ incidents: OperationalIncident[]; total: number }>(`/incidents?${query}`);
  if (!Array.isArray(payload?.incidents) || typeof payload.total !== 'number') throw new Error('인시던트 목록 응답이 올바르지 않습니다.');
  return payload;
}

export async function getIncidentDetail(incidentId: string): Promise<OperationalIncidentDetail> {
  const payload = await request<OperationalIncidentDetail>(`/incidents/${encodeURIComponent(incidentId)}`);
  if (payload?.incident_id !== incidentId || !Array.isArray(payload.events)) throw new Error('인시던트 상세 응답이 올바르지 않습니다.');
  return payload;
}

export async function acknowledgeIncident(incidentId: string): Promise<OperationalIncident> {
  const response = await fetch(`${API_ROOT}/incidents/${encodeURIComponent(incidentId)}/acknowledge`, { method: 'POST' });
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) throw new Error(payload && typeof payload === 'object' && 'error' in payload && typeof payload.error === 'string' ? payload.error : `HTTP ${response.status}`);
  if (!payload || typeof payload !== 'object' || !('incident_id' in payload) || payload.incident_id !== incidentId) throw new Error('인시던트 확인 응답이 올바르지 않습니다.');
  return payload as OperationalIncident;
}

export async function getFailures(): Promise<{ failures: FailureRecord[]; total: number }> {
  const payload = await request<{ failures: FailureRecord[]; total: number }>('/failures');
  if (!Array.isArray(payload?.failures) || typeof payload.total !== 'number') throw new Error('장애 기록 응답이 올바르지 않습니다.');
  return payload;
}

export async function getFailureDetail(failureId: string): Promise<FailureRecord> {
  const payload = await request<FailureRecord>(`/failures/${encodeURIComponent(failureId)}`);
  if (payload?.failure_id !== failureId) throw new Error('장애 상세 응답이 올바르지 않습니다.');
  return payload;
}
