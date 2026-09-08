# ER-Bridge 확장 분석

## 0. 분석 범위와 확인 기준

- 분석 저장소: `/home/juhyeon/projects/EMS-Simulator`, `/home/juhyeon/projects/EMS-Simulator-Demos`
- 확인한 실행 구성: `examples/minimal.yaml`, `examples/simple.yaml`, `Minimal Example.py`, `Simple Example.py`
- 이 문서에서 “현재 동작”은 위 저장소의 실제 구현을 기준으로 한다.
- “ER-Bridge에서의 활용 방법”은 현재 클래스·함수의 입력, 출력, 호출 위치를 유지하거나 확장할 수 있는 지점을 제시한다.
- 현재 코드에는 독립적인 `Hospital`, `Base`, `DemandPoint` 모델 클래스가 없다. `HospitalSet`, `BaseSet`, `DemandSet`은 모두 `LocationSet`을 상속하고 내부에 `geopy.Point`를 저장한다.
- `sim.run()`의 반환값은 DataFrame이 아니라 `CaseRecordSet`이다. 결과 DataFrame은 `CaseRecordSet.write_to_file()` 및 `MetricAggregator.write_to_file()` 안에서 CSV 저장 직전에만 만들어진다.

## 1. 전체 실행 흐름

### 1.1 Driver 생성과 YAML 로딩

- **파일 경로:** `/home/juhyeon/projects/EMS-Simulator-Demos/Minimal Example.py`, `/home/juhyeon/projects/EMS-Simulator-Demos/Simple Example.py`, `/home/juhyeon/projects/EMS-Simulator/ems/run.py`
- **클래스 또는 함수명:** `Driver.__init__()`
- **현재 동작:** 데모는 각각 `Driver('examples/minimal.yaml')`, `Driver('examples/simple.yaml')`을 호출한다. `Driver.__init__()`은 파일을 UTF-8로 열고 `yaml.safe_load()`한 딕셔너리를 `kwargs`에 합쳐 `self.params`에 저장한다.
- **ER-Bridge에서의 활용 방법:** ER-Bridge 데이터셋, 정책, 시뮬레이터 클래스를 YAML의 완전한 클래스 경로로 선언하는 구성 진입점으로 재사용할 수 있다.
- **수정 위험도:** 낮음. YAML에 새 객체를 추가하는 것은 기존 로더가 지원하지만, 로더 자체 변경은 모든 구성 생성에 영향을 준다.
- **테스트해야 할 항목:** 빈 YAML, 잘못된 클래스 경로, 생성자 인자 누락, 객체 참조 순서, 날짜·숫자 타입의 YAML 역직렬화.

### 1.2 YAML 객체 그래프 생성

- **파일 경로:** `/home/juhyeon/projects/EMS-Simulator/ems/run.py`
- **클래스 또는 함수명:** `Driver.create_simulator()`, `Driver._create_objects()`, `Driver._create_recurse()`
- **현재 동작:** 최상위 YAML 항목을 기재 순서대로 순회한다. `class` 값을 모듈 경로와 클래스명으로 나눈 뒤 `importlib.import_module()`과 `getattr()`로 클래스를 찾고 `c(**params)`로 생성한다. `$name` 문자열은 이미 생성된 최상위 객체 `objects[name]`으로 치환된다. `create_simulator()`는 생성 결과에서 `simulator`를 `pop()`하여 `(sim, data)`로 반환한다.
- **ER-Bridge에서의 활용 방법:** 병원 자원 집합, 수용 정책, 광역 이송 정책, ER-Bridge 메트릭을 앞에서 정의하고 `$` 참조로 시뮬레이터나 정책에 주입할 수 있다.
- **수정 위험도:** 중간. 참조는 앞서 생성된 객체만 가리킬 수 있고, `class` 없는 일반 딕셔너리도 클래스 생성 경로로 들어가 `cpath/cname=None` 문제가 생긴다. 순환 참조도 지원하지 않는다.
- **테스트해야 할 항목:** 전방 참조 실패, 중첩 목록 객체 생성, 일반 딕셔너리 인자, 같은 키 덮어쓰기, ER-Bridge 패키지 import 가능 여부.

### 1.3 Simulator 생성과 실행

- **파일 경로:** `/home/juhyeon/projects/EMS-Simulator/ems/simulators/simulator.py`, `/home/juhyeon/projects/EMS-Simulator-Demos/examples/minimal.yaml`, `/home/juhyeon/projects/EMS-Simulator-Demos/examples/simple.yaml`
- **클래스 또는 함수명:** `EventDispatcherSimulator.__init__()`, `EventDispatcherSimulator.run()`
- **현재 동작:** YAML은 `ambulances`, `cases`, `ambulance_selector`, 선택적으로 `metric_aggregator`, `debug`를 생성자에 주입한다. 생성자는 빈 `CaseRecordSet`을 만든다. `run()` 시작 시 모든 구급차의 `location`을 `base`로 재설정하고 case iterator의 첫 case를 가져온다.
- **ER-Bridge에서의 활용 방법:** 기존 이벤트 디스패치 순서를 유지하는 ER-Bridge 전용 simulator subclass 또는 동일 인터페이스의 새 simulator를 YAML에서 선택할 수 있다.
- **수정 위험도:** 높음. 단일 루프가 case 도착, pending, 진행 이벤트, 구급차 상태, 메트릭, 기록 완료를 모두 담당한다.
- **테스트해야 할 항목:** case 0건, 첫 case 취득, 동일 timestamp 충돌, simulator 재실행 시 상태 초기화, metric 유무에 따른 반환·저장.

