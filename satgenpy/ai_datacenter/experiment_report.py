"""Generate deterministic analysis, figures, findings, and reports."""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import math
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping, Sequence


VERSION = "1.0.0"
SOURCE_FILES = ("runs.csv", "summary.csv", "policy_ranking.csv", "metadata.json")
SCENARIO_ORDER = ("normal", "single", "multi")
SCENARIO_LABELS = {"normal": "정상", "single": "단일 장애", "multi": "다중 장애"}
METRICS = (
    "placement_success_ratio", "jobs_unplaced", "deadline_met_ratio",
    "average_queue_wait_seconds", "p95_queue_wait_seconds",
    "average_total_time_seconds", "p95_total_time_seconds",
    "node_load_imbalance_ratio",
)
RATIO_METRICS = {"placement_success_ratio", "deadline_met_ratio"}
METRIC_LABELS = {
    "placement_success_ratio": "배치 성공률", "jobs_unplaced": "평균 미배치 작업 수",
    "deadline_met_ratio": "마감 준수율", "average_queue_wait_seconds": "평균 큐 대기시간",
    "p95_queue_wait_seconds": "P95 큐 대기시간", "average_total_time_seconds": "평균 총 시간",
    "p95_total_time_seconds": "P95 총 시간", "node_load_imbalance_ratio": "노드 부하 불균형",
}
FIGURE_SPECS = (
    ("placement_success_ratio", "placement_success_ratio.svg", "시나리오·정책별 배치 성공률", "비율 (0–1)"),
    ("jobs_unplaced", "jobs_unplaced.svg", "시나리오·정책별 평균 미배치 작업 수", "작업 수"),
    ("deadline_met_ratio", "deadline_met_ratio.svg", "시나리오·정책별 마감 준수율", "비율 (0–1)"),
    ("p95_queue_wait_seconds", "p95_queue_wait_seconds.svg", "시나리오·정책별 P95 큐 대기시간", "초"),
    ("p95_total_time_seconds", "p95_total_time_seconds.svg", "시나리오·정책별 P95 총 시간", "초"),
    ("node_load_imbalance_ratio", "node_load_imbalance_ratio.svg", "시나리오·정책별 노드 부하 불균형", "표준편차 / 평균"),
)
RUN_REQUIRED = {"scenario", "policy", "workload", "seed", "status", "error"}
SUMMARY_REQUIRED = {"scenario", "policy", "workload", "successful_run_count", "failed_run_count"} | {
    f"{metric}_mean" for metric in METRICS
}
RANKING_REQUIRED = {"scenario", "workload", "rank", "policy"}
FINDING_COLUMNS = (
    "finding_id", "scenario", "workload", "policy", "metric", "finding_type",
    "baseline_value", "compared_value", "absolute_change",
    "relative_change_percent", "statement",
)


class ReportError(ValueError):
    pass


def _read_csv(path: Path, required: set[str]) -> list[dict[str, str]]:
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            fields = set(reader.fieldnames or ())
            missing = required - fields
            if missing:
                raise ReportError(f"필수 열 누락({path.name}): {', '.join(sorted(missing))}")
            rows = []
            for line, row in enumerate(reader, 2):
                if None in row or any(value is None for value in row.values()):
                    raise ReportError(f"CSV 형식 오류({path.name} {line}행)")
                rows.append({key: value.strip() for key, value in row.items()})
            return rows
    except ReportError:
        raise
    except (OSError, csv.Error, UnicodeError) as error:
        raise ReportError(f"CSV 읽기 실패({path.name}): {error}") from error


def _number(value: str, context: str, *, optional: bool = False) -> float | None:
    if value == "" and optional:
        return None
    try:
        result = float(value)
    except ValueError as error:
        raise ReportError(f"숫자 형식 오류({context})") from error
    if not math.isfinite(result):
        raise ReportError(f"유한하지 않은 숫자({context})")
    return result


def _integer(value: object, context: str) -> int:
    try:
        parsed = int(str(value))
    except ValueError as error:
        raise ReportError(f"정수 형식 오류({context})") from error
    return parsed


