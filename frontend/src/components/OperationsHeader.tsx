interface OperationsHeaderProps {
  timeNs: number;
  playing: boolean;
  onTogglePlayback: () => void;
}

export function OperationsHeader({ timeNs, playing, onTogglePlayback }: OperationsHeaderProps) {
  return (
    <header className="operations-header">
      <div className="brand">
        <span className="brand-mark">H</span>
        <div><h1>HYPATIA LEO 운영 콘솔</h1><p>SPACE AI DATA CENTER</p></div>
      </div>
      <div className="header-status"><span className="status-dot" /> 시뮬레이션 정상</div>
      <nav className="monitoring-links" aria-label="모니터링 도구">
        <a href="http://localhost:3000" target="_blank" rel="noreferrer">Grafana 관제</a>
        <a href="http://localhost:9090/targets" target="_blank" rel="noreferrer">Prometheus 상태</a>
      </nav>
      <div className="header-clock"><span>현재 시점</span><strong>T + {(timeNs / 1e9).toFixed(1)}초</strong></div>
      <button className="playback-button" type="button" onClick={onTogglePlayback} aria-label={playing ? '일시정지' : '재생'}>
        {playing ? 'Ⅱ' : '▶'} <span>{playing ? '일시정지' : '재생'}</span>
      </button>
    </header>
  );
}
