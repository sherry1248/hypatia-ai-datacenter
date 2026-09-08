#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "사용법: $0 INPUT_DIR [OUTPUT_DIR]" >&2
  exit 2
fi

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repository_dir="$(cd -- "$script_dir/.." && pwd)"
input_dir="$1"
output_dir="${2:-$input_dir/report}"

if [[ ! -d "$input_dir" ]]; then
  echo "오류: 입력 디렉터리가 없습니다: $input_dir" >&2
  exit 1
fi

for required_file in runs.csv summary.csv policy_ranking.csv metadata.json; do
  if [[ ! -f "$input_dir/$required_file" ]]; then
    echo "오류: 필수 입력 파일 누락: $required_file" >&2
    exit 1
  fi
done

cd "$repository_dir"
exec .venv/bin/python -m satgenpy.ai_datacenter.experiment_report \
  --input "$input_dir" --output "$output_dir"
