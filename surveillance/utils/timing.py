"""Stage timer utility for pipeline metrics."""

from __future__ import annotations

import time
from typing import Dict


class StageTimer:
    """Measures latency of different execution stages in milliseconds."""

    def __init__(self) -> None:
        self.start_time = time.perf_counter()
        self.last_mark = self.start_time
        self.metrics: Dict[str, float] = {}

    def mark(self, stage_name: str) -> float:
        now = time.perf_counter()
        elapsed_ms = (now - self.last_mark) * 1000.0
        self.metrics[f"{stage_name}_ms"] = round(elapsed_ms, 2)
        self.last_mark = now
        return elapsed_ms

    def total(self) -> float:
        now = time.perf_counter()
        total_ms = (now - self.start_time) * 1000.0
        self.metrics["total_latency_ms"] = round(total_ms, 2)
        return total_ms
