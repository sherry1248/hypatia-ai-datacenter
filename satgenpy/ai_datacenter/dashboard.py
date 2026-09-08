import math
import os

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st


EARTH_RADIUS_M = 6_371_000.0


def _cartesian_position(
    latitude_deg: float,
    longitude_deg: float,
    altitude_m: float = 0.0,
) -> tuple[float, float, float]:
    latitude = math.radians(latitude_deg)
    longitude = math.radians(longitude_deg)
    radius = EARTH_RADIUS_M + altitude_m
    return (
        radius * math.cos(latitude) * math.cos(longitude),
        radius * math.cos(latitude) * math.sin(longitude),
        radius * math.sin(latitude),
    )


def _elevated_arc(
    start: tuple[float, float, float],
    end: tuple[float, float, float],
    point_count: int = 40,
) -> tuple[list[float], list[float], list[float]]:
    start_radius = math.sqrt(sum(value * value for value in start))
    end_radius = math.sqrt(sum(value * value for value in end))
    start_unit = tuple(value / start_radius for value in start)
    end_unit = tuple(value / end_radius for value in end)
    dot = max(-1.0, min(1.0, sum(
        start_unit[index] * end_unit[index] for index in range(3)
    )))
    angle = math.acos(dot)
    sin_angle = math.sin(angle)
    lift = abs(start_radius - end_radius) / 2 + max(
        180_000.0, angle * EARTH_RADIUS_M * 0.12
    )
    coordinates: list[tuple[float, float, float]] = []
    for index in range(point_count):
        fraction = index / (point_count - 1)
        if abs(sin_angle) < 1e-9:
            direction = tuple(
                start_unit[axis] * (1 - fraction)
                + end_unit[axis] * fraction
                for axis in range(3)
            )
            direction_norm = math.sqrt(sum(value * value for value in direction))
            direction = tuple(value / direction_norm for value in direction)
        else:
            start_weight = math.sin((1 - fraction) * angle) / sin_angle
            end_weight = math.sin(fraction * angle) / sin_angle
            direction = tuple(
                start_unit[axis] * start_weight
                + end_unit[axis] * end_weight
                for axis in range(3)
            )
        radius = (
            start_radius * (1 - fraction)
            + end_radius * fraction
            + lift * math.sin(math.pi * fraction)
        )
        coordinates.append(tuple(radius * value for value in direction))
    return tuple(
        [coordinate[axis] for coordinate in coordinates]
        for axis in range(3)
    )


def _add_dynamic_load_markers(figure: go.Figure) -> None:
    figure.add_vline(
        x=60,
        line_dash="dash",
        annotation_text="7번 위성 고부하 시작",
    )
    figure.add_vline(
        x=120,
        line_dash="dash",
        annotation_text="7번 위성 정상 복구",
    )


