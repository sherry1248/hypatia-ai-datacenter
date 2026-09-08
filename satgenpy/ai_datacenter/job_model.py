from typing import TypedDict


class _AISchedulingFields(TypedDict, total=False):
    arrival_time_ns: int
    deadline_ms: float


class AIJob(_AISchedulingFields):
    job_id: str
    job_type: str
    input_size_mb: float
    required_compute: float
    required_memory_mb: int
    source_node: int


def create_demo_job() -> AIJob:
    return {
        "job_id": "job_001",
        "arrival_time_ns": 0,
        "job_type": "image_inference",
        "input_size_mb": 500.0,
        "required_compute": 1000.0,
        "required_memory_mb": 2048,
        "deadline_ms": 1000.0,
        "source_node": 12,
    }
