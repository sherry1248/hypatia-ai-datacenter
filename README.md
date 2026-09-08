# LEO 위성 기반 우주 AI 데이터센터

## 연산 부하·네트워크 장애 인지형 작업 배치 및 적응형 라우팅 시스템

Hypatia의 LEO 위성 네트워크 시뮬레이션을 기반으로, 우주 환경에서 AI 작업을 안정적으로 배치하고 네트워크 장애에 적응하는 과정을 연구하는 졸업 프로젝트입니다. 위성 간 라우팅, 연산 위성 선택, 동적 작업 큐, 링크 장애 시나리오, 3D 시각화와 자동 보고서 생성을 하나의 재현 가능한 실험 파이프라인으로 통합합니다.

## 프로젝트 개요

LEO 위성망에서는 위성 이동에 따라 지상국 연결과 최적 경로가 계속 변하며, 위성 간 링크(ISL) 장애는 특정 연산 위성을 도달 불가능하게 만들 수 있습니다. 동시에 여러 AI 작업이 짧은 시간에 유입되면 연산 위성의 큐가 증가하여 네트워크 지연이 짧은 노드가 반드시 가장 빠른 선택은 아닙니다.

본 프로젝트는 다음 요소를 함께 고려합니다.

- Hypatia 기반 LEO 궤도·토폴로지·라우팅 시뮬레이션
- ISL 장애를 우회하는 적응형 라우팅
- 네트워크 RTT와 위성 연산 속도 및 동적 큐를 반영한 AI 작업 배치
- 정상, 링크 장애, 연산 고부하 및 버스트 워크로드 비교
- 3D 지구본과 실험 지표를 결합한 Streamlit 대시보드
- CSV 검증을 포함한 한국어 실험 보고서 자동 생성

## 핵심 기능

- LEO 위성 네트워크 상태와 시간별 경로 생성
- ISL 장애 발생 시 실패 링크를 제외한 적응형 우회 경로 계산
- 위성 `0`, `3`, `7`을 AI 연산 노드로 구성
- `compute_only`, `network_only`, `compute_aware`, `completion_time` 배치 알고리즘 비교
- 세 가지 AI 작업 유형을 포함하는 결정적 다중 작업 생성
- 300개 버스트 작업과 연산 위성별 독립 동적 큐 시뮬레이션
- 단일 링크 및 다중 링크 장애 실험
- 도달 가능한 연산 위성이 없는 작업의 `UNPLACED` 처리와 복구 지표
- 실제 위성 고도를 반영한 3D 지구·위성·경로 시각화
- 실험 비교 CSV 및 한국어 Markdown 보고서 자동 생성

## 시스템 구조

```text
Hypatia 위성 시뮬레이션
        │
        ├── network_costs.csv
        └── node_positions.csv
                 │
                 ▼
        AI 워크로드 생성
                 │
                 ▼
       작업 배치 및 동적 큐 시뮬레이션
                 │
                 ▼
          정상·장애 시나리오 실험
                 │
          ┌──────┴──────┐
          ▼             ▼
      3D 대시보드    CSV·Markdown 보고서
```

## 주요 모듈

| 모듈 | 역할 |
|---|---|
| `compute_model.py` | 연산 위성 0·3·7의 GPU 사용률, 정적 메타데이터 및 상대 연산 속도 정의 |
| `job_model.py` | AI 작업 타입과 단일 데모 작업 정의 |
| `workload.py` | 100개 기본 작업 및 300개 버스트 작업의 결정적 생성과 CSV 내보내기 |
| `placement.py` | 네트워크 전용, 연산 전용, 복합 및 완료시간 기반 배치 선택 |
| `cost_model.py` | 네트워크·큐·연산 시간을 결합한 완료시간 비용 계산 |
| `workload_simulator.py` | 도착 이벤트와 위성별 독립 단일 서버 큐를 이용한 다중 작업 시뮬레이션 |
| `workload_experiment.py` | 동일한 버스트 워크로드로 정상·단일 장애·다중 장애 실험 수행 및 요약 |
| `report_generator.py` | 실험 CSV 검증, 정상 대비 변화 계산, 한국어 보고서 생성 |
| `run_demo.py` | 기존 네 가지 배치 알고리즘과 정상·장애·고부하 시나리오 실행 |
| `run_all.py` | 네트워크 CSV 생성 이후의 전체 AI 데이터센터 파이프라인 실행 |
| `dashboard.py` | 3D 위성망, 배치 결과, 복구 지표 및 버스트 실험 비교 시각화 |

