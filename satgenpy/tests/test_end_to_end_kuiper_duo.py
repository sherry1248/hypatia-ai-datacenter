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

import csv
import satgen
import unittest
from unittest.mock import patch
from satgen.dynamic_state.generate_dynamic_state import generate_dynamic_state
import math
import os
import random
import exputil
from astropy import units as u
from ai_datacenter.placement import load_network_costs, select_after_failure
from ai_datacenter import create_demo_job, get_compute_nodes
from ai_datacenter.run_demo import main as run_placement_demo, _build_scenario_rows


# WGS72 value; taken from https://geographiclib.sourceforge.io/html/NET/NETGeographicLib_8h_source.html
EARTH_RADIUS = 6378135.0

# Target altitude of ~630 km
ALTITUDE_M = 630000

# Considering an elevation angle of 30 degrees; possible values [1]: 20(min)/30/35/45
SATELLITE_CONE_RADIUS_M = ALTITUDE_M / math.tan(math.radians(30.0))

# Maximum GSL length
MAX_GSL_LENGTH_M = math.sqrt(math.pow(SATELLITE_CONE_RADIUS_M, 2) + math.pow(ALTITUDE_M, 2))

# ISLs are not allowed to dip below 80 km altitude in order to avoid weather conditions
MAX_ISL_LENGTH_M = 2 * math.sqrt(math.pow(EARTH_RADIUS + ALTITUDE_M, 2) - math.pow(EARTH_RADIUS + 80000, 2))


class TestPlacementAfterFailure(unittest.TestCase):
    policies = ("network_only", "compute_aware", "completion_time")

    def setUp(self):
        self.nodes = get_compute_nodes()
        self.job = create_demo_job()
        self.cost = dict(time_ns=10, source=12, compute_node=3, route="12-3",
                         rtt_ns=1000.0, hop_count=1, failed_isls="0-1", status="AVAILABLE")

    def test_three_policies_select_reachable_at_timestamp(self):
        costs = [self.cost, dict(self.cost, time_ns=9, compute_node=0, route="12-0", rtt_ns=1),
                 dict(self.cost, compute_node=7, route="12-7", rtt_ns=1)]
        for policy in self.policies:
            with self.subTest(policy=policy):
                result = select_after_failure(policy, [0, 3], costs, 10, self.nodes, self.job)
                self.assertEqual(result["status"], "PLACED")
                self.assertEqual(result["selected_compute_node"], 3)
                self.assertIn(result["selected_compute_node"], [0, 3])

    def test_all_unreachable(self):
        for policy in self.policies:
            with self.subTest(policy=policy):
                result = select_after_failure(policy, [], [self.cost], 10, self.nodes, self.job)
                self.assertEqual(result, {"status": "FAILED", "selected_compute_node": None})

    def test_no_valid_cost(self):
        for costs in ([], [dict(self.cost, time_ns=9)], [dict(self.cost, status="UNREACHABLE")],
                      [dict(self.cost, route="")], [dict(self.cost, rtt_ns=float("inf"))]):
            for policy in self.policies:
                with self.subTest(policy=policy, costs=costs):
                    result = select_after_failure(policy, [3], costs, 10, self.nodes, self.job)
                    self.assertEqual(result, {"status": "FAILED", "selected_compute_node": None})

    def test_csv_rows_for_three_policies(self):
        for costs, status in (([self.cost], "PLACED"), ([], "FAILED")):
            rows = _build_scenario_rows("FAILURE", "0-1", self.job, self.nodes, costs, 10)
            results = [row for row in rows if row["algorithm"] in self.policies]
            self.assertEqual(len(results), 3)
            for row in results:
                self.assertEqual(row["placement_status"], status)
                self.assertEqual(row["selected_node"], 3 if costs else -1)
                self.assertEqual(row["failed_isls"], "0-1")


