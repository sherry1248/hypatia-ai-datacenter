# Hypatia 기반 위성 네트워크 장애 대응·라우팅 시각화 프로젝트 진행 기록

작성일: 2026-07-22  
프로젝트 경로: `/home/juhyeon/projects/hypatia-master`

---

## 1. 프로젝트 개요

### 1.1 현재 프로젝트 방향

현재 졸업작품의 핵심 방향은 다음과 같다.

> **LEO 위성 네트워크 환경에서 링크 장애가 발생했을 때 우회 경로를 자동으로 계산하고, 그 결과를 시각적으로 모니터링하는 시스템**

초기에는 단순한 라우팅 알고리즘 비교나 네트워크 시뮬레이션을 생각했지만, 현재는 아래 요소를 결합하는 방향으로 구체화되었다.

- Hypatia 기반 LEO 위성 네트워크 시뮬레이션
- 위성 간 링크(ISL) 장애 주입
- 장애 링크를 제외한 최단경로 재계산
- 정상 경로와 우회 경로 비교
- 테스트 자동화
- Streamlit 기반 시각화
- 이후 실제 시뮬레이션 결과를 CSV/JSON으로 내보내는 Telemetry 구조
- 최종적으로 3D 지구 기반 위성 네트워크 시각화 확장 가능

---

## 2. 사용 중인 오픈소스와 주요 구성

### 2.1 Hypatia

사용 중인 저장소:

```text
snkas/hypatia
```

Hypatia의 주요 구성은 다음과 같다.

```text
hypatia-master/
├── satgenpy/
│   ├── satgen/
│   │   ├── dynamic_state/
│   │   ├── tles/
│   │   ├── ground_stations/
│   │   ├── post_analysis/
│   │   └── ...
│   ├── tests/
│   ├── routing_demo.py
│   └── demo_data/
├── ns3-sat-sim/
├── satviz/
└── paper/
```

현재 집중하고 있는 영역은 `satgenpy`이다.

### 2.2 현재 확인된 실행·호출 흐름

라우팅 동적 상태 생성 흐름은 다음과 같이 확인되었다.

```text
satgenpy/tests/test_end_to_end_kuiper_duo.py
        ↓
satgenpy/satgen/dynamic_state/helper_dynamic_state.py
        ↓
worker(args)
        ↓
generate_dynamic_state(...)
        ↓
generate_dynamic_state_at(...)
        ↓
algorithm_free_one_only_over_isls(...)
        ↓
calculate_fstate_shortest_path_without_gs_relaying(...)
        ↓
NetworkX nx.floyd_warshall_numpy(...)
```

---

## 3. 코드 분석으로 확인한 핵심 내용

### 3.1 라우팅 알고리즘 선택 위치

파일:

```text
satgenpy/satgen/dynamic_state/generate_dynamic_state.py
```

알고리즘 선택은 `generate_dynamic_state_at()` 내부의 `if / elif` 분기에서 이루어진다.

확인된 라우팅 알고리즘 이름:

```text
algorithm_free_one_only_over_isls
algorithm_free_gs_one_sat_many_only_over_isls
algorithm_free_one_only_gs_relays
algorithm_paired_many_only_over_isls
```

현재 장애 우회 기능을 적용한 대상:

```text
algorithm_free_one_only_over_isls
```

### 3.2 실제 최단경로 계산

파일:

```text
satgenpy/satgen/dynamic_state/fstate_calculation.py
```

함수:

```text
calculate_fstate_shortest_path_without_gs_relaying
```

사용하는 최단경로 계산:

```python
nx.floyd_warshall_numpy(...)
```

확인된 특성:

- 입력 그래프는 수정하지 않고 읽기만 한다.
- ISL edge 형식은 `(src_satellite_id, dst_satellite_id)`이다.
- edge에는 `weight` 속성이 필요하다.
- 경로가 없으면 Floyd-Warshall 거리 결과가 `inf`가 된다.
- 유효한 경로 후보가 없으면 다음 값으로 드롭 처리된다.

```python
(-1, -1, -1)
```

### 3.3 장애 링크 제거 위치

장애 링크를 제거하기 가장 안전한 위치는:

```text
algorithm_free_one_only_over_isls()
내에서 최단경로 함수 호출 직전
```

현재 방식은 원본 그래프를 직접 수정하지 않고 복사본을 만든 뒤 실패 edge만 제거한다.

개념적인 구조:

```python
routing_graph = sat_net_graph_only_satellites_with_isls.copy()
routing_graph.remove_edges_from(failed_isls)
```

그 후 기존 그래프 대신 `routing_graph`를 최단경로 계산 함수에 전달한다.

---

## 4. 구현 완료된 기능

### 4.1 실패 ISL 입력 전달 구조

기존에는 테스트를 위해 아래처럼 장애 링크가 코드에 하드코딩되어 있었다.

