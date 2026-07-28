"""Real GPU utilization, via DCGM exporters through Prometheus.

DISABLED until the exporters are deployed. This module and the site panels
that consume it both exist already; flipping `sources.dcgm.enabled` in
sources.yaml is the entire rollout.

Why this matters enough to build ahead of time: Slurm can only tell us a GPU
was ALLOCATED to a job. It cannot tell us the GPU was busy. Those are very
different claims, and conflating them is the most common way an HPC dashboard
becomes untrustworthy. Until DCGM lands, every published figure says
"allocated" and the methodology page says why.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .prometheus import PrometheusSource


class DcgmSource:
    def __init__(self, settings: dict, prometheus: PrometheusSource):
        self.settings = settings or {}
        self.prometheus = prometheus
        self.queries = self.settings.get("queries", {})

    @property
    def enabled(self) -> bool:
        return bool(self.settings.get("enabled")) and self.prometheus.configured

    def fetch(self, start: datetime, end: datetime) -> tuple[dict[str, Any], list[str]]:
        if not self.enabled:
            return (
                {
                    "available": False,
                    "reason": "dcgm-exporters-not-deployed",
                },
                [],
            )

        warnings: list[str] = []
        out: dict[str, Any] = {"available": True}

        sm_query = self.queries.get("sm_active")
        if sm_query:
            value, warning = self.prometheus.mean_fraction(sm_query, start, end)
            if warning:
                warnings.append(warning)
            # DCGM reports SM_ACTIVE as a 0..1 fraction already.
            out["sm_active_mean"] = round(value, 4) if value is not None else None

        power_query = self.queries.get("power_watts")
        if power_query:
            joules, warning = self.prometheus.integral_bytes(power_query, start, end)
            if warning:
                warnings.append(warning)
            out["energy_mwh"] = round(joules / 3_600_000_000.0, 4) if joules is not None else None

        if not out.get("sm_active_mean") and not out.get("energy_mwh"):
            out["available"] = False
            out["reason"] = "no-data-returned"

        return out, warnings