모듈 경로는 `satgenpy/ai_datacenter/`입니다.

## 설치

### 가상환경

```bash
python -m venv .venv
source .venv/bin/activate
```

### 저장소에 문서화된 의존성 설치

전체 Hypatia 환경은 저장소 루트에서 다음 스크립트로 설치할 수 있습니다.

```bash
bash hypatia_install_dependencies.sh
bash hypatia_build.sh
```

`satgenpy/README.md`에 문서화된 Python 및 시스템 의존성 설치 방식은 다음과 같습니다. 패키지 버전은 원 저장소 문서와 동일하게 고정하지 않습니다.

```bash
pip install numpy astropy ephem networkx sgp4 geopy matplotlib statsmodels
sudo apt-get install libproj-dev proj-data proj-bin libgeos-dev
pip install cartopy
pip install git+https://github.com/snkas/exputilpy.git@v1.6
```

AI 데이터센터 대시보드를 실행하려면 현재 환경에 프로젝트에서 사용하는 `pandas`, `plotly`, `streamlit`이 준비되어 있어야 합니다.

### AI 데이터센터 백엔드 테스트

저장소 루트에서 기존 가상환경 Python으로 실행합니다.

```bash
# AI 데이터센터 백엔드 테스트만 실행
.venv/bin/python -m unittest discover -s satgenpy/ai_datacenter/tests -p "test_*.py"

# 테스트 파일 하나 실행
.venv/bin/python -m unittest satgenpy.ai_datacenter.tests.test_api_endpoints

# 이름으로 테스트 하나 실행
.venv/bin/python -m unittest satgenpy.ai_datacenter.tests.test_api_endpoints.ApiEndpointTests.test_unknown_node_returns_korean_json_error

# 자세한 실패 출력
.venv/bin/python -m unittest discover -s satgenpy/ai_datacenter/tests -p "test_*.py" -v
```

## 네트워크 데이터 생성

전체 실험 전에 Hypatia 테스트를 통해 `network_costs.csv`와 `node_positions.csv`를 생성합니다.

```bash
cd satgenpy
python -m unittest discover -s tests -p "test_end_to_end_kuiper_duo.py" -v
cd ..
```

이 테스트는 정상 및 장애 경로를 생성하고 데모용 네트워크 비용과 노드 위치 데이터를 `satgenpy/demo_data/`에 내보냅니다.

## 전체 실험 실행

네트워크 데이터 생성이 끝난 뒤 저장소 루트에서 다음 명령을 실행합니다.

```bash
python -m satgenpy.ai_datacenter.run_all
```

이 명령은 100개 기본 작업 생성, 기존 배치 시나리오, 300개 버스트 실험, 결과 요약 및 보고서 생성을 순서대로 수행합니다. 동일한 입력에서는 동일한 결과를 생성합니다.

## 결정적 배치 실험과 통계 분석

지원 옵션은 저장소의 기존 시나리오, 정책, 워크로드에서 자동으로 제한됩니다. 각 `runs.csv` 행은 실제 배치 시뮬레이션에 전달된 작업 입력의 SHA-256 `workload_fingerprint`와 `workload_job_count`를 기록합니다. fingerprint에는 작업 ID, 도착 시각, 작업 종류, 연산 요구량, 입력 크기, 메모리, deadline과 source node가 포함됩니다.

```bash
.venv/bin/python -m satgenpy.ai_datacenter.experiment_runner --list-options

# 작은 개발 실행
.venv/bin/python -m satgenpy.ai_datacenter.experiment_runner \
  --scenarios normal --policies completion_time --workloads demo \
  --seeds 0 --output experiments/development

# 최종 20-seed 실행(0:19는 양 끝을 포함)
.venv/bin/python -m satgenpy.ai_datacenter.experiment_runner \
  --scenarios normal,single,multi \
  --policies compute_only,network_only,compute_aware,completion_time \
  --workloads burst --seeds 0:19 --output experiments/results

# 성공한 동일 조합을 건너뛰고 실패 조합만 다시 실행
.venv/bin/python -m satgenpy.ai_datacenter.experiment_runner \
  --scenarios normal,single,multi \
  --policies compute_only,network_only,compute_aware,completion_time \
  --workloads burst --seeds 0:19 --output experiments/results --resume
```

