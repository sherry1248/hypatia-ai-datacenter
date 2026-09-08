from pathlib import Path

from .report_generator import generate_experiment_report
from .run_demo import main as run_placement_demo
from .workload import export_workload_csv, generate_demo_workload
from .workload_experiment import run_burst_experiment


def main() -> None:
    demo_data_dir = Path(__file__).resolve().parent.parent / "demo_data"
    required_inputs = (
        demo_data_dir / "network_costs.csv",
        demo_data_dir / "node_positions.csv",
    )
    for input_path in required_inputs:
        if not input_path.is_file():
            raise FileNotFoundError(
                f"required pipeline input was not found: {input_path}"
            )

    export_workload_csv(
        generate_demo_workload(),
        demo_data_dir / "ai_jobs.csv",
    )
    print("workload generated")

    run_placement_demo()
    print("placement scenarios completed")

    run_burst_experiment()
    print("burst experiment completed")

    generate_experiment_report()
    print("report generated")
    print("pipeline completed")


if __name__ == "__main__":
    main()