### 1.4 Case 발생

- **파일 경로:** `/home/juhyeon/projects/EMS-Simulator/ems/datasets/case.py`, `/home/juhyeon/projects/EMS-Simulator/ems/models/case.py`
- **클래스 또는 함수명:** `CSVCaseSet.iterator()`, `RandomCaseSet.iterator()`, `RandomCase`
- **현재 동작:** Minimal은 `RandomCaseSet`이 이전 case 시각에 `case_time_generator`의 duration을 더하고 위치와 priority를 생성한다. Simple은 `CSVCaseSet`이 CSV를 읽어 `RandomCase` 목록을 만들고 `date_recorded`순으로 정렬한다. simulator는 `next_case.date_recorded`와 가장 이른 진행 이벤트 종료 시각을 비교한다.
- **ER-Bridge에서의 활용 방법:** 중증도·필수 진료과·골든타임을 가진 ER-Bridge case subclass와 대응 CaseSet을 만들어 동일 iterator 계약을 사용할 수 있다.
- **수정 위험도:** 중간. simulator와 선택 정책은 `Case`의 `date_recorded`, `incident_location`, `priority`, `iterator()`를 직접 사용한다.
- **테스트해야 할 항목:** CSV 정렬, timestamp 파싱 형식, 무한/유한 random iterator, 중증도별 생성 분포, 필수 진료과 누락, 골든타임 기준 시각.

### 1.5 구급차 선택

- **파일 경로:** `/home/juhyeon/projects/EMS-Simulator/ems/simulators/simulator.py`, `/home/juhyeon/projects/EMS-Simulator/ems/algorithms/ambulance.py`
- **클래스 또는 함수명:** `EventDispatcherSimulator.process_new_case()`, `EventDispatcherSimulator.select_ambulance()`, `AmbulanceSelector.select_ambulance()`
- **현재 동작:** `deployed == False`인 구급차만 다시 필터링해 선택 정책에 `(available_ambulances, case, time)`을 전달한다. 반환된 단일 `Ambulance`의 `deployed`를 즉시 `True`로 바꾼다.
- **ER-Bridge에서의 활용 방법:** 중증도, 구급차 capability, 예상 현장 도착시간을 함께 평가하는 `AmbulanceSelector` subclass를 주입할 수 있다.
- **수정 위험도:** 중간. 선택 정책 추가는 낮은 위험이지만 반환값이 단일 구급차라는 계약과 `deployed` 이진 상태는 다중 자원·취소·재배정에 제약이 된다.
- **테스트해야 할 항목:** 빈 후보 목록, capability 불일치, 동률, 재현 가능한 선택, 선택 직후 deployed 전환, pending case 배정.

### 1.6 현장 이동부터 병원 이송까지

- **파일 경로:** `/home/juhyeon/projects/EMS-Simulator/ems/models/case.py`, `/home/juhyeon/projects/EMS-Simulator/ems/generators/event.py`
- **클래스 또는 함수명:** `RandomCase.iterator()`, `EventGenerator.generate()`
- **현재 동작:** 한 case는 고정 순서 `TO_INCIDENT → AT_INCIDENT → TO_HOSPITAL → AT_HOSPITAL → TO_BASE`의 5개 이벤트를 lazy 생성한다. `TO_INCIDENT` 목적지는 사건 위치, `TO_HOSPITAL` 목적지는 병원 선택 결과, `TO_BASE` 목적지는 구급차 base다. `TO_HOSPITAL`에서 정한 `hospital_location`을 `AT_HOSPITAL`에서 재사용한다.
- **ER-Bridge에서의 활용 방법:** 병원 탐색·거절·재탐색·광역 이송을 별도 이벤트 타입과 상태 전이로 표현하려면 이 고정 iterator 또는 이를 대체하는 ER-Bridge case workflow가 핵심 확장점이다.
- **수정 위험도:** 높음. 고정 이벤트 순서와 한 번만 선택되는 병원 위치가 기록 컬럼 및 simulator 완료 처리와 결합돼 있다.
- **테스트해야 할 항목:** 각 이벤트 순서, timestamp 누적, 이벤트별 목적지, 병원 선택 호출 횟수, 병원 거절 시 추가 이벤트, 최종 기지 복귀.

### 1.7 이벤트 완료와 결과 기록

- **파일 경로:** `/home/juhyeon/projects/EMS-Simulator/ems/simulators/simulator.py`, `/home/juhyeon/projects/EMS-Simulator/ems/analysis/record.py`
- **클래스 또는 함수명:** `process_ongoing_case()`, `CaseRecordSet.add_case_record()`, `CaseRecordSet.write_to_file()`
- **현재 동작:** 이벤트 종료 시 구급차 `location`을 이벤트 목적지로 바꾸고 다음 이벤트를 생성한다. 마지막 이벤트 뒤 `deployed=False`로 바꾸며 완성된 `CaseRecord`를 case 시간순으로 삽입한다. CSV 저장 시 case와 이벤트 이력을 행 딕셔너리로 평탄화한다.
- **ER-Bridge에서의 활용 방법:** 병원 후보 평가, 수용/거절, 지역·광역 구분, 골든타임 충족 여부를 별도 결정 기록 및 결과 serializer에 추가해야 한다.
- **수정 위험도:** 높음. 현재 record serializer는 이벤트 타입별 duration 하나와 병원 좌표 하나만 저장한다.
- **테스트해야 할 항목:** 이벤트 history 중복 여부, 완료 순서와 기록 정렬, 병원 좌표 기록, 추가 이벤트의 직렬화, 중단·미배정 case 기록 정책.

