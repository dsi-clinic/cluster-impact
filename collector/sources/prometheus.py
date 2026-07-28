"""Prometheus range queries: node availability and I/O throughput.

Talks to the Prometheus API directly rather than through the Grafana proxy,
so no Grafana session or API key is involved. Everything returns
(value, warnings) and degrades to None rather than raising: a metrics site
that goes blank because one exporter is down is worse than one that says
"unavailable" in a single panel.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

try:  # httpx is only needed when the source is enabled
    import httpx
except ImportError:  # pragma: no cover - exercised only in minimal envs
    httpx = None  # type: ignore[assignment]


class PrometheusSource:
    def __init__(self, settings: dict):
        self.settings = settings or {}
        self.url = (self.settings.get("url") or "").rstrip("/")
        self.step = self.settings.get("step", "5m")

    @property
    def configured(self) -> bool:
        return bool(self.url) and httpx is not None

    def _query_range(
        self, query: str, start: datetime, end: datetime
    ) -> tuple[list[dict[str, Any]], str | None]:
        if not self.configured:
            return [], "prometheus: not configured"
        try:
            response = httpx.get(
                f"{self.url}/api/v1/query_range",
                params={
                    "query": query,
                    "start": start.timestamp(),
                    "end": end.timestamp(),
                    "step": self.step,
                },
                timeout=120.0,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:  # noqa: BLE001 - any failure degrades the panel
            return [], f"prometheus: query failed ({type(exc).__name__})"

        if payload.get("status") != "success":
            return [], f"prometheus: {payload.get('error', 'query returned non-success')}"
        return payload.get("data", {}).get("result", []), None

    def integral_bytes(
        self, query: str, start: datetime, end: datetime
    ) -> tuple[float | None, str | None]:
        """Integrate a bytes/second rate series into total bytes over the window."""
        series, warning = self._query_range(query, start, end)
        if warning:
            return None, warning
        step_seconds = _parse_duration(self.step)
        total = 0.0
        for entry in series:
            for _timestamp, value in entry.get("values", []):
                try:
                    total += float(value) * step_seconds
                except (TypeError, ValueError):
                    continue
        return total, None

    def mean_fraction(
        self, query: str, start: datetime, end: datetime
    ) -> tuple[float | None, str | None]:
        """Mean of a 0..1 series across all reporting targets."""
        series, warning = self._query_range(query, start, end)
        if warning:
            return None, warning
        count = 0
        total = 0.0
        for entry in series:
            for _timestamp, value in entry.get("values", []):
                try:
                    total += float(value)
                    count += 1
                except (TypeError, ValueError):
                    continue
        if count == 0:
            return None, None
        return total / count, None


def _parse_duration(text: str) -> float:
    units = {"s": 1.0, "m": 60.0, "h": 3600.0, "d": 86400.0}
    text = (text or "5m").strip()
    try:
        if text[-1] in units:
            return float(text[:-1]) * units[text[-1]]
        return float(text)
    except (ValueError, IndexError):
        return 300.0
