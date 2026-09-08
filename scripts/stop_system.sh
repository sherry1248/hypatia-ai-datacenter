#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="$ROOT_DIR/.runtime"

if [[ "${1:-}" == "--docker" ]]; then
  command -v docker >/dev/null 2>&1 || { echo "docker 명령을 찾을 수 없습니다." >&2; exit 1; }
  docker compose --project-directory "$ROOT_DIR" -f "$ROOT_DIR/docker-compose.yml" down
  exit 0
elif [[ -n "${1:-}" ]]; then
  echo "지원하지 않는 옵션입니다: $1 (--docker)" >&2
  exit 2
fi

stop_managed_process() {
  local name="$1" pid_file="$2" expected_command="$3" expected_dir="$4"
  local pid command cwd pgid attempt
  [[ -f "$pid_file" ]] || { echo "$name: PID 파일이 없습니다."; return; }
  read -r pid < "$pid_file" || pid=""
  if [[ ! "$pid" =~ ^[0-9]+$ ]] || ! kill -0 "$pid" 2>/dev/null; then
    echo "$name: stale PID 파일을 건너뜁니다 (수동 확인 필요: $pid_file)."
    return
  fi
  command="$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)"
  cwd="$(readlink -f "/proc/$pid/cwd" 2>/dev/null || true)"
  pgid="$(ps -o pgid= -p "$pid" 2>/dev/null | tr -d ' ' || true)"
  if [[ "$command" != *"$expected_command"* || "$cwd" != "$expected_dir" || "$pgid" != "$pid" ]]; then
    echo "$name: PID 소유권이 일치하지 않아 신호를 보내거나 PID 파일을 제거하지 않습니다 (PID $pid)." >&2
    return
  fi

  echo "$name: SIGTERM 전송 (PID $pid)."
  kill -TERM -- "-$pid"
  for ((attempt = 1; attempt <= 10; attempt++)); do
    kill -0 "$pid" 2>/dev/null || break
    sleep 1
  done
  if kill -0 "$pid" 2>/dev/null; then
    echo "$name: 10초 내 종료되지 않아 SIGKILL을 전송합니다." >&2
    kill -KILL -- "-$pid"
  fi
  rm -f "$pid_file"
  echo "$name: 중지 완료."
}

stop_managed_process "메트릭 서버" "$RUNTIME_DIR/metrics_server.pid" "satgenpy.ai_datacenter.metrics_server" "$ROOT_DIR"
stop_managed_process "Cesium 프런트엔드" "$RUNTIME_DIR/frontend.pid" "npm run dev" "$ROOT_DIR/frontend"

if [[ -f "$ROOT_DIR/monitoring/docker-compose.yml" ]] && command -v docker >/dev/null 2>&1; then
  echo "Prometheus/Grafana: compose 종료 요청 중..."
  (cd "$ROOT_DIR/monitoring" && docker compose down)
else
  echo "Prometheus/Grafana: compose 파일 또는 docker 명령이 없어 건너뜁니다." >&2
fi
echo "시스템 중지 절차가 완료되었습니다."
