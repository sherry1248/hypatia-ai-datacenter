import type { BackendScenario, Scenario } from '../types';

const SCENARIO_API_URL = '/api/scenario';

export const BACKEND_SCENARIO_BY_FRONTEND: Record<Scenario, BackendScenario> = {
  NORMAL: 'NORMAL_BURST',
  FAILED_ISL_0_1: 'FAILED_ISL_0_1_BURST',
  MULTI_FAILED_ISL_0_1_10_11: 'MULTI_FAILED_ISL_0_1_10_11_BURST',
};

export const FRONTEND_SCENARIO_BY_BACKEND: Record<BackendScenario, Scenario> = {
  NORMAL_BURST: 'NORMAL',
  FAILED_ISL_0_1_BURST: 'FAILED_ISL_0_1',
  MULTI_FAILED_ISL_0_1_10_11_BURST: 'MULTI_FAILED_ISL_0_1_10_11',
};

interface ScenarioResponse {
  scenario: BackendScenario;
  updated_at: string;
}

const isBackendScenario = (value: unknown): value is BackendScenario =>
  typeof value === 'string' && value in FRONTEND_SCENARIO_BY_BACKEND;

async function parseResponse(response: Response): Promise<ScenarioResponse> {
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const message = payload && typeof payload === 'object' && 'error' in payload && typeof payload.error === 'string' ? payload.error : `HTTP ${response.status}`;
    throw new Error(message);
  }
  if (!payload || typeof payload !== 'object' || !('scenario' in payload) || !isBackendScenario(payload.scenario) || !('updated_at' in payload) || typeof payload.updated_at !== 'string') {
    throw new Error('메트릭 서버 응답이 올바르지 않습니다.');
  }
  return { scenario: payload.scenario, updated_at: payload.updated_at };
}

export async function getBackendScenario(): Promise<BackendScenario> {
  return (await parseResponse(await fetch(SCENARIO_API_URL))).scenario;
}

export async function setBackendScenario(scenario: Scenario): Promise<BackendScenario> {
  const response = await fetch(SCENARIO_API_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ scenario: BACKEND_SCENARIO_BY_FRONTEND[scenario] }),
  });
  return (await parseResponse(response)).scenario;
}