최종 실험은 시뮬레이터와 실행 환경에 따라 상당한 시간이 걸릴 수 있습니다.

출력 디렉터리에는 실행별 요청값·상태·작업/시간/노드 부하 지표를 담은 `runs.csv`, 시나리오·정책·워크로드별 통계를 담은 `summary.csv`, 평가 순위를 담은 `policy_ranking.csv`, 재현 정보를 담은 `metadata.json`이 생성됩니다. 빈 CSV 필드는 실제 데이터에서 계산할 수 없는 값입니다. 백분위수는 작업별 원시 값에 nearest-rank `ceil(p*n)` 방식을 적용합니다. 요약 표준편차는 표본 표준편차(`n-1`, 값이 하나면 빈 필드), 노드 부하 표준편차는 사용할 수 없어 부하가 0인 노드까지 포함한 전체 구성 노드의 모집단 표준편차입니다.

정책 순위는 각 시나리오와 워크로드 안에서 배치 성공률 내림차순, 마감 준수율 내림차순, 미배치 작업 수 오름차순, P95 총 시간 오름차순, 노드 부하 불균형 오름차순의 사전식 규칙을 사용합니다. 이는 실험 결과를 비교하는 평가 규칙이며 AI가 내리는 의사결정이 아닙니다.

### 시드 유효성

- `demo`는 의도적으로 고정된 워크로드이므로 서로 다른 시드에서도 fingerprint가 같을 수 있습니다. 여러 demo 시드를 반복해도 독립적인 확률 표본으로 해석하면 안 됩니다.
- `burst`는 실험 runner가 명시적 시드를 전달할 때 기존 burst 구간 안에서 도착 시각을 seed-dependent하게 생성합니다. 같은 시드는 같은 작업과 fingerprint를, 다른 시드는 다른 fingerprint를 만듭니다.
- 인자 없는 기존 `generate_burst_workload()` 호출은 저장된 정적 시나리오와 회귀 기대값을 보존하기 위해 기존 고정 워크로드를 그대로 생성합니다.
- `metadata.json`의 `distinct_workload_fingerprint_count`는 실제 고유 workload 수이고, `seed_effective`는 같은 scenario/policy/workload 조합에서 둘 이상의 요청 시드가 서로 다른 fingerprint를 만들었을 때만 `true`입니다. 여러 시드를 요청했는데 모든 fingerprint가 같으면 runner가 경고합니다.

```bash
# burst의 서로 다른 시드 fingerprint 확인
.venv/bin/python -m satgenpy.ai_datacenter.experiment_runner \
  --scenarios normal --policies completion_time --workloads burst \
  --seeds 0:1 --output /tmp/hypatia-seed-check
```

### 실험 분석 보고서

배치 실험이 끝나면 네 입력 파일 `runs.csv`, `summary.csv`, `policy_ranking.csv`, `metadata.json`을 분석해 Markdown·HTML 보고서와 SVG 그림을 생성할 수 있습니다.

```bash
.venv/bin/python -m satgenpy.ai_datacenter.experiment_report \
  --input experiments/results \
  --output experiments/results/report \
  --format markdown,html \
  --title "우주 AI 데이터센터 결정적 배치 실험 보고서"

# 동일한 기본 동작을 제공하는 도우미
./scripts/generate_experiment_report.sh experiments/results
```

생성물은 `experiment_report.md`, `experiment_report.html`, `key_findings.csv`, `report_metadata.json`과 `figures/` 아래의 SVG 그림 7개입니다. 그림은 시나리오·정책별 배치 성공률(0–1), 평균 미배치 작업 수, 마감 준수율(0–1), P95 큐 대기시간(초), P95 총 시간(초), 노드 부하 불균형 및 정상 대비 배치 성공률 변화(%p)를 나타냅니다.