class TestEndToEnd(unittest.TestCase):

    def test_end_to_end(self):
        self._run_end_to_end()

    def test_end_to_end_reroutes_around_failed_isl(self):
        self._run_end_to_end(failed_isls=((0, 1),))
        self._run_end_to_end(failed_isls=((0, 1), (10, 11)))

    def test_end_to_end_random_failure(self):
        self._run_end_to_end(random_failure_enabled=True)

    @staticmethod
    def _save_demo_route(source, filename):
        demo_data_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "demo_data"
        )
        os.makedirs(demo_data_dir, exist_ok=True)
        with open(source, "r") as f_in:
            with open(os.path.join(demo_data_dir, filename), "w") as f_out:
                f_out.write(f_in.read())

    @staticmethod
    def _export_node_positions(
        generated_data_dir: str,
        time_step_ms: int,
        duration_s: int,
    ) -> None:
        demo_data_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "demo_data"
        )
        os.makedirs(demo_data_dir, exist_ok=True)
        output_filename = os.path.join(
            demo_data_dir, "node_positions.csv"
        )
        tles = satgen.read_tles(
            os.path.join(generated_data_dir, "tles.txt")
        )
        satellites = tles["satellites"]
        epoch = tles["epoch"]
        ground_stations = satgen.read_ground_stations_extended(
            os.path.join(generated_data_dir, "ground_stations.txt")
        )
        time_step_ns = time_step_ms * 1_000_000
        duration_ns = duration_s * 1_000_000_000

        with open(output_filename, "w", newline="") as f_out:
            writer = csv.DictWriter(
                f_out,
                fieldnames=[
                    "time_ns",
                    "node_id",
                    "node_type",
                    "latitude_deg",
                    "longitude_deg",
                    "altitude_m",
                ],
            )
            writer.writeheader()
            for time_ns in range(0, duration_ns, time_step_ns):
                time_moment_str = str(epoch + time_ns * u.ns)
                for node_id, satellite in enumerate(satellites):
                    position = (
                        satgen.create_basic_ground_station_for_satellite_shadow(
                            satellite,
                            str(epoch),
                            time_moment_str,
                        )
                    )
                    writer.writerow({
                        "time_ns": time_ns,
                        "node_id": node_id,
                        "node_type": "SATELLITE",
                        "latitude_deg": position[
                            "latitude_degrees_str"
                        ],
                        "longitude_deg": position[
                            "longitude_degrees_str"
                        ],
                        "altitude_m": float(satellite.elevation),
                    })

                for ground_station in ground_stations:
                    writer.writerow({
                        "time_ns": time_ns,
                        "node_id": (
                            len(satellites) + ground_station["gid"]
                        ),
                        "node_type": "GROUND_STATION",
                        "latitude_deg": ground_station[
                            "latitude_degrees_str"
                        ],
                        "longitude_deg": ground_station[
                            "longitude_degrees_str"
                        ],
                        "altitude_m": ground_station[
                            "elevation_m_float"
                        ],
                    })

    @staticmethod
    def _load_failure_timeline(data_dir, column="failed_isls"):
        filename = os.path.join(data_dir, "network_failures.csv")
        if not os.path.isfile(filename):
            return None
        with open(filename, newline="") as f_in:
            return {row["time_ns"]: row.get(column, "EXPLICIT" if row["failed_isls"] else "NONE")
                    for row in csv.DictReader(f_in)}

    @staticmethod
    def _export_demo_telemetry(route_filename, rtt_filename, failed_isls):
        demo_data_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "demo_data"
        )
        os.makedirs(demo_data_dir, exist_ok=True)
        output_filename = os.path.join(
            demo_data_dir, "routing_events.csv"
        )

        failure_timeline = TestEndToEnd._load_failure_timeline(os.path.dirname(route_filename))
        failure_modes = TestEndToEnd._load_failure_timeline(os.path.dirname(route_filename), "failure_mode")
        routes = {}
        with open(route_filename, "r") as f_in:
            for line in f_in:
                line = line.strip()
                if not line:
                    continue
                time_ns, route = line.split(",", 1)
                routes[time_ns] = route

        rtts = {}
        with open(rtt_filename, "r") as f_in:
            for line in f_in:
                line = line.strip()
                if not line:
                    continue
                time_ns, rtt_ns = line.split(",", 1)
                rtts[time_ns] = rtt_ns

        all_time_ns = sorted(set(routes) | set(rtts), key=int)
        append = bool(failed_isls) or bool(failure_timeline and any(failure_timeline.values()))
        write_header = not append or not os.path.isfile(output_filename)
        failed_isls_text = ";".join(
            "%d-%d" % edge for edge in sorted({tuple(sorted(edge)) for edge in failed_isls})
        )

        # The full two-scenario CSV assumes the baseline test runs first.
        with open(output_filename, "a" if append else "w", newline="") as f_out:
            writer = csv.DictWriter(
                f_out,
                fieldnames=[
                    "time_ns", "source", "destination", "route", "rtt_ns",
                    "hop_count", "failed_isls", "status", "failure_mode"
                ]
            )
            if write_header:
                writer.writeheader()

            current_route = None
            for time_ns in all_time_ns:
                if time_ns in routes:
                    current_route = routes[time_ns]

                current_failed_isls = (
                    failure_timeline[time_ns] if failure_timeline is not None else failed_isls_text
                )
                route = current_route or ""
                nodes = route.split("-") if route else []
                valid_route = (
                    len(nodes) >= 2
                    and nodes[0] == "12"
                    and nodes[-1] == "13"
                )
                writer.writerow({
                    "time_ns": time_ns,
                    "source": 12,
                    "destination": 13,
                    "route": route if valid_route else "",
                    "rtt_ns": rtts.get(time_ns, "") if valid_route else "",
                    "hop_count": len(nodes) - 1 if valid_route else 0,
                    "failed_isls": current_failed_isls,
                    "failure_mode": (failure_modes[time_ns] if failure_modes is not None
                                     else "EXPLICIT" if failed_isls else "NONE"),
                    "status": (
                        "REROUTED" if current_failed_isls and valid_route
                        else "NORMAL" if valid_route
                        else "DROPPED"
                    )
                })

    @staticmethod
    def _export_network_costs(data_dir, failed_isls):
        demo_data_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "demo_data"
        )
        os.makedirs(demo_data_dir, exist_ok=True)
        output_filename = os.path.join(demo_data_dir, "network_costs.csv")
        failure_timeline = TestEndToEnd._load_failure_timeline(data_dir)
        failure_modes = TestEndToEnd._load_failure_timeline(data_dir, "failure_mode")
        append = bool(failed_isls) or bool(failure_timeline and any(failure_timeline.values()))
        write_header = not append or not os.path.isfile(output_filename)
        failed_isls_text = ";".join(
            "%d-%d" % edge for edge in sorted({tuple(sorted(edge)) for edge in failed_isls})
        )

        with open(output_filename, "a" if append else "w", newline="") as f_out:
            writer = csv.DictWriter(
                f_out,
                fieldnames=[
                    "time_ns", "source", "compute_node", "route", "rtt_ns",
                    "hop_count", "failed_isls", "status", "failure_mode"
                ]
            )
            if write_header:
                writer.writeheader()

            for compute_node in [0, 3, 7]:
                routes = {}
                route_filename = os.path.join(
                    data_dir,
                    "networkx_path_12_to_%d.txt" % compute_node
                )
                with open(route_filename, "r") as f_in:
                    for line in f_in:
                        line = line.strip()
                        if not line:
                            continue
                        time_ns, route = line.split(",", 1)
                        routes[time_ns] = route

                rtts = {}
                rtt_filename = os.path.join(
                    data_dir,
                    "networkx_rtt_12_to_%d.txt" % compute_node
                )
                with open(rtt_filename, "r") as f_in:
                    for line in f_in:
                        line = line.strip()
                        if not line:
                            continue
                        time_ns, rtt_ns = line.split(",", 1)
                        rtts[time_ns] = rtt_ns

                current_route = None
                for time_ns in sorted(set(routes) | set(rtts), key=int):
                    if time_ns in routes:
                        current_route = routes[time_ns]

                    current_failed_isls = (
                        failure_timeline[time_ns] if failure_timeline is not None else failed_isls_text
                    )
                    route = current_route or ""
                    nodes = route.split("-") if route else []
                    valid_route = (
                        len(nodes) >= 2
                        and nodes[0] == "12"
                        and nodes[-1] == str(compute_node)
                    )
                    rtt_ns = rtts.get(time_ns, "")
                    available = valid_route and rtt_ns != ""
                    writer.writerow({
                        "time_ns": time_ns,
                        "source": 12,
                        "compute_node": compute_node,
                        "route": route if available else "",
                        "rtt_ns": rtt_ns if available else "",
                        "hop_count": len(nodes) - 1 if available else 0,
                        "failed_isls": current_failed_isls,
                        "failure_mode": (failure_modes[time_ns] if failure_modes is not None
                                         else "EXPLICIT" if failed_isls else "NONE"),
                        "status": "AVAILABLE" if available else "UNREACHABLE"
                    })

    def _run_end_to_end(self, failed_isls=(), random_failure_enabled=False):
        local_shell = exputil.LocalShell()

        # Clean slate start
        local_shell.remove_force_recursive("temp_gen_data")
        local_shell.make_full_dir("temp_gen_data")

        # Both dynamic state algorithms should yield the same path and RTT
        for dynamic_state_algorithm in [
            "algorithm_free_one_only_over_isls",
            "algorithm_free_gs_one_sat_many_only_over_isls"
        ]:

            if random_failure_enabled and dynamic_state_algorithm != "algorithm_free_one_only_over_isls":
                continue

            # Specific outcomes
            output_generated_data_dir = "temp_gen_data"
            num_threads = 1
            default_time_step_ms = 100
            all_time_step_ms = [50, 100, 1000, 10000]
            duration_s = 200

            # Add base name to setting
            name = "reduced_kuiper_630_" + dynamic_state_algorithm

            # Path trace we base this test on:
            # 0,1173-184-183-217-1241
            # 18000000000,1173-218-217-1241
            # 27600000000,1173-648-649-650-616-1241
            # 74300000000,1173-218-217-216-250-1241
            # 125900000000,1173-647-648-649-650-616-1241
            # 128700000000,1173-647-648-649-615-1241

            # Create output directories
            if not os.path.isdir(output_generated_data_dir):
                os.makedirs(output_generated_data_dir)
            if not os.path.isdir(output_generated_data_dir + "/" + name):
                os.makedirs(output_generated_data_dir + "/" + name)

            # Ground stations
            print("Generating ground stations...")
            with open(output_generated_data_dir + "/" + name + "/ground_stations.basic.txt", "w+") as f_out:
                f_out.write("0,Manila,14.6042,120.9822,0\n")  # Originally no. 17
                f_out.write("1,Dalian,38.913811,121.602322,0\n")  # Originally no. 85
            satgen.extend_ground_stations(
                output_generated_data_dir + "/" + name + "/ground_stations.basic.txt",
                output_generated_data_dir + "/" + name + "/ground_stations.txt"
            )

            # TLEs (taken from Kuiper-610 first shell)
            print("Generating TLEs...")
            with open(output_generated_data_dir + "/" + name + "/tles.txt", "w+") as f_out:
                f_out.write("1 12\n")  # Pretend it's one orbit with 12 satellites
                f_out.write("Kuiper-630 0\n")  # 183
                f_out.write("1 00184U 00000ABC 00001.00000000  .00000000  00000-0  00000+0 0    06\n")
                f_out.write("2 00184  51.9000  52.9412 0000001   0.0000 142.9412 14.80000000    00\n")
                f_out.write("Kuiper-630 1\n")  # 184
                f_out.write("1 00185U 00000ABC 00001.00000000  .00000000  00000-0  00000+0 0    07\n")
                f_out.write("2 00185  51.9000  52.9412 0000001   0.0000 153.5294 14.80000000    07\n")
                f_out.write("Kuiper-630 2\n")  # 216
                f_out.write("1 00217U 00000ABC 00001.00000000  .00000000  00000-0  00000+0 0    03\n")
                f_out.write("2 00217  51.9000  63.5294 0000001   0.0000 127.0588 14.80000000    01\n")
                f_out.write("Kuiper-630 3\n")  # 217
                f_out.write("1 00218U 00000ABC 00001.00000000  .00000000  00000-0  00000+0 0    04\n")
                f_out.write("2 00218  51.9000  63.5294 0000001   0.0000 137.6471 14.80000000    00\n")
                f_out.write("Kuiper-630 4\n")  # 218
                f_out.write("1 00219U 00000ABC 00001.00000000  .00000000  00000-0  00000+0 0    05\n")
                f_out.write("2 00219  51.9000  63.5294 0000001   0.0000 148.2353 14.80000000    08\n")
                f_out.write("Kuiper-630 5\n")  # 250
                f_out.write("1 00251U 00000ABC 00001.00000000  .00000000  00000-0  00000+0 0    01\n")
                f_out.write("2 00251  51.9000  74.1176 0000001   0.0000 132.3529 14.80000000    00\n")
                f_out.write("Kuiper-630 6\n")  # 615
                f_out.write("1 00616U 00000ABC 00001.00000000  .00000000  00000-0  00000+0 0    06\n")
                f_out.write("2 00616  51.9000 190.5882 0000001   0.0000  31.7647 14.80000000    05\n")
                f_out.write("Kuiper-630 7\n")  # 616
                f_out.write("1 00617U 00000ABC 00001.00000000  .00000000  00000-0  00000+0 0    07\n")
                f_out.write("2 00617  51.9000 190.5882 0000001   0.0000  42.3529 14.80000000    03\n")
                f_out.write("Kuiper-630 8\n")  # 647
                f_out.write("1 00648U 00000ABC 00001.00000000  .00000000  00000-0  00000+0 0    01\n")
                f_out.write("2 00648  51.9000 201.1765 0000001   0.0000  15.8824 14.80000000    09\n")
                f_out.write("Kuiper-630 9\n")  # 648
                f_out.write("1 00649U 00000ABC 00001.00000000  .00000000  00000-0  00000+0 0    02\n")
                f_out.write("2 00649  51.9000 201.1765 0000001   0.0000  26.4706 14.80000000    07\n")
                f_out.write("Kuiper-630 10\n")  # 649
                f_out.write("1 00650U 00000ABC 00001.00000000  .00000000  00000-0  00000+0 0    04\n")
                f_out.write("2 00650  51.9000 201.1765 0000001   0.0000  37.0588 14.80000000    05\n")
                f_out.write("Kuiper-630 11\n")  # 650
                f_out.write("1 00651U 00000ABC 00001.00000000  .00000000  00000-0  00000+0 0    05\n")
                f_out.write("2 00651  51.9000 201.1765 0000001   0.0000  47.6471 14.80000000    04\n")

            # Nodes
            #
            # Original ID   Test ID
            # 183           0
            # 184           1
            # 216           2
            # 217           3
            # 218           4
            # 250           5
            # 615           6
            # 616           7
            # 647           8
            # 648           9
            # 649           10
            # 650           11
            #
            # ISLs
            #
            # Original      Test
            # 183-184       0-1
            # 183-217       0-3
            # 216-217       2-3
            # 216-250       2-5
            # 217-218       3-4
            # 615-649       6-10
            # 616-650       7-11
            # 647-648       8-9
            # 648-649       9-10
            # 649-650       10-11
            #
            # Necessary ISLs (above) inferred from trace:
            #
            # 0,1173-184-183-217-1241
            # 18000000000,1173-218-217-1241
            # 27600000000,1173-648-649-650-616-1241
            # 74300000000,1173-218-217-216-250-1241
            # 125900000000,1173-647-648-649-650-616-1241
            # 128700000000,1173-647-648-649-615-1241
            #
            print("Generating ISLs...")
            with open(output_generated_data_dir + "/" + name + "/isls.txt", "w+") as f_out:
                f_out.write("0 1\n")
                f_out.write("0 3\n")
                f_out.write("2 3\n")
                f_out.write("2 5\n")
                f_out.write("3 4\n")
                f_out.write("6 10\n")
                f_out.write("7 11\n")
                f_out.write("8 9\n")
                f_out.write("9 10\n")
                f_out.write("10 11\n")

            # Description
            print("Generating description...")
            satgen.generate_description(
                output_generated_data_dir + "/" + name + "/description.txt",
                MAX_GSL_LENGTH_M,
                MAX_ISL_LENGTH_M
            )

            # Extended ground stations
            ground_stations = satgen.read_ground_stations_extended(
                output_generated_data_dir + "/" + name + "/ground_stations.txt"
            )
            if not random_failure_enabled:
                self._export_node_positions(
                    output_generated_data_dir + "/" + name,
                    default_time_step_ms,
                    duration_s,
                )

            # GSL interfaces
            if dynamic_state_algorithm == "algorithm_free_one_only_over_isls":
                gsl_interfaces_per_satellite = 1
                gsl_satellite_max_agg_bandwidth = 1.0
            elif dynamic_state_algorithm == "algorithm_free_gs_one_sat_many_only_over_isls":
                gsl_interfaces_per_satellite = len(ground_stations)
                gsl_satellite_max_agg_bandwidth = len(ground_stations)
            else:
                raise ValueError("Unknown dynamic state algorithm: " + dynamic_state_algorithm)
            print("Generating GSL interfaces info..")
            satgen.generate_simple_gsl_interfaces_info(
                output_generated_data_dir + "/" + name + "/gsl_interfaces_info.txt",
                12,  # 12 satellites
                len(ground_stations),
                gsl_interfaces_per_satellite,  # GSL interfaces per satellite
                1,  # (GSL) Interfaces per ground station
                gsl_satellite_max_agg_bandwidth,  # Aggregate max. bandwidth satellite (unit unspecified)
                1   # Aggregate max. bandwidth ground station (same unspecified unit)
            )

            # Random failure is a separate opt-in scenario, with a finite window.
            random_failure_start_ns = 10_000_000_000
            random_failure_end_ns = 20_000_000_000
            if random_failure_enabled:
                with open(output_generated_data_dir + "/" + name + "/isls.txt") as f_in:
                    available_isls = sorted(
                        tuple(sorted(map(int, line.split())))
                        for line in f_in if line.strip()
                    )
                expected_failed_isl = random.Random(42).choice(available_isls)

            # Forwarding state
            for time_step_ms in all_time_step_ms:
                print("Generating forwarding state...")
                with patch(
                    "satgen.dynamic_state.helper_dynamic_state.generate_dynamic_state",
                    wraps=generate_dynamic_state,
                ) as generate:
                    satgen.help_dynamic_state(
                        output_generated_data_dir,
                        num_threads,
                        name,
                        time_step_ms,
                        duration_s,
                        MAX_GSL_LENGTH_M,
                        MAX_ISL_LENGTH_M,
                        dynamic_state_algorithm,
                        False,
                        failed_isls,
                        random_failure_enabled=random_failure_enabled,
                        random_failure_seed=42,
                        random_failure_start_ns=random_failure_start_ns,
                        random_failure_end_ns=random_failure_end_ns,
                    )

                if random_failure_enabled:
                    self.assertGreater(generate.call_count, 0)
                    for invocation in generate.call_args_list:
                        self.assertEqual(
                            invocation.kwargs["random_failure_state"]["link"],
                            expected_failed_isl,
                        )
                    # Read every timestamp, applying forwarding-state deltas.
                    fstate = {}
                    active_timestamps = 0
                    state_dir = (
                        output_generated_data_dir + "/" + name
                        + "/dynamic_state_%dms_for_%ds" % (time_step_ms, duration_s)
                    )
                    for timestamp in range(0, duration_s * 1_000_000_000, time_step_ms * 1_000_000):
                        with open(state_dir + "/fstate_%d.txt" % timestamp) as f_in:
                            for line in f_in:
                                current, destination, next_hop = map(int, line.split(",")[:3])
                                fstate[(current, destination)] = next_hop
                        active = random_failure_start_ns <= timestamp < random_failure_end_ns
                        if active:
                            active_timestamps += 1
                            # Even an unreachable end-to-end route must not hide
                            # a forwarding entry that still uses the failed link.
                            for (current, _), next_hop in fstate.items():
                                self.assertNotIn(
                                    (current, next_hop),
                                    (expected_failed_isl, expected_failed_isl[::-1]),
                                )
                        for source, destination in ((12, 13), (13, 12)):
                            if fstate[(source, destination)] == -1:
                                continue  # Explicit unreachable forwarding result.
                            route = [source]
                            while route[-1] != destination:
                                next_hop = fstate[(route[-1], destination)]
                                self.assertGreaterEqual(next_hop, 0)
                                self.assertNotIn(next_hop, route)
                                route.append(next_hop)
                            self.assertEqual(route[0], source)
                            self.assertEqual(route[-1], destination)
                            if active:
                                hops = set(zip(route, route[1:]))
                                self.assertNotIn(expected_failed_isl, hops)
                                self.assertNotIn(expected_failed_isl[::-1], hops)
                    self.assertGreater(active_timestamps, 0)

            # Clean slate start
            local_shell.remove_force_recursive("temp_analysis_data")
            local_shell.make_full_dir("temp_analysis_data")
            output_analysis_data_dir = "temp_analysis_data"
            satgen.post_analysis.print_routes_and_rtt(
                output_analysis_data_dir + "/" + name,
                output_generated_data_dir + "/" + name,
                default_time_step_ms,
                duration_s,
                12,
                13,
                "satgenpy/"
            )
            for compute_satellite in [0, 3, 7]:
                satgen.post_analysis.print_routes_and_rtt(
                    output_analysis_data_dir + "/" + name,
                    output_generated_data_dir + "/" + name,
                    default_time_step_ms,
                    duration_s,
                    12,
                    compute_satellite,
                    "satgenpy/"
                )

            self._export_network_costs(
                output_analysis_data_dir + "/" + name + "/data",
                failed_isls
            )

            run_placement_demo()

            if random_failure_enabled:
                self._export_demo_telemetry(
                    output_analysis_data_dir + "/" + name + "/data/networkx_path_12_to_13.txt",
                    output_analysis_data_dir + "/" + name + "/data/networkx_rtt_12_to_13.txt",
                    failed_isls,
                )
                local_shell.remove_force_recursive("temp_gen_data")
                local_shell.remove_force_recursive("temp_analysis_data")
                return

            if dynamic_state_algorithm == "algorithm_free_one_only_over_isls":
                demo_data_dir = os.path.join(
                    os.path.dirname(os.path.dirname(__file__)), "demo_data"
                )
                scenario_failed_isls = ";".join(
                    "%d-%d" % failed_isl for failed_isl in failed_isls
                )
                network_costs = [
                    cost for cost in load_network_costs(
                        os.path.join(demo_data_dir, "network_costs.csv")
                    )
                    if (
                        cost["time_ns"] == 0
                        and cost["failed_isls"] == scenario_failed_isls
                    )
                ]
                reachable_compute_nodes = [
                    compute_node for compute_node in (0, 3, 7)
                    if any(
                        cost["compute_node"] == compute_node
                        and cost["status"] == "AVAILABLE"
                        for cost in network_costs
                    )
                ]
                for policy in ("network_only", "compute_aware", "completion_time"):
                    placement = select_after_failure(
                        policy, reachable_compute_nodes, network_costs, time_ns=0,
                        compute_nodes=get_compute_nodes(), job=create_demo_job(),
                    )
                    if reachable_compute_nodes:
                        self.assertEqual(placement["status"], "PLACED")
                        self.assertIn(placement["selected_compute_node"], reachable_compute_nodes)
                    else:
                        self.assertEqual(placement["status"], "FAILED")

            route_filename = (
                output_analysis_data_dir + "/" + name
                + "/data/networkx_path_12_to_13.txt"
            )
            rtt_filename = (
                output_analysis_data_dir + "/" + name
                + "/data/networkx_rtt_12_to_13.txt"
            )

            if failed_isls:
                with open(route_filename, "r") as f_in:
                    timestamp, route = f_in.readline().strip().split(",", 1)

                nodes = route.split("-") if route else []
                hops = list(zip(nodes, nodes[1:]))

                self.assertEqual(timestamp, "0")
                if len(failed_isls) == 1:
                    self.assertGreaterEqual(len(nodes), 3)
                    self.assertEqual(nodes[0], "12")
                    self.assertEqual(nodes[-1], "13")
                    self.assertNotIn(("0", "1"), hops)
                    self.assertNotIn(("1", "0"), hops)

                else:
                    if len(nodes) >= 3:
                        self.assertEqual(nodes[0], "12")
                        self.assertEqual(nodes[-1], "13")

                        for failed_src, failed_dst in failed_isls:
                            failed_edge = (str(failed_src), str(failed_dst))
                            reverse_edge = (str(failed_dst), str(failed_src))

                            self.assertNotIn(failed_edge, hops)
                            self.assertNotIn(reverse_edge, hops)

                self._save_demo_route(route_filename, "failed_route.txt")
                self._export_demo_telemetry(
                    route_filename,
                    rtt_filename,
                    failed_isls
                )
                local_shell.remove_force_recursive("temp_gen_data")
                local_shell.remove_force_recursive("temp_analysis_data")
                return

            # Validate generated routes without depending on one exact path.
            route_count = 0
            with open(route_filename, "r") as f_in:
                for line in f_in:
                    line = line.strip()
                    self.assertTrue(line)
                    timestamp, route = line.split(",", 1)
                    nodes = route.split("-")
                    self.assertGreaterEqual(len(nodes), 2)
                    self.assertEqual(nodes[0], "12")
                    self.assertEqual(nodes[-1], "13")

                    route_count += 1
            self.assertGreater(route_count, 0)

            # A changed valid route may have a different RTT.
            with open(
                output_analysis_data_dir + "/" + name
                + "/data/networkx_rtt_12_to_13.txt",
                "r",
            ) as f_in:
                rtt_rows = [line.strip() for line in f_in if line.strip()]
            self.assertGreater(len(rtt_rows), 0)
            for row in rtt_rows:
                timestamp, rtt_ns = row.split(",", 1)
                self.assertGreaterEqual(int(timestamp), 0)
                self.assertGreater(float(rtt_ns), 0.0)

            # Now let's run all analyses available

            # TODO: Disabled because it requires downloading files from CDNs, which can take too long
            # # Print graphically
            #
            # satgen.post_analysis.print_graphical_routes_and_rtt(
            #     output_analysis_data_dir + "/" + name,
            #     output_generated_data_dir + "/" + name,
            #     default_time_step_ms,
            #     duration_s,
            #     12,
            #     13
            # )

            # Analyze paths
            satgen.post_analysis.analyze_path(
                output_analysis_data_dir + "/" + name,
                output_generated_data_dir + "/" + name,
                default_time_step_ms,
                duration_s,
                "satgenpy/"
            )

            # Number of path changes per pair
            columns = exputil.read_csv_direct_in_columns(
                output_analysis_data_dir + "/" + name +
                "/" + name + "/100ms_for_200s/path/data/ecdf_pairs_num_path_changes.txt",
                "float,pos_float"
            )
            for i in range(len(columns[0])):

                # Cumulative y-axis check
                if i == 0:
                    self.assertEqual(columns[1][i], 0)
                else:
                    self.assertEqual(columns[1][i], 1.0)

                # Only one pair with 5 path changes
                if i == 0:
                    self.assertEqual(columns[0][i], float("-inf"))
                else:
                    self.assertEqual(columns[0][i], 5)

            # Max minus min hop count per pair
            columns = exputil.read_csv_direct_in_columns(
                output_analysis_data_dir + "/" + name +
                "/" + name + "/100ms_for_200s/path/data/ecdf_pairs_max_minus_min_hop_count.txt",
                "float,pos_float"
            )
            for i in range(len(columns[0])):

                # Cumulative y-axis check
                if i == 0:
                    self.assertEqual(columns[1][i], 0)
                else:
                    self.assertEqual(columns[1][i], 1.0)

                # Shortest is 3 hops, longest is 6 hops, max delta is 3
                if i == 0:
                    self.assertEqual(columns[0][i], float("-inf"))
                else:
                    self.assertEqual(columns[0][i], 3)

            # Max divided by min hop count per pair
            columns = exputil.read_csv_direct_in_columns(
                output_analysis_data_dir + "/" + name +
                "/" + name + "/100ms_for_200s/path/data/ecdf_pairs_max_hop_count_to_min_hop_count.txt",
                "float,pos_float"
            )
            for i in range(len(columns[0])):

                # Cumulative y-axis check
                if i == 0:
                    self.assertEqual(columns[1][i], 0)
                else:
                    self.assertEqual(columns[1][i], 1.0)

                # Shortest is 3 hops, longest is 6 hops, max/min division is 2.0
                if i == 0:
                    self.assertEqual(columns[0][i], float("-inf"))
                else:
                    self.assertEqual(columns[0][i], 2.0)

            # For all pairs, the distribution how many times they changed path
            columns = exputil.read_csv_direct_in_columns(
                output_analysis_data_dir + "/" + name +
                "/" + name + "/100ms_for_200s/path/data/ecdf_time_step_num_path_changes.txt",
                "float,pos_float"
            )
            start_cumulative = 0.0
            for i in range(len(columns[0])):

                # Cumulative y-axis check
                if i == 0:
                    self.assertEqual(columns[1][i], start_cumulative)
                else:
                    self.assertGreater(columns[1][i], start_cumulative)
                if i - 1 == range(len(columns[0])):
                    self.assertEqual(columns[1][i], 1.0)

                # There are only 5 time moments, none of which overlap, so this needs to be 5 times 1
                if i == 0:
                    self.assertEqual(columns[0][i], float("-inf"))
                elif i > 2000 - 6:
                    self.assertEqual(columns[0][i], 1.0)
                else:
                    self.assertEqual(columns[0][i], 0)

            # Analyze RTTs
            satgen.post_analysis.analyze_rtt(
                output_analysis_data_dir + "/" + name,
                output_generated_data_dir + "/" + name,
                default_time_step_ms,
                duration_s,
                "satgenpy/"
            )

            # Min. RTT
            columns = exputil.read_csv_direct_in_columns(
                output_analysis_data_dir + "/" + name +
                "/" + name + "/100ms_for_200s/rtt/data/ecdf_pairs_min_rtt_ns.txt",
                "float,pos_float"
            )
            for i in range(len(columns[0])):

                # Cumulative y-axis check
                if i == 0:
                    self.assertEqual(columns[1][i], 0)
                else:
                    self.assertEqual(columns[1][i], 1.0)

                # Only one pair with minimum RTT 25ish
                if i == 0:
                    self.assertEqual(columns[0][i], float("-inf"))
                else:
                    self.assertAlmostEqual(columns[0][i], 25229775.250687573, delta=100)

            # Max. RTT
            columns = exputil.read_csv_direct_in_columns(
                output_analysis_data_dir + "/" + name +
                "/" + name + "/100ms_for_200s/rtt/data/ecdf_pairs_max_rtt_ns.txt",
                "float,pos_float"
            )
            for i in range(len(columns[0])):

                # Cumulative y-axis check
                if i == 0:
                    self.assertEqual(columns[1][i], 0)
                else:
                    self.assertEqual(columns[1][i], 1.0)

                # Only one pair with max. RTT 48ish
                if i == 0:
                    self.assertEqual(columns[0][i], float("-inf"))
                else:
                    self.assertAlmostEqual(columns[0][i], 48165140.010532916, delta=100)

            # Max. - Min. RTT
            columns = exputil.read_csv_direct_in_columns(
                output_analysis_data_dir + "/" + name +
                "/" + name + "/100ms_for_200s/rtt/data/ecdf_pairs_max_minus_min_rtt_ns.txt",
                "float,pos_float"
            )
            for i in range(len(columns[0])):

                # Cumulative y-axis check
                if i == 0:
                    self.assertEqual(columns[1][i], 0)
                else:
                    self.assertEqual(columns[1][i], 1.0)

                # Only one pair with minimum RTT of 25ish, max. RTT is 48ish
                if i == 0:
                    self.assertEqual(columns[0][i], float("-inf"))
                else:
                    self.assertAlmostEqual(columns[0][i], 48165140.010532916 - 25229775.250687573, delta=100)

            # Max. / Min. RTT
            columns = exputil.read_csv_direct_in_columns(
                output_analysis_data_dir + "/" + name +
                "/" + name + "/100ms_for_200s/rtt/data/ecdf_pairs_max_rtt_to_min_rtt_slowdown.txt",
                "float,pos_float"
            )
            for i in range(len(columns[0])):

                # Cumulative y-axis check
                if i == 0:
                    self.assertEqual(columns[1][i], 0)
                else:
                    self.assertEqual(columns[1][i], 1.0)

                # Only one pair with minimum RTT of 25ish, max. RTT is 48ish
                if i == 0:
                    self.assertEqual(columns[0][i], float("-inf"))
                else:
                    self.assertAlmostEqual(columns[0][i], 48165140.010532916 / 25229775.250687573, delta=0.01)

            # Geodesic slowdown
            columns = exputil.read_csv_direct_in_columns(
                output_analysis_data_dir + "/" + name +
                "/" + name + "/100ms_for_200s/rtt/data/ecdf_pairs_max_rtt_to_geodesic_slowdown.txt",
                "float,pos_float"
            )
            for i in range(len(columns[0])):

                # Cumulative y-axis check
                if i == 0:
                    self.assertEqual(columns[1][i], 0)
                else:
                    self.assertEqual(columns[1][i], 1.0)

                # Distance Manila to Dalian is 2,703 km according to Google Maps, RTT = 2*D / c
                if i == 0:
                    self.assertEqual(columns[0][i], float("-inf"))
                else:
                    self.assertAlmostEqual(columns[0][i], 48165140.010532916 / (2 * 2703000 / 0.299792), delta=0.01)

            # Analyze time step paths
            satgen.post_analysis.analyze_time_step_path(
                output_analysis_data_dir + "/" + name,
                output_generated_data_dir + "/" + name,
                all_time_step_ms,
                duration_s
            )

            # Missed path changes
            for time_step_ms in all_time_step_ms:
                columns = exputil.read_csv_direct_in_columns(
                    output_analysis_data_dir + "/" + name +
                    "/" + name + "/200s/path/data/"
                    + "ecdf_pairs_" + str(time_step_ms) + "ms_missed_path_changes.txt",
                    "float,pos_float"
                )
                for i in range(len(columns[0])):

                    # Cumulative y-axis check
                    if i == 0:
                        self.assertEqual(columns[1][i], 0)
                    else:
                        self.assertEqual(columns[1][i], 1.0)

                    # Only one should have missed for the 10s one
                    if i == 0:
                        self.assertEqual(columns[0][i], float("-inf"))
                    else:
                        if time_step_ms == 10000:
                            self.assertEqual(columns[0][i], 1)
                        else:
                            self.assertEqual(columns[0][i], 0)

            # Time between path changes
            columns = exputil.read_csv_direct_in_columns(
                output_analysis_data_dir + "/" + name +
                "/" + name + "/200s/path/data/"
                + "ecdf_overall_time_between_path_change.txt",
                "float,pos_float"
            )
            self.assertEqual(len(columns[0]), 5)  # Total 5 path changes, but only 4 of them are not from epoch
            for i in range(len(columns[0])):

                # Cumulative y-axis check
                if i == 0:
                    self.assertEqual(columns[1][i], 0)
                else:
                    if i == 1:
                        self.assertEqual(columns[1][i], 0.25)
                    elif i == 2:
                        self.assertEqual(columns[1][i], 0.5)
                    elif i == 3:
                        self.assertEqual(columns[1][i], 0.75)
                    elif i == 4:
                        self.assertEqual(columns[1][i], 1.0)

                # Gap values
                if i == 0:
                    self.assertEqual(columns[0][i], float("-inf"))
                else:
                    if i == 1:
                        self.assertEqual(columns[0][i], 2750000000)
                    elif i == 2:
                        self.assertEqual(columns[0][i], 9600000000)
                    elif i == 3:
                        self.assertEqual(columns[0][i], 46700000000)
                    elif i == 4:
                        self.assertEqual(columns[0][i], 51650000000)

            if (
                dynamic_state_algorithm
                == "algorithm_free_one_only_over_isls"
            ):
                self._save_demo_route(route_filename, "normal_route.txt")
                self._export_demo_telemetry(
                    route_filename,
                    rtt_filename,
                    ()
                )

            # Clean up
            local_shell.remove_force_recursive("temp_gen_data")
            local_shell.remove_force_recursive("temp_analysis_data")