def calculate_change(metric: str, baseline: float, compared: float) -> dict[str, float | None]:
    absolute = compared - baseline
    if metric in RATIO_METRICS:
        return {"absolute_change": absolute, "relative_change_percent": None}
    relative = None if baseline == 0 else absolute / abs(baseline) * 100.0
    return {"absolute_change": absolute, "relative_change_percent": relative}


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def detect_missing_combinations(metadata: Mapping[str, object], runs: Sequence[Mapping[str, str]]) -> list[dict[str, object]]:
    matrix = metadata.get("requested_matrix")
    if not isinstance(matrix, dict):
        raise ReportError("metadata.json의 requested_matrix가 올바르지 않습니다")
    dimensions = []
    for name in ("scenarios", "policies", "workloads", "seeds"):
        values = matrix.get(name)
        if not isinstance(values, list) or not values:
            raise ReportError(f"metadata.json의 {name} 행렬이 올바르지 않습니다")
        dimensions.append(values)
    actual = {
        (row["scenario"], row["policy"], row["workload"], _integer(row["seed"], "runs.csv seed"))
        for row in runs
    }
    expected = {
        (str(s), str(p), str(w), _integer(seed, "metadata seed"))
        for s in dimensions[0] for p in dimensions[1] for w in dimensions[2] for seed in dimensions[3]
    }
    outside = actual - expected
    if outside:
        raise ReportError("metadata.json과 runs.csv의 실행 구성이 일치하지 않습니다")
    return [
        {"scenario": item[0], "policy": item[1], "workload": item[2], "seed": item[3]}
        for item in sorted(expected - actual)
    ]