정상 대비 분석은 정책과 워크로드별로 수행합니다. 배치 성공률과 마감 준수율은 퍼센트포인트 차이로, 시간·개수·불균형은 정상값이 0일 때를 제외하고 백분율 변화로 표시합니다. 정상 기준이 0이면 0으로 나누지 않고 절대 차이를 보존하며 상대 변화는 `계산 불가`로 기록합니다. 자동 생성된 발견은 실제 집계 수치의 관측 서술이며 인과관계나 평가하지 않은 환경으로의 일반화를 제공하지 않습니다. 보고서의 한계 절에는 시뮬레이션·저장 토폴로지·워크로드·실물 에너지 측정·링크 복구·강화학습 정책의 범위를 명시합니다.

## 시간 기반 장애·복구 시나리오

정적 `normal`, `single`, `multi` 시나리오는 그대로 유지됩니다. 동적 시나리오는 `experiments/scenarios/`의 JSON 파일로 정의하며 다음 스키마를 사용합니다.

```json
{
  "name": "link_failure_recovery",
  "duration_seconds": 30,
  "tick_seconds": 1,
  "events": [
    {"event_id": "fail-link-0-1", "time_seconds": 10, "type": "link_failure", "target": "0-1", "metadata": {}},
    {"event_id": "recover-link-0-1", "time_seconds": 20, "type": "link_recovery", "target": "0-1"}
  ]
}
```

지원 이벤트는 `link_failure`, `link_recovery`, `node_failure`, `node_recovery`입니다. 이벤트는 시뮬레이션 시간, failure/recovery 우선순위, `event_id` 순으로 처리됩니다. 음수·기간 밖 시간, 중복 ID, 잘못된 target/type, matching failure 전 recovery는 시작 전에 거부됩니다. 링크 이벤트는 저장 네트워크 데이터에 존재하는 장애 조합만 실행할 수 있습니다.

```bash
.venv/bin/python -m satgenpy.ai_datacenter.dynamic_scenario \
  --scenario experiments/scenarios/link_failure_recovery.json --validate-only

.venv/bin/python -m satgenpy.ai_datacenter.experiment_runner \
  --dynamic-scenario experiments/scenarios/link_failure_recovery.json \
  --policies completion_time --workloads demo --seeds 0 \
  --output experiments/dynamic-development

# API·프런트엔드·Prometheus에서 같은 동적 결과 게시
.venv/bin/python -m satgenpy.ai_datacenter.metrics_server \
  --dynamic-scenario experiments/scenarios/link_failure_recovery.json \
  --dynamic-policy completion_time --dynamic-workload demo --seed 0
```

운영 단계는 `healthy`(정상), `degraded`(성능 저하), `rerouting`(우회 중), `recovering`(정상 조건 검증 중)입니다. 모든 활성 장애가 해제되고 미배치 작업과 사용 불가 노드가 남지 않을 때만 정상 복원으로 기록합니다.

- `detection_time_seconds`: 최초 장애 발생부터 결정적 틱 감지까지
- `reroute_time_seconds`: 감지부터 저장 경로 상태를 이용한 우회 완료까지
- `service_recovery_time_seconds`: 최초 장애부터 모든 장애 해제와 서비스 정상 조건 검증까지
- `jobs_unplaced_during_failure`: 장애 활성 중 도착해 최초 배치에 실패한 작업 수
- `retry_success_ratio`: recovery 후 pending 작업 재시도 대비 성공 비율; 재시도가 없으면 null

pending 작업 재시도와 새 작업 재스케줄링은 지원하지만 실행 중 작업의 라이브 마이그레이션과 체크포인트 복원은 지원하지 않습니다. 결과는 저장 토폴로지/경로, 기존 워크로드·정책과 틱 간격에 의존하며 물리 링크 복구 지연이나 실제 하드웨어 에너지를 측정하지 않습니다.

## 대시보드 실행

```bash
python -m streamlit run satgenpy/ai_datacenter/dashboard.py
```

대시보드는 시간·알고리즘·시나리오 선택, 3D 지구와 위성 경로, 배치 및 복구 지표, 버스트 워크로드 비교 결과를 제공합니다.

## 생성 파일

모든 결과는 `satgenpy/demo_data/`에 저장됩니다.

