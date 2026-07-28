"""Job records -> one aggregate per calendar day.

The output of this module still contains usernames and raw account names. It
is an INTERNAL type and must never be serialized to the repo directly —
`privacy.py` is the only sanctioned path from here to disk.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from ..sources.slurm import JobRecord, UtilizationReport

# GPUs requested by a single job. Chosen to distinguish the three things
# stakeholders actually ask about: laptop-replacement work, single-node
# training, and genuine multi-node capability runs.
SIZE_BUCKETS: list[tuple[str, int, int | None]] = [
    ("cpu_only", 0, 0),
    ("1", 1, 1),
    ("2-4", 2, 4),
    ("5-8", 5, 8),
    ("9-16", 9, 16),
    ("17+", 17, None),
]


def size_bucket(gpus: int) -> str:
    for label, lo, hi in SIZE_BUCKETS:
        if gpus >= lo and (hi is None or gpus <= hi):
            return label
    return "17+"


def percentile(values: list[float], pct: float) -> float | None:
    """Linear-interpolated percentile. None for an empty sample."""
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * (pct / 100.0)
    lo = math.floor(rank)
    hi = math.ceil(rank)
    if lo == hi:
        return ordered[int(rank)]
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (rank - lo)


@dataclass
class GroupUsage:
    """Per-account usage. `users` is internal and never published."""

    gpu_seconds: float = 0.0
    cpu_seconds: float = 0.0
    jobs: int = 0
    users: set[str] = field(default_factory=set)


@dataclass
class DayAggregate:
    """Everything the site needs about one calendar day.

    INTERNAL: carries usernames. Pass through privacy.scrub_day() before it
    touches the filesystem.
    """

    day: date

    # Numerator, from sacct.
    gpu_seconds_allocated: float = 0.0
    cpu_seconds_allocated: float = 0.0

    # Denominator, from sreport.
    gpu_seconds_reported: float = 0.0
    gpu_seconds_down: float = 0.0
    gpu_seconds_planned_down: float = 0.0
    gpu_seconds_idle: float = 0.0
    utilization_from_sreport: bool = False

    jobs_total: int = 0
    jobs_by_state: dict[str, int] = field(default_factory=dict)
    jobs_by_size: dict[str, int] = field(default_factory=dict)

    gpu_seconds_by_model: dict[str, float] = field(default_factory=dict)
    gpu_seconds_by_partition: dict[str, float] = field(default_factory=dict)
    gpu_seconds_by_qos: dict[str, float] = field(default_factory=dict)

    by_account: dict[str, GroupUsage] = field(default_factory=dict)

    users: set[str] = field(default_factory=set)
    wait_samples: list[float] = field(default_factory=list)

    # 24 buckets of GPU-seconds allocated by hour of day.
    hourly_gpu_seconds: list[float] = field(default_factory=lambda: [0.0] * 24)

    largest_job_gpus: int = 0
    largest_job_gpu_hours: float = 0.0
    longest_job_hours: float = 0.0
    max_nodes_in_job: int = 0

    @property
    def gpu_seconds_available(self) -> float:
        return max(
            self.gpu_seconds_reported - self.gpu_seconds_down - self.gpu_seconds_planned_down,
            0.0,
        )

    @property
    def utilization_available(self) -> float | None:
        denom = self.gpu_seconds_available
        if denom <= 0:
            return None
        return min(self.gpu_seconds_allocated / denom, 1.0)

    @property
    def utilization_installed(self) -> float | None:
        if self.gpu_seconds_reported <= 0:
            return None
        return min(self.gpu_seconds_allocated / self.gpu_seconds_reported, 1.0)

    @property
    def availability_rate(self) -> float | None:
        if self.gpu_seconds_reported <= 0:
            return None
        return self.gpu_seconds_available / self.gpu_seconds_reported

    @property
    def success_rate(self) -> float | None:
        finished = sum(
            count
            for state, count in self.jobs_by_state.items()
            if state not in {"RUNNING", "PENDING", "SUSPENDED", "REQUEUED"}
        )
        if finished <= 0:
            return None
        return self.jobs_by_state.get("COMPLETED", 0) / finished


def _bump(mapping: dict[str, float], key: str, value: float) -> None:
    if value:
        mapping[key] = mapping.get(key, 0.0) + value


def aggregate_days(
    jobs: list[JobRecord],
    window_start: datetime,
    window_end: datetime,
    utilization_by_day: dict[date, UtilizationReport] | None = None,
) -> dict[date, DayAggregate]:
    """Fold job records into per-day aggregates over [window_start, window_end)."""
    days: dict[date, DayAggregate] = {}

    def day_for(d: date) -> DayAggregate:
        if d not in days:
            days[d] = DayAggregate(day=d)
        return days[d]

    # Pre-create every day in the window so a genuinely idle day is published
    # as a zero rather than vanishing from the series.
    cursor = window_start.date()
    while cursor < window_end.date():
        day_for(cursor)
        cursor += timedelta(days=1)

    for job in jobs:
        gpu_by_day = job.gpu_seconds_by_day(window_start, window_end)
        cpu_by_day = job.cpu_seconds_by_day(window_start, window_end)

        for d, gpu_seconds in gpu_by_day.items():
            agg = day_for(d)
            agg.gpu_seconds_allocated += gpu_seconds
            _bump(agg.gpu_seconds_by_partition, job.partition or "unknown", gpu_seconds)
            _bump(agg.gpu_seconds_by_qos, job.qos or "unknown", gpu_seconds)

            if job.gpu_models:
                # Split proportionally when a job holds more than one model.
                total_typed = sum(job.gpu_models.values()) or 1
                for model, count in job.gpu_models.items():
                    _bump(agg.gpu_seconds_by_model, model, gpu_seconds * count / total_typed)
            elif job.gpus > 0:
                _bump(agg.gpu_seconds_by_model, "unspecified", gpu_seconds)

            usage = agg.by_account.setdefault(job.account or "unknown", GroupUsage())
            usage.gpu_seconds += gpu_seconds
            if job.user:
                usage.users.add(job.user)

        for d, cpu_seconds in cpu_by_day.items():
            agg = day_for(d)
            agg.cpu_seconds_allocated += cpu_seconds
            usage = agg.by_account.setdefault(job.account or "unknown", GroupUsage())
            usage.cpu_seconds += cpu_seconds
            if job.user:
                usage.users.add(job.user)

        # Job-level facts land on the day the job STARTED, so counts are not
        # double-reported across a midnight boundary.
        anchor = job.start.date() if job.start else (job.submit.date() if job.submit else None)
        if anchor is None or not (window_start.date() <= anchor < window_end.date()):
            continue

        agg = day_for(anchor)
        agg.jobs_total += 1
        agg.jobs_by_state[job.state] = agg.jobs_by_state.get(job.state, 0) + 1
        bucket = size_bucket(job.gpus)
        agg.jobs_by_size[bucket] = agg.jobs_by_size.get(bucket, 0) + 1
        if job.user:
            agg.users.add(job.user)
        usage = agg.by_account.setdefault(job.account or "unknown", GroupUsage())
        usage.jobs += 1

        wait = job.wait_seconds
        if wait is not None:
            agg.wait_samples.append(wait)

        if job.ran:
            elapsed_hours = job.elapsed_seconds / 3600.0
            agg.largest_job_gpus = max(agg.largest_job_gpus, job.gpus)
            agg.largest_job_gpu_hours = max(agg.largest_job_gpu_hours, job.gpus * elapsed_hours)
            agg.longest_job_hours = max(agg.longest_job_hours, elapsed_hours)
            agg.max_nodes_in_job = max(agg.max_nodes_in_job, job.nodes)

        # Hour-of-day heatmap: spread the job's GPU-seconds over the hours it
        # actually occupied, not the hour it happened to start.
        if job.gpus > 0 and job.start is not None:
            end = job.end or window_end
            cursor_dt = max(job.start, window_start)
            stop = min(end, window_end)
            while cursor_dt < stop:
                next_hour = (cursor_dt + timedelta(hours=1)).replace(
                    minute=0, second=0, microsecond=0
                )
                chunk_end = min(next_hour, stop)
                seconds = (chunk_end - cursor_dt).total_seconds() * job.gpus
                hour_agg = day_for(cursor_dt.date())
                hour_agg.hourly_gpu_seconds[cursor_dt.hour] += seconds
                cursor_dt = chunk_end

    for d, report in (utilization_by_day or {}).items():
        if d not in days:
            continue
        agg = days[d]
        agg.gpu_seconds_reported = report.reported
        agg.gpu_seconds_down = report.down
        agg.gpu_seconds_planned_down = report.planned_down
        agg.gpu_seconds_idle = report.idle
        agg.utilization_from_sreport = True

    return days


def fallback_denominator(agg: DayAggregate, installed_gpus: int) -> None:
    """Derive the denominator from the capacity timeline when sreport is absent.

    Only used for historical days where sreport data is unavailable. Marks the
    day as not-from-sreport so the methodology page can say so honestly: this
    path cannot distinguish downtime from idleness, and therefore reports
    available == installed.
    """
    if agg.utilization_from_sreport or installed_gpus <= 0:
        return
    agg.gpu_seconds_reported = installed_gpus * 86400.0
    agg.gpu_seconds_down = 0.0
    agg.gpu_seconds_planned_down = 0.0
    agg.gpu_seconds_idle = max(agg.gpu_seconds_reported - agg.gpu_seconds_allocated, 0.0)
