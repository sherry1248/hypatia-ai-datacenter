from typing import TypedDict


class ComputeNode(TypedDict):
    gpu_util_percent: float
    queue_length: int
    compute_speed: float


_COMPUTE_NODES: dict[int, ComputeNode] = {
    0: {"gpu_util_percent": 35.0, "queue_length": 2, "compute_speed": 1.0},
    3: {"gpu_util_percent": 50.0, "queue_length": 4, "compute_speed": 1.2},
    7: {"gpu_util_percent": 20.0, "queue_length": 1, "compute_speed": 0.9},
}


def get_compute_nodes() -> dict[int, ComputeNode]:
    return {node_id: node.copy() for node_id, node in _COMPUTE_NODES.items()}
