#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="$ROOT_DIR/.runtime"
SCENARIO_ARG="${1:-multi}"
MODE_ARG="${2:-}"

case "$SCENARIO_ARG" in
  normal) METRICS_SCENARIO="NORMAL_BURST" ;;
  single) METRICS_SCENARIO="FAILED_ISL_0_1_BURST" ;;
  multi) METRICS_SCENARIO="MULTI_FAILED_ISL_0_1_10_11_BURST" ;;
  *) echo "지원하지 않는 시나리오입니다: $SCENARIO_ARG (normal|single|multi)" >&2; exit 2 ;;
esac

if [[ -n "$MODE_ARG" && "$MODE_ARG" != "--docker" ]]; then
  echo "지원하지 않는 실행 옵션입니다: $MODE_ARG (--docker)" >&2
  exit 2
fi

fail() { echo "$*" >&2; exit 1; }
require_command() { command -v "$1" >/dev/null 2>&1 || fail "필수 명령을 찾을 수 없습니다: $1"; }
require_file() { [[ -f "$1" ]] || fail "필수 파일이 없습니다: ${1#"$ROOT_DIR/"}"; }
require_dir() { [[ -d "$1" ]] || fail "필수 디렉터리가 없습니다: ${1#"$ROOT_DIR/"}"; }

listener_details() {
  local port="$1"
  if command -v ss >/dev/null 2>&1; then
    ss -ltnp "sport = :$port" 2>/dev/null | tail -n +2
  elif command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"$port" -sTCP:LISTEN 2>/dev/null
  else
    return 2
  fi
}

check_free_port() {
  local port="$1" details
  details="$(listener_details "$port")" || {
    [[ $? -eq 2 ]] && fail "포트 점검을 위해 ss 또는 lsof가 필요합니다."
    details=""
  }
  if [[ -n "$details" ]]; then
    echo "포트 $port가 이미 사용 중입니다. 관련 프로세스를 자동 종료하지 않습니다." >&2
    echo "$details" >&2
    exit 1
  fi
}

start_background() {
  local name="$1" pid_file="$2" log_file="$3" working_dir="$4"
  shift 4
  [[ ! -e "$pid_file" ]] || fail "$name PID 파일이 이미 있습니다: $pid_file (status/stop 명령으로 확인하세요)."
  (
    cd "$working_dir"
    exec setsid "$@"
  ) >>"$log_file" 2>&1 &
  local pid=$!
  printf '%s\n' "$pid" > "$pid_file"
  sleep 1
  if ! kill -0 "$pid" 2>/dev/null; then
    echo "$name 시작에 실패했습니다. 로그: $log_file" >&2
    return 1
  fi
  echo "$name: 프로세스 시작됨 (PID $pid), HTTP 준비 상태를 확인합니다."
}

wait_for_url() {
  local name="$1" url="$2" log_path="$3" attempts="${4:-20}" attempt
  for ((attempt = 1; attempt <= attempts; attempt++)); do
    if curl --fail --silent --show-error --max-time 2 "$url" >/dev/null 2>&1; then
      echo "$name: HTTP 확인 완료 ($url)."
      return 0
    fi
    sleep 2
  done
  echo "$name: 제한 시간 내 응답하지 않았습니다 ($url)." >&2
  echo "관련 로그: $log_path" >&2
  return 1
}

require_command curl
require_command docker
require_file "$ROOT_DIR/docker-compose.yml"
for port in 5173 8000 9090 3000; do check_free_port "$port"; done

if [[ "$MODE_ARG" == "--docker" ]]; then
  echo "Docker Compose 모드로 전체 플랫폼을 시작합니다."
  SCENARIO="$METRICS_SCENARIO" docker compose --project-directory "$ROOT_DIR" -f "$ROOT_DIR/docker-compose.yml" up -d --build --wait --wait-timeout 120
  docker compose --project-directory "$ROOT_DIR" -f "$ROOT_DIR/docker-compose.yml" ps
  echo "Docker 서비스 URL: frontend=http://localhost:5173 backend=http://localhost:8000 prometheus=http://localhost:9090 grafana=http://localhost:3000"
  exit 0
fi

for command_name in npm setsid; do require_command "$command_name"; done
require_file "$ROOT_DIR/.venv/bin/python"
require_file "$ROOT_DIR/frontend/package.json"
require_file "$ROOT_DIR/monitoring/docker-compose.yml"
require_dir "$ROOT_DIR/satgenpy/demo_data"
mkdir -p "$RUNTIME_DIR"

start_background "메트릭 서버" "$RUNTIME_DIR/metrics_server.pid" "$RUNTIME_DIR/metrics_server.log" "$ROOT_DIR" \
  "$ROOT_DIR/.venv/bin/python" -m satgenpy.ai_datacenter.metrics_server --scenario "$METRICS_SCENARIO" --port 8000

echo "Prometheus/Grafana: 시작 중..."
(cd "$ROOT_DIR/monitoring" && docker compose up -d)

echo "프런트엔드 CSV 데이터를 복사합니다."
(cd "$ROOT_DIR/frontend" && npm run copy:data)
start_background "Cesium 프런트엔드" "$RUNTIME_DIR/frontend.pid" "$RUNTIME_DIR/frontend.log" "$ROOT_DIR/frontend" npm run dev

failures=0
wait_for_url "백엔드 liveness" "http://localhost:8000/health" "$RUNTIME_DIR/metrics_server.log" || failures=$((failures + 1))
wait_for_url "백엔드 readiness" "http://localhost:8000/ready" "$RUNTIME_DIR/metrics_server.log" || failures=$((failures + 1))
wait_for_url "Cesium 프런트엔드" "http://localhost:5173" "$RUNTIME_DIR/frontend.log" || failures=$((failures + 1))
wait_for_url "Prometheus" "http://localhost:9090/-/ready" "docker compose -f $ROOT_DIR/monitoring/docker-compose.yml logs prometheus" || failures=$((failures + 1))
wait_for_url "Grafana" "http://localhost:3000/api/health" "docker compose -f $ROOT_DIR/monitoring/docker-compose.yml logs grafana" || failures=$((failures + 1))

if ((failures > 0)); then
  echo "$failures개 필수 서비스가 준비되지 않았습니다. ./scripts/status_system.sh 로 확인하세요." >&2
  exit 1
fi

echo "모든 서비스가 준비되었습니다."
echo "Cesium 운영 콘솔: http://localhost:5173"
echo "Grafana 관제: http://localhost:3000"
echo "Prometheus 상태: http://localhost:9090/targets"
echo "백엔드 상태: http://localhost:8000/ready"
