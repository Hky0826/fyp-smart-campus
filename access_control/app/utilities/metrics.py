"""Thread-safe measured runtime counters and latency summaries."""
from __future__ import annotations

from collections import defaultdict, deque
from statistics import fmean
from threading import RLock
from time import monotonic


class RuntimeMetrics:
    def __init__(self, enabled=False, window_seconds=10.0, latency_samples=120):
        self.enabled = bool(enabled)
        self.window_seconds = max(1.0, float(window_seconds))
        self._events = defaultdict(deque)
        self._latencies = defaultdict(lambda: deque(maxlen=latency_samples))
        self._gauges = {}
        self._lock = RLock()

    def tick(self, name, count=1, at=None):
        at = monotonic() if at is None else float(at)
        with self._lock:
            events = self._events[name]
            for _ in range(max(0, int(count))):
                events.append(at)
            self._prune(events, at)

    def observe_ms(self, name, value):
        with self._lock:
            self._latencies[name].append(max(0.0, float(value)))

    def gauge(self, name, value):
        with self._lock:
            self._gauges[name] = value

    def snapshot(self):
        now = monotonic()
        with self._lock:
            rates = {}
            for name, events in self._events.items():
                self._prune(events, now)
                rates[name + '_fps'] = round(len(events) / self.window_seconds, 3)
            latency = {}
            for name, values in self._latencies.items():
                if values:
                    latency[name + '_ms'] = {
                        'last': round(values[-1], 3),
                        'average': round(fmean(values), 3),
                        'maximum': round(max(values), 3),
                        'samples': len(values),
                    }
            return {'enabled': self.enabled, 'window_seconds': self.window_seconds, 'rates': rates, 'latency': latency, 'gauges': dict(self._gauges)}

    def _prune(self, events, now):
        cutoff = now - self.window_seconds
        while events and events[0] < cutoff:
            events.popleft()
