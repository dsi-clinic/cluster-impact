"""Configuration loading.

Three files, each with a distinct job:

  cluster.yaml   static hardware facts + the capacity timeline
  groups.yaml    the fail-closed account allowlist
  sources.yaml   endpoints, feature flags, privacy thresholds

Nothing here reads secrets. Credentials come from the environment so they
cannot be committed to what is, by necessity, a public repository.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_DIR = Path(os.environ.get("CLUSTER_IMPACT_CONFIG", "config"))


class ConfigError(RuntimeError):
    """Raised when configuration is missing or internally inconsistent."""


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"missing config file: {path}")
    with path.open() as fh:
        data = yaml.safe_load(fh)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: expected a mapping at the top level")
    return data


@dataclass(frozen=True)
class GpuModel:
    key: str
    display: str
    memory_gb: int
    tflops_fp16_dense: float | None
    tflops_fp8_dense: float | None
    tdp_watts: int | None


@dataclass(frozen=True)
class CapacitySnapshot:
    effective: date
    gpus: dict[str, int]
    note: str = ""

    @property
    def total_gpus(self) -> int:
        return sum(self.gpus.values())


@dataclass(frozen=True)
class Filesystem:
    name: str
    display: str
    host: str
    dataset: str
    kind: str
    purge_days: int | None = None


@dataclass
class ClusterConfig:
    """Static hardware facts. Live counts come from sinfo, never from here."""

    gpu_models: dict[str, GpuModel]
    capacity_timeline: list[CapacitySnapshot]
    cloud_pricing: dict[str, Any]
    filesystems: list[Filesystem]

    def capacity_on(self, day: date) -> CapacitySnapshot | None:
        """GPU counts in service on `day`.

        The timeline holds absolute snapshots, so this is the latest entry
        that had taken effect by `day`. Days before the first entry have no
        defined capacity and yield None rather than a misleading zero.
        """
        applicable = [s for s in self.capacity_timeline if s.effective <= day]
        if not applicable:
            return None
        return max(applicable, key=lambda s: s.effective)

    def peak_pflops(self, gpus: dict[str, int], precision: str = "fp16") -> float | None:
        """Aggregate dense peak PFLOPS for a given GPU mix.

        Returns None if any model in the mix lacks a figure for `precision`,
        rather than quietly under-counting by treating it as zero.
        """
        attr = f"tflops_{precision}_dense"
        total = 0.0
        for key, count in gpus.items():
            model = self.gpu_models.get(key)
            if model is None:
                return None
            value = getattr(model, attr, None)
            if value is None:
                return None
            total += value * count
        return total / 1000.0

    def priced_models(self) -> dict[str, float]:
        return {
            k: v
            for k, v in (self.cloud_pricing.get("usd_per_gpu_hour") or {}).items()
            if v is not None
        }

    def pricing_is_publishable(self) -> tuple[bool, str]:
        """Cost avoidance is only computed from a sourced, dated price table.

        An unsourced dollar figure on a public page invites exactly the
        challenge it is meant to survive, so this gate is deliberately strict.
        """
        pricing = self.cloud_pricing or {}
        if not pricing.get("source"):
            return False, "cloud_pricing.source is unset"
        if not pricing.get("asof"):
            return False, "cloud_pricing.asof is unset"
        latest = self.capacity_timeline[-1] if self.capacity_timeline else None
        if latest is None:
            return False, "capacity_timeline is empty"
        priced = self.priced_models()
        missing = sorted(set(latest.gpus) - set(priced))
        if missing:
            return False, f"no price for in-service model(s): {', '.join(missing)}"
        return True, ""


@dataclass(frozen=True)
class GroupIdentity:
    display_name: str
    department: str
    division: str
    type: str


@dataclass
class GroupsConfig:
    """The account allowlist. Absence means anonymous, never an error."""

    accounts: dict[str, GroupIdentity]
    fallback: GroupIdentity

    def resolve(self, account: str | None) -> GroupIdentity:
        if not account:
            return self.fallback
        return self.accounts.get(account.strip().lower(), self.fallback)

    def is_named(self, account: str | None) -> bool:
        return bool(account) and account.strip().lower() in self.accounts


@dataclass
class SourcesConfig:
    cluster_name: str
    privacy: dict[str, Any]
    sources: dict[str, Any]
    publish: dict[str, Any]

    @property
    def k_anonymity(self) -> int:
        return int(self.privacy.get("k_anonymity", 3))

    @property
    def resettle_days(self) -> int:
        return int(self.privacy.get("resettle_days", 7))

    def source(self, name: str) -> dict[str, Any]:
        return self.sources.get(name, {}) or {}

    def enabled(self, name: str) -> bool:
        return bool(self.source(name).get("enabled", False))


@dataclass
class Config:
    cluster: ClusterConfig
    groups: GroupsConfig
    sources: SourcesConfig
    config_dir: Path = field(default_factory=lambda: DEFAULT_CONFIG_DIR)


def _parse_date(value: Any, ctx: str) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value)
    raise ConfigError(f"{ctx}: expected a date, got {value!r}")


def load_cluster(path: Path) -> ClusterConfig:
    raw = _load_yaml(path)

    models: dict[str, GpuModel] = {}
    for key, spec in (raw.get("gpu_models") or {}).items():
        models[key] = GpuModel(
            key=key,
            display=spec.get("display", key.upper()),
            memory_gb=int(spec.get("memory_gb", 0)),
            tflops_fp16_dense=spec.get("tflops_fp16_dense"),
            tflops_fp8_dense=spec.get("tflops_fp8_dense"),
            tdp_watts=spec.get("tdp_watts"),
        )

    timeline: list[CapacitySnapshot] = []
    for entry in raw.get("capacity_timeline") or []:
        gpus = {k: int(v) for k, v in (entry.get("gpus") or {}).items()}
        unknown = sorted(set(gpus) - set(models))
        if unknown:
            raise ConfigError(
                f"{path}: capacity_timeline entry {entry.get('effective')} references "
                f"unknown gpu_models: {', '.join(unknown)}"
            )
        timeline.append(
            CapacitySnapshot(
                effective=_parse_date(entry.get("effective"), f"{path}:capacity_timeline"),
                gpus=gpus,
                note=entry.get("note", ""),
            )
        )
    timeline.sort(key=lambda s: s.effective)

    filesystems = [
        Filesystem(
            name=fs["name"],
            display=fs.get("display", fs["name"]),
            host=fs.get("host", ""),
            dataset=fs.get("dataset", ""),
            kind=fs.get("kind", "persistent"),
            purge_days=fs.get("purge_days"),
        )
        for fs in raw.get("filesystems") or []
    ]

    return ClusterConfig(
        gpu_models=models,
        capacity_timeline=timeline,
        cloud_pricing=raw.get("cloud_pricing") or {},
        filesystems=filesystems,
    )


def load_groups(path: Path) -> GroupsConfig:
    raw = _load_yaml(path)

    fb = raw.get("fallback") or {}
    fallback = GroupIdentity(
        display_name=fb.get("display_name", "Other"),
        department=fb.get("department", "Other"),
        division=fb.get("division", "Other"),
        type=fb.get("type", "other"),
    )

    accounts: dict[str, GroupIdentity] = {}
    for account, spec in (raw.get("accounts") or {}).items():
        if not isinstance(spec, dict):
            raise ConfigError(f"{path}: account {account!r} must map to a mapping")
        missing = [k for k in ("display_name", "department", "division", "type") if k not in spec]
        if missing:
            raise ConfigError(
                f"{path}: account {account!r} is missing required field(s): {', '.join(missing)}"
            )
        accounts[str(account).strip().lower()] = GroupIdentity(
            display_name=spec["display_name"],
            department=spec["department"],
            division=spec["division"],
            type=spec["type"],
        )

    return GroupsConfig(accounts=accounts, fallback=fallback)


def load_sources(path: Path) -> SourcesConfig:
    raw = _load_yaml(path)
    return SourcesConfig(
        cluster_name=raw.get("cluster_name", "dsicluster"),
        privacy=raw.get("privacy") or {},
        sources=raw.get("sources") or {},
        publish=raw.get("publish") or {},
    )


def load(config_dir: Path | str | None = None) -> Config:
    directory = Path(config_dir) if config_dir else DEFAULT_CONFIG_DIR
    return Config(
        cluster=load_cluster(directory / "cluster.yaml"),
        groups=load_groups(directory / "groups.yaml"),
        sources=load_sources(directory / "sources.yaml"),
        config_dir=directory,
    )