## 2. 핵심 객체

| 객체 | 파일 경로 / 클래스 | 현재 동작과 주요 속성 | ER-Bridge에서의 활용 방법 | 위험도 | 테스트해야 할 항목 |
|---|---|---|---|---|---|
| Case | `ems/models/case.py` / `Case`, `RandomCase`, `DefinedCase` | `id`, `date_recorded`, `incident_location`, `priority`; `RandomCase`는 `event_generator`를 보유하고 5개 이벤트를 생성 | ER case subclass에 중증도, 필수 진료과, 골든타임 필드를 추가하고 기존 공통 속성 유지 | 중간 | 생성/CSV 파싱, 비교·정렬, 필드 유효성, iterator 계약 |
| Ambulance | `ems/models/ambulance.py` / `Ambulance` | `id`, `base`, `capability`, `deployed`, `location`; capability는 `BASIC/ADVANCED` | 기존 capability와 위치를 dispatch 제약에 사용하고 필요 시 ER 자원 속성 확장 | 중간 | 상태 전환, 위치 이동, capability 필터, ID 동등성/해시 |
| Base | `ems/datasets/base.py` / `BaseSet`, `FilteredBaseSet` | 별도 Base 객체 없이 `LocationSet.locations`의 `Point`; CSV는 latitude/longitude만 읽음 | 기지 좌표가 목적이면 재사용; 기지별 속성이 필요하면 별도 모델/레지스트리 필요 | 중간 | CSV 좌표, KDTree 최근접점, 구급차 base 참조 동일성 |
| Hospital | `ems/datasets/hospital.py` / `HospitalSet` | 별도 Hospital 객체 없이 `Point` 목록; latitude/longitude만 읽음 | 병상·진료과·의료진·혼잡도를 표현할 ER Hospital 모델과 저장소가 필요 | 높음 | 고유 ID, 좌표 매핑, 동적 자원, 수용/해제, 동시 요청 |
| Demand point | `ems/datasets/demand.py` / `DemandSet` | `Point` 목록이며 이동시간 행렬 destination 및 coverage 계산에 사용 | 지역 수요 지점과 권역 태그를 별도 매핑하여 수요/격차 지표에 사용 가능 | 낮음 | CSV 좌표, nearest mapping, 권역 경계 매핑, 중복 좌표 |
| Duration/Time generator | `ems/generators/duration.py` / `DurationGenerator` 계열, `ems/datasets/times.py` / `TravelTimes` | duration generator는 `{'duration': timedelta, ...}` 반환; `TravelTimes`는 좌표 집합과 초 단위 행렬 조회 | 현장·병원·광역 이송 구간별 travel-time provider를 교체하거나 확장 | 중간 | 단위, 방향성, 행렬 shape, 좌표 snapping, 시간대별 값 |
| Selection policy | `ems/algorithms/ambulance.py`, `ems/algorithms/hospital.py` / selector 계열 | 구급차 정책은 단일 Ambulance, 병원 정책은 단일 Point 반환 | ER 구급차 정책과 병원 후보 ranking/수용 정책의 인터페이스 출발점 | 중간~높음 | 후보 필터, 동률, 불가 후보, 정책별 deterministic 비교 |

## 3. 주요 속성과 상태 변화 시점

### 3.1 Case와 CaseState

- **파일 경로:** `ems/models/case.py`, `ems/simulators/simulator.py`
- **클래스 또는 함수명:** `Case`, `RandomCase.iterator()`, `CaseState`
- **현재 동작:** Case의 핵심 값은 생성 시 정해진다. `OptimalTravelTimeWithCoverage.select_ambulance()`만 priority가 falsy이면 `3`으로 직접 변경한다. 실행 중 상태는 별도 `CaseState`의 `assigned_ambulance`, `event_iterator`, `next_event_time`, `next_event`, `case_record`에 저장된다. 다음 이벤트마다 `next_event_time/next_event`가 갱신된다.
- **ER-Bridge에서의 활용 방법:** 환자 임상 속성은 Case, 실행 단계·후보 병원·거절 이력·남은 골든타임은 CaseState 또는 ER 전용 state에 두는 구분이 현재 구조에 맞다.
- **수정 위험도:** 높음. `CaseState`는 simulator 내부 클래스이고 외부 정책에 전달되지 않는다.
- **테스트해야 할 항목:** 불변 입력과 실행 상태 분리, priority 0/None 처리, 거절 이력 보존, 다음 이벤트 시간 정렬.

### 3.2 Ambulance

- **파일 경로:** `ems/models/ambulance.py`, `ems/simulators/simulator.py`
- **클래스 또는 함수명:** `Ambulance`, `run()`, `process_new_case()`, `process_ongoing_case()`
- **현재 동작:** `run()` 시작 때 `location=base`; 배정 순간 `deployed=True`; 이벤트 완료마다 `location=destination`; 마지막 이벤트 완료 때 `deployed=False`. 병원 도착 후에도 `AT_HOSPITAL`, `TO_BASE`가 끝날 때까지 배치 상태다.
- **ER-Bridge에서의 활용 방법:** 광역 이송 동안 장시간 점유와 현재 위치는 그대로 표현 가능하다. 단계별 상태가 필요하면 이진 `deployed` 외 상태 모델이 필요하다.
- **수정 위험도:** 중간.
- **테스트해야 할 항목:** 전체 이벤트 동안 점유 유지, 복귀 완료 후 해제, 병원 거절 중 위치, simulator 재실행 초기화.

