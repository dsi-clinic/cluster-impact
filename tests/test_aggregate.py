from datetime import date, datetime
from pathlib import Path

import pytest

from collector import config as config_module
from collector.runner import FixtureRunner
from collector.sources.slurm import SlurmSource
from collector.transform.aggregate import (
    aggregate_days,
    fallback_denominator,
    percentile,
    safe_key,
    size_bucket,
)
from collector.transform.derive import build_rollup, estimate_cost_avoided
from collector.transform.privacy import SAFE_TOKEN

CONFIG_DIR = Path(__file__).parent / "config"
FIXTURES = Path(__file__).parent / "fixtures"
WINDOW_START = datetime(2026, 7, 20)
WINDOW_END = datetime(2026, 7, 23)


@pytest.fixture
def cfg():
    return config_module.load(CONFIG_DIR)


@pytest.fixture
def aggregates(cfg):
    slurm = SlurmSource(FixtureRunner(FIXTURES), cfg.sources.source("slurm"))
    jobs = slurm.fetch_jobs(WINDOW_START, WINDOW_END)
    report = slurm.fetch_utilization(WINDOW_START, WINDOW_END)
    days = {}
    cursor = date(2026, 7, 20)
    while cursor < date(2026, 7, 23):
        days[cursor] = report
        cursor = date.fromordinal(cursor.toordinal() + 1)
    return aggregate_days(jobs, WINDOW_START, WINDOW_END, days)


def test_every_day_in_window_is_present(aggregates):
    assert set(aggregates) == {date(2026, 7, 20), date(2026, 7, 21), date(2026, 7, 22)}


def test_midnight_crossing_job_is_split(aggregates):
    # Job 1010: 4 x h100, 22:00 on the 20th to 06:00 on the 21st.
    # 2h on the 20th, 6h on the 21st -> 8 and 24 GPU-hours respectively.
    day20 = aggregates[date(2026, 7, 20)]
    day21 = aggregates[date(2026, 7, 21)]
    assert day20.gpu_seconds_by_model["h100"] / 3600 == pytest.approx(
        8 * 12 + 2 * 12 + 4 * 2, abs=0.1
    )
    # The 21st receives 4 GPUs x 6h from the crossing job alone.
    assert day21.gpu_seconds_by_model["h100"] / 3600 >= 24


def test_job_counted_once_on_its_start_day(aggregates):
    total_jobs = sum(a.jobs_total for a in aggregates.values())
    # 30 rows in the fixture, all starting inside the window.
    assert total_jobs == 30


def test_cancelled_state_normalised(aggregates):
    states = {}
    for agg in aggregates.values():
        for state, count in agg.jobs_by_state.items():
            states[state] = states.get(state, 0) + count
    assert "CANCELLED" in states
    assert not any(" " in s for s in states)


def test_size_buckets():
    assert size_bucket(0) == "cpu_only"
    assert size_bucket(1) == "1"
    assert size_bucket(4) == "2-4"
    assert size_bucket(8) == "5-8"
    assert size_bucket(16) == "9-16"
    assert size_bucket(64) == "17+"


def test_cpu_only_job_is_bucketed(aggregates):
    day22 = aggregates[date(2026, 7, 22)]
    assert day22.jobs_by_size.get("cpu_only") == 1


def test_utilization_uses_available_not_reported(aggregates):
    day = aggregates[date(2026, 7, 20)]
    assert day.gpu_seconds_reported == 3456000
    assert day.gpu_seconds_available == 3456000 - 345600
    assert day.utilization_available > day.utilization_installed


def test_availability_rate(aggregates):
    day = aggregates[date(2026, 7, 20)]
    assert day.availability_rate == pytest.approx(0.9, abs=0.001)


def test_success_rate_excludes_running_jobs(aggregates):
    day = aggregates[date(2026, 7, 20)]
    assert 0.0 < day.success_rate <= 1.0


def test_hourly_heatmap_sums_to_daily_total(aggregates):
    for day, agg in aggregates.items():
        assert sum(agg.hourly_gpu_seconds) == pytest.approx(agg.gpu_seconds_allocated, rel=0.001), (
            day
        )


def test_percentile_interpolates():
    assert percentile([], 50) is None
    assert percentile([5.0], 90) == 5.0
    assert percentile([0.0, 10.0], 50) == 5.0
    assert percentile([0.0, 1.0, 2.0, 3.0, 4.0], 50) == 2.0


def test_largest_job_records(aggregates):
    day21 = aggregates[date(2026, 7, 21)]
    # Job 1015: 16 x h200 across 2 nodes for 12h.
    assert day21.largest_job_gpus == 16
    assert day21.max_nodes_in_job == 2
    assert day21.largest_job_gpu_hours == pytest.approx(192.0)