```python
failed_isls = [(0, 1)]
```

현재는 하드코딩이 제거되었으며, 외부에서 선택적으로 전달할 수 있게 수정되었다.

전달 흐름:

```text
help_dynamic_state(failed_isls=())
        ↓
worker(args)
        ↓
generate_dynamic_state(..., failed_isls)
        ↓
generate_dynamic_state_at(..., failed_isls)
        ↓
algorithm_free_one_only_over_isls(..., failed_isls)
```

기본값:

```python
failed_isls=()
```

따라서 실패 링크를 전달하지 않으면 기존 Hypatia 동작이 그대로 유지된다.

### 4.2 정상 라우팅 검증

실패 링크를 지정하지 않았을 때 기존 정상 경로:

```text
12-1-0-3-13
```

기본 테스트 결과:

```text
Ran 1 test
OK
```

이후 장애 테스트까지 추가한 뒤:

```text
Ran 2 tests
OK
```

정상 라우팅이 기존과 동일하게 유지되는 것을 확인했다.

### 4.3 ISL 0-1 장애 주입

테스트에서 실제 존재하는 ISL:

```text
0-1
```

장애 입력:

```python
failed_isls=((0, 1),)
```

기존 경로:

```text
12-1-0-3-13
```

장애 후 실제 생성된 우회 경로:

```text
12-9-10-11-7-13
```

이 결과로 다음이 검증되었다.

- `(0, 1)` 링크 제거 성공
- 기존 경로의 `1-0` hop 회피 성공
- Floyd-Warshall 재계산 성공
- 유효한 대체 경로 생성 성공
- 장애 링크 양방향 사용 방지 성공

### 4.4 장애 전용 테스트 추가

파일:

```text
satgenpy/tests/test_end_to_end_kuiper_duo.py
```

기존 테스트는 유지되며, 장애 전용 테스트가 별도로 추가되었다.

구조:

```python
def test_end_to_end(self):
    self._run_end_to_end()

def test_end_to_end_reroutes_around_failed_isl(self):
    self._run_end_to_end(failed_isls=((0, 1),))
```

장애 테스트에서 검증하는 내용:

- 출발 노드가 12인지 확인
- 도착 노드가 13인지 확인
- 유효한 경로가 생성되는지 확인
- hop `0-1`이 포함되지 않는지 확인
- hop `1-0`이 포함되지 않는지 확인
- 전체 우회 경로를 강제로 하드코딩하지 않음

---

## 5. 개발 환경 설정 현황

### 5.1 Python 환경

기본 시스템 Python:

```text
Python 3.14.4
```

기본 pip:

```text
pip 25.1.1
```

Ubuntu의 PEP 668 정책으로 인해 시스템 Python에 직접 pip 설치 시 다음 오류가 발생했다.

```text
error: externally-managed-environment
```

### 5.2 가상환경 생성

프로젝트 루트에 가상환경 생성:

```text
/home/juhyeon/projects/hypatia-master/.venv
```

생성 명령:

```bash
cd /home/juhyeon/projects/hypatia-master
python3 -m venv .venv
source .venv/bin/activate
```

### 5.3 설치 완료된 주요 의존성

설치 및 확인된 패키지/도구:

```text
exputil 1.8.2
ephem
geopy
astropy
numpy
networkx
sgp4
matplotlib
statsmodels
cartopy
streamlit
plotly
gnuplot
```

`exputil` 설치:

```bash
.venv/bin/python -m pip install \
  git+https://github.com/snkas/exputilpy.git@v1.8.2
```

확인:

```text
exputil OK
```

### 5.4 발생했던 환경 오류와 해결

#### 오류 1

```text
python: command not found
```

해결:

```text
python 대신 python3 또는 가상환경의 python 사용
```

#### 오류 2

```text
ModuleNotFoundError: No module named 'tests'
```

해결:

```bash
cd satgenpy
python -m unittest discover -s tests -p "test_end_to_end_kuiper_duo.py" -v
```

#### 오류 3

```text
ModuleNotFoundError: No module named 'exputil'
```

해결:

```text
가상환경 생성 후 exputil 설치
```

#### 오류 4

```text
ModuleNotFoundError: No module named 'ephem'
ModuleNotFoundError: No module named 'geopy'
ModuleNotFoundError: No module named 'astropy'
ModuleNotFoundError: No module named 'cartopy'
```

해결:

```text
가상환경 내부에 필요한 Python 패키지 설치
```

#### 오류 5

```text
gnuplot: not found
```

해결:

```bash
sudo apt install gnuplot
```

---

## 6. 현재 테스트 실행 방법

프로젝트 루트 이동:

```bash
cd /home/juhyeon/projects/hypatia-master
```

가상환경 활성화:

```bash
source .venv/bin/activate
```

satgenpy 이동:

