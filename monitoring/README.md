# 우주 AI 데이터센터 모니터링

Prometheus와 Grafana가 호스트의 `8000` 포트에서 실행 중인 Python 메트릭 서버를 수집하는 로컬 모니터링 구성입니다.

## 실행

먼저 저장소 루트에서 Python 메트릭 서버를 계속 실행해 둡니다.

```bash
python -m satgenpy.ai_datacenter.metrics_server
```

다른 터미널에서 모니터링 스택을 시작합니다.

```bash
cd monitoring
docker compose up -d
```

- Prometheus: http://localhost:9090
- Grafana: http://localhost:3000
- Grafana 로그인: `admin` / `admin`

기본 Grafana 계정은 로컬 개발 전용입니다. 공유 또는 운영 환경에서는 반드시 비밀번호와 보안 설정을 변경하세요.

Prometheus의 **Status → Targets**에서 `space-ai-datacenter` 대상이 `UP`인지 확인합니다. Grafana에는 기본 Prometheus 데이터소스와 **우주 AI 데이터센터 운영 현황** 대시보드가 자동으로 프로비저닝됩니다.

대시보드는 기존 작업·노드·운영 등급 패널을 유지하면서 활성 장애 수, 운영 단계, 장애 감지 시간, 우회 시간, 서비스 복구 시간과 장애 중 미배치 작업 패널을 추가로 제공합니다. 운영 단계의 `phase` 라벨은 `healthy`, `degraded`, `rerouting`, `recovering` 네 고정값만 사용하여 라벨 카디널리티를 제한합니다.

## 종료

```bash
docker compose down
```

명명된 볼륨의 모니터링 데이터는 종료 후에도 유지됩니다.
