import type { DisplayOptions, Scenario } from '../types';

export const SCENARIO_LABELS: Record<Scenario, string> = { NORMAL: '정상', FAILED_ISL_0_1: '단일 링크 장애', MULTI_FAILED_ISL_0_1_10_11: '다중 링크 장애' };

interface Props { scenario: Scenario; options: DisplayOptions; onScenarioChange: (scenario: Scenario) => void; onOptionsChange: (options: DisplayOptions) => void; }

export function LayerControls({ scenario, options, onScenarioChange, onOptionsChange }: Props) {
  const toggles: [keyof DisplayOptions, string][] = [['allLinks', '전체 링크'], ['selectedRoute', '선택 경로'], ['failedLinks', '장애 링크'], ['nodeLabels', '노드 라벨']];
  return <div className="layer-controls">
    <label className="scenario-select">시나리오<select value={scenario} onChange={(event) => onScenarioChange(event.target.value as Scenario)}>{Object.entries(SCENARIO_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
    <div className="toggle-row">{toggles.map(([key, label]) => <label key={key}><input type="checkbox" checked={options[key]} onChange={(event) => onOptionsChange({ ...options, [key]: event.target.checked })} /><span />{label}</label>)}</div>
  </div>;
}
