"""Minimal Streamlit demo for ISL failure rerouting."""

import csv
import sys
from pathlib import Path

try:
    import streamlit as st
except ImportError:
    print(
        "Missing dependency: streamlit. Install streamlit to run this demo.",
        file=sys.stderr,
    )
    raise SystemExit(1)

try:
    import networkx as nx
except ImportError:
    st.error("Missing dependency: networkx. Install networkx to run this demo.")
    st.stop()

try:
    import plotly.graph_objects as go
except ImportError:
    st.error("Missing dependency: plotly. Install plotly to run this demo.")
    st.stop()


FALLBACK_ROUTES = {
    "NORMAL": [12, 1, 0, 3, 13],
    "FAILED ISL (0, 1)": [12, 9, 10, 11, 7, 13],
}
DEMO_DATA_DIR = Path(__file__).resolve().parent / "demo_data"
TELEMETRY_FILE = DEMO_DATA_DIR / "routing_events.csv"
FAILED_EDGE = (0, 1)
ALL_EDGES = {
    (12, 1),
    (1, 0),
    (0, 3),
    (3, 13),
    (12, 9),
    (9, 10),
    (10, 11),
    (11, 7),
    (7, 13),
}


def read_telemetry(path):
    required_columns = {
        "time_ns", "source", "destination", "route", "rtt_ns",
        "hop_count", "failed_isls", "status",
    }
    try:
        with path.open("r") as route_file:
            reader = csv.DictReader(route_file)
            if not reader.fieldnames or not required_columns.issubset(reader.fieldnames):
                raise ValueError("required telemetry columns are missing")

            rows = []
            for row in reader:
                time_ns = int(row["time_ns"])
                route = (
                    [int(node) for node in row["route"].split("-")]
                    if row["route"]
                    else []
                )
                rows.append({
                    "time_ns": time_ns,
                    "route": route,
                    "rtt_ms": (
                        float(row["rtt_ns"]) / 1_000_000
                        if row["rtt_ns"]
                        else None
                    ),
                    "hop_count": int(row["hop_count"]),
                    "failed_isls": row["failed_isls"].strip(),
                    "status": row["status"].strip(),
                })

        if not rows:
            raise ValueError("telemetry file is empty")
        return rows, None
    except (OSError, ValueError, TypeError, csv.Error) as error:
        return [], str(error)


def edge_key(left, right):
    return frozenset((left, right))


def edge_trace(graph, positions, edges, color, width, dash="solid"):
    x_values = []
    y_values = []
    for left, right in edges:
        x0, y0 = positions[left]
        x1, y1 = positions[right]
        x_values.extend((x0, x1, None))
        y_values.extend((y0, y1, None))
    return go.Scatter(
        x=x_values,
        y=y_values,
        mode="lines",
        line=dict(color=color, width=width, dash=dash),
        hoverinfo="skip",
        showlegend=False,
    )


def build_figure(route, failed):
    nodes = {node for edge in ALL_EDGES for node in edge}
    nodes.update(route)
    nodes.update(FAILED_EDGE)

    graph = nx.Graph()
    graph.add_nodes_from(nodes)
    graph.add_edges_from(ALL_EDGES)
    active_edges = list(zip(route, route[1:]))
    graph.add_edges_from(active_edges)
    positions = nx.spring_layout(graph, seed=7)
    

    figure = go.Figure()
    figure.add_trace(edge_trace(graph, positions, graph.edges(), "#A0A0A0", 2))
    figure.add_trace(edge_trace(graph, positions, active_edges, "#16A34A", 7))
    if failed:
        figure.add_trace(
            edge_trace(graph, positions, [FAILED_EDGE], "#DC2626", 5, "dash")
        )

    figure.add_trace(
        go.Scatter(
            x=[positions[node][0] for node in graph.nodes()],
            y=[positions[node][1] for node in graph.nodes()],
            mode="markers+text",
            text=[str(node) for node in graph.nodes()],
            textposition="middle center",
            marker=dict(size=34, color="#E2E8F0", line=dict(color="#334155", width=2)),
            textfont=dict(color="#0F172A", size=13),
            hovertemplate="Node %{text}<extra></extra>",
            showlegend=False,
        )
    )
    figure.update_layout(
        margin=dict(l=10, r=10, t=10, b=10),
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        plot_bgcolor="white",
        height=560,
    )
    return figure


st.set_page_config(page_title="ISL Routing Demo", layout="wide")
st.title("ISL Routing Demo")

scenario = st.radio(
    "Scenario",
    ("NORMAL", "FAILED ISL (0, 1)"),
    horizontal=True,
)
failed_scenario = scenario == "FAILED ISL (0, 1)"
telemetry, telemetry_error = read_telemetry(TELEMETRY_FILE)
st.caption(f"Telemetry file: `{TELEMETRY_FILE}`")

if telemetry_error:
    st.warning(
        f"Could not read valid telemetry ({telemetry_error}); "
        "using the built-in fallback route."
    )
    scenario_rows = [{
        "time_ns": 0,
        "route": FALLBACK_ROUTES[scenario],
        "rtt_ms": None,
        "hop_count": len(FALLBACK_ROUTES[scenario]) - 1,
        "failed_isls": "0-1" if failed_scenario else "",
        "status": "REROUTED" if failed_scenario else "NORMAL",
    }]
else:
    scenario_rows = [
        row for row in telemetry
        if (
            "0-1" in row["failed_isls"].split(";")
            if failed_scenario
            else not row["failed_isls"]
        )
    ]
    scenario_rows.sort(key=lambda row: row["time_ns"])
    if not scenario_rows:
        st.warning(
            f"No {scenario} telemetry rows were found; "
            "using the built-in fallback route."
        )
        scenario_rows = [{
            "time_ns": 0,
            "route": FALLBACK_ROUTES[scenario],
            "rtt_ms": None,
            "hop_count": len(FALLBACK_ROUTES[scenario]) - 1,
            "failed_isls": "0-1" if failed_scenario else "",
            "status": "REROUTED" if failed_scenario else "NORMAL",
        }]

time_ns = st.select_slider(
    "Simulation time (ns)",
    options=[row["time_ns"] for row in scenario_rows],
)
selected = next(row for row in scenario_rows if row["time_ns"] == time_ns)
route = selected["route"]
failed = "0-1" in selected["failed_isls"].split(";")

top_left, top_middle, top_right = st.columns(3)
top_left.metric("Current route", "-".join(map(str, route)) if route else "No route")
top_middle.metric(
    "RTT",
    f"{selected['rtt_ms']:.3f} ms" if selected["rtt_ms"] is not None else "—",
)
top_right.metric("Hop count", selected["hop_count"])

bottom_left, bottom_middle, bottom_right = st.columns(3)
bottom_left.metric("Failed ISL", selected["failed_isls"] or "None")
bottom_middle.metric("Status", selected["status"])
bottom_right.metric("Simulation time", f"{time_ns / 1_000_000_000:.3f} s")

st.plotly_chart(build_figure(route, failed), use_container_width=True)