```bash
cd satgenpy
```

테스트 실행:

```bash
python -m unittest discover \
  -s tests \
  -p "test_end_to_end_kuiper_duo.py" \
  -v
```

정상 결과:

```text
Ran 2 tests
OK
```

---

## 7. 시각화 구현 현황

### 7.1 Streamlit 프로토타입

새로 만든 파일:

```text
satgenpy/routing_demo.py
```

현재 기능:

- `Normal` 모드
- `Failed ISL (0, 1)` 모드
- NetworkX 그래프 생성
- Plotly로 네트워크 시각화
- 전체 링크는 회색
- 현재 사용 경로는 초록색 굵은 선
- 장애 링크 `0-1`은 빨간 점선
- 각 노드에 위성 ID 표시
- 현재 경로 텍스트 표시
- hop count 표시
- 장애 링크 상태 표시

초기 정상 경로:

```text
12-1-0-3-13
```

장애 경로:

```text
12-9-10-11-7-13
```

실행 명령:

```bash
cd /home/juhyeon/projects/hypatia-master
source .venv/bin/activate
cd satgenpy
streamlit run routing_demo.py
```

### 7.2 실제 Hypatia 결과 파일 연결

처음에는 Streamlit 코드 내부에 경로를 고정했다.

```python
NORMAL_ROUTE = [12, 1, 0, 3, 13]
FAILED_ROUTE = [12, 9, 10, 11, 7, 13]
```

이후 테스트가 만든 실제 결과를 별도 파일로 저장하도록 개선했다.

저장 위치:

```text
satgenpy/demo_data/normal_route.txt
satgenpy/demo_data/failed_route.txt
```

테스트 종료 전에 실제 route 파일을 복사하고, 기존 `temp_analysis_data`는 그대로 삭제한다.

현재 Streamlit은 아래 실제 파일을 읽는다.

```text
demo_data/normal_route.txt
demo_data/failed_route.txt
```

파일이 없거나 형식이 잘못된 경우에만 fallback 경로를 사용한다.

### 7.3 실제 파일 저장 확인 명령

```bash
cd /home/juhyeon/projects/hypatia-master/satgenpy
ls -l demo_data
cat demo_data/normal_route.txt
cat demo_data/failed_route.txt
```

현재 두 파일 모두 생성되는 것을 확인했다.

---

## 8. 지금까지 완료된 범위 요약

### 완료

- Hypatia 저장소 구조 분석
- 라우팅 실행 진입점 확인
- 라우팅 알고리즘 선택 위치 확인
- Floyd-Warshall 최단경로 계산 위치 확인
- 실패 ISL 제거 위치 결정
- 그래프 복사본 기반 장애 링크 제거 구현
- `failed_isls` 선택적 인자 전달 구조 구현
- 정상 경로 유지 검증
- `(0, 1)` 장애 발생 시 우회 경로 검증
- 기본 테스트와 장애 테스트 분리
- 테스트 2개 통과
- Python 가상환경 구성
- Hypatia 실행 의존성 설치
- Streamlit 2D 네트워크 시각화 구현
- 정상/장애 경로 시각적 전환 구현
- 실제 Hypatia route 결과 파일 저장
- Streamlit이 실제 route 파일을 읽도록 연결

### 아직 미완료

- 시간에 따라 장애가 발생하고 복구되는 실제 시나리오
- 하나의 실행 안에서 정상 → 장애 → 복구 변화
- 시간별 route/RTT/hop/drop 데이터 통합
- `routing_events.csv` 생성
- RTT 그래프
- 경로 변경 횟수
- 패킷 드롭 횟수
- 장애 후 복구 시간 측정
- 복수 링크 장애
- 위성 자체 장애
- 혼잡도 기반 가중치
- 제안 알고리즘과 기존 알고리즘 비교
- 3D 지구 기반 위성 네트워크 시각화
- CesiumJS 또는 Plotly 3D 연동
- 최종 발표용 대시보드 구성

---

## 9. 현재 프로젝트의 수준

현재 상태는 단순한 예시 코드 수준을 넘어 다음 핵심 기능이 실제로 검증된 상태다.

> **Hypatia 위성 네트워크에서 특정 ISL을 장애 처리하고, 해당 링크를 제외한 최단경로를 다시 계산해 우회 경로를 생성하는 기능**

그러나 현재만으로는 졸업작품 최종본이라기보다 다음 단계의 기반이 완성된 상태다.

```text
핵심 기능 검증 완료
        ↓
실험 데이터 수집
        ↓
성능 비교
        ↓
모니터링 대시보드
        ↓
3D 시각화
        ↓
졸업작품 완성
```

---

## 10. 향후 권장 최종 시스템 구조

전문가가 실제 네트워크 모니터링 시스템을 만드는 방식과 비슷하게 다음 구조로 확장한다.

