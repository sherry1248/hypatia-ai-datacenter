# 우주 AI 데이터센터 졸업작품 단계별 로드맵

## 프로젝트 목표

**LEO 위성 기반 우주 AI 데이터센터의 연산 부하·네트워크 장애 인지형 작업 배치 및 적응형 라우팅 시스템**

핵심 연구 질문:

> 위성 간 링크 장애와 각 위성의 연산 부하가 계속 변하는 환경에서, AI 작업을 어느 연산 위성에 배치하고 어떤 경로로 전송해야 전체 작업 완료시간을 줄일 수 있는가?

---

# 전체 진행 현황

- [x] 1단계: Hypatia 실행 환경 및 구조 파악
- [x] 2단계: 위성 간 링크 장애 주입
- [x] 3단계: 장애 우회 경로 검증
- [x] 4단계: 네트워크 Telemetry 수집
- [x] 5단계: Streamlit 네트워크 모니터링 화면
- [ ] **6단계: 우주 AI 데이터센터 연산 모델 설계 ← 현재 다음 단계**
- [ ] 7단계: AI 작업 모델 설계
- [ ] 8단계: 작업 배치 알고리즘 구현
- [ ] 9단계: 네트워크·연산 통합 비용 함수 구현
- [ ] 10단계: 다양한 장애 및 부하 시나리오 구현
- [ ] 11단계: 비교 알고리즘 및 반복 실험
- [ ] 12단계: 결과 분석·논문·발표 자료 완성

## 현재 위치

> **현재는 5단계까지 완료했으며, 6단계인 ‘우주 AI 데이터센터 연산 모델 설계’에 진입하기 직전이다.**

현재 완성된 것은 전체 시스템 중 **네트워크 시뮬레이션 및 모니터링 기반**이다.  
아직 AI 연산 작업, GPU 자원, 작업 큐, 연산 위성 선택 알고리즘은 구현되지 않았다.

예상 전체 완성도: **약 15~20%**

---

# 1단계. Hypatia 실행 환경 및 구조 파악

## 목표

Hypatia가 위성 위치, ISL, 지상국 연결, 동적 경로를 어떤 흐름으로 생성하는지 파악한다.

## 주요 작업

- [x] Hypatia 저장소 실행
- [x] Python 가상환경 구성
- [x] 필수 패키지 설치
- [x] Kuiper Duo end-to-end 테스트 실행
- [x] 주요 호출 흐름 확인

## 확인한 호출 흐름

```text
test_end_to_end_kuiper_duo.py
→ helper_dynamic_state.worker
→ generate_dynamic_state
→ generate_dynamic_state_at
→ algorithm_free_one_only_over_isls
→ calculate_fstate_shortest_path_without_gs_relaying
→ nx.floyd_warshall_numpy
```

## 완료 기준

- Hypatia 테스트가 정상 실행된다.
- 경로 계산이 어느 함수에서 수행되는지 설명할 수 있다.

## 상태

**완료**

---

# 2단계. 위성 간 링크 장애 주입

## 목표

특정 ISL을 제거해 실제 장애 상황을 재현한다.

## 주요 작업

- [x] `failed_isls` 매개변수 추가
- [x] helper → generator → algorithm으로 전달
- [x] 최단 경로 계산 전에 장애 링크 제거
- [x] 기존 정상 실행 동작 유지
- [x] 하드코딩된 장애 처리 제거

## 현재 장애 예시

```text
실패 링크: 0-1
```

## 완료 기준

- 장애가 없는 경우 기존 경로가 유지된다.
- 장애가 있는 경우 해당 링크가 실제 그래프에서 제거된다.

## 상태

**완료**

---

# 3단계. 장애 우회 경로 검증

## 목표

링크 장애 후 새로운 경로가 실제로 계산되는지 테스트로 증명한다.

## 현재 검증 결과

```text
정상 경로:
12-1-0-3-13

0-1 장애 후 우회 경로:
12-9-10-11-7-13
```

## 주요 작업

- [x] 정상 시나리오 테스트
- [x] 장애 시나리오 테스트
- [x] 실패 링크가 우회 경로에 포함되지 않는지 검증
- [x] 테스트 2개 통과

## 완료 기준

- 정상 및 장애 테스트가 모두 통과한다.
- 장애 경로에 `(0, 1)` 또는 `(1, 0)`이 포함되지 않는다.

## 상태

**완료**

---

# 4단계. 네트워크 Telemetry 수집

## 목표

Hypatia가 생성한 경로와 RTT 결과를 분석 가능한 CSV로 저장한다.

## 생성 파일

```text
satgenpy/demo_data/routing_events.csv
```

## 현재 컬럼

```text
time_ns
source
destination
route
rtt_ns
hop_count
failed_isls
status
```

## 상태 값

```text
NORMAL
REROUTED
DROPPED
```

## 주요 작업