| 파일 | 내용 |
|---|---|
| `network_costs.csv` | 시간·시나리오·연산 위성별 경로, RTT, 홉 수 및 가용 상태 |
| `node_positions.csv` | 시간별 위성·지상국 위도, 경도 및 고도 |
| `placement_results.csv` | 기존 배치 알고리즘과 시나리오별 선택 결과 |
| `ai_jobs.csv` | 결정적으로 생성한 100개 기본 AI 작업 |
| `workload_experiment_results.csv` | 300개 버스트 작업의 시나리오별 상세 배치·큐·완료 결과 |
| `workload_experiment_summary.csv` | 시나리오별 배치 성공률, 마감 준수율 및 시간 통계 |
| `experiment_comparison.csv` | 정상 대비 성공률 차이, 시간 비율 및 추가 미배치 작업 수 |
| `experiment_report.md` | 검증된 CSV 수치로 자동 생성한 한국어 실험 보고서 |

## 실험 시나리오

### 기본 배치 시나리오

| 시나리오 | 설명 |
|---|---|
| `NORMAL` | 링크 및 연산 상태가 정상인 기준 환경 |
| `FAILED_ISL_0_1` | 위성 간 링크 0-1 장애 |
| `MULTI_FAILED_ISL_0_1_10_11` | 링크 0-1과 10-11 동시 장애 |
| `HIGH_LOAD_NODE_7` | 7번 연산 위성의 지속 고부하 |
| `DYNAMIC_LOAD_NODE_7` | 특정 시간 구간에 7번 위성 부하가 증가한 뒤 복구 |

### 버스트 워크로드 시나리오

| 시나리오 | 설명 |
|---|---|
| `NORMAL_BURST` | 정상 링크에서 300개 버스트 작업 처리 |
| `FAILED_ISL_0_1_BURST` | 링크 0-1 장애에서 동일한 300개 작업 처리 |
| `MULTI_FAILED_ISL_0_1_10_11_BURST` | 링크 0-1·10-11 장애에서 동일한 300개 작업 처리 |

## 작업 배치 알고리즘

- `compute_only`: 네트워크 경로와 무관하게 큐 길이, GPU 사용률, 연산 속도를 기준으로 연산 위성을 선택합니다.
- `network_only`: 가용 후보 중 RTT가 가장 낮은 연산 위성을 선택합니다.
- `compute_aware`: 정규화한 네트워크 비용과 연산 상태 점수를 함께 비교합니다.
- `completion_time`: 네트워크 전달시간, 동적 큐 대기시간, 작업별 연산시간을 합산하여 예상 완료시간이 가장 짧은 위성을 선택합니다.

## 현재 버스트 실험 결과

아래 값은 현재 `satgenpy/demo_data/workload_experiment_summary.csv`에서 읽은 결과입니다. 시간은 가독성을 위해 밀리초 원본을 초로 변환했습니다.

| 시나리오 | 배치 성공률 | 마감 준수율 | 평균 큐 대기시간 | 평균 완료시간 |
|---|---:|---:|---:|---:|
| 정상 | 100.00% | 13.33% | 22.42초 | 24.28초 |
| 단일 링크 장애 | 100.00% | 11.33% | 22.49초 | 24.37초 |
| 다중 링크 장애 | 96.33% | 8.65% | 55.29초 | 57.05초 |

현재 결과에서는 단일 링크 장애가 우회 경로로 대부분 흡수되어 배치 성공률을 유지합니다. 다중 링크 장애에서는 11개 작업이 미배치되고 접근 가능한 연산 위성에 부하가 집중되어 평균 큐 대기시간과 완료시간이 크게 증가합니다. 이 해석은 현재 CSV 결과에 한정됩니다.

## 디렉터리 구조

```text
.
├── README.md
├── satgenpy/
│   ├── README.md
│   ├── ai_datacenter/
│   │   ├── compute_model.py
│   │   ├── job_model.py
│   │   ├── workload.py
│   │   ├── placement.py
│   │   ├── cost_model.py
│   │   ├── workload_simulator.py
│   │   ├── workload_experiment.py
│   │   ├── report_generator.py
│   │   ├── run_demo.py
│   │   ├── run_all.py
│   │   └── dashboard.py
│   ├── demo_data/
│   └── tests/test_end_to_end_kuiper_duo.py
├── ns3-sat-sim/
└── satviz/
```

## 전체 시스템 시작

### 로컬 프로세스 모드

저장소 루트에서 메트릭 서버와 Vite를 로컬 프로세스로, Prometheus와 Grafana를 기존 monitoring Compose로 관리합니다. 시작 시나리오는 `normal`, `single`, `multi` 중 선택하며 생략하면 `multi`가 사용됩니다.

