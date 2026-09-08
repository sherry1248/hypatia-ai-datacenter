from pathlib import Path

import pandas as pd


SCENARIOS = (
    "NORMAL_BURST",
    "FAILED_ISL_0_1_BURST",
    "MULTI_FAILED_ISL_0_1_10_11_BURST",
)
SCENARIO_LABELS = {
    "NORMAL_BURST": "정상",
    "FAILED_ISL_0_1_BURST": "단일 링크 장애",
    "MULTI_FAILED_ISL_0_1_10_11_BURST": "다중 링크 장애",
}
SUMMARY_COLUMNS = (
    "scenario",
    "total_jobs",
    "placed_jobs",
    "unplaced_jobs",
    "placement_success_rate_percent",
    "deadline_met_rate_percent",
    "average_queue_wait_ms",
    "maximum_queue_wait_ms",
    "average_total_time_ms",
)
COMPARISON_COLUMNS = (
    "scenario",
    "scenario_label",
    *SUMMARY_COLUMNS[1:],
    "placement_rate_change_pp",
    "deadline_rate_change_pp",
    "queue_wait_ratio_vs_normal",
    "total_time_ratio_vs_normal",
    "additional_unplaced_jobs",
)


def _validate_inputs(summary: pd.DataFrame, results: pd.DataFrame) -> None:
    missing_summary = set(SUMMARY_COLUMNS) - set(summary.columns)
    if missing_summary:
        raise ValueError(
            "summary CSV is missing columns: "
            + ", ".join(sorted(missing_summary))
        )
    required_results = {"scenario", "placement_status", "selected_node"}
    missing_results = required_results - set(results.columns)
    if missing_results:
        raise ValueError(
            "detailed results CSV is missing columns: "
            + ", ".join(sorted(missing_results))
        )

    summary_scenarios = set(summary["scenario"].dropna())
    if summary_scenarios != set(SCENARIOS):
        raise ValueError(
            "summary CSV must contain exactly these scenarios: "
            + ", ".join(SCENARIOS)
        )
    scenario_counts = summary["scenario"].value_counts()
    if any(scenario_counts.get(scenario, 0) != 1 for scenario in SCENARIOS):
        raise ValueError("summary CSV must contain one row per scenario")

    for row in summary.itertuples(index=False):
        if int(row.total_jobs) != 300:
            raise ValueError(f"{row.scenario}: total_jobs must equal 300")
        if int(row.placed_jobs) + int(row.unplaced_jobs) != int(row.total_jobs):
            raise ValueError(
                f"{row.scenario}: placed_jobs + unplaced_jobs must equal total_jobs"
            )

    detail_scenarios = set(results["scenario"].dropna())
    if detail_scenarios != set(SCENARIOS):
        raise ValueError(
            "detailed results CSV must contain exactly the expected scenarios"
        )
    detail_counts = results["scenario"].value_counts()
    for scenario in SCENARIOS:
        if int(detail_counts.get(scenario, 0)) != 300:
            raise ValueError(
                f"{scenario}: detailed results must contain exactly 300 rows"
            )


def _ratio(value: float, baseline: float) -> float:
    if baseline == 0:
        return 1.0 if value == 0 else float("inf")
    return value / baseline


def _markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    header = "| " + " | ".join(headers) + " |"
    divider = "| " + " | ".join("---" for _ in headers) + " |"
    body = ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join([header, divider, *body])


def _format_ratio(value: float) -> str:
    return "∞" if value == float("inf") else f"{value:.2f}배"