### 3.3 Base/Hospital/Demand point

- **파일 경로:** `ems/datasets/location.py`, `base.py`, `hospital.py`, `demand.py`
- **클래스 또는 함수명:** `LocationSet`, `BaseSet`, `HospitalSet`, `DemandSet`
- **현재 동작:** 생성 시 `Point` 목록과 정적 KDTree를 만든다. 실행 중 집합 상태 변화는 없다.
- **ER-Bridge에서의 활용 방법:** 좌표 nearest-neighbor 색인으로는 재사용할 수 있으나 병원 가용 자원은 KDTree의 정적 Point와 분리해 관리해야 한다.
- **수정 위험도:** 중간.
- **테스트해야 할 항목:** Point와 도메인 병원 ID 매핑, 좌표 중복, 동적 자원 변경이 KDTree에 영향을 주지 않는지.

### 3.4 Event와 기록

- **파일 경로:** `ems/models/event.py`, `ems/analysis/record.py`
- **클래스 또는 함수명:** `Event`, `EventType`, `CaseRecord`
- **현재 동작:** Event는 `destination`, `event_type`, `duration`, `error`, `sim_dest`; CaseRecord는 `case`, `ambulance`, `event_history`, `start_time`을 가진다. 이벤트는 시작 시 한 번, 종료 처리 시 다시 history에 append되어 첫 이벤트가 중복 기록된다. CSV는 같은 event type key를 나중 값으로 덮어쓴다.
- **ER-Bridge에서의 활용 방법:** decision event나 별도 decision record를 추가할 때 중복 append 동작과 단일 key 평탄화 문제를 먼저 정의해야 한다.
- **수정 위험도:** 높음.
- **테스트해야 할 항목:** 첫 이벤트 중복, 동일 타입 반복 이벤트 보존, 수용/거절 메타데이터, duration 합계.

## 4. 구급차 선택 알고리즘 위치와 계약

| 파일 경로 / 클래스·함수 | 입력 | 출력 | 현재 동작 | ER-Bridge 활용 | 위험도 | 테스트해야 할 항목 |
|---|---|---|---|---|---|---|
| `ems/simulators/simulator.py` / `EventDispatcherSimulator.select_ambulance()` | 전체 ambulances, `Case`, datetime | `Ambulance` | 미배치 구급차만 거르고 주입된 selector 호출 | 공통 dispatch 진입점 | 중간 | available 필터, selector 반환 검증 |
| `ems/algorithms/ambulance.py` / `AmbulanceSelector.select_ambulance()` | `List[Ambulance]`, `Case`, datetime | 구현 계약상 단일 `Ambulance` | 추상 인터페이스 | ER selector의 기본 계약 | 낮음 | subclass 계약 |
| 같은 파일 / `RandomSelector.select_ambulance()` | 동일 | 무작위 `Ambulance` | `random.sample(..., 1)[0]` | 기준선 정책 | 낮음 | seed 재현, 단일 후보, 빈 후보 |
| 같은 파일 / `BestTravelTime.select_ambulance()`, `find_fastest_ambulance()` | 후보, Case, 시간; 내부 closest demand | 최소 travel-time Ambulance | 현재 위치와 사건을 travel matrix origin/destination에 snap해 최소값 선택 | ETA 기준 dispatch 기준선 | 중간 | snap, 동률, 행렬 방향, 후보 없음 |
| 같은 파일 / `LeastDisruption.select_ambulance()` | 후보, Case, 시간 | coverage 감소가 가장 작은 Ambulance | 각 구급차를 제외한 조합의 이중 coverage 비교 | 지역 격차/coverage 보존 정책 기준선 | 중간 | 1대 후보, coverage cache, 동률 |
| 같은 파일 / `OptimalTravelTimeWithCoverage.select_ambulance()` | 후보, Case(priority), 시간 | 가중 점수 최대 Ambulance | travel time score와 coverage score를 priority로 가중 | 중증도별 도착시간-지역 coverage trade-off 비교 기반 | 높음 | priority 1~4/None, 0 travel time, 0 coverage, 수식 타입 |

## 5. 병원 선택 알고리즘 위치와 계약

| 파일 경로 / 클래스·함수 | 입력 | 출력 | 현재 동작 | ER-Bridge 활용 | 위험도 | 테스트해야 할 항목 |
|---|---|---|---|---|---|---|
| `ems/generators/event.py` / `EventGenerator.generate()` | ambulance, incident location, timestamp, event type, 이전 hospital location | `Event` | `TO_HOSPITAL` 생성 시 selector를 호출하고 이후 같은 Point 재사용 | 병원 결정 호출 지점; 현재는 Case가 selector에 전달되지 않음 | 높음 | 호출 시 ambulance 위치가 현장인지, timestamp, 재호출 여부 |
| `ems/algorithms/hospital.py` / `HospitalSelector.select()` | timestamp, Ambulance | 구현 계약상 병원 위치 `Point` | 추상 인터페이스 | 단순 위치 선택 정책의 기반 | 중간 | 반환 Point가 집합 소속인지 |
| 같은 파일 / `RandomHospitalSelector.select()` | timestamp, Ambulance | 무작위 Point | `random.choice(hospital_set.locations)` | 기준선 정책 | 낮음 | seed, 빈 병원 집합 |
| 같은 파일 / `FastestHospitalSelector.select()`, `find_fastest_hospital()` | timestamp, Ambulance; 내부 snapped location | 최소 이동시간 Point | ambulance 현재 위치를 origin에 snap하고 각 병원을 destination에 snap하여 최소 행렬 시간 선택 | 거리/시간 기준 병원 정책 기준선 | 중간 | 동률, 병원 없음, snap 오차, 방향성 |