def _render_burst_workload_section(demo_data_dir: str) -> None:
    st.header("버스트 워크로드 시나리오 비교")
    summary_path = os.path.join(
        demo_data_dir, "workload_experiment_summary.csv"
    )
    results_path = os.path.join(
        demo_data_dir, "workload_experiment_results.csv"
    )
    if not os.path.isfile(summary_path) or not os.path.isfile(results_path):
        st.info(
            "버스트 워크로드 실험 결과가 없습니다. "
            "워크로드 실험을 먼저 실행해 주세요."
        )
        return

    try:
        experiment_summary = pd.read_csv(summary_path)
        experiment_results = pd.read_csv(results_path, low_memory=False)
    except (OSError, pd.errors.EmptyDataError, pd.errors.ParserError):
        st.info("버스트 워크로드 실험 결과를 불러올 수 없습니다.")
        return
    if experiment_summary.empty or experiment_results.empty:
        st.info("버스트 워크로드 실험 결과가 비어 있습니다.")
        return

    burst_scenario_names = {
        "NORMAL_BURST": "정상",
        "FAILED_ISL_0_1_BURST": "단일 링크 장애",
        "MULTI_FAILED_ISL_0_1_10_11_BURST": "다중 링크 장애",
    }
    numeric_columns = (
        "total_jobs",
        "placed_jobs",
        "unplaced_jobs",
        "placement_success_rate_percent",
        "deadline_met_rate_percent",
        "average_queue_wait_ms",
        "maximum_queue_wait_ms",
        "average_total_time_ms",
    )
    for column in numeric_columns:
        experiment_summary[column] = pd.to_numeric(
            experiment_summary[column], errors="coerce"
        )
    experiment_summary["시나리오"] = experiment_summary["scenario"].map(
        burst_scenario_names
    ).fillna(experiment_summary["scenario"])
    experiment_summary["평균 대기시간 (초)"] = (
        experiment_summary["average_queue_wait_ms"] / 1000.0
    )
    experiment_summary["최대 대기시간 (초)"] = (
        experiment_summary["maximum_queue_wait_ms"] / 1000.0
    )
    experiment_summary["평균 완료시간 (초)"] = (
        experiment_summary["average_total_time_ms"] / 1000.0
    )

    scenario_values = experiment_summary["scenario"].dropna().tolist()
    selected_scenario = st.selectbox(
        "버스트 실험 시나리오",
        scenario_values,
        format_func=lambda value: burst_scenario_names.get(value, value),
    )
    selected_summary = experiment_summary[
        experiment_summary["scenario"] == selected_scenario
    ].iloc[0]
    first_metrics = st.columns(4)
    first_metrics[0].metric("전체 작업 수", int(selected_summary["total_jobs"]))
    first_metrics[1].metric("배치 성공 작업", int(selected_summary["placed_jobs"]))
    first_metrics[2].metric("미배치 작업", int(selected_summary["unplaced_jobs"]))
    first_metrics[3].metric(
        "배치 성공률",
        f"{selected_summary['placement_success_rate_percent']:.1f}%",
    )
    second_metrics = st.columns(3)
    second_metrics[0].metric(
        "마감 준수율",
        f"{selected_summary['deadline_met_rate_percent']:.1f}%",
    )
    second_metrics[1].metric(
        "평균 대기시간",
        f"{selected_summary['평균 대기시간 (초)']:.2f}초",
    )
    second_metrics[2].metric(
        "평균 완료시간",
        f"{selected_summary['평균 완료시간 (초)']:.2f}초",
    )

    chart_specs = (
        (
            "placement_success_rate_percent",
            "배치 성공률 (%)",
            "시나리오별 배치 성공률",
        ),
        (
            "평균 대기시간 (초)",
            "평균 대기시간 (초)",
            "시나리오별 평균 대기시간",
        ),
        (
            "평균 완료시간 (초)",
            "평균 완료시간 (초)",
            "시나리오별 평균 완료시간",
        ),
        (
            "deadline_met_rate_percent",
            "마감 준수율 (%)",
            "시나리오별 마감 준수율",
        ),
    )
    chart_columns = st.columns(2)
    for index, (value_column, axis_label, title) in enumerate(chart_specs):
        figure = px.bar(
            experiment_summary,
            x="시나리오",
            y=value_column,
            color="시나리오",
            title=title,
            labels={value_column: axis_label},
            hover_data={"최대 대기시간 (초)": ":.2f"},
        )
        figure.update_layout(showlegend=False, height=360)
        chart_columns[index % 2].plotly_chart(
            figure, use_container_width=True
        )

    placed_results = experiment_results[
        experiment_results["placement_status"] == "PLACED"
    ].copy()
    placed_results["selected_node"] = pd.to_numeric(
        placed_results["selected_node"], errors="coerce"
    )
    placed_results = placed_results.dropna(subset=["selected_node"])
    placed_results["selected_node"] = placed_results["selected_node"].astype(int)
    placed_results["시나리오"] = placed_results["scenario"].map(
        burst_scenario_names
    ).fillna(placed_results["scenario"])
    node_counts = (
        placed_results.groupby(["시나리오", "selected_node"])
        .size()
        .reset_index(name="처리 작업 수")
    )
    st.plotly_chart(
        px.bar(
            node_counts,
            x="selected_node",
            y="처리 작업 수",
            color="시나리오",
            barmode="group",
            title="시나리오별 연산 위성 처리 작업 수",
            labels={"selected_node": "연산 위성 ID"},
        ),
        use_container_width=True,
    )
    st.info(
        "단일 링크 장애는 대부분 우회 경로로 흡수됩니다. "
        "다중 링크 장애에서는 일부 연산 위성이 도달 불가능해지고, "
        "남은 위성으로 부하가 집중되어 대기시간과 완료시간이 크게 증가합니다."
    )


