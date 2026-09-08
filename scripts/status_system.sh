#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="$ROOT_DIR/.runtime"

if [[ "${1:-}" == "--docker" ]]; then
  command -v docker >/dev/null 2>&1 || { echo "docker 명령을 찾을 수 없습니다." >&2; exit 1; }
  docker compose --project-directory "$ROOT_DIR" -f "$ROOT_DIR/docker-compose.yml" ps
  echo "Frontend  http://localhost:${FRONTEND_PORT:-5173}"
  echo "Backend   http://localhost:${BACKEND_PORT:-8000}/ready"
  echo "Prometheus http://localhost:${PROMETHEUS_PORT:-9090}"
  echo "Grafana   http://localhost:${GRAFANA_PORT:-3000}"
  exit 0
elif [[ -n "${1:-}" ]]; then
  echo "지원하지 않는 옵션입니다: $1 (--docker)" >&2
  exit 2
fi

pid_status() {
  local pid_file="$1" expected_command="$2" expected_dir="$3" pid command cwd
  [[ -f "$pid_file" ]] || { printf '관리 PID 없음'; return; }
  read -r pid < "$pid_file" || pid=""
  if [[ ! "$pid" =~ ^[0-9]+$ ]] || ! kill -0 "$pid" 2>/dev/null; then printf '프로세스 down (stale PID)'; return; fi
  command="$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)"
  cwd="$(readlink -f "/proc/$pid/cwd" 2>/dev/null || true)"
  if [[ "$command" == *"$expected_command"* && "$cwd" == "$expected_dir" ]]; then
    printf '프로세스 실행 (PID %s)' "$pid"
  else
    printf '관리 대상 불일치 (PID %s)' "$pid"
  fi
}

port_status() {
  local port="$1"
  if command -v ss >/dev/null 2>&1; then
    ss -ltn "sport = :$port" 2>/dev/null | tail -n +2 | grep -q . && printf 'listener 있음' || printf 'listener 없음'
  elif command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1 && printf 'listener 있음' || printf 'listener 없음'
  else
    printf 'listener 확인 불가'
  fi
}

http_status() {
  local url="$1" code
  code="$(curl --silent --output /dev/null --write-out '%{http_code}' --max-time 2 "$url" 2>/dev/null || true)"
  [[ "$code" == "200" ]] && printf 'HTTP 정상' || printf 'HTTP unavailable (%s)' "${code:-연결 실패}"
}

backend_health() {
  local live ready
  live="$(curl --silent --output /dev/null --write-out '%{http_code}' --max-time 2 http://localhost:8000/health 2>/dev/null || true)"
  ready="$(curl --silent --output /dev/null --write-out '%{http_code}' --max-time 2 http://localhost:8000/ready 2>/dev/null || true)"
  if [[ "$live" != "200" ]]; then printf 'HTTP unavailable';
  elif [[ "$ready" == "200" ]]; then printf 'ready';
  else printf 'healthy, not ready'; fi
}

compose_status() {
  local service="$1"
  if [[ ! -f "$ROOT_DIR/monitoring/docker-compose.yml" ]] || ! command -v docker >/dev/null 2>&1; then printf '컨테이너 확인 불가'; return; fi
  if (cd "$ROOT_DIR/monitoring" && docker compose ps --status running --services 2>/dev/null) | grep -Fxq "$service"; then printf '컨테이너 실행'; else printf '컨테이너 down'; fi
}

command -v curl >/dev/null 2>&1 || { echo "curl 명령을 찾을 수 없습니다." >&2; exit 1; }

printf '%-18s | %-28s | %-15s | %-20s | %s\n' "Backend" "$(pid_status "$RUNTIME_DIR/metrics_server.pid" "satgenpy.ai_datacenter.metrics_server" "$ROOT_DIR")" "$(port_status 8000)" "$(backend_health)" "http://localhost:8000/ready"
printf '%-18s | %-28s | %-15s | %-20s | %s\n' "Frontend" "$(pid_status "$RUNTIME_DIR/frontend.pid" "npm run dev" "$ROOT_DIR/frontend")" "$(port_status 5173)" "$(http_status http://localhost:5173)" "http://localhost:5173"
printf '%-18s | %-28s | %-15s | %-20s | %s\n' "Prometheus" "$(compose_status prometheus)" "$(port_status 9090)" "$(http_status http://localhost:9090/-/ready)" "http://localhost:9090"
printf '%-18s | %-28s | %-15s | %-20s | %s\n' "Grafana" "$(compose_status grafana)" "$(port_status 3000)" "$(http_status http://localhost:3000/api/health)" "http://localhost:3000"