현재 병원 선택 계약에는 `Case`, 중증도, 필수 진료과, 병상, 의료진, 혼잡도, 거절 사유가 전달되거나 반환되지 않는다.

## 6. 이동시간 계산 또는 조회 방식

### 6.1 Minimal Example

- **파일 경로:** `examples/minimal.yaml`, `ems/generators/duration.py`
- **클래스 또는 함수명:** `RandomDurationGenerator.generate()`
- **현재 동작:** 이동·현장·병원 체류 모두 같은 10~20분 균등 정수 초 generator를 사용한다. 분 경계를 초로 변환해 `randint(ceil(lower), floor(upper))`로 생성한다.
- **ER-Bridge에서의 활용 방법:** 기능 검증용 확률적 기준선으로만 사용할 수 있다.
- **수정 위험도:** 낮음.
- **테스트해야 할 항목:** 초 경계, seed, 구간 없음, 각 이벤트에 동일 generator가 연결되는지.

### 6.2 Simple Example

- **파일 경로:** `examples/simple.yaml`, `ems/datasets/times.py`, `ems/generators/duration.py`
- **클래스 또는 함수명:** `TravelTimes.get_time()`, `TravelTimeDurationGenerator.generate()`
- **현재 동작:** 600×600 CSV 행렬의 값은 초 단위 정수로 변환된다. 실제 양 끝 좌표를 각각 `origins`와 `destinations`의 최근접점으로 snap하고 행렬 시간을 조회한다. generator는 실제 geodesic 거리와 snapped 점 거리의 차이를 `error`로 함께 반환한다.
- **ER-Bridge에서의 활용 방법:** 권역 내/광역 경로 행렬을 origin/destination 세트별로 제공하거나 시간대별 provider로 대체할 수 있다.
- **수정 위험도:** 중간. `get_time()`은 정확히 집합에 포함된 snapped Point만 허용하고 행렬 방향이 고정돼 있다.
- **테스트해야 할 항목:** 행렬 크기, 초 단위, 양방향 비대칭, 병원 좌표가 demand destination에 snap되는 방식, 권역 외 좌표.

### 6.3 거리 기반 방식

- **파일 경로:** `ems/generators/duration.py`
- **클래스 또는 함수명:** `DistanceDurationGenerator.generate()`
- **현재 동작:** geodesic `distance_km / velocity`를 그대로 초로 해석해 정수 절삭한다. 코드에는 velocity 단위 변환이 없다.
- **ER-Bridge에서의 활용 방법:** 단위를 명시·검증하지 않은 채 광역 이송 ETA에 사용하면 안 되며, 계약을 확정한 별도 provider가 안전하다.
- **수정 위험도:** 중간.
- **테스트해야 할 항목:** velocity 단위, 0/음수, 장거리, 초 변환.

## 7. Pending case와 Ambulance 상태 관리

- **파일 경로:** `ems/simulators/simulator.py`
- **클래스 또는 함수명:** `EventDispatcherSimulator.run()`, `process_new_case()`, `process_ongoing_case()`
- **현재 동작:** `pending_cases`는 지역 리스트이며 구급차가 없을 때 도착 case를 append하고, 구급차가 생기면 `pop(0)`하여 FIFO 처리한다. pending이 있고 가용 구급차가 있으면 새 case 도착보다 우선 처리한다. `ongoing_case_states`는 `next_event_time` 기준으로 `bisect` 정렬한다. Ambulance 가용성은 `not deployed` 하나로 판정한다.
- **ER-Bridge에서의 활용 방법:** 골든타임/중증도 우선 pending queue, 병원 수용 대기 queue, 재탐색 상태를 구현하려면 queue 선정 규칙과 state를 명시적으로 확장해야 한다.
- **수정 위험도:** 높음. 두 리스트와 이벤트 시간 비교 분기가 simulator의 핵심 스케줄러다.
- **테스트해야 할 항목:** FIFO, 동일 시각 case/event 우선순위, 중증도 우선순위, 장기 pending delay, 구급차 해제 즉시 재배정, starvation, 빈 iterator.

Metric 전달값은 매 루프의 `ambulances`, ongoing Case 목록, `pending_cases`다. `CountPending`은 길이, `TotalDelay`는 각 pending case에 대해 `timestamp - date_recorded` 합계를 계산한다.

## 8. 결과 DataFrame 컬럼과 의미

### 8.1 Case 결과

- **파일 경로:** `ems/analysis/record.py`
- **클래스 또는 함수명:** `CaseRecordSet.write_to_file()`
- **현재 동작:** 아래 컬럼으로 DataFrame을 만든 뒤 CSV로 쓴다. DataFrame 자체는 반환하거나 객체에 보관하지 않는다.
- **ER-Bridge에서의 활용 방법:** 기존 컬럼을 공통 성능 비교 스키마로 유지하면서 병원 결정·거절·골든타임·권역 이송 컬럼 또는 별도 정규화된 decision/event 테이블을 추가할 수 있다.
- **수정 위험도:** 높음. 반복 이벤트를 단일 wide row에 안전하게 담지 못한다.
- **테스트해야 할 항목:** 컬럼 순서·타입, timedelta CSV 표현, null, 반복 이벤트, 미완료 case.

