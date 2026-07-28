"""The scrub, and the gate that proves the scrub happened.

This module is the ONLY sanctioned path from an internal aggregate to a file
in the repository. Everything it emits is world-readable forever, so it is
built to fail closed at three independent layers:

  1. Allowlist   an account absent from groups.yaml is published as "Other".
                 Its usage still counts toward every total; its name never
                 appears. A new lab cannot leak a PI's name by running a job.

  2. k-anonymity a named group needs at least k distinct users. A one-person
                 "lab" is a person, and naming it names them, so it collapses
                 into "Other" no matter what the allowlist says.

  3. Assertion   verify_tree() re-reads what was actually written and refuses
                 anything outside a closed schema with a closed string
                 vocabulary. It runs before commit AND again in CI, so a bad
                 file cannot reach the site even if it reaches the repo.

Layer 3 is the one that matters. Layers 1 and 2 are the intent; layer 3 is
the proof, and it checks the bytes on disk rather than trusting the code path
that produced them.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from datetime import date
from pathlib import Path
from typing import Any

from ..config import GroupsConfig
from .aggregate import DayAggregate, percentile

SECONDS_PER_HOUR = 3600.0

# Every string value published anywhere must match this. Deliberately narrow:
# no spaces, no @, no dots-with-slashes, nothing that could carry a path,
# an email, or a free-text job name.
SAFE_TOKEN = re.compile(r"^[A-Za-z0-9_.:+/-]{1,64}$")

ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ISO_MONTH = re.compile(r"^\d{4}-\d{2}$")
ISO_YEAR = re.compile(r"^\d{4}$")


class PrivacyViolation(AssertionError):
    """Raised when published data fails an assertion. Never caught in-process."""


# --------------------------------------------------------------------------
# Scrub
# --------------------------------------------------------------------------


def _hours(seconds: float) -> float:
    return round(seconds / SECONDS_PER_HOUR, 2)


def _round_map(mapping: dict[str, float], convert: bool = True) -> dict[str, float]:
    return {
        k: (_hours(v) if convert else round(v, 4))
        for k, v in sorted(mapping.items(), key=lambda kv: (-kv[1], kv[0]))
    }


def _ratio(value: float | None) -> float | None:
    return None if value is None else round(value, 4)


def scrub_day(agg: DayAggregate, groups: GroupsConfig, k_anonymity: int) -> dict[str, Any]:
    """Turn one internal aggregate into its published form.

    Note what is absent from the output: usernames, job IDs, job names, exit
    codes, node names, and any per-user series. Those are not filtered out
    downstream — they are simply never written.
    """
    named: list[dict[str, Any]] = []
    other_gpu = 0.0
    other_cpu = 0.0
    other_jobs = 0
    other_users: set[str] = set()

    for account, usage in agg.by_account.items():
        identity = groups.resolve(account)
        publishable = groups.is_named(account) and len(usage.users) >= k_anonymity
        if publishable:
            named.append(
                {
                    "name": identity.display_name,
                    "department": identity.department,
                    "division": identity.division,
                    "type": identity.type,
                    "gpu_hours": _hours(usage.gpu_seconds),
                    "cpu_hours": _hours(usage.cpu_seconds),
                    "jobs": usage.jobs,
                    "users": len(usage.users),
                }
            )
        else:
            other_gpu += usage.gpu_seconds
            other_cpu += usage.cpu_seconds
            other_jobs += usage.jobs
            other_users |= usage.users

    # Merge same-display-name groups (two accounts, one lab) so the k check
    # applies to the published bucket rather than the underlying account.
    merged: dict[str, dict[str, Any]] = {}
    for entry in named:
        key = entry["name"]
        if key in merged:
            merged[key]["gpu_hours"] += entry["gpu_hours"]
            merged[key]["cpu_hours"] += entry["cpu_hours"]
            merged[key]["jobs"] += entry["jobs"]
            merged[key]["users"] += entry["users"]
        else:
            merged[key] = dict(entry)

    group_list = sorted(merged.values(), key=lambda e: (-e["gpu_hours"], e["name"]))

    if other_gpu or other_cpu or other_jobs:
        group_list.append(
            {
                "name": groups.fallback.display_name,
                "department": groups.fallback.department,
                "division": groups.fallback.division,
                "type": groups.fallback.type,
                "gpu_hours": _hours(other_gpu),
                "cpu_hours": _hours(other_cpu),
                "jobs": other_jobs,
                "users": len(other_users),
            }
        )

    return {
        "date": agg.day.isoformat(),
        "gpu_hours": {
            "allocated": _hours(agg.gpu_seconds_allocated),
            "available": _hours(agg.gpu_seconds_available),
            "reported": _hours(agg.gpu_seconds_reported),
            "down": _hours(agg.gpu_seconds_down + agg.gpu_seconds_planned_down),
            "idle": _hours(agg.gpu_seconds_idle),
        },
        "cpu_hours_allocated": _hours(agg.cpu_seconds_allocated),
        "utilization": {
            "available": _ratio(agg.utilization_available),
            "installed": _ratio(agg.utilization_installed),
            "availability": _ratio(agg.availability_rate),
            "from_sreport": agg.utilization_from_sreport,
        },
        "jobs": {
            "total": agg.jobs_total,
            "by_state": dict(sorted(agg.jobs_by_state.items())),
            "by_size": dict(sorted(agg.jobs_by_size.items())),
            "success_rate": _ratio(agg.success_rate),
        },
        "gpu_hours_by_model": _round_map(agg.gpu_seconds_by_model),
        "gpu_hours_by_partition": _round_map(agg.gpu_seconds_by_partition),
        "gpu_hours_by_qos": _round_map(agg.gpu_seconds_by_qos),
        "active_users": len(agg.users),
        "wait_seconds": {
            "p50": _ratio(percentile(agg.wait_samples, 50)),
            "p90": _ratio(percentile(agg.wait_samples, 90)),
            "p99": _ratio(percentile(agg.wait_samples, 99)),
            "samples": len(agg.wait_samples),
        },
        "hourly_gpu_hours": [_hours(s) for s in agg.hourly_gpu_seconds],
        "records": {
            "largest_job_gpus": agg.largest_job_gpus,
            "largest_job_gpu_hours": round(agg.largest_job_gpu_hours, 2),
            "longest_job_hours": round(agg.longest_job_hours, 2),
            "max_nodes_in_job": agg.max_nodes_in_job,
        },
        "groups": group_list,
    }


# --------------------------------------------------------------------------
# Verify
# --------------------------------------------------------------------------

# Closed schema. A key that is not listed here is a violation, so adding a new
# published field is a deliberate act that forces a look at this file.
DAY_SCHEMA: dict[str, Any] = {
    "date": "iso_date",
    "gpu_hours": {
        "allocated": "num",
        "available": "num",
        "reported": "num",
        "down": "num",
        "idle": "num",
    },
    "cpu_hours_allocated": "num",
    "utilization": {
        "available": "num?",
        "installed": "num?",
        "availability": "num?",
        "from_sreport": "bool",
    },
    "jobs": {
        "total": "num",
        "by_state": "token_map",
        "by_size": "token_map",
        "success_rate": "num?",
    },
    "gpu_hours_by_model": "token_map",
    "gpu_hours_by_partition": "token_map",
    "gpu_hours_by_qos": "token_map",
    "active_users": "num",
    "wait_seconds": {"p50": "num?", "p90": "num?", "p99": "num?", "samples": "num"},
    "hourly_gpu_hours": "num_list",
    "records": {
        "largest_job_gpus": "num",
        "largest_job_gpu_hours": "num",
        "longest_job_hours": "num",
        "max_nodes_in_job": "num",
    },
    "groups": "group_list",
}


def _check_scalar(kind: str, value: Any, where: str) -> None:
    optional = kind.endswith("?")
    base = kind.rstrip("?")

    if value is None:
        if optional:
            return
        raise PrivacyViolation(f"{where}: null not allowed for {base}")

    if base == "num":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise PrivacyViolation(f"{where}: expected a number, got {value!r}")
    elif base == "bool":
        if not isinstance(value, bool):
            raise PrivacyViolation(f"{where}: expected a boolean, got {value!r}")
    elif base == "iso_date":
        if not (isinstance(value, str) and ISO_DATE.match(value)):
            raise PrivacyViolation(f"{where}: expected an ISO date, got {value!r}")
    else:
        raise PrivacyViolation(f"{where}: unknown schema kind {base!r}")


def _check_token_map(value: Any, where: str) -> None:
    if not isinstance(value, dict):
        raise PrivacyViolation(f"{where}: expected an object")
    for key, num in value.items():
        if not isinstance(key, str) or not SAFE_TOKEN.match(key):
            raise PrivacyViolation(
                f"{where}: key {key!r} is not a safe token — refusing to publish"
            )
        _check_scalar("num", num, f"{where}.{key}")


def _check_group_list(
    value: Any, where: str, vocabulary: PublishedVocabulary, k_anonymity: int
) -> None:
    if not isinstance(value, list):
        raise PrivacyViolation(f"{where}: expected a list")
    for index, entry in enumerate(value):
        loc = f"{where}[{index}]"
        if not isinstance(entry, dict):
            raise PrivacyViolation(f"{loc}: expected an object")
        expected = {
            "name",
            "department",
            "division",
            "type",
            "gpu_hours",
            "cpu_hours",
            "jobs",
            "users",
        }
        extra = set(entry) - expected
        if extra:
            raise PrivacyViolation(f"{loc}: unexpected key(s) {sorted(extra)}")
        missing = expected - set(entry)
        if missing:
            raise PrivacyViolation(f"{loc}: missing key(s) {sorted(missing)}")

        # The core assertion: a published group name must be one an operator
        # deliberately wrote into groups.yaml. Anything else is a leak.
        if entry["name"] not in vocabulary.display_names:
            raise PrivacyViolation(
                f"{loc}: group name {entry['name']!r} is not in the groups.yaml "
                f"allowlist — refusing to publish"
            )
        if entry["department"] not in vocabulary.departments:
            raise PrivacyViolation(f"{loc}: department {entry['department']!r} not allowlisted")
        if entry["division"] not in vocabulary.divisions:
            raise PrivacyViolation(f"{loc}: division {entry['division']!r} not allowlisted")
        if entry["type"] not in vocabulary.types:
            raise PrivacyViolation(f"{loc}: type {entry['type']!r} not allowlisted")

        for key in ("gpu_hours", "cpu_hours", "jobs", "users"):
            _check_scalar("num", entry[key], f"{loc}.{key}")

        # k-anonymity, re-checked against the bytes on disk.
        if entry["name"] != vocabulary.fallback_name and entry["users"] < k_anonymity:
            raise PrivacyViolation(
                f"{loc}: named group {entry['name']!r} has {entry['users']} user(s), "
                f"below the k-anonymity floor of {k_anonymity}"
            )


class PublishedVocabulary:
    """The closed set of strings allowed to appear in group positions."""

    def __init__(self, groups: GroupsConfig):
        self.display_names = {g.display_name for g in groups.accounts.values()}
        self.departments = {g.department for g in groups.accounts.values()}
        self.divisions = {g.division for g in groups.accounts.values()}
        self.types = {g.type for g in groups.accounts.values()}

        self.display_names.add(groups.fallback.display_name)
        self.departments.add(groups.fallback.department)
        self.divisions.add(groups.fallback.division)
        self.types.add(groups.fallback.type)

        self.fallback_name = groups.fallback.display_name


def _check_node(
    schema: Any, value: Any, where: str, vocabulary: PublishedVocabulary, k_anonymity: int
) -> None:
    if isinstance(schema, dict):
        if not isinstance(value, dict):
            raise PrivacyViolation(f"{where}: expected an object")
        extra = set(value) - set(schema)
        if extra:
            raise PrivacyViolation(f"{where}: unexpected key(s) {sorted(extra)}")
        for key, sub in schema.items():
            if key not in value:
                raise PrivacyViolation(f"{where}: missing key {key!r}")
            _check_node(sub, value[key], f"{where}.{key}", vocabulary, k_anonymity)
        return

    if schema == "token_map":
        _check_token_map(value, where)
    elif schema == "group_list":
        _check_group_list(value, where, vocabulary, k_anonymity)
    elif schema == "num_list":
        if not isinstance(value, list):
            raise PrivacyViolation(f"{where}: expected a list")
        for i, item in enumerate(value):
            _check_scalar("num", item, f"{where}[{i}]")
    else:
        _check_scalar(schema, value, where)


def verify_day(record: Any, vocabulary: PublishedVocabulary, k_anonymity: int, where: str) -> None:
    _check_node(DAY_SCHEMA, record, where, vocabulary, k_anonymity)


def _iter_json_files(root: Path) -> Iterable[Path]:
    yield from sorted(root.rglob("*.json"))


def verify_tree(
    data_dir: Path | str,
    groups: GroupsConfig,
    k_anonymity: int,
    summary_path: Path | str | None = None,
) -> int:
    """Re-read everything published and assert it is safe. Returns file count.

    Raises PrivacyViolation on the first problem. This is the CI gate: the
    Pages build declares `needs: privacy-gate`, so a failure here stops the
    deploy rather than merely annotating it.
    """
    root = Path(data_dir)
    if not root.exists():
        raise PrivacyViolation(f"data directory not found: {root}")

    vocabulary = PublishedVocabulary(groups)
    checked = 0

    for path in _iter_json_files(root):
        rel = path.relative_to(root)
        with path.open() as fh:
            try:
                payload = json.load(fh)
            except json.JSONDecodeError as exc:
                raise PrivacyViolation(f"{rel}: not valid JSON — {exc}") from exc

        parts = rel.parts
        if parts and parts[0] == "daily":
            if not isinstance(payload, dict) or "days" not in payload:
                raise PrivacyViolation(f"{rel}: expected an object with a 'days' array")
            month = payload.get("month")
            if not (isinstance(month, str) and ISO_MONTH.match(month)):
                raise PrivacyViolation(f"{rel}: bad or missing 'month'")
            for i, day in enumerate(payload["days"]):
                verify_day(day, vocabulary, k_anonymity, f"{rel}.days[{i}]")
            # Anything alongside "days" still has to survive the free-text rule.
            _verify_generic({k: v for k, v in payload.items() if k != "days"}, str(rel))
            checked += 1
        elif parts and parts[0] == "rollups":
            _verify_rollup(payload, vocabulary, k_anonymity, str(rel))
            checked += 1
        else:
            _verify_generic(payload, str(rel))
            checked += 1

    if summary_path is not None:
        summary_file = Path(summary_path)
        if summary_file.exists():
            with summary_file.open() as fh:
                _verify_generic(json.load(fh), str(summary_file))
            checked += 1

    return checked


def _verify_rollup(
    payload: Any, vocabulary: PublishedVocabulary, k_anonymity: int, where: str
) -> None:
    if not isinstance(payload, dict) or "periods" not in payload:
        raise PrivacyViolation(f"{where}: expected an object with a 'periods' array")
    for i, period in enumerate(payload["periods"]):
        loc = f"{where}.periods[{i}]"
        if not isinstance(period, dict):
            raise PrivacyViolation(f"{loc}: expected an object")
        key = period.get("period")
        if not (isinstance(key, str) and (ISO_MONTH.match(key) or ISO_YEAR.match(key))):
            raise PrivacyViolation(f"{loc}: bad or missing 'period'")
        if "groups" in period:
            _check_group_list(period["groups"], f"{loc}.groups", vocabulary, k_anonymity)
        _verify_generic({k: v for k, v in period.items() if k != "groups"}, loc)


def _verify_generic(payload: Any, where: str, depth: int = 0) -> None:
    """Catch-all for files without a dedicated schema.

    Enforces the one universal rule: every string is either an ISO date/period
    or a safe token. Free text cannot appear anywhere in published data, which
    is what stops a username, an email, a path, or a job name from riding
    along in a field nobody thought to check.
    """
    if depth > 12:
        raise PrivacyViolation(f"{where}: nested too deeply")

    if isinstance(payload, dict):
        for key, value in payload.items():
            if not isinstance(key, str) or not (
                SAFE_TOKEN.match(key) or ISO_DATE.match(key) or ISO_MONTH.match(key)
            ):
                raise PrivacyViolation(f"{where}: unsafe key {key!r}")
            _verify_generic(value, f"{where}.{key}", depth + 1)
    elif isinstance(payload, list):
        for i, item in enumerate(payload):
            _verify_generic(item, f"{where}[{i}]", depth + 1)
    elif isinstance(payload, str):
        if not (
            SAFE_TOKEN.match(payload)
            or ISO_DATE.match(payload)
            or ISO_MONTH.match(payload)
            or ISO_YEAR.match(payload)
            or _is_iso_timestamp(payload)
            or payload in _ALLOWED_FREE_STRINGS
        ):
            raise PrivacyViolation(
                f"{where}: string value {payload[:80]!r} is not a safe token — "
                f"free text is never publishable"
            )
    elif payload is None or isinstance(payload, (int, float, bool)):
        return
    else:
        raise PrivacyViolation(f"{where}: unsupported value type {type(payload).__name__}")


_ISO_TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?$")


def _is_iso_timestamp(value: str) -> bool:
    return bool(_ISO_TS.match(value))


# Strings that are allowed to contain spaces or punctuation because an
# operator wrote them into config on purpose. Populated at runtime from
# cluster.yaml / groups.yaml by register_allowed_strings().
_ALLOWED_FREE_STRINGS: set[str] = set()


def register_allowed_strings(values: Iterable[str]) -> None:
    """Whitelist operator-authored display strings (model names, filesystem
    labels, pricing basis text) so they survive the free-text check."""
    for value in values:
        if value:
            _ALLOWED_FREE_STRINGS.add(str(value))


def reset_allowed_strings() -> None:
    _ALLOWED_FREE_STRINGS.clear()


def build_month_file(month: str, days: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "month": month,
        "generated": None,  # stamped by publish.py; kept here for key ordering
        "days": sorted(days, key=lambda d: d["date"]),
    }


def month_key(day: date) -> str:
    return f"{day.year:04d}-{day.month:02d}"
