"""Command execution, with a fixture backend so the pipeline is testable offline.

Every external command goes through a Runner. In production that shells out;
in tests and in `make collect-dry` it reads canned output from a directory.
That is what makes the whole aggregation path runnable on a laptop with no
Slurm, no LDAP, and no cluster network.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Protocol


class CommandError(RuntimeError):
    def __init__(self, argv: list[str], returncode: int, stderr: str):
        self.argv = argv
        self.returncode = returncode
        self.stderr = stderr
        super().__init__(f"{argv[0]} exited {returncode}: {stderr.strip()[:500]}")


class Runner(Protocol):
    def run(self, argv: list[str], *, timeout: int = 300) -> str: ...


class SubprocessRunner:
    """Runs commands for real."""

    def run(self, argv: list[str], *, timeout: int = 300) -> str:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        if proc.returncode != 0:
            raise CommandError(argv, proc.returncode, proc.stderr)
        return proc.stdout


class FixtureRunner:
    """Reads canned output from `<dir>/<command>.txt`.

    Dispatch is on the command name alone (argv[0] basename), so a fixture
    covers every invocation of that tool. Good enough: the parsers are what we
    are testing, and pinning exact argv would make fixtures brittle.
    """

    def __init__(self, directory: Path | str):
        self.directory = Path(directory)
        self.calls: list[list[str]] = []

    def run(self, argv: list[str], *, timeout: int = 300) -> str:
        self.calls.append(list(argv))
        name = Path(argv[0]).name
        path = self.directory / f"{name}.txt"
        if not path.exists():
            raise CommandError(argv, 127, f"no fixture at {path}")
        return path.read_text()