def test_fallback_denominator_marks_itself_as_such():
    from collector.transform.aggregate import DayAggregate

    agg = DayAggregate(day=date(2026, 1, 1))
    agg.gpu_seconds_allocated = 3600.0
    fallback_denominator(agg, installed_gpus=10)
    assert agg.gpu_seconds_reported == 10 * 86400
    assert agg.utilization_from_sreport is False
    # Without sreport we cannot distinguish downtime from idleness, so
    # available == installed and the site must say so.
    assert agg.gpu_seconds_available == agg.gpu_seconds_reported


def test_fallback_does_not_overwrite_real_sreport_data(aggregates):
    day = aggregates[date(2026, 7, 20)]
    before = day.gpu_seconds_reported
    fallback_denominator(day, installed_gpus=9999)
    assert day.gpu_seconds_reported == before


def test_cost_avoidance_requires_a_sourced_price_table(cfg):
    priced = estimate_cost_avoided({"a100": 100.0}, cfg.cluster)
    assert priced == pytest.approx(220.0)

    cfg.cluster.cloud_pricing = {**cfg.cluster.cloud_pricing, "source": None}
    assert estimate_cost_avoided({"a100": 100.0}, cfg.cluster) is None


def test_unpriced_model_contributes_zero_not_a_guess(cfg):
    cfg.cluster.cloud_pricing["usd_per_gpu_hour"]["h200"] = None
    # h200 is in the latest capacity snapshot, so the whole table is withheld
    # rather than silently valuing H200 hours at zero.
    assert estimate_cost_avoided({"h200": 100.0}, cfg.cluster) is None


def test_rollup_users_uses_max_not_sum(cfg):
    days = [
        {
            "date": "2026-07-20",
            "gpu_hours": {
                "allocated": 10.0,
                "available": 20.0,
                "reported": 24.0,
                "down": 4.0,
                "idle": 10.0,
            },
            "cpu_hours_allocated": 5.0,
            "utilization": {
                "available": 0.5,
                "installed": 0.42,
                "availability": 0.83,
                "from_sreport": True,
            },
            "jobs": {
                "total": 2,
                "by_state": {"COMPLETED": 2},
                "by_size": {"1": 2},
                "success_rate": 1.0,
            },
            "gpu_hours_by_model": {"a100": 10.0},
            "gpu_hours_by_partition": {"general": 10.0},
            "gpu_hours_by_qos": {"general": 10.0},
            "active_users": 3,
            "wait_seconds": {"p50": 60.0, "p90": 120.0, "p99": 200.0, "samples": 2},
            "hourly_gpu_hours": [0.0] * 24,
            "records": {
                "largest_job_gpus": 1,
                "largest_job_gpu_hours": 5.0,
                "longest_job_hours": 5.0,
                "max_nodes_in_job": 1,
            },
            "groups": [
                {
                    "name": "Kolar Lab",
                    "department": "Statistics",
                    "division": "Physical Sciences Division",
                    "type": "lab",
                    "gpu_hours": 10.0,
                    "cpu_hours": 5.0,
                    "jobs": 2,
                    "users": 3,
                }
            ],
        }
    ]
    days.append({**days[0], "date": "2026-07-21"})
    rollup = build_rollup(days, "monthly", cfg.cluster)
    group = rollup["periods"][0]["groups"][0]
    assert group["gpu_hours"] == 20.0  # summed
    assert group["users"] == 3  # NOT 6


# A job submitted with `-p clab,general` keeps the whole request list in the
# Partition field. That string becomes a key in a published token_map, and
# privacy.SAFE_TOKEN rejects commas — so an unnormalised value would fail the
# gate and abort a collection run partway through.
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("clab,general", "clab+general"),
        ("ai+s,general", "ai+s+general"),
        ("general", "general"),
        ("complementary-ai", "complementary-ai"),
        ("DDRI", "DDRI"),
        ("", "unknown"),
        ("   ", "unknown"),
        ("weird name", "weird+name"),
    ],
)
def test_safe_key_survives_the_privacy_gate(raw, expected):
    assert safe_key(raw) == expected
    assert SAFE_TOKEN.match(safe_key(raw))


def test_unpriceable_hours_are_withheld_not_published_as_zero(cfg):
    # This cluster's AccountingStorageTRES omits typed gres, so real GPU-hours
    # arrive keyed "unspecified". $0 would read as "saved nothing"; withhold.
    assert estimate_cost_avoided({"unspecified": 50_000.0}, cfg.cluster) is None
    # A partially-priced mix still publishes, counting only what it can price.
    mixed = estimate_cost_avoided({"a100": 100.0, "unspecified": 100.0}, cfg.cluster)
    assert mixed == pytest.approx(220.0)
    # Genuinely no usage is a real zero, not a withholding.
    assert estimate_cost_avoided({}, cfg.cluster) == 0.0
