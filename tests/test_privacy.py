import json
from datetime import datetime
from pathlib import Path

import pytest

from collector import config as config_module
from collector.runner import FixtureRunner
from collector.sources.slurm import SlurmSource
from collector.state import MemoryStateStore
from collector.transform import privacy
from collector.transform.aggregate import aggregate_days

CONFIG_DIR = Path(__file__).parent / "config"
FIXTURES = Path(__file__).parent / "fixtures"

WINDOW_START = datetime(2026, 7, 20)
WINDOW_END = datetime(2026, 7, 23)


@pytest.fixture
def cfg():
    return config_module.load(CONFIG_DIR)


@pytest.fixture
def day_records(cfg):
    runner = FixtureRunner(FIXTURES)
    slurm = SlurmSource(runner, cfg.sources.source("slurm"))
    jobs = slurm.fetch_jobs(WINDOW_START, WINDOW_END)
    report = slurm.fetch_utilization(WINDOW_START, WINDOW_END)
    aggregates = aggregate_days(jobs, WINDOW_START, WINDOW_END, {d: report for d in _days()})
    state = MemoryStateStore()
    out = []
    for day in sorted(aggregates):
        state.record_users(day, aggregates[day].users)
        out.append(privacy.scrub_day(aggregates[day], cfg.groups, cfg.sources.k_anonymity))
    return out


def _days():
    from datetime import date, timedelta

    cursor = date(2026, 7, 20)
    while cursor < date(2026, 7, 23):
        yield cursor
        cursor += timedelta(days=1)


def _group(record, name):
    for entry in record["groups"]:
        if entry["name"] == name:
            return entry
    return None


def test_named_group_with_enough_users_is_published(day_records):
    first = day_records[0]
    kolar = _group(first, "Kolar Lab")
    assert kolar is not None
    assert kolar["users"] >= 3
    assert kolar["department"] == "Statistics"


def test_single_user_lab_collapses_despite_being_allowlisted(day_records):
    # solo-lab IS in groups.yaml but has one user. Naming it names them.
    for record in day_records:
        assert _group(record, "Solo Lab") is None


def test_unlisted_account_is_never_named(day_records):
    for record in day_records:
        assert _group(record, "unlisted-lab") is None
        assert _group(record, "Unlisted Lab") is None


def test_collapsed_usage_still_counts_toward_totals(day_records):
    first = day_records[0]
    other = _group(first, "Other")
    assert other is not None
    # solo-lab (4 GPUs x 12h = 48) + unlisted-lab all land in Other.
    assert other["gpu_hours"] > 0
    named_total = sum(g["gpu_hours"] for g in first["groups"])
    assert named_total == pytest.approx(first["gpu_hours"]["allocated"], rel=0.02)


def test_no_username_appears_anywhere(day_records):
    blob = json.dumps(day_records)
    for username in (
        "alice",
        "bob",
        "carol",
        "dave",
        "erin",
        "frank",
        "grace",
        "hank",
        "iris",
        "jack",
        "karen",
        "liam",
        "mia",
        "nora",
    ):
        assert f'"{username}"' not in blob
        assert f":{username}" not in blob


def test_no_raw_account_names_appear(day_records):
    blob = json.dumps(day_records)
    for account in ("kolar-lab", "dsi-clinic", "solo-lab", "unlisted-lab", "cmsc-25025"):
        assert account not in blob


def test_verify_accepts_clean_output(tmp_path, cfg, day_records):
    _write_tree(tmp_path, day_records)
    privacy.reset_allowed_strings()
    privacy.register_allowed_strings(_operator_strings(cfg))
    checked = privacy.verify_tree(tmp_path / "data", cfg.groups, cfg.sources.k_anonymity)
    assert checked >= 1


def test_verify_rejects_unallowlisted_group_name(tmp_path, cfg, day_records):
    poisoned = json.loads(json.dumps(day_records))
    poisoned[0]["groups"][0]["name"] = "Smith Lab"
    _write_tree(tmp_path, poisoned)
    privacy.reset_allowed_strings()
    privacy.register_allowed_strings(_operator_strings(cfg))
    with pytest.raises(privacy.PrivacyViolation, match="not in the groups.yaml allowlist"):
        privacy.verify_tree(tmp_path / "data", cfg.groups, cfg.sources.k_anonymity)


def test_verify_rejects_group_below_k_anonymity(tmp_path, cfg, day_records):
    poisoned = json.loads(json.dumps(day_records))
    for entry in poisoned[0]["groups"]:
        if entry["name"] != "Other":
            entry["users"] = 1
            break
    _write_tree(tmp_path, poisoned)
    privacy.reset_allowed_strings()
    privacy.register_allowed_strings(_operator_strings(cfg))
    with pytest.raises(privacy.PrivacyViolation, match="k-anonymity floor"):
        privacy.verify_tree(tmp_path / "data", cfg.groups, cfg.sources.k_anonymity)


def test_verify_rejects_smuggled_username_in_a_token_map(tmp_path, cfg, day_records):
    poisoned = json.loads(json.dumps(day_records))
    poisoned[0]["gpu_hours_by_partition"]["user alice smith"] = 12.0
    _write_tree(tmp_path, poisoned)
    privacy.reset_allowed_strings()
    privacy.register_allowed_strings(_operator_strings(cfg))
    with pytest.raises(privacy.PrivacyViolation, match="not a safe token"):
        privacy.verify_tree(tmp_path / "data", cfg.groups, cfg.sources.k_anonymity)


def test_verify_rejects_unexpected_key(tmp_path, cfg, day_records):
    poisoned = json.loads(json.dumps(day_records))
    poisoned[0]["top_users"] = 5
    _write_tree(tmp_path, poisoned)
    privacy.reset_allowed_strings()
    privacy.register_allowed_strings(_operator_strings(cfg))
    with pytest.raises(privacy.PrivacyViolation, match="unexpected key"):
        privacy.verify_tree(tmp_path / "data", cfg.groups, cfg.sources.k_anonymity)


def test_verify_rejects_free_text_in_an_auxiliary_file(tmp_path, cfg, day_records):
    _write_tree(tmp_path, day_records)
    (tmp_path / "data" / "notes.json").write_text(
        json.dumps({"note": "contact jane.doe@uchicago.edu about the outage"})
    )
    privacy.reset_allowed_strings()
    privacy.register_allowed_strings(_operator_strings(cfg))
    with pytest.raises(privacy.PrivacyViolation, match="free text is never publishable"):
        privacy.verify_tree(tmp_path / "data", cfg.groups, cfg.sources.k_anonymity)


def _write_tree(root: Path, day_records: list[dict]) -> None:
    daily = root / "data" / "daily"
    daily.mkdir(parents=True, exist_ok=True)
    (daily / "2026-07.json").write_text(
        json.dumps({"month": "2026-07", "generated": None, "days": day_records}, indent=2)
    )


def _operator_strings(cfg):
    values = [m.display for m in cfg.cluster.gpu_models.values()]
    for fs in cfg.cluster.filesystems:
        values.extend([fs.display, fs.name])
    for identity in cfg.groups.accounts.values():
        values.extend(
            [identity.display_name, identity.department, identity.division, identity.type]
        )
    values.extend(
        [
            cfg.groups.fallback.display_name,
            cfg.groups.fallback.department,
            cfg.groups.fallback.division,
            cfg.groups.fallback.type,
        ]
    )
    pricing = cfg.cluster.cloud_pricing or {}
    for key in ("basis", "source", "currency"):
        if pricing.get(key):
            values.append(str(pricing[key]))
    return values