```text
Hypatia Simulation Engine
        ↓
Routing / RTT / Link Failure Data
        ↓
Telemetry Exporter
        ↓
CSV 또는 SQLite
        ↓
Streamlit Monitoring Dashboard
        ↓
CesiumJS 3D Satellite Visualization
```

### 수집 예정 데이터

```text
time_ns
source
destination
route
rtt_ns
hop_count
failed_isls
status
route_change_count
drop_count
```

### 예정 CSV

파일:

```text
satgenpy/demo_data/routing_events.csv
```

예상 형식:

```csv
time_ns,source,destination,route,rtt_ns,hop_count,failed_isls,status
0,12,13,12-1-0-3-13,12345678,4,,NORMAL
10000000000,12,13,12-9-10-11-7-13,18765432,5,0-1,REROUTED
20000000000,12,13,12-1-0-3-13,12400000,4,,RECOVERED
```

---

## 11. 다음 작업 우선순위

### 1순위: 실제 Telemetry CSV 생성

Hypatia의 기존 route 파일과 RTT 파일을 읽어 아래 파일로 통합한다.

```text
satgenpy/demo_data/routing_events.csv
```

필수 컬럼:

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

### 2순위: Streamlit이 CSV를 읽도록 변경

현재의 두 TXT 파일 방식에서 벗어나 시간별 데이터를 읽도록 변경한다.

필요 기능:

- 시간 슬라이더
- 현재 경로 표시
- 장애 링크 표시
- RTT 표시
- hop count 표시
- 상태 표시

상태 예시:

```text
NORMAL
REROUTED
DROPPED
RECOVERED
```

### 3순위: 시간 기반 장애

예시:

```text
0~9초: 정상
10~19초: ISL 0-1 장애
20초 이후: 복구
```

중요한 점은 화면만 예시로 바꾸는 것이 아니라, 실제 Hypatia 실행에서 시간에 따라 `failed_isls`가 달라져야 한다.

### 4순위: 실험 지표

- 평균 RTT
- 최대 RTT
- hop 증가량
- 경로 변경 횟수
- 드롭 수
- 장애 복구 시간
- 정상 대비 성능 저하율

### 5순위: 3D 시각화

최종적으로 다음을 표시한다.

- 3D 지구
- 위성 위치
- ISL
- 정상 링크
- 장애 링크
- 현재 경로
- 지상국
- 시간 재생

추천 기술:

```text
Plotly Scatter3d: 빠른 프로토타입
CesiumJS: 최종 발표용
```

---

## 12. Codex 사용 원칙

사용량을 아끼기 위해 다음 원칙을 유지한다.

### 권장

- 한 번에 파일 1~2개만 읽게 한다.
- 전체 저장소 분석을 요청하지 않는다.
- 먼저 diff만 요청한다.
- 적용 전에 diff를 검토한다.
- 테스트와 설치는 사용자가 직접 실행한다.
- Codex에는 코드 분석과 수정만 맡긴다.
- 결과는 짧게 요청한다.

### 피해야 할 요청

```text
Analyze the whole repository.
Redesign the entire architecture.
Run all tests.
Install every dependency.
Build the complete dashboard.
```

### 권장 프롬프트 형태

```text
You may read repository files directly.

Do not run tests or install packages.
Do not modify files yet.

Inspect only:
- file A
- file B

Goal:
[한 가지 목표]

Requirements:
- 최소 수정
- unrelated code 금지
- diff only
```

---

## 13. 현재 주요 파일 정리

### 수정된 핵심 파일

```text
satgenpy/satgen/dynamic_state/helper_dynamic_state.py
satgenpy/satgen/dynamic_state/generate_dynamic_state.py
satgenpy/satgen/dynamic_state/algorithm_free_one_only_over_isls.py
satgenpy/tests/test_end_to_end_kuiper_duo.py
satgenpy/routing_demo.py
```

### 생성된 파일/폴더

```text
.venv/
satgenpy/demo_data/
satgenpy/demo_data/normal_route.txt
satgenpy/demo_data/failed_route.txt
```

---

## 14. 현재 한 줄 요약

> Hypatia 기반 LEO 위성 네트워크에서 ISL 0-1 장애를 외부 입력으로 주입하고, Floyd-Warshall 기반 우회 경로를 생성하며, 정상·장애 테스트와 Streamlit 시각화까지 연결한 상태이다.

---

## 15. 다음 세션 시작 시 바로 할 일

다음 작업은 아래 한 가지부터 시작한다.

> **Hypatia의 실제 route 및 RTT 출력 파일을 시간 기준으로 합쳐 `routing_events.csv`를 생성한다.**

Codex에 요청할 핵심 목표:

```text
Use existing Hypatia route and RTT output files.
Export one row per timestamp to:
satgenpy/demo_data/routing_events.csv
```