```bash
./scripts/start_system.sh multi
./scripts/status_system.sh
./scripts/stop_system.sh
```

### Docker Compose 모드

첫 실행 전에 예시 환경 파일을 복사하고 실제 환경에 맞게 값을 변경합니다. `.env`에는 실제 비밀번호를 넣을 수 있지만 저장소에 커밋하지 않습니다.

```bash
cp .env.example .env
docker compose config
docker compose up -d --build
```

스크립트 인터페이스로도 같은 Compose 프로젝트를 관리할 수 있습니다.

```bash
./scripts/start_system.sh multi --docker
./scripts/status_system.sh --docker
./scripts/stop_system.sh --docker
```

Compose 상태와 JSON 구조 로그는 다음 명령으로 확인합니다.

```bash
docker compose ps
docker compose logs -f
docker compose down
```

모니터링 이력까지 완전히 초기화하려면 다음 명령을 사용합니다. `down -v`는 `prometheus-data`와 `grafana-data` 볼륨을 삭제하므로 Prometheus 시계열과 Grafana 저장 이력이 복구되지 않습니다.

```bash
docker compose down -v
```

모든 컨테이너는 내부 `operations` 네트워크에서 서비스 이름으로 통신합니다. 프런트엔드 Nginx는 `/api/*`, `/metrics`, `/health`, `/ready`를 `backend:8000`으로 전달하고 SPA 경로 및 Cesium 정적 자산을 제공합니다. Prometheus는 `backend:8000`을 스크레이프하며 Grafana 데이터 소스는 `prometheus:9090`입니다. 데이터는 `prometheus-data`, `grafana-data` 이름 있는 볼륨에 유지됩니다.

기본 호스트 URL은 다음과 같습니다.

- Cesium 운영 콘솔: `http://localhost:5173`
- 백엔드 API: `http://localhost:8000`
- Prometheus: `http://localhost:9090`
- Grafana: `http://localhost:3000`
- liveness/readiness: `http://localhost:8000/health`, `http://localhost:8000/ready`

Cesium 운영 콘솔의 시나리오 선택기는 메트릭 서버의 활성 시나리오와 자동 동기화됩니다. 화면을 열 때 서버 값을 불러오고, 정상·단일 장애·다중 장애 선택 시 CSV 시각화와 Prometheus/Grafana 메트릭을 함께 전환합니다. 동기화 상태는 우측 모니터링 패널에서 확인할 수 있으며, 메트릭 서버가 중단되어도 CSV 화면은 계속 사용할 수 있습니다.

## Prometheus 메트릭 서버

Prometheus 클라이언트 의존성을 설치한 뒤 저장소 루트에서 서버를 실행합니다.

```bash
pip install prometheus-client
python -m satgenpy.ai_datacenter.metrics_server
```

메트릭 엔드포인트는 `http://localhost:8000/metrics`입니다. 시나리오, 포트와 CSV 갱신 주기는 선택적으로 지정할 수 있습니다.

서비스 상태는 다음 엔드포인트로 확인합니다.

```text
GET http://localhost:8000/health
GET http://localhost:8000/ready
```

`/health`는 HTTP 프로세스가 응답하는지만 확인하는 liveness 검사입니다. `/ready`는 활성 스냅샷과 Prometheus 메트릭 상태까지 준비되었는지 확인하며, 준비되지 않았으면 HTTP 503을 반환합니다. 시작 스크립트는 두 검사를 순서대로 통과한 뒤 백엔드 준비 완료를 보고합니다.

```bash
python -m satgenpy.ai_datacenter.metrics_server \
  --scenario FAILED_ISL_0_1_BURST \
  --port 8000 \
  --refresh-seconds 30
```

Prometheus 스크레이프 설정 예시:

```yaml
scrape_configs:
  - job_name: space-ai-datacenter
    static_configs:
      - targets: ["localhost:8000"]
```

CSV를 읽지 못하면 서버는 기존의 마지막 정상 스냅샷을 유지하면서 한국어 오류 로그를 기록합니다.