def generate_experiment_report() -> tuple[str, str]:
    demo_data_dir = Path(__file__).resolve().parent.parent / "demo_data"
    summary_path = demo_data_dir / "workload_experiment_summary.csv"
    results_path = demo_data_dir / "workload_experiment_results.csv"
    if not summary_path.is_file():
        raise ValueError(f"summary CSV was not found: {summary_path}")
    if not results_path.is_file():
        raise ValueError(f"detailed results CSV was not found: {results_path}")

    summary = pd.read_csv(summary_path)
    results = pd.read_csv(results_path, low_memory=False)
    _validate_inputs(summary, results)
    summary = summary.set_index("scenario").loc[list(SCENARIOS)].reset_index()
    numeric_columns = SUMMARY_COLUMNS[1:]
    for column in numeric_columns:
        summary[column] = pd.to_numeric(summary[column], errors="raise")

    normal = summary[summary["scenario"] == "NORMAL_BURST"].iloc[0]
    comparison = summary.copy()
    comparison.insert(
        1,
        "scenario_label",
        comparison["scenario"].map(SCENARIO_LABELS),
    )
    comparison["placement_rate_change_pp"] = (
        comparison["placement_success_rate_percent"]
        - normal["placement_success_rate_percent"]
    )
    comparison["deadline_rate_change_pp"] = (
        comparison["deadline_met_rate_percent"]
        - normal["deadline_met_rate_percent"]
    )
    comparison["queue_wait_ratio_vs_normal"] = comparison[
        "average_queue_wait_ms"
    ].map(lambda value: _ratio(value, normal["average_queue_wait_ms"]))
    comparison["total_time_ratio_vs_normal"] = comparison[
        "average_total_time_ms"
    ].map(lambda value: _ratio(value, normal["average_total_time_ms"]))
    comparison["additional_unplaced_jobs"] = (
        comparison["unplaced_jobs"] - normal["unplaced_jobs"]
    )
    comparison = comparison[list(COMPARISON_COLUMNS)]

    placed_results = results[results["placement_status"] == "PLACED"].copy()
    placed_results["selected_node"] = pd.to_numeric(
        placed_results["selected_node"], errors="raise"
    ).astype(int)
    node_counts = (
        placed_results.groupby(["scenario", "selected_node"], sort=True)
        .size()
        .reset_index(name="placed_job_count")
    )

    summary_rows = [[
        SCENARIO_LABELS[row.scenario],
        str(int(row.total_jobs)),
        str(int(row.placed_jobs)),
        str(int(row.unplaced_jobs)),
        f"{row.placement_success_rate_percent:.2f}%",
        f"{row.deadline_met_rate_percent:.2f}%",
        f"{row.average_queue_wait_ms:.2f}",
        f"{row.maximum_queue_wait_ms:.2f}",
        f"{row.average_total_time_ms:.2f}",
    ] for row in summary.itertuples(index=False)]
    change_rows = [[
        row.scenario_label,
        f"{row.placement_rate_change_pp:+.2f}",
        f"{row.deadline_rate_change_pp:+.2f}",
        _format_ratio(row.queue_wait_ratio_vs_normal),
        _format_ratio(row.total_time_ratio_vs_normal),
        f"{int(row.additional_unplaced_jobs):+d}",
    ] for row in comparison.itertuples(index=False)]
    node_rows = [[
        SCENARIO_LABELS[row.scenario],
        str(row.selected_node),
        str(row.placed_job_count),
    ] for row in node_counts.itertuples(index=False)]

    failure_interpretations = []
    for scenario in SCENARIOS[1:]:
        row = comparison[comparison["scenario"] == scenario].iloc[0]
        failure_interpretations.append(
            f"- {row['scenario_label']}에서는 정상 대비 배치 성공률이 "
            f"{row['placement_rate_change_pp']:+.2f}%p, 마감 준수율이 "
            f"{row['deadline_rate_change_pp']:+.2f}%p 변화했다. 평균 대기시간은 "
            f"{_format_ratio(row['queue_wait_ratio_vs_normal'])}, 평균 완료시간은 "
            f"{_format_ratio(row['total_time_ratio_vs_normal'])}이며, 미배치 작업은 "
            f"{int(row['additional_unplaced_jobs']):+d}개이다."
        )

    report = "\n".join([
        "# 버스트 워크로드 실험 보고서",
        "",
        "## 프로젝트 및 실험 개요",
        "",
        "동일한 결정적 300개 AI 작업을 정상 및 링크 장애 조건에서 "
        "completion-time 배치 방식으로 비교했다.",
        "",
        "## 시나리오 정의",
        "",
        "- 정상: 링크 장애가 없는 기준 시나리오",
        "- 단일 링크 장애: ISL 0-1 장애 시나리오",
        "- 다중 링크 장애: ISL 0-1 및 10-11 동시 장애 시나리오",
        "",
        "## 실험 조건",
        "",
        "- 세 시나리오에 동일한 300개 결정적 버스트 작업을 적용했다.",
        "- 작업 배치는 completion-time 알고리즘으로 수행했다.",
        "- 네트워크 비용은 작업 도착 시점 이전의 가장 가까운 관측값을 사용했다.",
        "- 연산 위성별 독립 단일 서버 큐의 대기시간을 반영했다.",
        "",
        "## 시나리오별 결과 비교표",
        "",
        _markdown_table(
            ["시나리오", "전체", "배치", "미배치", "배치 성공률", "마감 준수율",
             "평균 대기(ms)", "최대 대기(ms)", "평균 완료(ms)"],
            summary_rows,
        ),
        "",
        "## 정상 대비 변화표",
        "",
        _markdown_table(
            ["시나리오", "배치율 변화(%p)", "마감 변화(%p)", "대기시간 비율",
             "완료시간 비율", "추가 미배치"],
            change_rows,
        ),
        "",
        "## 위성별 작업 처리 분포",
        "",
        _markdown_table(["시나리오", "선택 노드", "배치 작업 수"], node_rows),
        "",
        "## 실제 CSV 수치 기반 결과 해석",
        "",
        *failure_interpretations,
        "",
        "링크 장애로 접근 가능한 연산 노드가 줄어들면 남은 노드에 작업이 "
        "집중되며, 위 표의 실제 대기시간·완료시간 및 미배치 변화로 그 영향을 "
        "확인할 수 있다.",
        "",
        "## 한계점",
        "",
        "- 연산 속도는 실제 장비 처리량이 아닌 시뮬레이션용 상대 단위이다.",
        "- 각 연산 위성은 단순화된 단일 서버 큐로 모델링되었다.",
        "- 워크로드는 고정된 결정적 작업 집합이므로 확률적 변동을 반영하지 않는다.",
        "- 전력, 열 및 방사선 환경 모델은 포함하지 않았다.",
        "- 시연을 위해 축소된 위성군을 사용했다.",
        "",
    ])

    report_path = demo_data_dir / "experiment_report.md"
    comparison_path = demo_data_dir / "experiment_comparison.csv"
    report_path.write_text(report, encoding="utf-8")
    comparison.to_csv(comparison_path, index=False)
    return str(report_path), str(comparison_path)


if __name__ == "__main__":
    generated_report, generated_comparison = generate_experiment_report()
    print(generated_report)
    print(generated_comparison)
