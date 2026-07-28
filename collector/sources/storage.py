"""ZFS capacity and I/O on the storage nodes.

Root on cluster-storage2/4 is reachable from builder, not from the login
nodes (permitted_root_nets), so commands are wrapped in an ssh hop through
whatever `ssh_via` names. Capacity comes from `zfs list`; I/O RATES come from
Prometheus, because zpool iostat's cumulative counters reset on reboot and
would produce nonsense deltas.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from ..config import Filesystem
from ..runner import CommandError, Runner


@dataclass
class DatasetUsage:
    filesystem: str
    display: str
    kind: str
    used_bytes: int
    available_bytes: int
    referenced_bytes: int

    @property
    def total_bytes(self) -> int:
        return self.used_bytes + self.available_bytes


class StorageSource:
    def __init__(self, runner: Runner, settings: dict):
        self.runner = runner
        self.settings = settings or {}

    def _ssh(self, host: str, command: list[str]) -> list[str]:
        via = self.settings.get("ssh_via")
        user = self.settings.get("ssh_user", "root")
        remote = " ".join(command)
        if via:
            # Hop through the jump host, then on to the storage node.
            return [
                "ssh",
                "-o",
                "BatchMode=yes",
                f"{user}@{via}",
                "ssh",
                "-o",
                "BatchMode=yes",
                f"{user}@{host}",
                remote,
            ]
        return ["ssh", "-o", "BatchMode=yes", f"{user}@{host}", remote]

    def fetch_capacity(self, filesystems: list[Filesystem]) -> tuple[list[DatasetUsage], list[str]]:
        """Per-dataset capacity. Returns (results, warnings).

        A single unreachable storage node degrades its own panel rather than
        failing the run — one node down should not blank the whole site.
        """
        results: list[DatasetUsage] = []
        warnings: list[str] = []
        timeout = int(self.settings.get("timeout_seconds", 60))

        by_host: dict[str, list[Filesystem]] = {}
        for fs in filesystems:
            if fs.host and fs.dataset:
                by_host.setdefault(fs.host, []).append(fs)

        for host, entries in sorted(by_host.items()):
            datasets = [fs.dataset for fs in entries]
            argv = self._ssh(
                host,
                ["zfs", "list", "-Hp", "-o", "name,used,available,referenced", *datasets],
            )
            try:
                out = self.runner.run(argv, timeout=timeout)
            except (CommandError, OSError) as exc:
                warnings.append(f"storage: {host} unreachable ({type(exc).__name__})")
                continue

            by_dataset = {fs.dataset: fs for fs in entries}
            for line in out.splitlines():
                parts = line.split("\t")
                if len(parts) < 4:
                    continue
                fs = by_dataset.get(parts[0].strip())
                if fs is None:
                    continue
                try:
                    results.append(
                        DatasetUsage(
                            filesystem=fs.name,
                            display=fs.display,
                            kind=fs.kind,
                            used_bytes=int(parts[1]),
                            available_bytes=int(parts[2]),
                            referenced_bytes=int(parts[3]),
                        )
                    )
                except ValueError:
                    warnings.append(f"storage: unparsable zfs row on {host}: {line[:80]}")

        return results, warnings

    @staticmethod
    def to_public(usages: list[DatasetUsage]) -> dict[str, Any]:
        tib = 1024**4
        entries = []
        for usage in usages:
            entries.append(
                {
                    **{k: v for k, v in asdict(usage).items() if k in ("kind",)},
                    "name": usage.display,
                    "used_tib": round(usage.used_bytes / tib, 2),
                    "total_tib": round(usage.total_bytes / tib, 2),
                    "percent_used": (
                        round(usage.used_bytes / usage.total_bytes, 4)
                        if usage.total_bytes > 0
                        else None
                    ),
                }
            )
        total_tib = round(sum(u.total_bytes for u in usages) / tib, 2)
        used_tib = round(sum(u.used_bytes for u in usages) / tib, 2)
        return {
            "available": bool(entries),
            "filesystems": sorted(entries, key=lambda e: -e["total_tib"]),
            "total_tib": total_tib,
            "used_tib": used_tib,
            "total_pib": round(total_tib / 1024, 3),
        }