백엔드는 표준 오류로 한 줄당 하나의 JSON 로그를 출력하며 `scripts/start_system.sh` 실행 시 `.runtime/metrics_server.log`에 저장됩니다. 프런트엔드 로그는 `.runtime/frontend.log`에 저장되고, Prometheus와 Grafana 로그는 `monitoring` 디렉터리에서 `docker compose logs`로 확인합니다. JSON 로그의 기본 필드는 `timestamp`, `level`, `component`, `event_type`, `message`이며 상황에 따라 `scenario`, `node`, `job_id`, `incident_id`, `method`, `path`, `status_code`, `duration_ms`가 추가됩니다.

현재 활성 스냅샷의 운영 지표는 다음 API에서 확인할 수 있습니다.

```text
GET http://localhost:8000/api/status
```

이 API는 Prometheus Gauge와 동일한 메모리 스냅샷을 반환합니다. Cesium의 현재 운영 상태는 이 API를 사용하고, 세 시나리오 동시 비교는 저장된 실험 CSV 결과를 사용합니다.

### 운영 경보 등급

운영 등급은 AI 이상 탐지가 아니라 활성 스냅샷에 적용하는 결정적 규칙입니다.

- `심각`: 미배치 작업이 있거나, 배치 성공률이 0.95 미만이거나, 평균 큐 대기시간이 60초 이상
- `주의`: 심각 조건이 없으면서 사용 불가 연산 노드가 있거나, 평균 큐 대기시간이 30초 이상이거나, 장애 링크가 있음
- `정상`: 위 조건이 모두 없음

`/api/status`의 `severity`, `severity_label`, `alert_reasons`와 Prometheus의 `space_ai_datacenter_alert_severity`, `space_ai_datacenter_unavailable_nodes`는 같은 규칙 계산 결과를 사용합니다.

### 운영 상세 API

집계 운영 상태는 `GET /api/status`가 제공하고, 다음 API는 같은 활성 시나리오 스냅샷의 상세 데이터를 제공합니다.

```text
GET http://localhost:8000/api/nodes
GET http://localhost:8000/api/nodes/{node_id}
GET http://localhost:8000/api/jobs?status=unplaced&node=7&limit=50
GET http://localhost:8000/api/events?level=warning&category=node&limit=50
```

작업 필터 `status`는 `placed`, `unplaced`, `deadline_missed`를 지원합니다. 이벤트는 `info`, `warning`, `critical` 등급과 `network`, `node`, `job`, `system` 분류를 지원하며 최근 항목부터 반환됩니다.

### 인시던트 API

```text
GET  http://localhost:8000/api/incidents?status=open&severity=critical&limit=20
GET  http://localhost:8000/api/incidents/{incident_id}
POST http://localhost:8000/api/incidents/{incident_id}/acknowledge
```

인시던트 생명주기는 `open → acknowledged → resolved`입니다. 확인 처리는 멱등이며 인시던트를 종료하지 않습니다. 장애 링크·사용 불가 노드·미배치 작업·운영 등급 전이를 같은 운영 문제로 묶고, 모든 장애 조건이 사라져 정상 등급으로 돌아오면 종료합니다. 이 생성·종료 및 원인 표시는 결정적 운영 규칙이며 AI 기반 근본 원인 분석이 아닙니다.

## 한계

- 시연과 분석 속도를 위해 축소된 위성군을 사용합니다.
- `compute_speed`는 실제 GPU 처리량이 아닌 상대 연산 속도 단위입니다.
- 각 연산 위성은 단순화된 단일 서버 큐로 모델링됩니다.
- 작업 종류, 크기, 도착 패턴은 재현성을 위한 결정적 워크로드입니다.
- 전력, 열, 방사선 및 하드웨어 고장 모델은 포함하지 않습니다.
- 본 시스템은 연구·졸업 프로젝트용 프로토타입이며 실제 위성 배치·운영 시스템이 아닙니다.

## 재현 순서 요약

```bash
source .venv/bin/activate
cd satgenpy
python -m unittest discover -s tests -p "test_end_to_end_kuiper_duo.py" -v
cd ..
python -m satgenpy.ai_datacenter.run_all
python -m streamlit run satgenpy/ai_datacenter/dashboard.py
```

네트워크 CSV 생성과 전체 파이프라인 실행을 분리함으로써 Hypatia 계산 결과를 재사용하면서 AI 작업 배치 실험, 시각화 및 보고서 생성을 반복 재현할 수 있습니다.
