# The MIT License (MIT)
#
# Copyright (c) 2020 ETH Zurich
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import random

from .fstate_calculation import *


def algorithm_free_one_only_over_isls(
        output_dynamic_state_dir,
        time_since_epoch_ns,
        satellites,
        ground_stations,
        sat_net_graph_only_satellites_with_isls,
        ground_station_satellites_in_range,
        num_isls_per_sat,
        sat_neighbor_to_if,
        list_gsl_interfaces_info,
        prev_output,
        enable_verbose_logs,
        failed_isls=(),
        random_failure_enabled=False,
        random_failure_seed=42,
        random_failure_start_ns=0,
        random_failure_end_ns=None,
        random_failure_state=None
):
    """
    FREE-ONE ONLY OVER INTER-SATELLITE LINKS ALGORITHM

    "one"
    This algorithm assumes that every satellite and ground station has exactly 1 GSL interface.

    "free"
    This 1 interface is bound to a maximum outgoing bandwidth, but can send to any other
    GSL interface (well, satellite -> ground-station, and ground-station -> satellite) in
    range. ("free") There is no reciprocation of the bandwidth asserted.

    "only_over_isls"
    It calculates a forwarding state, which is essentially a single shortest path.
    It only considers paths which go over the inter-satellite network, and does not make use of ground
    stations relay. This means that every path looks like:
    (src gs) - (sat) - (sat) - ... - (sat) - (dst gs)

    """

    # The failure window is [start, end); None means no scheduled recovery.
    if random_failure_enabled and (
        random_failure_start_ns < 0
        or (random_failure_end_ns is not None
            and random_failure_end_ns <= random_failure_start_ns)
    ):
        raise ValueError("Invalid random failure interval")

    if enable_verbose_logs:
        print("\nALGORITHM: FREE ONE ONLY OVER ISLS")

    # Check the graph
    if sat_net_graph_only_satellites_with_isls.number_of_nodes() != len(satellites):
        raise ValueError("Number of nodes in the graph does not match the number of satellites")
    for sid in range(len(satellites)):
        for n in sat_net_graph_only_satellites_with_isls.neighbors(sid):
            if n >= len(satellites):
                raise ValueError("Graph cannot contain satellite-to-ground-station links")

    #################################
    # BANDWIDTH STATE
    #

    # There is only one GSL interface for each node (pre-condition), which as-such will get the entire bandwidth
    output_filename = output_dynamic_state_dir + "/gsl_if_bandwidth_" + str(time_since_epoch_ns) + ".txt"
    if enable_verbose_logs:
        print("  > Writing interface bandwidth state to: " + output_filename)
    with open(output_filename, "w+") as f_out:
        if time_since_epoch_ns == 0:
            for node_id in range(len(satellites)):
                f_out.write("%d,%d,%f\n"
                            % (node_id, num_isls_per_sat[node_id],
                               list_gsl_interfaces_info[node_id]["aggregate_max_bandwidth"]))
            for node_id in range(len(satellites), len(satellites) + len(ground_stations)):
                f_out.write("%d,%d,%f\n"
                            % (node_id, 0, list_gsl_interfaces_info[node_id]["aggregate_max_bandwidth"]))

    #################################
    # FORWARDING STATE
    #

    # Previous forwarding state (to only write delta)
    prev_fstate = None
    if prev_output is not None:
        prev_fstate = prev_output["fstate"]

    # GID to satellite GSL interface index
    gid_to_sat_gsl_if_idx = [0] * len(ground_stations)  # (Only one GSL interface per satellite, so the first)

    # Forwarding state using shortest paths
    routing_graph = sat_net_graph_only_satellites_with_isls.copy()
    routing_graph.remove_edges_from(failed_isls)
    reachable_compute_nodes = None

    # Reuse simulation state, including an empty selection, across timestamps.
    if random_failure_state is None:
        random_failure_state = (
            prev_output.get("random_failure_state", {})
            if prev_output is not None else {}
        )
    if random_failure_enabled and "link" not in random_failure_state:
        available_isls = sorted(
            (min(left, right), max(left, right))
            for left, right in routing_graph.edges()
        )
        random_failure_state["link"] = (
            random.Random(random_failure_seed).choice(available_isls)
            if available_isls else None
        )
    random_failed_isl = random_failure_state.get("link")
    random_failure_active = (
        random_failure_enabled
        and random_failure_start_ns <= time_since_epoch_ns
        and (random_failure_end_ns is None
             or time_since_epoch_ns < random_failure_end_ns)
    )
    if random_failure_active and random_failed_isl is not None:
        routing_graph.remove_edges_from([random_failed_isl])

    if random_failure_active and time_since_epoch_ns == 0:
        source = 0
        source_component = nx.node_connected_component(routing_graph, source)
        reachable_destinations = sorted(source_component - {source})
        print("\n[Random failed ISL: %s]" % (random_failed_isl,))

        compute_nodes = (0, 3, 7)
        source_component_after_failure = nx.node_connected_component(
            routing_graph, source
        )
        reachable_compute_nodes = [
            node for node in compute_nodes
            if node in source_component_after_failure
        ]
        print("\n[Reachable compute nodes after failure]")
        for node in compute_nodes:
            status = (
                "REACHABLE"
                if node in source_component_after_failure
                else "UNREACHABLE"
            )
            print("SAT-%d: %s" % (node, status))

        if reachable_destinations:
            destination = reachable_destinations[-1]
            candidates = calculate_alternative_path_candidates(
                routing_graph,
                source,
                destination,
                max_paths=3
            )
            print(
                "[Alternative path candidates SAT-%d -> SAT-%d after failure]"
                % (source, destination)
            )
            print(candidates)
        else:
            print("\n[Alternative path candidates: SAT-0 has no reachable destination]")

    fstate = calculate_fstate_shortest_path_without_gs_relaying(
        output_dynamic_state_dir,
        time_since_epoch_ns,
        len(satellites),
        len(ground_stations),
        routing_graph,
        num_isls_per_sat,
        gid_to_sat_gsl_if_idx,
        ground_station_satellites_in_range,
        sat_neighbor_to_if,
        prev_fstate,
        enable_verbose_logs
    )

    if enable_verbose_logs:
        print("")

    return {
        "fstate": fstate,
        "reachable_compute_nodes": reachable_compute_nodes,
        "random_failure_state": random_failure_state
    }