| 컬럼 | 현재 의미 |
|---|---|
| `id` | Case ID |
| `date` | 신고/기록 시각 `case.date_recorded` |
| `latitude`, `longitude` | 사건 위치 |
| `priority` | Case priority; Simple 입력에서는 비어 있음 |
| `ambulance` | 배정 구급차 ID |
| `start_time` | 실제 구급차 배정 처리 시각; pending이면 `date`보다 늦음 |
| `TO_INCIDENT_duration` | 현장 이동 이벤트 duration |
| `AT_INCIDENT_duration` | 현장 처치 이벤트 duration |
| `TO_HOSPITAL_duration` | 병원 이동 이벤트 duration |
| `AT_HOSPITAL_duration` | 병원 인계 이벤트 duration |
| `TO_BASE_duration` | 기지 복귀 이벤트 duration |
| `OTHER_duration` | OTHER 이벤트 duration 합계를 의도한 컬럼. 현재 비교문이 `event == EventType.OTHER`여서 Event 객체와 enum을 비교하며, 실제 OTHER 누적은 동작하지 않는다. |
| `hospital_latitude`, `hospital_longitude` | `TO_HOSPITAL` 이벤트 목적지 좌표 |

### 8.2 Metric 결과

- **파일 경로:** `ems/analysis/metric.py`
- **클래스 또는 함수명:** `MetricAggregator.calculate()`, `write_to_file()`
- **현재 동작:** 매 simulator 루프 뒤 `results`에 딕셔너리를 append한다. Simple은 `timestamp`, `total_delay`, `count_pending` 컬럼을 저장한다.
- **ER-Bridge에서의 활용 방법:** 골든타임 준수율, 수용률, 거절 횟수, 광역 이송률, 병원 부하 분산 지표를 `Metric` subclass로 추가할 수 있다. 단, 현재 metric kwargs에는 병원 상태와 결정 이력이 없다.
- **수정 위험도:** 중간.
- **테스트해야 할 항목:** tag 중복, 리스트 tag, event마다 계산되는 시점, 정책 간 동일 입력 비교, 병원 상태 전달.

## 9. 새 정책을 추가할 수 있는 확장 지점

| 파일 경로 / 클래스·함수 | 현재 동작 | ER-Bridge 활용 방법 | 위험도 | 테스트해야 할 항목 |
|---|---|---|---|---|
| `ems/algorithms/ambulance.py` / `AmbulanceSelector` | 가용 구급차·Case·시각을 받아 한 대 반환 | ER dispatch selector subclass | 낮음 | 후보 제약, 동률, deterministic 결과 |
| `ems/algorithms/hospital.py` / `HospitalSelector` | 시각·Ambulance를 받아 Point 반환 | 단순 hospital ranking 기준선; Case와 자원 상태가 필요하면 새 계약 필요 | 중간 | 환자 조건 전달, 불가 결과 |
| `ems/analysis/metric.py` / `Metric` | timestamp와 kwargs로 값 계산 | 정책 KPI subclass | 낮음 | tag/schema, 계산 시점 |
| `ems/generators/duration.py` / `DurationGenerator` | 이동/처치 duration 딕셔너리 반환 | 시간대·권역·교통 조건 provider | 낮음~중간 | 단위, 입력 좌표, fallback |
| `ems/datasets/case.py` / `CaseSet` | 시간순 Case iterator | 동일 사건군을 정책별 재생하는 ER CaseSet | 중간 | 동일 입력 재현, 정렬 |
| `ems/models/case.py` / `RandomCase.iterator()` | 고정 5단계 이벤트 | 수용/거절/재탐색을 포함하는 workflow | 높음 | 상태 전이 전체 |
| `ems/simulators/simulator.py` / `EventDispatcherSimulator` | 단일 이벤트 루프와 자원 상태 관리 | 병원 동적 상태와 다단계 결정을 처리하는 ER simulator subclass | 높음 | 동시성, queue, 자원 원자성 |
| `ems/run.py` / `Driver` | 클래스 경로 기반 DI | `er_bridge.*` 객체를 YAML에서 조립 | 낮음 | import와 참조 순서 |

## 10. ER-Bridge 기능별 적절한 구현 위치

아래 위치는 현재 호출 계약과 상태 소유 위치를 기준으로 한 확장 배치다.