def load_inputs(input_dir: Path) -> dict[str, object]:
    missing = [name for name in SOURCE_FILES if not (input_dir / name).is_file()]
    if missing:
        raise ReportError("필수 입력 파일 누락: " + ", ".join(missing))
    runs = _read_csv(input_dir / "runs.csv", RUN_REQUIRED)
    summaries = _read_csv(input_dir / "summary.csv", SUMMARY_REQUIRED)
    rankings = _read_csv(input_dir / "policy_ranking.csv", RANKING_REQUIRED)
    try:
        metadata = json.loads((input_dir / "metadata.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ReportError(f"metadata.json 읽기 실패: {error}") from error
    if not isinstance(metadata, dict):
        raise ReportError("metadata.json 최상위 값은 객체여야 합니다")
    success_count = sum(row["status"] == "success" for row in runs)
    failed_count = sum(row["status"] == "failed" for row in runs)
    unknown = sorted({row["status"] for row in runs} - {"success", "failed"})
    if unknown:
        raise ReportError("runs.csv의 status 값이 올바르지 않습니다")
    if not success_count:
        raise ReportError("성공한 실행이 없습니다")
    if _integer(metadata.get("completed_run_count", -1), "completed_run_count") != success_count or _integer(
        metadata.get("failed_run_count", -1), "failed_run_count"
    ) != failed_count:
        raise ReportError("metadata.json의 실행 수와 runs.csv가 일치하지 않습니다")
    summary_keys = {(row["scenario"], row["workload"], row["policy"]) for row in summaries}
    successful_keys = {
        (row["scenario"], row["workload"], row["policy"])
        for row in runs if row["status"] == "success"
    }
    if not successful_keys.issubset(summary_keys):
        raise ReportError("summary.csv에 성공 실행 조합이 누락되었습니다")
    run_keys = {(row["scenario"], row["workload"], row["policy"]) for row in runs}
    if not summary_keys.issubset(run_keys):
        raise ReportError("summary.csv가 runs.csv에 없는 조합을 포함합니다")
    for row in summaries:
        for metric in METRICS:
            _number(row[f"{metric}_mean"], f"summary.csv {metric}", optional=True)
    seen_ranks: set[tuple[str, str, int]] = set()
    ranked_keys: set[tuple[str, str, str]] = set()
    for row in rankings:
        key = (row["scenario"], row["workload"], row["policy"])
        rank = _integer(row["rank"], "policy_ranking.csv rank")
        if key not in summary_keys:
            raise ReportError("policy_ranking.csv가 실제 요약 조합을 참조하지 않습니다")
        rank_key = (row["scenario"], row["workload"], rank)
        if rank_key in seen_ranks:
            raise ReportError("policy_ranking.csv에 중복 순위가 있습니다")
        seen_ranks.add(rank_key)
        ranked_keys.add(key)
    if not successful_keys.issubset(ranked_keys):
        raise ReportError("policy_ranking.csv에 성공 실행 정책이 누락되었습니다")
    missing_combinations = detect_missing_combinations(metadata, runs)
    return {
        "runs": runs, "summaries": summaries, "rankings": rankings,
        "metadata": metadata, "success_count": success_count,
        "failed_count": failed_count, "missing_combinations": missing_combinations,
    }


def build_degradations(summaries: Sequence[Mapping[str, str]]) -> list[dict[str, object]]:
    indexed = {(row["scenario"], row["policy"], row["workload"]): row for row in summaries}
    rows: list[dict[str, object]] = []
    for scenario, policy, workload in sorted(indexed, key=lambda key: (
        SCENARIO_ORDER.index(key[0]) if key[0] in SCENARIO_ORDER else 99, key[2], key[1]
    )):
        if scenario == "normal":
            continue
        baseline = indexed.get(("normal", policy, workload))
        if baseline is None:
            continue
        compared = indexed[(scenario, policy, workload)]
        for metric in METRICS:
            base = _number(baseline[f"{metric}_mean"], metric, optional=True)
            value = _number(compared[f"{metric}_mean"], metric, optional=True)
            if base is None or value is None:
                continue
            change = calculate_change(metric, base, value)
            rows.append({
                "scenario": scenario, "workload": workload, "policy": policy,
                "metric": metric, "baseline_value": base, "compared_value": value,
                **change,
            })
    return rows


def build_findings(degradations: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    findings = []
    for index, row in enumerate(degradations, 1):
        metric = str(row["metric"])
        absolute = float(row["absolute_change"])
        relative = row["relative_change_percent"]
        if metric in RATIO_METRICS:
            change_text = f"{absolute * 100:+.2f}%p"
            kind = "percentage_point_change"
        elif relative is None:
            change_text = f"절대 변화 {absolute:+.4g}, 상대 변화 계산 불가(정상 기준 0)"
            kind = "absolute_change_zero_baseline"
        else:
            change_text = f"{float(relative):+.2f}%"
            kind = "percentage_change"
        statement = (
            f"{SCENARIO_LABELS.get(str(row['scenario']), str(row['scenario']))} 조건에서 "
            f"{row['policy']} 정책의 {METRIC_LABELS[metric]}은(는) 정상 대비 {change_text} 변화했습니다."
        )
        findings.append({
            "finding_id": f"F{index:04d}", **row, "finding_type": kind,
            "statement": statement,
        })
    return findings


def _policy_label(policy: str) -> str:
    return policy.replace("_", " ")


def generate_figures(summaries: Sequence[Mapping[str, str]], degradations: Sequence[Mapping[str, object]], output: Path) -> list[str]:
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/hypatia-matplotlib")
    try:
        import matplotlib
        matplotlib.use("Agg")
        from matplotlib import pyplot as plt
        from matplotlib import font_manager
    except ImportError as error:
        raise ReportError("matplotlib을 사용할 수 없습니다") from error
    figures_dir = output / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    available_fonts = {font.name for font in font_manager.fontManager.ttflist}
    korean_font = next(
        (name for name in ("NanumGothic", "NanumBarunGothic", "D2Coding ligature") if name in available_fonts),
        "DejaVu Sans",
    )
    matplotlib.rcParams.update({
        "font.family": korean_font,
        "axes.unicode_minus": False,
        "svg.hashsalt": "hypatia-experiment-report",
    })
    workloads = sorted({row["workload"] for row in summaries})
    policies = sorted({row["policy"] for row in summaries})
    figure_names = []
    for metric, filename, title, ylabel in FIGURE_SPECS:
        fig, axes = plt.subplots(len(workloads), 1, figsize=(10, 4.8 * len(workloads)), squeeze=False)
        for axis, workload in zip(axes[:, 0], workloads):
            width = 0.8 / max(1, len(policies))
            for p_index, policy in enumerate(policies):
                values = []
                for scenario in SCENARIO_ORDER:
                    match = next((row for row in summaries if row["scenario"] == scenario and row["policy"] == policy and row["workload"] == workload), None)
                    value = _number(match[f"{metric}_mean"], metric, optional=True) if match else None
                    values.append(float("nan") if value is None else value)
                positions = [index - 0.4 + width / 2 + p_index * width for index in range(3)]
                axis.bar(positions, values, width, label=_policy_label(policy))
            axis.set_xticks(range(3), [SCENARIO_LABELS[item] for item in SCENARIO_ORDER])
            axis.set_ylabel(ylabel)
            axis.set_title(f"{title} — {workload}")
            axis.grid(axis="y", alpha=0.25)
            if metric in RATIO_METRICS:
                axis.set_ylim(0, 1.0)
            axis.legend(title="정책 (원시 식별자는 캡션 참조)", fontsize="small")
        fig.tight_layout()
        fig.savefig(figures_dir / filename, format="svg", metadata={"Date": None})
        plt.close(fig)
        figure_names.append(f"figures/{filename}")
    # Percentage-point degradation is plotted separately to avoid mixing units.
    filename = "degradation_vs_normal.svg"
    fig, axes = plt.subplots(len(workloads), 1, figsize=(10, 4.8 * len(workloads)), squeeze=False)
    for axis, workload in zip(axes[:, 0], workloads):
        width = 0.8 / max(1, len(policies))
        for p_index, policy in enumerate(policies):
            values = []
            for scenario in ("single", "multi"):
                match = next((row for row in degradations if row["scenario"] == scenario and row["policy"] == policy and row["workload"] == workload and row["metric"] == "placement_success_ratio"), None)
                values.append(float(match["absolute_change"]) * 100 if match else float("nan"))
            positions = [index - 0.4 + width / 2 + p_index * width for index in range(2)]
            axis.bar(positions, values, width, label=_policy_label(policy))
        axis.axhline(0, color="black", linewidth=0.8)
        axis.set_xticks(range(2), [SCENARIO_LABELS["single"], SCENARIO_LABELS["multi"]])
        axis.set_ylabel("정상 대비 변화 (%p)")
        axis.set_title(f"정상 대비 배치 성공률 저하 — {workload}")
        axis.grid(axis="y", alpha=0.25)
        axis.legend(title="정책", fontsize="small")
    fig.tight_layout()
    fig.savefig(figures_dir / filename, format="svg", metadata={"Date": None})
    plt.close(fig)
    figure_names.append(f"figures/{filename}")
    return figure_names


def _fmt(value: object, metric: str | None = None) -> str:
    if value is None or value == "":
        return "계산 불가"
    number = float(value)
    if metric in RATIO_METRICS:
        return f"{number:.4f}"
    return f"{number:.4g}"


def _md_table(headers: Sequence[str], rows: Iterable[Sequence[object]]) -> str:
    safe_rows = [[str(value).replace("|", "\\|").replace("\n", " ") for value in row] for row in rows]
    return "\n".join([
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
        *("| " + " | ".join(row) + " |" for row in safe_rows),
    ])


def _matrix_text(metadata: Mapping[str, object]) -> str:
    matrix = metadata["requested_matrix"]
    assert isinstance(matrix, dict)
    return "; ".join(f"{name}={','.join(map(str, matrix[name]))}" for name in ("scenarios", "policies", "workloads", "seeds"))


def generate_markdown(title: str, generated_at: str, data: Mapping[str, object], degradations: Sequence[Mapping[str, object]], findings: Sequence[Mapping[str, object]], figures: Sequence[str]) -> str:
    metadata = data["metadata"]
    assert isinstance(metadata, dict)
    summaries = data["summaries"]
    rankings = sorted(data["rankings"], key=lambda row: (row["scenario"], row["workload"], int(row["rank"])))
    missing = data["missing_combinations"]
    failed = [row for row in data["runs"] if row["status"] == "failed"]
    comparison_rows = [[
        SCENARIO_LABELS.get(row["scenario"], row["scenario"]), row["workload"], row["policy"],
        *(_fmt(row[f"{metric}_mean"], metric) for metric in METRICS),
    ] for row in sorted(summaries, key=lambda row: (row["workload"], SCENARIO_ORDER.index(row["scenario"]) if row["scenario"] in SCENARIO_ORDER else 99, row["policy"]))]
    degradation_rows = [[
        SCENARIO_LABELS.get(str(row["scenario"]), row["scenario"]), row["workload"], row["policy"], METRIC_LABELS[str(row["metric"])],
        _fmt(row["baseline_value"], str(row["metric"])), _fmt(row["compared_value"], str(row["metric"])),
        f"{float(row['absolute_change']) * 100:+.2f}%p" if row["metric"] in RATIO_METRICS else _fmt(row["absolute_change"]),
        "계산 불가" if row["relative_change_percent"] is None else f"{float(row['relative_change_percent']):+.2f}%",
    ] for row in degradations]
    best = [row for row in rankings if int(row["rank"]) == 1]
    presentation = list(findings)[:5]
    lines = [
        f"# {title}", "", f"생성 시각(UTC): {generated_at}", "",
        f"- 저장소 리비전: {metadata.get('repository_revision') or '확인 불가'}",
        f"- Python: {metadata.get('python_version', '확인 불가')}",
        f"- 요청 행렬: {_matrix_text(metadata)}",
        f"- 성공 실행: {data['success_count']}, 실패 실행: {data['failed_count']}", "",
        "## 발표용 핵심 결과", "", *(f"- {row['statement']}" for row in presentation), "",
        "## 방법론", "",
        "결과는 명시적 시드를 사용한 반복 결정적 시뮬레이션에서 생성되었습니다. 집계 비교는 `summary.csv`, 실행 분포와 검증은 `runs.csv`, 정책 순위는 기존 평가 규칙이 기록된 `policy_ranking.csv`를 사용했습니다.", "",
        f"- 백분위수: {metadata.get('percentile_method', '확인 불가')}",
        f"- 표준편차: {metadata.get('standard_deviation_method', '확인 불가')}",
        "- 순위 규칙: 배치 성공률 내림차순, 마감 준수율 내림차순, 미배치 수 오름차순, P95 총 시간 오름차순, 노드 부하 불균형 오름차순의 기존 사전식 평가 규칙입니다. 이는 AI 의사결정 규칙이 아닙니다.", "",
        "## 전체 비교", "",
        _md_table(["시나리오", "워크로드", "정책", *[METRIC_LABELS[m] for m in METRICS]], comparison_rows), "",
        "## 시나리오별 정책 순위", "",
        _md_table(["시나리오", "워크로드", "순위", "정책"], [[SCENARIO_LABELS.get(r["scenario"], r["scenario"]), r["workload"], r["rank"], r["policy"]] for r in rankings]), "",
        "## 정상 대비 저하", "",
        "비율 지표는 퍼센트포인트(%p), 시간·개수·불균형은 정상값이 0이 아닐 때 백분율 변화로 표시합니다. 정상값이 0이면 절대 차이는 보존하고 상대 변화는 계산 불가로 표시합니다.", "",
        _md_table(["시나리오", "워크로드", "정책", "지표", "정상", "비교", "절대/%p 변화", "상대 변화"], degradation_rows), "",
        "## 핵심 발견", "", *(f"- [{row['finding_id']}] {row['statement']} (관측 결과)" for row in findings), "",
        "## 행렬 완전성", "",
        ("누락된 실행 조합이 없습니다." if not missing else f"누락 조합 {len(missing)}개: " + "; ".join(f"{r['scenario']}/{r['policy']}/{r['workload']}/seed={r['seed']}" for r in missing)), "",
        "## 실패 실행", "",
        ("실패 실행이 없습니다." if not failed else _md_table(["시나리오", "정책", "워크로드", "시드", "오류"], [[r["scenario"], r["policy"], r["workload"], r["seed"], r["error"]] for r in failed])), "",
        "## 그림", "", *sum(([f"![{Path(path).stem}]({path})", f"원시 정책 식별자: {', '.join(sorted({r['policy'] for r in summaries}))}", ""] for path in figures), []),
        "## 한계", "",
        "- 물리 위성 배치가 아닌 시뮬레이션 결과입니다.",
        "- 저장된 시나리오 토폴로지와 워크로드 가정에 의존합니다.",
        "- 실제 위성 하드웨어의 에너지 소비를 측정하지 않았습니다.",
        "- 동적 물리 링크 복구 시간은 구현되어 있지 않아 평가하지 않았습니다.",
        "- 강화학습 정책은 구현되어 있지 않습니다.",
        "- 결론은 평가된 시나리오 행렬에 의존하며 자동 문장은 관측 수치의 서술이지 인과 설명이 아닙니다.", "",
    ]
    return "\n".join(lines)


def _html_table(headers: Sequence[str], rows: Iterable[Sequence[object]]) -> str:
    head = "".join(f"<th scope=\"col\">{html.escape(str(value))}</th>" for value in headers)
    body = "".join("<tr>" + "".join(f"<td>{html.escape(str(value))}</td>" for value in row) + "</tr>" for row in rows)
    return f"<div class=\"table-wrap\"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>"


def generate_html(title: str, generated_at: str, data: Mapping[str, object], degradations: Sequence[Mapping[str, object]], findings: Sequence[Mapping[str, object]], figures: Sequence[str]) -> str:
    metadata = data["metadata"]
    assert isinstance(metadata, dict)
    summaries = sorted(data["summaries"], key=lambda row: (row["workload"], row["scenario"], row["policy"]))
    rankings = sorted(data["rankings"], key=lambda row: (row["scenario"], row["workload"], int(row["rank"])))
    missing = data["missing_combinations"]
    failed = [row for row in data["runs"] if row["status"] == "failed"]
    comparison = _html_table(
        ["시나리오", "워크로드", "정책", *[METRIC_LABELS[m] for m in METRICS]],
        [[SCENARIO_LABELS.get(r["scenario"], r["scenario"]), r["workload"], r["policy"], *(_fmt(r[f"{m}_mean"], m) for m in METRICS)] for r in summaries],
    )
    ranking_table = _html_table(["시나리오", "워크로드", "순위", "정책"], [[SCENARIO_LABELS.get(r["scenario"], r["scenario"]), r["workload"], r["rank"], r["policy"]] for r in rankings])
    degradation_table = _html_table(["시나리오", "워크로드", "정책", "지표", "정상", "비교", "절대 변화", "상대 변화"], [[SCENARIO_LABELS.get(str(r["scenario"]), str(r["scenario"])), r["workload"], r["policy"], METRIC_LABELS[str(r["metric"])], _fmt(r["baseline_value"], str(r["metric"])), _fmt(r["compared_value"], str(r["metric"])), f"{float(r['absolute_change'])*100:+.2f}%p" if r["metric"] in RATIO_METRICS else _fmt(r["absolute_change"]), "계산 불가" if r["relative_change_percent"] is None else f"{float(r['relative_change_percent']):+.2f}%"] for r in degradations])
    failed_html = "<p>실패 실행이 없습니다.</p>" if not failed else _html_table(["시나리오", "정책", "워크로드", "시드", "오류"], [[r["scenario"], r["policy"], r["workload"], r["seed"], r["error"]] for r in failed])
    missing_text = "누락된 실행 조합이 없습니다." if not missing else f"누락된 실행 조합: {len(missing)}개"
    figure_html = "".join(f'<figure><img src="{html.escape(path, quote=True)}" alt="{html.escape(Path(path).stem)}"><figcaption>원시 정책 식별자: {html.escape(", ".join(sorted({r["policy"] for r in summaries})))}</figcaption></figure>' for path in figures)
    presentation = "".join(f"<li>{html.escape(str(r['statement']))}</li>" for r in list(findings)[:5])
    finding_html = "".join(f"<li><strong>{html.escape(str(r['finding_id']))}</strong> {html.escape(str(r['statement']))} <em>(관측 결과)</em></li>" for r in findings)
    return f'''<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title><style>body{{font-family:system-ui,sans-serif;max-width:1200px;margin:auto;padding:2rem;line-height:1.6;color:#17202a}}h1,h2{{color:#17365d}}.meta{{background:#f4f7fa;padding:1rem;border-radius:.5rem}}.table-wrap{{overflow-x:auto}}table{{border-collapse:collapse;width:100%;font-size:.9rem}}th,td{{border:1px solid #ccd4dc;padding:.45rem;text-align:left}}th{{background:#e9f0f7}}figure{{margin:2rem 0}}img{{max-width:100%;height:auto}}figcaption{{font-size:.85rem;color:#555}}code{{overflow-wrap:anywhere}}@media(max-width:600px){{body{{padding:1rem}}}}</style></head><body><main><h1>{html.escape(title)}</h1><div class="meta"><p>생성 시각(UTC): {html.escape(generated_at)}</p><p>저장소 리비전: {html.escape(str(metadata.get("repository_revision") or "확인 불가"))}<br>Python: {html.escape(str(metadata.get("python_version", "확인 불가")))}<br>요청 행렬: {html.escape(_matrix_text(metadata))}<br>성공 실행: {data["success_count"]}, 실패 실행: {data["failed_count"]}</p></div><h2>발표용 핵심 결과</h2><ul>{presentation}</ul><h2>방법론</h2><p>결과는 명시적 시드를 사용한 반복 결정적 시뮬레이션에서 생성되었습니다. 집계는 summary.csv, 실행 검증은 runs.csv, 기존 평가 순위는 policy_ranking.csv를 사용했습니다.</p><ul><li>백분위수: {html.escape(str(metadata.get("percentile_method", "확인 불가")))}</li><li>표준편차: {html.escape(str(metadata.get("standard_deviation_method", "확인 불가")))}</li><li>순위: 배치 성공률↓, 마감 준수율↓, 미배치 수↑, P95 총 시간↑, 노드 부하 불균형↑의 기존 사전식 평가 규칙이며 AI 의사결정 규칙이 아닙니다.</li></ul><h2>전체 비교</h2>{comparison}<h2>시나리오별 정책 순위</h2>{ranking_table}<h2>정상 대비 저하</h2><p>비율 지표는 퍼센트포인트, 나머지는 정상 기준 백분율 변화로 표시하며 0 기준은 상대 변화 계산 불가로 둡니다.</p>{degradation_table}<h2>핵심 발견</h2><ul>{finding_html}</ul><h2>행렬 완전성</h2><p>{html.escape(missing_text)}</p><h2>실패 실행</h2>{failed_html}<h2>그림</h2>{figure_html}<h2>한계</h2><ul><li>물리 위성 배치가 아닌 시뮬레이션입니다.</li><li>저장된 시나리오 토폴로지와 워크로드 가정에 의존합니다.</li><li>실제 위성 하드웨어 에너지 소비를 측정하지 않았습니다.</li><li>동적 물리 링크 복구 시간은 구현되어 있지 않습니다.</li><li>강화학습 정책은 구현되어 있지 않습니다.</li><li>결과는 평가된 시나리오 행렬에 의존하며 자동 해석은 인과 설명이 아닙니다.</li></ul></main></body></html>'''


def generate_report(input_dir: Path, output_dir: Path, title: str, formats: Sequence[str]) -> list[Path]:
    data = load_inputs(input_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(timezone.utc).isoformat()
    degradations = build_degradations(data["summaries"])
    findings = build_findings(degradations)
    figures = generate_figures(data["summaries"], degradations, output_dir)
    artifacts: list[Path] = []
    findings_path = output_dir / "key_findings.csv"
    with findings_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FINDING_COLUMNS)
        writer.writeheader()
        writer.writerows({column: row.get(column) for column in FINDING_COLUMNS} for row in findings)
    artifacts.append(findings_path)
    if "markdown" in formats:
        path = output_dir / "experiment_report.md"
        path.write_text(generate_markdown(title, generated_at, data, degradations, findings, figures), encoding="utf-8")
        artifacts.append(path)
    if "html" in formats:
        path = output_dir / "experiment_report.html"
        path.write_text(generate_html(title, generated_at, data, degradations, findings, figures), encoding="utf-8")
        artifacts.append(path)
    report_metadata = {
        "source_input_paths": {name: str((input_dir / name).resolve()) for name in SOURCE_FILES},
        "source_file_hashes": {name: _hash(input_dir / name) for name in SOURCE_FILES},
        "report_generation_time": generated_at, "report_generator_version": VERSION,
        "figure_list": figures, "detected_missing_combinations": data["missing_combinations"],
        "successful_run_count": data["success_count"], "failed_run_count": data["failed_count"],
    }
    metadata_path = output_dir / "report_metadata.json"
    metadata_path.write_text(json.dumps(report_metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    artifacts.extend(output_dir / path for path in figures)
    artifacts.append(metadata_path)
    return artifacts


def _formats(value: str) -> list[str]:
    values = [item.strip() for item in value.split(",") if item.strip()]
    invalid = set(values) - {"markdown", "html"}
    if not values or invalid:
        raise argparse.ArgumentTypeError("format은 markdown,html 중 하나 이상이어야 합니다")
    return list(dict.fromkeys(values))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--format", type=_formats, default=["markdown", "html"])
    parser.add_argument("--title", default="우주 AI 데이터센터 결정적 배치 실험 보고서")
    args = parser.parse_args(argv)
    try:
        artifacts = generate_report(args.input, args.output, args.title, args.format)
    except ReportError as error:
        print(f"오류: {error}", file=sys.stderr)
        return 1
    print(f"보고서 생성 완료: {len(artifacts)}개 파일")
    for path in artifacts:
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
