"""On-cluster state. Never part of the repository.

Two things live here that cannot live in a public repo but are needed to
compute correct numbers:

  raw/       daily snapshots of source output, so aggregates can be re-derived
             without re-querying slurmdbd (which purges old records)

  users/     a per-day index of HASHED usernames, which is what makes
             "unique users this month", new-user growth, and retention
             cohorts computable at all

Usernames are hashed with a machine-local secret before they touch disk. The
hash is deterministic, so first-seen dates and cohort membership still work,
but a leaked cache directory does not hand over a roster. The secret is
generated on first use and stays in the state directory.
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import os
import secrets
from datetime import date, datetime, timedelta
from pathlib import Path

DEFAULT_STATE_DIR = Path(os.environ.get("CLUSTER_IMPACT_RAW", "/var/lib/cluster-impact/raw"))


class StateStore:
    def __init__(self, root: Path | str | None = None):
        self.root = Path(root) if root else DEFAULT_STATE_DIR
        self.users_dir = self.root / "users"
        self.raw_dir = self.root / "raw"
        self._secret: bytes | None = None

    def ensure(self) -> None:
        self.users_dir.mkdir(parents=True, exist_ok=True)
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.accounts_dir.mkdir(parents=True, exist_ok=True)

    @property
    def accounts_dir(self) -> Path:
        return self.root / "accounts"

    # -- username hashing -------------------------------------------------

    @property
    def secret(self) -> bytes:
        if self._secret is not None:
            return self._secret
        path = self.root / "user-hash.secret"
        if path.exists():
            self._secret = path.read_bytes().strip()
        else:
            self.root.mkdir(parents=True, exist_ok=True)
            value = secrets.token_hex(32).encode()
            path.write_bytes(value)
            with contextlib.suppress(OSError):
                path.chmod(0o600)
            self._secret = value
        return self._secret

    def hash_user(self, username: str) -> str:
        digest = hmac.new(self.secret, username.strip().lower().encode(), hashlib.sha256)
        return digest.hexdigest()[:16]

    # -- the user-day index ----------------------------------------------

    def record_users(self, day: date, usernames: set[str]) -> None:
        self.ensure()
        path = self.users_dir / f"{day.isoformat()}.txt"
        hashed = sorted({self.hash_user(u) for u in usernames if u})
        path.write_text("\n".join(hashed) + ("\n" if hashed else ""))

    def users_on(self, day: date) -> set[str]:
        path = self.users_dir / f"{day.isoformat()}.txt"
        if not path.exists():
            return set()
        return {line.strip() for line in path.read_text().splitlines() if line.strip()}

    def users_between(self, start: date, end: date) -> set[str]:
        """Union of hashed users over [start, end]."""
        out: set[str] = set()
        cursor = start
        while cursor <= end:
            out |= self.users_on(cursor)
            cursor += timedelta(days=1)
        return out

    def known_days(self) -> list[date]:
        if not self.users_dir.exists():
            return []
        days = []
        for path in self.users_dir.glob("*.txt"):
            try:
                days.append(date.fromisoformat(path.stem))
            except ValueError:
                continue
        return sorted(days)

    def first_seen(self) -> dict[str, date]:
        """Earliest day each hashed user appears. Drives growth and cohorts."""
        first: dict[str, date] = {}
        for day in self.known_days():
            for user in self.users_on(day):
                if user not in first:
                    first[user] = day
        return first

    # -- the account-day index --------------------------------------------
    #
    # Why this exists: k-anonymity has to be applied at the granularity of the
    # bucket being published. A course with three students who each run on
    # different days never has three users on ANY single day, so per-day
    # suppression would hide it from the monthly view too if rollups were
    # derived from already-suppressed daily records. This index keeps the
    # per-account usage and hashed user sets on-cluster so a monthly bucket
    # can be judged on its own monthly distinct-user count.

    def record_accounts(self, day: date, by_account: dict) -> None:
        """Persist per-account usage for one day. Usernames are hashed."""
        self.ensure()
        payload = {
            account: {
                "gpu_seconds": round(usage.gpu_seconds, 3),
                "cpu_seconds": round(usage.cpu_seconds, 3),
                "jobs": usage.jobs,
                "users": sorted(self.hash_user(u) for u in usage.users if u),
            }
            for account, usage in by_account.items()
        }
        path = self.accounts_dir / f"{day.isoformat()}.json"
        path.write_text(json.dumps(payload, sort_keys=True))

    def accounts_on(self, day: date) -> dict:
        path = self.accounts_dir / f"{day.isoformat()}.json"
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            return {}

    def accounts_between(self, start: date, end: date) -> dict:
        """Merge per-account usage over [start, end], unioning user sets."""
        merged: dict[str, dict] = {}
        cursor = start
        while cursor <= end:
            for account, usage in self.accounts_on(cursor).items():
                entry = merged.setdefault(
                    account, {"gpu_seconds": 0.0, "cpu_seconds": 0.0, "jobs": 0, "users": set()}
                )
                entry["gpu_seconds"] += usage.get("gpu_seconds", 0.0)
                entry["cpu_seconds"] += usage.get("cpu_seconds", 0.0)
                entry["jobs"] += usage.get("jobs", 0)
                entry["users"].update(usage.get("users", []))
            cursor += timedelta(days=1)
        return merged

    def has_account_index(self) -> bool:
        return self.accounts_dir.exists() and any(self.accounts_dir.glob("*.json"))

    # -- raw snapshots ----------------------------------------------------

    def write_raw(self, day: date, name: str, content: str) -> Path:
        self.ensure()
        directory = self.raw_dir / f"{day.year:04d}" / f"{day.month:02d}"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{day.isoformat()}.{name}.txt"
        path.write_text(content)
        return path

    def read_raw(self, day: date, name: str) -> str | None:
        path = (
            self.raw_dir / f"{day.year:04d}" / f"{day.month:02d}" / f"{day.isoformat()}.{name}.txt"
        )
        return path.read_text() if path.exists() else None

    # -- run bookkeeping --------------------------------------------------

    def write_checkpoint(self, payload: dict) -> None:
        self.ensure()
        (self.root / "checkpoint.json").write_text(json.dumps(payload, indent=2, default=str))

    def read_checkpoint(self) -> dict:
        path = self.root / "checkpoint.json"
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            return {}


class MemoryStateStore(StateStore):
    """In-memory variant for tests and `make collect-dry`."""

    def __init__(self) -> None:
        super().__init__(root=Path("/nonexistent"))
        self._users: dict[date, set[str]] = {}
        self._accounts: dict[date, dict] = {}
        self._secret = b"test-secret-not-for-production"

    def ensure(self) -> None:  # no-op
        return

    def record_users(self, day: date, usernames: set[str]) -> None:
        self._users[day] = {self.hash_user(u) for u in usernames if u}

    def users_on(self, day: date) -> set[str]:
        return set(self._users.get(day, set()))

    def known_days(self) -> list[date]:
        return sorted(self._users)

    def record_accounts(self, day: date, by_account: dict) -> None:
        self._accounts[day] = {
            account: {
                "gpu_seconds": usage.gpu_seconds,
                "cpu_seconds": usage.cpu_seconds,
                "jobs": usage.jobs,
                "users": sorted(self.hash_user(u) for u in usage.users if u),
            }
            for account, usage in by_account.items()
        }

    def accounts_on(self, day: date) -> dict:
        return self._accounts.get(day, {})

    def has_account_index(self) -> bool:
        return bool(self._accounts)

    def write_raw(self, day: date, name: str, content: str) -> Path:
        return Path("/dev/null")

    def read_raw(self, day: date, name: str) -> str | None:
        return None

    def write_checkpoint(self, payload: dict) -> None:
        return

    def read_checkpoint(self) -> dict:
        return {}


def utc_now_iso() -> str:
    return datetime.now().astimezone().replace(microsecond=0).isoformat()
