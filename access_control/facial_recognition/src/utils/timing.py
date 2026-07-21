"""Small timing helpers for per-stage latency metrics."""

from __future__ import annotations

from time import perf_counter
from typing import Dict


class StageTimer:
    def __init__(self) -> None:
        self._start = perf_counter()
        self._last = self._start
        self.metrics: Dict[str, float] = {}

    def mark(self, name: str) -> float:
        now = perf_counter()
        elapsed_ms = (now - self._last) * 1000.0
        self.metrics[f"{name}_latency_ms"] = elapsed_ms
        self._last = now
        return elapsed_ms

    def total(self, name: str = "total_frame") -> float:
        elapsed_ms = (perf_counter() - self._start) * 1000.0
        self.metrics[f"{name}_latency_ms"] = elapsed_ms
        return elapsed_ms