- [x] 경로 파일 읽기
- [x] RTT 파일 읽기
- [x] 시간별 CSV 생성
- [x] 정상 실행은 CSV 새로 작성
- [x] 장애 실행은 CSV에 추가
- [x] 이벤트 기반 경로를 다음 변경 시점까지 forward-fill
- [x] 잘못 생성되던 대량 `DROPPED` 문제 수정

## 완료 기준

- 정상 행에 `NORMAL`이 기록된다.
- 장애 우회 행에 `0-1`, `REROUTED`가 기록된다.
- 경로 변경 사이 시간에도 직전 경로와 RTT가 정상적으로 기록된다.

## 상태

**완료**

---

# 5단계. Streamlit 네트워크 모니터링 화면

## 목표

CSV에 저장된 실제 시뮬레이션 결과를 시간별로 확인한다.

## 현재 기능

- [x] `routing_events.csv` 직접 읽기
- [x] 정상/장애 시나리오 선택
- [x] 실제 시간값 기반 슬라이더
- [x] 현재 경로 표시
- [x] RTT를 ms로 변환해 표시
- [x] hop count 표시
- [x] 실패 ISL 표시
- [x] 상태 표시
- [x] 시뮬레이션 시간을 초 단위로 표시
- [x] 정상 경로를 초록색으로 표시
- [x] 장애 링크를 빨간 점선으로 표시
- [x] 시간에 따라 새로운 노드가 등장해도 그래프가 깨지지 않도록 수정

## 현재 화면의 의미

현재 화면은 **우주 AI 데이터센터 전체 화면이 아니라, 네트워크 계층 모니터링 화면**이다.

## 완료 기준

- 시간 슬라이더를 이동할 때 경로와 RTT가 바뀐다.
- 정상 및 장애 시나리오를 각각 확인할 수 있다.
- `12-4-3-13`처럼 새로운 노드가 등장해도 오류가 발생하지 않는다.

## 상태

**완료**

---

# 6단계. 우주 AI 데이터센터 연산 모델 설계

## 목표

각 위성을 단순 라우팅 노드가 아니라 AI 연산 자원을 가진 데이터센터 노드로 모델링한다.

## 현재 위치

> **지금부터 시작할 단계**

## 위성별로 필요한 상태

```text
node_id
gpu_capacity
gpu_util_percent
memory_total_mb
memory_used_mb
queue_length
power_available_percent
temperature_c
compute_available
```

## 최소 구현안

처음부터 모든 물리 요소를 구현하지 않고 아래 3개부터 시작한다.

```text
gpu_util_percent
queue_length
compute_speed
```

## 중요한 원칙

- 값은 단순 화면 장식이 아니라 명시된 시뮬레이션 가정에 따라 생성한다.
- 난수 사용 시 seed를 고정해 재현 가능하게 만든다.
- 각 값의 단위와 범위를 문서화한다.
- 지상국과 위성 ID를 구분한 후 연산 위성을 지정한다.

## 완료 기준

- 후보 연산 위성이 정의된다.
- 각 연산 위성의 GPU 부하와 큐 상태를 시간별로 조회할 수 있다.
- 같은 seed에서 같은 결과가 나온다.

## 상태

**다음 작업**

---

# 7단계. AI 작업 모델 설계

## 목표

우주 데이터센터가 처리할 AI 작업을 데이터 구조로 만든다.

## 작업 속성

```text
job_id
arrival_time_ns
job_type
input_size_mb
required_compute
required_memory_mb
deadline_ms
priority
source_node
```

## 초기 작업 종류 예시

```text
image_inference
satellite_image_analysis
object_detection
weather_prediction
```

## 완료 기준

- 시간에 따라 작업이 생성된다.
- 작업 요구량과 연산 노드 자원을 비교할 수 있다.
- 작업 생성 조건이 재현 가능하다.

## 상태

**미착수**

---

# 8단계. 작업 배치 알고리즘 구현

## 목표

AI 작업을 어느 연산 위성에 보낼지 선택한다.

## 비교 알고리즘

### A. Network-only

RTT가 가장 낮은 연산 위성을 선택한다.

```text
score = network_rtt
```

### B. Compute-only

GPU 부하 또는 작업 큐가 가장 낮은 위성을 선택한다.

```text
score = gpu_load + queue_wait
```

### C. Compute-aware

네트워크와 연산 상태를 함께 고려한다.

```text
score =
network_delay
+ queue_delay
+ estimated_compute_time
+ failure_penalty
```

## 완료 기준

- 동일 작업에 대해 각 알고리즘의 선택 결과를 비교할 수 있다.
- 선택 이유와 점수를 로그로 확인할 수 있다.

## 상태

**미착수**

---

# 9단계. 네트워크·연산 통합 비용 함수

## 목표

경로 지연과 연산 지연을 하나의 작업 완료시간 모델로 통합한다.

