import csv
import hashlib
import json
import random
from collections.abc import Iterable
from os import PathLike

from .job_model import AIJob


WORKLOAD_COLUMNS = (
    "job_id",
    "arrival_time_ns",
    "job_type",
    "required_compute",
    "input_size_mb",
    "deadline_ms",
    "source_node",
)


def generate_demo_workload() -> list[AIJob]:
    job_profiles = (
        ("image_inference", 850.0, 48.0, 750.0, 1536),
        ("object_detection", 1400.0, 96.0, 1100.0, 2048),
        ("llm_inference", 3200.0, 24.0, 1800.0, 4096),
    )
    jobs: list[AIJob] = []
    for index in range(100):
        job_type, compute, input_mb, deadline_ms, memory_mb = (
            job_profiles[index % len(job_profiles)]
        )
        jobs.append({
            "job_id": f"job_{index + 1:03d}",
            "arrival_time_ns": round(index * 199_900_000_000 / 99),
            "job_type": job_type,
            "required_compute": compute + (index % 5) * 50.0,
            "input_size_mb": input_mb + (index % 4) * 4.0,
            "required_memory_mb": memory_mb,
            "deadline_ms": deadline_ms + (index % 3) * 100.0,
            "source_node": 12,
        })
    return jobs


def generate_burst_workload(seed: int | None = None) -> list[AIJob]:
    job_profiles = (
        ("image_inference", 850.0, 48.0, 1536),
        ("object_detection", 1400.0, 96.0, 2048),
        ("llm_inference", 3200.0, 24.0, 4096),
    )
    arrival_windows = (
        (0, 49_900_000_000, 30),
        (50_000_000_000, 79_900_000_000, 108),
        (80_000_000_000, 119_900_000_000, 24),
        (120_000_000_000, 149_900_000_000, 108),
        (150_000_000_000, 199_900_000_000, 30),
    )
    random_source = random.Random(seed) if seed is not None else None
    arrival_times = []
    for start_ns, end_ns, count in arrival_windows:
        spacing = (end_ns - start_ns) / (count - 1)
        window_times = []
        for offset in range(count):
            base = start_ns + offset * spacing
            jitter = random_source.uniform(-spacing * 0.4, spacing * 0.4) if random_source else 0.0
            window_times.append(round(min(end_ns, max(start_ns, base + jitter))))
        arrival_times.extend(sorted(window_times))
    jobs: list[AIJob] = []
    for index, arrival_time_ns in enumerate(arrival_times):
        job_type, compute, input_mb, memory_mb = (
            job_profiles[index % len(job_profiles)]
        )
        deadline_base_ms = {
            "image_inference": 1500.0,
            "object_detection": 3000.0,
            "llm_inference": 6000.0,
        }[job_type]
        deadline_step_ms = deadline_base_ms / 3
        jobs.append({
            "job_id": f"burst_job_{index + 1:03d}",
            "arrival_time_ns": arrival_time_ns,
            "job_type": job_type,
            "required_compute": compute + (index % 5) * 50.0,
            "input_size_mb": input_mb + (index % 4) * 4.0,
            "required_memory_mb": memory_mb,
            "deadline_ms": deadline_base_ms + (index % 4) * deadline_step_ms,
            "source_node": 12,
        })
    return jobs


def generate_workload(workload: str, seed: int) -> list[AIJob]:
    """Generate the exact workload used by seeded experiments."""
    if workload == "demo":
        return generate_demo_workload()
    if workload == "burst":
        return generate_burst_workload(seed=seed)
    raise ValueError(f"unsupported workload: {workload}")


def workload_fingerprint(jobs: Iterable[AIJob]) -> tuple[str, int]:
    """Hash canonical job inputs, independent of dict insertion order."""
    fields = (
        "job_id", "arrival_time_ns", "job_type", "required_compute",
        "input_size_mb", "required_memory_mb", "deadline_ms", "source_node",
    )
    canonical = [
        {field: job[field] for field in fields if field in job}
        for job in jobs
    ]
    encoded = json.dumps(
        canonical, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest(), len(canonical)


def export_workload_csv(
    jobs: Iterable[AIJob],
    output_path: str | PathLike[str],
) -> None:
    with open(output_path, "w", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=WORKLOAD_COLUMNS)
        writer.writeheader()
        for job in jobs:
            writer.writerow({column: job[column] for column in WORKLOAD_COLUMNS})