def main() -> None:
    st.set_page_config(layout="wide")
    st.title("우주 AI 데이터센터 작업 배치 대시보드")
    csv_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "demo_data",
        "placement_results.csv",
    )
    positions_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "demo_data",
        "node_positions.csv",
    )
    if not os.path.isfile(csv_path):
        st.error("placement_results.csv was not found.")
        return

    try:
        dataframe = pd.read_csv(
            csv_path,
            dtype={"failed_isls": "string"},
            low_memory=False,
        )
    except pd.errors.EmptyDataError:
        st.error("placement_results.csv is empty.")
        return
    if dataframe.empty:
        st.error("placement_results.csv is empty.")
        return
    if not os.path.isfile(positions_path):
        st.error("node_positions.csv was not found.")
        return
    try:
        node_positions = pd.read_csv(positions_path)
    except pd.errors.EmptyDataError:
        st.error("node_positions.csv is empty.")
        return
    if node_positions.empty:
        st.error("node_positions.csv is empty.")
        return

    scenarios = dataframe["scenario"].dropna().unique().tolist()
    algorithms = dataframe["algorithm"].dropna().unique().tolist()
    scenario_names = {
        "NORMAL": "정상",
        "FAILED_ISL_0_1": "위성 링크 0-1 장애",
        "MULTI_FAILED_ISL_0_1_10_11": "위성 링크 0-1·10-11 다중 장애",
        "HIGH_LOAD_NODE_7": "7번 위성 고부하",
        "DYNAMIC_LOAD_NODE_7": "7번 위성 동적 부하",
    }
    scenario = st.selectbox(
        "시나리오",
        scenarios,
        format_func=lambda value: scenario_names.get(value, value),
    )
    selected_algorithms = st.multiselect(
        "배치 알고리즘", algorithms, default=algorithms
    )
    filtered = dataframe[
        (dataframe["scenario"] == scenario)
        & dataframe["algorithm"].isin(selected_algorithms)
    ].copy()
    if filtered.empty:
        st.error("No placement results match the selected filters.")
        return

    filtered["time_ns"] = pd.to_numeric(
        filtered["time_ns"],
        errors="coerce"
    )
    filtered = filtered.dropna(subset=["time_ns"]).copy()

    if filtered.empty:
        st.error("유효한 시간 데이터가 없습니다.")
        return

    placed = filtered[
        filtered["placement_status"] == "PLACED"
    ].copy()

    unplaced = filtered[
        filtered["placement_status"] == "UNPLACED"
    ].copy()

    filtered["time_s"] = filtered["time_ns"] / 1_000_000_000
    placed["time_s"] = placed["time_ns"] / 1_000_000_000
    unplaced["time_s"] = unplaced["time_ns"] / 1_000_000_000

    filtered["rtt_ms"] = (
        pd.to_numeric(filtered["rtt_ns"], errors="coerce") / 1_000_000
    )
    placed["rtt_ms"] = (
        pd.to_numeric(placed["rtt_ns"], errors="coerce") / 1_000_000
    )

    st.caption(
        f"데이터 시점 범위 (ns): {filtered['time_ns'].min()} ~ "
        f"{filtered['time_ns'].max()}"
    )
    if scenario == "MULTI_FAILED_ISL_0_1_10_11":
        st.info(
            "다중 링크 장애로 인해 일부 시간 구간에는 도달 가능한 "
            "연산 위성이 없어 작업을 배치하지 못할 수 있습니다."
        )
    st.header("LEO 위성 네트워크 현황")
    node_positions["time_ns"] = pd.to_numeric(
        node_positions["time_ns"], errors="coerce"
    )
    node_positions["node_id"] = pd.to_numeric(
        node_positions["node_id"], errors="coerce"
    )
    node_positions["latitude_deg"] = pd.to_numeric(
        node_positions["latitude_deg"], errors="coerce"
    )
    node_positions["longitude_deg"] = pd.to_numeric(
        node_positions["longitude_deg"], errors="coerce"
    )
    node_positions["altitude_m"] = pd.to_numeric(
        node_positions["altitude_m"], errors="coerce"
    )
    node_positions = node_positions.dropna(
        subset=["time_ns", "node_id", "latitude_deg", "longitude_deg"]
    ).copy()
    node_positions["node_id"] = node_positions["node_id"].astype(int)

    scenario_times: list[int] = sorted(
        int(time_ns) for time_ns in filtered["time_ns"].unique()
    )
    selected_time_ns: int = st.select_slider(
        "시각화 시점",
        options=scenario_times,
        format_func=lambda time_ns: f"{time_ns / 1_000_000_000:.1f}초",
    )
    visualization_algorithms: list[str] = [
        algorithm
        for algorithm in selected_algorithms
        if algorithm in filtered["algorithm"].unique()
    ]
    visualization_algorithm: str = st.selectbox(
        "시각화 알고리즘",
        visualization_algorithms,
    )
    selected_rows = filtered[
        (filtered["time_ns"] == selected_time_ns)
        & (filtered["algorithm"] == visualization_algorithm)
    ]
    selected_row = selected_rows.iloc[0]
    timestamp_positions = node_positions[
        node_positions["time_ns"] == selected_time_ns
    ]

    network_figure = go.Figure()
    satellites = timestamp_positions[
        timestamp_positions["node_type"] == "SATELLITE"
    ]
    ground_stations = timestamp_positions[
        timestamp_positions["node_type"] == "GROUND_STATION"
    ]
    other_satellites = satellites[
        ~satellites["node_id"].isin([0, 3, 7])
    ]
    compute_satellites = satellites[
        satellites["node_id"].isin([0, 3, 7])
    ]
    sphere_latitudes = [math.radians(-90 + index * 6) for index in range(31)]
    sphere_longitudes = [math.radians(-180 + index * 6) for index in range(61)]
    sphere_x = [
        [EARTH_RADIUS_M * math.cos(lat) * math.cos(lon) for lon in sphere_longitudes]
        for lat in sphere_latitudes
    ]
    sphere_y = [
        [EARTH_RADIUS_M * math.cos(lat) * math.sin(lon) for lon in sphere_longitudes]
        for lat in sphere_latitudes
    ]
    sphere_z = [[
        EARTH_RADIUS_M * math.sin(lat) for _ in sphere_longitudes
    ] for lat in sphere_latitudes]
    surface_color = [[
        (
            math.sin(2.4 * lon + 0.7 * math.sin(3 * lat))
            + 0.65 * math.cos(3.2 * lat - 1.3 * lon)
            + 0.35 * math.sin(6 * lat + lon)
        )
        for lon in sphere_longitudes
    ] for lat in sphere_latitudes]
    network_figure.add_trace(go.Surface(
        x=sphere_x,
        y=sphere_y,
        z=sphere_z,
        surfacecolor=surface_color,
        colorscale=[
            [0.0, "#071e3d"],
            [0.43, "#0d4f73"],
            [0.5, "#176b65"],
            [0.68, "#4f7942"],
            [1.0, "#b6a269"],
        ],
        showscale=False,
        hoverinfo="skip",
        name="Earth",
    ))
    atmosphere_radius = EARTH_RADIUS_M * 1.018
    atmosphere_scale = atmosphere_radius / EARTH_RADIUS_M
    network_figure.add_trace(go.Surface(
        x=[[value * atmosphere_scale for value in row] for row in sphere_x],
        y=[[value * atmosphere_scale for value in row] for row in sphere_y],
        z=[[value * atmosphere_scale for value in row] for row in sphere_z],
        surfacecolor=[[1.0 for _ in row] for row in sphere_z],
        colorscale=[[0, "#60a5fa"], [1, "#60a5fa"]],
        opacity=0.1,
        showscale=False,
        hoverinfo="skip",
        showlegend=False,
    ))

    positions_by_node: dict[int, tuple[float, float, float]] = {}
    for row in timestamp_positions.itertuples():
        altitude_m = 0.0
        if row.node_type == "SATELLITE":
            if pd.isna(row.altitude_m):
                continue
            altitude_m = float(row.altitude_m)
        positions_by_node[int(row.node_id)] = _cartesian_position(
            float(row.latitude_deg), float(row.longitude_deg), altitude_m
        )

    def add_nodes(
        rows: pd.DataFrame,
        name: str,
        color: str,
        size: int,
        show_labels: bool = False,
    ) -> None:
        nodes = [
            (int(row.node_id), positions_by_node[int(row.node_id)])
            for row in rows.itertuples()
            if int(row.node_id) in positions_by_node
        ]
        if not nodes:
            return
        network_figure.add_trace(go.Scatter3d(
            x=[position[0] for _, position in nodes],
            y=[position[1] for _, position in nodes],
            z=[position[2] for _, position in nodes],
            text=[f"{name} {node_id}" for node_id, _ in nodes],
            hovertemplate="%{text}<extra></extra>",
            mode="markers+text" if show_labels else "markers",
            textposition="top center",
            marker={"size": size, "color": color, "opacity": 0.85},
            name=name,
        ))

    add_nodes(other_satellites, "위성", "#718096", 2)
    add_nodes(compute_satellites, "연산 위성", "#38bdf8", 5)
    add_nodes(ground_stations, "지상국", "#facc15", 6, show_labels=True)

    placement_status = str(selected_row["placement_status"])
    route = (
        str(selected_row["route"])
        if pd.notna(selected_row["route"]) else ""
    )
    failed_isls: list[tuple[int, int]] = []
    if scenario == "FAILED_ISL_0_1":
        failed_isls = [(0, 1)]
    elif scenario == "MULTI_FAILED_ISL_0_1_10_11":
        failed_isls = [(0, 1), (10, 11)]
    failed_edges = {
        edge
        for from_node, to_node in failed_isls
        for edge in ((from_node, to_node), (to_node, from_node))
    }
    if placement_status == "PLACED" and route:
        route_nodes: list[int] = [
            int(node_id) for node_id in route.split("-")
        ]
        route_x: list[float | None] = []
        route_y: list[float | None] = []
        route_z: list[float | None] = []
        for from_node, to_node in zip(route_nodes, route_nodes[1:]):
            if (
                (from_node, to_node) in failed_edges
                or from_node not in positions_by_node
                or to_node not in positions_by_node
            ):
                continue
            from_position = positions_by_node[from_node]
            to_position = positions_by_node[to_node]
            arc_x, arc_y, arc_z = _elevated_arc(from_position, to_position)
            route_x.extend([*arc_x, None])
            route_y.extend([*arc_y, None])
            route_z.extend([*arc_z, None])
        if route_x:
            network_figure.add_trace(go.Scatter3d(
                x=route_x,
                y=route_y,
                z=route_z,
                mode="lines",
                line={"width": 6, "color": "#fb923c"},
                hoverinfo="skip",
                name="활성 경로",
            ))

    selected_node = int(selected_row["selected_node"])
    if placement_status == "PLACED" and selected_node in positions_by_node:
        position = positions_by_node[selected_node]
        network_figure.add_trace(go.Scatter3d(
            x=[position[0]],
            y=[position[1]],
            z=[position[2]],
            text=[f"선택 위성 {selected_node}"],
            mode="markers+text",
            textposition="top center",
            marker={
                "size": 9,
                "color": "#f43f5e",
                "symbol": "diamond",
                "line": {"width": 1.5, "color": "white"},
            },
            name="선택 연산 위성",
        ))

    for from_node, to_node in failed_isls:
        if from_node not in positions_by_node or to_node not in positions_by_node:
            continue
        from_position = positions_by_node[from_node]
        to_position = positions_by_node[to_node]
        arc_x, arc_y, arc_z = _elevated_arc(from_position, to_position)
        network_figure.add_trace(go.Scatter3d(
            x=arc_x,
            y=arc_y,
            z=arc_z,
            mode="lines",
            line={"width": 2, "color": "#ef4444", "dash": "dash"},
            hovertext=f"장애 ISL {from_node}-{to_node}",
            name=f"장애 ISL {from_node}-{to_node}",
        ))
    network_figure.update_layout(
        height=720,
        margin={"l": 0, "r": 0, "t": 10, "b": 0},
        paper_bgcolor="#020617",
        scene={
            "aspectmode": "data",
            "camera": {"eye": {"x": 1.2, "y": 1.2, "z": 0.7}},
            "xaxis": {"visible": False, "showgrid": False},
            "yaxis": {"visible": False, "showgrid": False},
            "zaxis": {"visible": False, "showgrid": False},
            "bgcolor": "#020617",
        },
        legend={
            "orientation": "h",
            "x": 0.5,
            "xanchor": "center",
            "y": 0.01,
            "font": {"size": 11, "color": "#e2e8f0"},
        },
    )
    st.plotly_chart(network_figure, use_container_width=True)

    rtt_value = (
        selected_row["rtt_ns"]
        if pd.notna(selected_row["rtt_ns"]) else ""
    )
    detail_metrics = st.columns(6)
    detail_metrics[0].metric("시점", f"{selected_time_ns / 1e9:.1f}초")
    detail_metrics[1].metric("알고리즘", visualization_algorithm)
    detail_metrics[2].metric("선택 위성", selected_node)
    detail_metrics[3].metric("상태", placement_status)
    detail_metrics[4].metric("RTT", f"{rtt_value} ns" if rtt_value != "" else "-")
    detail_metrics[5].metric("경로", route or "-")
    if scenario == "MULTI_FAILED_ISL_0_1_10_11":
        st.write("장애 ISL: 0-1, 10-11")
        if placement_status == "UNPLACED":
            st.warning(
                "현재 시점에는 도달 가능한 연산 위성이 없어 "
                "작업이 배치되지 않았습니다."
            )

    selected_node_figure = go.Figure()

    completion = placed[
        filtered["algorithm"] == "completion_time"
    ].copy()
    if not completion.empty:
        completion["total_time_ms"] = pd.to_numeric(
            completion["total_time_ms"], errors="coerce"
        )

    placement_metrics = st.columns(3)
    placement_metrics[0].metric("배치 성공 행", len(placed))
    placement_metrics[1].metric("미배치 행", len(unplaced))
    placement_metrics[2].metric(
        "배치 성공률",
        f"{len(placed) / len(filtered) * 100:.2f}%",
    )
    if not unplaced.empty:
        first_time_s: float = float(filtered["time_s"].min())
        last_time_s: float = float(filtered["time_s"].max())
        placed_times = sorted(placed["time_s"].unique())
        recovery_time_s: float | None = next(
            (
                float(time_s)
                for time_s in placed_times
                if time_s >= first_time_s
            ),
            None,
        )
        outage_duration_s = (
            recovery_time_s - first_time_s
            if recovery_time_s is not None
            else last_time_s - first_time_s
        )
        recovery_metrics = st.columns(3)
        recovery_metrics[0].metric(
            "최초 배치 가능 시점",
            (
                f"{recovery_time_s:.1f}초"
                if recovery_time_s is not None else "없음"
            ),
        )
        recovery_metrics[1].metric(
            "초기 서비스 중단 시간",
            f"{outage_duration_s:.1f}초",
        )
        recovery_metrics[2].metric(
            "배치 복구 상태",
            "복구 완료" if recovery_time_s is not None else "복구 실패",
        )

    metric_columns = st.columns(5 if not completion.empty else 4)
    metric_columns[0].metric(
        "시뮬레이션 시점", filtered["time_ns"].nunique()
    )
    metric_columns[1].metric(
        "비교 알고리즘", filtered["algorithm"].nunique()
    )
    metric_columns[2].metric(
        "최다 선택 위성",
        placed["selected_node"].mode().iloc[0] if not placed.empty else "",
    )
    metric_columns[3].metric(
        "평균 RTT (ms)",
        f"{placed['rtt_ms'].mean():.2f}" if not placed.empty else "",
    )
    if not completion.empty:
        metric_columns[4].metric(
            "평균 예상 완료시간 (ms)",
            f"{completion['total_time_ms'].mean():.2f}",
        )
    if scenario == "DYNAMIC_LOAD_NODE_7":
        st.info(
            "60초부터 120초까지 7번 위성의 GPU 사용률은 95%, "
            "작업 큐 길이는 10으로 설정됩니다."
        )

    selected_node_figure = go.Figure()
    for algorithm in selected_algorithms:
        algorithm_rows = placed[
            filtered["algorithm"] == algorithm
        ].sort_values("time_s")
        selected_node_figure.add_trace(go.Scatter(
            x=algorithm_rows["time_s"],
            y=algorithm_rows["selected_node"],
            mode="lines+markers",
            line_shape="hv",
            name=algorithm,
        ))
    selected_node_figure.update_layout(
        title="시간에 따른 연산 위성 선택",
        xaxis_title="시뮬레이션 시간 (초)",
        yaxis_title="선택 위성 ID",
        height=500,
    )
    selected_node_figure.update_yaxes(
        tickmode="array",
        tickvals=sorted(placed["selected_node"].unique()),
    )
    if scenario == "DYNAMIC_LOAD_NODE_7":
        _add_dynamic_load_markers(selected_node_figure)
    st.plotly_chart(selected_node_figure, use_container_width=True)

    rtt_figure = px.line(
        placed,
        x="time_s",
        y="rtt_ms",
        color="algorithm",
        title="시간에 따른 RTT 변화",
        labels={
            "time_s": "시뮬레이션 시간 (초)",
            "rtt_ms": "RTT (ms)",
        },
    )
    if scenario == "DYNAMIC_LOAD_NODE_7":
        _add_dynamic_load_markers(rtt_figure)
    st.plotly_chart(rtt_figure, use_container_width=True)

    if not completion.empty:
        completion_figure = px.line(
            completion,
            x="time_s",
            y="total_time_ms",
            title="예상 작업 완료시간",
            labels={
                "time_s": "시뮬레이션 시간 (초)",
                "total_time_ms": "예상 완료시간 (ms)",
            },
        )
        if scenario == "DYNAMIC_LOAD_NODE_7":
            _add_dynamic_load_markers(completion_figure)
        st.plotly_chart(completion_figure, use_container_width=True)

    selection_counts = (
        placed.groupby(["algorithm", "selected_node"])
        .size()
        .reset_index(name="selection_count")
    )
    st.plotly_chart(
        px.bar(
            selection_counts,
            x="algorithm",
            y="selection_count",
            color="selected_node",
            title="알고리즘별 연산 위성 선택 횟수",
            labels={
                "algorithm": "배치 알고리즘",
                "selection_count": "선택 횟수",
            },
        ),
        use_container_width=True,
    )
    st.dataframe(selection_counts, use_container_width=True)

    st.header("정상·장애·고부하 시나리오 비교")
    comparison = dataframe[
        dataframe["placement_status"] == "PLACED"
    ].copy()
    comparison["average_rtt_ms"] = (
        pd.to_numeric(comparison["rtt_ns"], errors="coerce") / 1_000_000
    )
    comparison["average_total_time_ms"] = pd.to_numeric(
        comparison["total_time_ms"], errors="coerce"
    )
    summary = (
        comparison.groupby(["scenario", "algorithm"])
        .agg(
            most_selected_node=(
                "selected_node",
                lambda values: values.mode().iloc[0],
            ),
            average_rtt_ms=("average_rtt_ms", "mean"),
            average_total_time_ms=("average_total_time_ms", "mean"),
            timestamp_count=("time_ns", "nunique"),
        )
        .reset_index()
    )
    transition_rows = []
    for algorithm in summary["algorithm"].unique():
        algorithm_summary = summary[summary["algorithm"] == algorithm]
        normal_nodes = algorithm_summary[
            algorithm_summary["scenario"] == "NORMAL"
        ]["most_selected_node"]
        failed_nodes = algorithm_summary[
            algorithm_summary["scenario"] == "FAILED_ISL_0_1"
        ]["most_selected_node"]
        high_load_nodes = algorithm_summary[
            algorithm_summary["scenario"] == "HIGH_LOAD_NODE_7"
        ]["most_selected_node"]
        normal_node = normal_nodes.iloc[0] if not normal_nodes.empty else ""
        failed_node = failed_nodes.iloc[0] if not failed_nodes.empty else ""
        high_load_node = (
            high_load_nodes.iloc[0] if not high_load_nodes.empty else ""
        )
        transition_rows.append({
            "배치 알고리즘": algorithm,
            "정상 최다 선택 위성": normal_node,
            "링크 장애 시 최다 선택 위성": failed_node,
            "7번 고부하 시 최다 선택 위성": high_load_node,
            "장애 시 선택 변경": (
                "" if normal_node == "" or failed_node == ""
                else "예" if normal_node != failed_node else "아니오"
            ),
            "고부하 시 선택 변경": (
                "" if normal_node == "" or high_load_node == ""
                else "예" if normal_node != high_load_node else "아니오"
            ),
        })

    summary["scenario"] = summary["scenario"].map(scenario_names)
    summary_display = summary.rename(columns={
        "scenario": "시나리오",
        "algorithm": "배치 알고리즘",
        "most_selected_node": "최다 선택 위성",
        "average_rtt_ms": "평균 RTT (ms)",
        "average_total_time_ms": "평균 예상 완료시간 (ms)",
        "timestamp_count": "시뮬레이션 시점 수",
    })
    st.dataframe(summary_display, use_container_width=True)
    st.plotly_chart(
        px.bar(
            summary_display,
            x="배치 알고리즘",
            y="평균 RTT (ms)",
            color="시나리오",
            barmode="group",
            title="시나리오별 평균 RTT 비교",
        ),
        use_container_width=True,
    )
    st.plotly_chart(
        px.bar(
            summary_display,
            x="배치 알고리즘",
            y="최다 선택 위성",
            color="시나리오",
            barmode="group",
            title="시나리오별 알고리즘 최다 선택 위성",
        ),
        use_container_width=True,
    )

    completion_summary = summary_display[
        summary_display["배치 알고리즘"] == "completion_time"
    ]
    st.plotly_chart(
        px.bar(
            completion_summary,
            x="시나리오",
            y="평균 예상 완료시간 (ms)",
            title="시나리오별 평균 예상 완료시간 비교",
        ),
        use_container_width=True,
    )
    st.dataframe(
        pd.DataFrame(transition_rows),
        use_container_width=True,
    )
    _render_burst_workload_section(
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "demo_data")
    )


if __name__ == "__main__":
    main()