```text
total_completion_time =
upload_time
+ network_rtt
+ queue_wait_time
+ compute_time
+ result_return_time
```

## 완료 기준

- 각 작업의 예상 완료시간을 계산할 수 있다.
- 실제 시뮬레이션 결과와 예측값을 비교할 수 있다.

## 상태

**미착수**

---

# 10단계. 장애 및 부하 시나리오 확장

## 네트워크 시나리오

- [ ] 링크 1개 장애
- [ ] 임의 링크 장애
- [ ] 링크 2개 이상 동시 장애
- [ ] 위성 이동에 따른 경로 변경
- [ ] 지상국 연결 단절
- [ ] 특정 구간 혼잡

## 연산 시나리오

- [ ] GPU 과부하
- [ ] 큐 폭증
- [ ] 연산 위성 고장
- [ ] 메모리 부족
- [ ] 전력 부족
- [ ] 온도 제한으로 연산 성능 저하

## 복합 시나리오

- [ ] 링크 장애와 GPU 과부하 동시 발생
- [ ] 특정 지역에서 AI 작업 급증
- [ ] 최적 연산 위성으로 가는 경로 단절
- [ ] 작업 실행 중 연산 위성 고장

## 상태

**미착수**

---

# 11단계. 반복 실험 및 성능 비교

## 주요 평가지표

```text
평균 작업 완료시간
95번째 백분위 지연시간
작업 성공률
작업 드롭률
평균 큐 대기시간
평균 네트워크 RTT
평균 hop count
라우팅 변경 횟수
장애 복구시간
GPU 사용률 편차
```

## 최소 비교 구성

```text
Network-only
Compute-only
Compute-aware
```

## 상태

**미착수**

---

# 12단계. 논문·발표·최종 시연

## 보고서 구성

1. 연구 배경
2. 문제 정의
3. 관련 연구
4. 시스템 구조
5. 위성 네트워크 모델
6. AI 작업 및 연산 자원 모델
7. 제안 알고리즘
8. 실험 환경
9. 실험 결과
10. 한계점
11. 향후 연구
12. 결론

## 최종 제출물

- [ ] 소스코드
- [ ] README
- [ ] 설치 및 실행 방법
- [ ] 실험 설정
- [ ] 실험 결과 CSV
- [ ] 결과 그래프
- [ ] 시스템 구조도
- [ ] 졸업작품 보고서
- [ ] 발표 자료
- [ ] 시연 영상

## 상태

**미착수**

---

# 현재까지 만든 파일과 역할

| 파일 | 역할 |
|---|---|
| `helper_dynamic_state.py` | 장애 링크 정보를 동적 상태 생성기로 전달 |
| `generate_dynamic_state.py` | 시간별 상태 생성 과정에 장애 정보 전달 |
| `algorithm_free_one_only_over_isls.py` | 최단 경로 계산 전에 실패 ISL 제거 |
| `test_end_to_end_kuiper_duo.py` | 정상·장애 테스트, 경로·RTT·CSV 생성 |
| `routing_demo.py` | 실제 Telemetry 기반 Streamlit 모니터링 |

---

# 바로 다음 작업 체크리스트

- [ ] 경로의 `12`, `13`이 위성인지 지상국인지 정확히 확인
- [ ] AI 연산이 가능한 위성 ID 후보 선정
- [ ] 연산 노드 상태 데이터 구조 결정
- [ ] GPU 부하 생성 규칙 결정
- [ ] 큐 길이 생성 및 갱신 규칙 결정
- [ ] 연산 속도 및 예상 처리시간 공식 결정
- [ ] 연산 상태를 별도 모듈로 둘지 기존 Hypatia 코드에 붙일지 결정
- [ ] 첫 번째 AI 작업 형식 결정
- [ ] Network-only 기준선 설계
- [ ] 실험 결과에 추가할 Telemetry 컬럼 결정

## 다음으로 추가할 Telemetry 후보

```text
job_id
job_type
input_size_mb
compute_node
gpu_util_percent
queue_length
queue_wait_ms
compute_time_ms
total_completion_time_ms
placement_algorithm
placement_score
```

---

# 진행 원칙

- 한 번에 1~2개 파일만 수정한다.
- 기존 Hypatia 기능을 깨뜨리지 않는다.
- 정상 시나리오가 계속 통과하는지 확인한다.
- 화면에 보이는 값은 실제 시뮬레이션 결과 또는 문서화된 모델에서 생성한다.
- random seed를 고정해 결과를 재현할 수 있게 한다.
- 기능 개수보다 명확한 연구 질문과 비교 실험을 우선한다.

---

# 한 줄 요약

> 현재는 **Hypatia 기반 장애 우회 라우팅과 네트워크 모니터링 기반을 완성한 상태**이며, 이제부터 **각 위성을 AI 연산 노드로 모델링하는 6단계**를 시작한다.