| 기능 | 파일 경로 / 클래스 또는 함수명 | 현재 동작 | ER-Bridge에서의 활용 방법 | 위험도 | 테스트해야 할 항목 |
|---|---|---|---|---|---|
| 환자 중증도 | `ems/models/case.py` / `Case`; `ems/generators/priority.py` | `priority` 숫자만 보유/생성 | `er_bridge.models.case.ERCase`에 명시적 severity를 두고 필요하면 기존 priority mapping 유지 | 중간 | 등급 유효성, CSV/YAML 생성, dispatch 반영 |
| 필요한 필수 진료과 | `ems/models/case.py` / `Case` | 해당 속성 없음 | ERCase에 required_specialty 또는 복수 요구사항 저장 | 중간 | 단일/복수 과, 누락, 병원 capability 매칭 |
| 골든타임 | `Case.date_recorded`, `CaseState.next_event_time` | 신고 시각과 이벤트 시각은 있으나 deadline 없음 | ERCase에 deadline/허용 duration, ER state/metric에서 남은 시간과 준수 여부 계산 | 중간 | 경계 시각, pending 포함, 병원 도착/처치 중 어느 시점을 성공으로 볼지 계약 |
| 병원별 응급병상 | `ems/datasets/hospital.py` / `HospitalSet` | Point만 저장 | `er_bridge.models.hospital.Hospital`과 자원 상태 저장소에 capacity/occupied/reserved 관리 | 높음 | 예약·점유·해제, 동시 도착, 0 capacity |
| 병원별 진료과 가용 여부 | 동일 | 속성 없음 | Hospital capability에 specialty별 availability 저장 | 중간 | 시간대별 변경, 복수 과, 비가용 필터 |
| 의료진 가용 여부 | 동일 | 속성 없음 | 병원 동적 resource state로 인력 수/가용 여부 관리 | 높음 | 교대/점유/해제, 병상과 결합 조건 |
| 병원 혼잡도 | `ems/analysis/metric.py`; 병원 모델 부재 | 병원 상태 metric 없음 | 병원 상태에서 queue/occupied/capacity를 계산하고 selector score 및 metric에 제공 | 중간 | 0 capacity, 갱신 시점, 정책 점수 일관성 |
| 병원 수용 또는 거절 | `ems/generators/event.py` / `EventGenerator.generate()` | 병원을 무조건 하나 선택하며 수용 판정 없음 | hospital acceptance policy와 decision 결과 객체를 추가하고 event workflow가 판정 결과를 소비 | 높음 | 수용 원자성, 거절 사유, 자원 예약 rollback |
| 거절 후 재탐색 | `ems/models/case.py` / `RandomCase.iterator()` | 병원을 한 번 선택하고 같은 위치 재사용 | ER workflow/CaseState에 후보 목록과 거절 이력을 유지하며 다음 후보 탐색 이벤트 생성 | 높음 | 중복 후보 방지, 후보 소진, 탐색 시간, 기록 |
| 지역 실패 후 광역 이송 | `HospitalSelector`, `TravelTimes`, case workflow | 권역 개념과 fallback 없음 | 병원에 region을 부여하고 local 후보 소진 뒤 inter-region provider/정책으로 전환 | 높음 | 지역 경계, 행렬 범위, fallback 조건, 장거리 ETA |
| 병원 부하 분산 | `ems/algorithms/hospital.py` / selector 계열 | random 또는 최소 travel time만 사용 | travel time, resource availability, congestion을 함께 점수화하는 ER hospital allocation policy | 중간 | 부하 동률, capacity 보호, 분산 KPI, 최단시간 기준선 비교 |
| 정책별 성능 비교 | `Driver`, `MetricAggregator`, `CaseRecordSet`; Demos YAML | YAML로 정책 주입 가능하지만 seed/runner 비교 도구 없음 | 동일 고정 case/seed와 서로 다른 selector YAML을 반복 실행하고 공통 metric schema로 수집 | 중간 | 동일 입력, random seed, 실행 간 상태 초기화, 결과 schema |

## 11. 직접 포크 확장과 별도 `er_bridge` 패키지 비교

### 11.1 EMS-Simulator 직접 포크

- **파일 경로:** 기존 `ems/models`, `ems/datasets`, `ems/generators`, `ems/algorithms`, `ems/simulators`, `ems/analysis`
- **클래스 또는 함수명:** 특히 `RandomCase.iterator()`, `EventGenerator.generate()`, `EventDispatcherSimulator.run()` 및 `CaseRecordSet.write_to_file()`
- **현재 동작:** 핵심 클래스가 구체 타입과 고정 이벤트 순서를 직접 참조한다. 병원은 Point이고 simulator가 CaseState와 queue를 내부 소유한다.
- **ER-Bridge에서의 활용 방법:** 기존 클래스를 직접 변경하면 병원 모델, 이벤트 타입, simulator 상태, 결과 schema를 한 코드베이스에서 일괄 변경할 수 있다.
- **수정 위험도:** 높음. 이미 정상 동작하는 Minimal/Simple 흐름과 기존 YAML/CSV 계약을 동시에 회귀시킬 수 있다.
- **테스트해야 할 항목:** 기존 100/500 case 회귀, 기존 YAML 호환, CSV 컬럼 호환, 모든 selector, 신규 ER 흐름.

### 11.2 별도 `er_bridge` 패키지 연결

- **파일 경로:** 새 `er_bridge` 패키지와 기존 `ems/run.py`의 동적 import 경계
- **클래스 또는 함수명:** `Driver._create_recurse()`, `AmbulanceSelector`, `DurationGenerator`, `Metric`, 필요 시 `EventDispatcherSimulator` subclass
- **현재 동작:** Driver는 설치/import 가능한 임의 클래스 경로를 YAML에서 생성하며 특정 `ems.*` prefix를 강제하지 않는다.
- **ER-Bridge에서의 활용 방법:** `er_bridge.models`, `datasets`, `policies`, `simulation`, `analysis`에 새 타입을 두고 YAML에서 `er_bridge...` 경로를 참조한다. 낮은 결합 확장은 기존 selector/generator/metric 인터페이스를 구현하고, 병원 수용·재탐색처럼 계약이 부족한 부분은 ER 전용 simulator와 workflow로 대체한다.
- **수정 위험도:** 중간. 기존 소스 회귀 범위는 작지만, 기존 `EventGenerator`와 `HospitalSelector` 계약만으로는 Case 기반 수용 정책을 구현할 수 없어 adapter 또는 ER 전용 구현이 필요하다.
- **테스트해야 할 항목:** package import, YAML 객체 조립, 기존 Point/TravelTimes adapter, 기존 EMS 회귀, ER 전용 상태와 결과.

