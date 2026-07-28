"""Write the published tree and push it.

Two invariants enforced here:

  1. Only paths in `publish.allowed_paths` are ever staged. The collector
     holds a write-capable deploy key; a bug that stages the whole tree would
     let a machine rewrite site source or workflows. `git add` is scoped and
     the staged set is checked before commit.

  2. Nothing is committed until the privacy gate has passed over the bytes on
     disk. verify happens after writing, before staging.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from .config import Config
from .runner import CommandError, Runner, SubprocessRunner
from .state import utc_now_iso
from .transform import privacy


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        json.dump(payload, fh, indent=2, sort_keys=False)
        fh.write("\n")


def merge_month(
    existing: dict[str, Any] | None, month: str, new_days: list[dict]
) -> dict[str, Any]:
    """Merge freshly computed days into an existing month file.

    Recomputed days replace their previous version — that is what makes the
    resettle window work, and what makes a rerun idempotent.
    """
    by_date: dict[str, dict] = {}
    if existing and isinstance(existing.get("days"), list):
        for day in existing["days"]:
            if isinstance(day, dict) and "date" in day:
                by_date[day["date"]] = day
    for day in new_days:
        by_date[day["date"]] = day
    return {
        "month": month,
        "generated": utc_now_iso(),
        "days": [by_date[k] for k in sorted(by_date)],
    }


class Publisher:
    def __init__(self, config: Config, repo_dir: Path | str, runner: Runner | None = None):
        self.config = config
        self.repo_dir = Path(repo_dir)
        self.runner = runner or SubprocessRunner()
        publish = config.sources.publish
        self.data_dir = self.repo_dir / publish.get("data_dir", "data")
        self.summary_path = self.repo_dir / publish.get("summary_path", "_data/summary.json")
        self.allowed_paths = publish.get("allowed_paths", ["data/", "_data/summary.json"])

    # -- reading what is already published --------------------------------

    def read_month(self, month: str) -> dict[str, Any] | None:
        path = self.data_dir / "daily" / f"{month}.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            return None

    def read_all_days(self) -> list[dict]:
        """Every published day record, oldest first."""
        out: list[dict] = []
        daily = self.data_dir / "daily"
        if not daily.exists():
            return out
        for path in sorted(daily.glob("*.json")):
            try:
                payload = json.loads(path.read_text())
            except json.JSONDecodeError:
                continue
            for day in payload.get("days", []):
                if isinstance(day, dict) and "date" in day:
                    out.append(day)
        return sorted(out, key=lambda d: d["date"])

    # -- writing ----------------------------------------------------------

    def write_days(self, day_records: list[dict]) -> list[str]:
        """Write day records into their month files. Returns months touched."""
        by_month: dict[str, list[dict]] = {}
        for record in day_records:
            key = privacy.month_key(date.fromisoformat(record["date"]))
            by_month.setdefault(key, []).append(record)

        for month, days in sorted(by_month.items()):
            merged = merge_month(self.read_month(month), month, days)
            _write_json(self.data_dir / "daily" / f"{month}.json", merged)
        return sorted(by_month)

    def write_index(self) -> list[str]:
        """List the months that exist, so the browser never has to guess.

        Without this the client would 404 its way across the calendar looking
        for month files, which is slow and noisy in the console.
        """
        daily = self.data_dir / "daily"
        months = sorted(p.stem for p in daily.glob("*.json")) if daily.exists() else []
        _write_json(
            self.data_dir / "index.json",
            {"generated": utc_now_iso(), "months": months},
        )
        return months

    def write_rollup(self, name: str, payload: dict[str, Any]) -> None:
        payload = {**payload, "generated": utc_now_iso()}
        _write_json(self.data_dir / "rollups" / f"{name}.json", payload)

    def write_doc(self, name: str, payload: dict[str, Any]) -> None:
        payload = {**payload, "generated": utc_now_iso()}
        _write_json(self.data_dir / f"{name}.json", payload)

    def write_summary(self, payload: dict[str, Any]) -> None:
        payload = {**payload, "generated": utc_now_iso()}
        _write_json(self.summary_path, payload)

    # -- the gate ---------------------------------------------------------

    def verify(self) -> int:
        """Run every privacy assertion over what is actually on disk."""
        privacy.reset_allowed_strings()
        privacy.register_allowed_strings(self._operator_strings())
        return privacy.verify_tree(
            self.data_dir,
            self.config.groups,
            self.config.sources.k_anonymity,
            summary_path=self.summary_path,
        )

    def _operator_strings(self) -> list[str]:
        """Display strings an operator deliberately authored in config.

        These are the only values allowed to contain spaces or punctuation
        that the safe-token rule would otherwise reject.
        """
        values: list[str] = []
        for model in self.config.cluster.gpu_models.values():
            values.append(model.display)
        for fs in self.config.cluster.filesystems:
            values.extend([fs.display, fs.name])
        for identity in self.config.groups.accounts.values():
            values.extend(
                [identity.display_name, identity.department, identity.division, identity.type]
            )
        values.extend(
            [
                self.config.groups.fallback.display_name,
                self.config.groups.fallback.department,
                self.config.groups.fallback.division,
                self.config.groups.fallback.type,
            ]
        )
        pricing = self.config.cluster.cloud_pricing or {}
        for key in ("basis", "source", "currency"):
            if pricing.get(key):
                values.append(str(pricing[key]))
        return values

    # -- git --------------------------------------------------------------

    def _git(self, *args: str, timeout: int = 300) -> str:
        return self.runner.run(["git", "-C", str(self.repo_dir), *args], timeout=timeout)

    def has_changes(self) -> bool:
        out = self._git("status", "--porcelain", "--", *self.allowed_paths)
        return bool(out.strip())

    def commit_and_push(self, message: str, *, push: bool = True) -> str:
        """Stage only allowed paths, verify the staged set, commit, push.

        Rebase-and-retry on rejection: a human pushing to main at the same
        moment as the nightly run is normal and should not need intervention.
        """
        if not self.has_changes():
            return "no-changes"

        self._git("add", "--", *self.allowed_paths)

        staged = [
            line.strip()
            for line in self._git("diff", "--cached", "--name-only").splitlines()
            if line.strip()
        ]
        stray = [
            p for p in staged if not any(p.startswith(a.rstrip("/")) for a in self.allowed_paths)
        ]
        if stray:
            self._git("reset")
            raise RuntimeError(
                f"refusing to commit: staged path(s) outside publish.allowed_paths: {stray}"
            )

        author = self.config.sources.publish.get(
            "commit_author", "cluster-impact bot <techstaff@ds.uchicago.edu>"
        )
        self._git(
            "-c",
            f"user.name={author.split('<')[0].strip()}",
            "-c",
            f"user.email={author.split('<')[1].rstrip('>')}",
            "commit",
            "-m",
            message,
        )

        if not push:
            return "committed"

        branch = self.config.sources.publish.get("branch", "main")
        retries = int(self.config.sources.publish.get("rebase_retries", 3))
        last_error = ""
        for attempt in range(retries + 1):
            try:
                self._git("push", "origin", f"HEAD:{branch}")
                return "pushed"
            except CommandError as exc:
                last_error = exc.stderr
                if attempt == retries:
                    break
                try:
                    self._git("pull", "--rebase", "origin", branch)
                except CommandError as pull_exc:
                    last_error = pull_exc.stderr
                    break
        raise RuntimeError(f"push failed after {retries} retries: {last_error.strip()[:400]}")