### 11.3 비교 결론

| 기준 | 직접 포크 | 별도 `er_bridge` 패키지 |
|---|---|---|
| 기존 데모 보존 | 핵심 파일 변경에 따라 회귀 범위 큼 | 기존 `ems` 파일을 유지하면 회귀 범위 작음 |
| 새 병원 도메인 모델 | 기존 `HospitalSet` 계약을 직접 바꿀 수 있음 | ER 모델과 기존 Point 집합 사이 adapter 필요 |
| 거절·재탐색 workflow | 기존 simulator/case를 직접 재작성 | ER 전용 simulator/case workflow로 격리 가능 |
| YAML 연결 | 기존 경로 그대로 사용 | Driver가 임의 import 경로를 지원하므로 직접 연결 가능 |
| 결과 호환 | 기존 writer 변경 시 기존 schema 영향 | ER writer/metric을 별도로 유지 가능 |
| 확인된 구조에 따른 적합성 | 기존 API 자체를 새 표준으로 바꿔야 할 때 적합 | 기존 100/500 case 기준선을 보존하면서 ER 기능을 병행할 때 적합 |

현재 코드 구조만 기준으로 하면 **별도 `er_bridge` 패키지 + ER 전용 case workflow/simulator + 기존 selector/generator adapter**가 기존 정상 동작을 보존하는 범위가 더 명확하다. 단순 selector subclass만으로는 병원 수용·거절·재탐색을 구현할 수 없다.

## 12. 결합도가 높거나 수정 위험이 큰 부분

| 파일 경로 / 클래스·함수 | 현재 동작과 결합 원인 | ER-Bridge에서의 활용 방법 | 위험도 | 테스트해야 할 항목 |
|---|---|---|---|---|
| `ems/simulators/simulator.py` / `EventDispatcherSimulator.run()` | case scheduling, pending FIFO, ambulance availability, event completion, metrics를 한 루프가 소유 | 기존 코드는 기준선으로 두고 ER scheduler를 분리 | 높음 | 전체 이벤트 순서, 동시 timestamp, queue, 자원 상태 |
| 같은 파일 / `CaseState` | simulator 내부에서만 정의되고 정책에 노출되지 않음 | ER 상태 객체에 병원 후보·거절·예약 추가 | 높음 | 상태 보존, 정렬 비교 |
| `ems/models/case.py` / `RandomCase.iterator()` | 5개 이벤트 순서와 단일 병원 결정이 하드코딩 | ER workflow로 대체 | 높음 | 분기·반복·종료 상태 |
| `ems/generators/event.py` / `EventGenerator.generate()` | 이벤트 타입별 목적지·duration·hospital selector 호출을 한 함수가 분기 | ER event factory/decision service로 분리 | 높음 | 환자 정보 전달, 수용 실패, duration 반환 계약 |
| `ems/analysis/record.py` / `CaseRecordSet.write_to_file()` | 이벤트 타입을 wide 컬럼 하나로 덮어쓰며 병원 좌표 하나만 기록 | ER decision/event long-form 결과 추가 | 높음 | 반복 거절/이송 기록, 기존 schema |
| `ems/datasets/hospital.py` / `HospitalSet` | 병원이 Point로 축약되어 ID와 상태가 없음 | Point index와 ER Hospital registry를 분리 | 높음 | ID-좌표 매핑, 동적 자원 |
| `ems/datasets/times.py` / `TravelTimes` | 고정 origin/destination와 정적 행렬, 정확한 snapped Point 요구 | 권역별/시간대별 provider adapter | 중간 | 방향성, 범위 밖 위치, 행렬 검증 |
| `ems/run.py` / `Driver._create_recurse()` | YAML 순서 의존 `$` 참조와 생성자 reflection | 구성 조립에 재사용하되 복잡한 일반 dict는 별도 config 객체로 캡슐화 | 중간 | 전방 참조, import error, 일반 dict |
| `ems/algorithms/hospital.py` / `HospitalSelector` | Case 없이 Ambulance와 timestamp만 입력, Point만 출력 | 기존 기준선 adapter 또는 새 ER 계약 | 높음 | 중증도/진료과 전달, no-match 결과 |
| `ems/algorithms/ambulance.py` / `OptimalTravelTimeWithCoverage` | selector가 `case.priority`를 직접 변경하고 coverage metric 내부 상태를 정책 계산에도 사용 | 비교 기준선으로 격리하고 ER 정책은 입력을 변경하지 않도록 구현 | 높음 | priority None, metric state 오염, 수식 0 나눗셈 |

## 13. 구현 전 권장 검증 기준선

- **파일 경로:** `EMS-Simulator-Demos/Minimal Example.py`, `Simple Example.py`, 두 YAML 및 결과 CSV
- **클래스 또는 함수명:** `Driver`, `EventDispatcherSimulator.run()`, `write_results()`
- **현재 동작:** Minimal은 100 case, Simple은 500 case를 완료하며 Simple은 case와 metric CSV를 쓴다.
- **ER-Bridge에서의 활용 방법:** ER 패키지 연결 전후에 기존 두 실행을 회귀 기준으로 유지하고, ER 정책 비교는 동일 case 입력과 명시적 random seed를 사용하는 별도 runner로 검증한다.
- **수정 위험도:** 낮음(기준선 자체), 중간(랜덤 결과의 값 단위 비교).
- **테스트해야 할 항목:** 완료 case 수, 예외 없음, 이벤트 5단계, 결과 컬럼, 이동시간 단위, pending metric, 정책별 입력 동일성.
