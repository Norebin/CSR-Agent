"""Helpers for safe external command execution in tool adapters."""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


@dataclass(slots=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str
    command: list[str]
    cwd: str | None

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    def tail(self, text: str, max_chars: int = 4000) -> str:
        if len(text) <= max_chars:
            return text
        return text[-max_chars:]


def run_command(
    command: list[str],
    cwd: str | Path | None = None,
    timeout_sec: int = 120,
    env: Mapping[str, str] | None = None,
) -> CommandResult:
    """Run command and return captured output with robust decoding."""
    cwd_str = str(cwd) if cwd is not None else None
    try:
        proc = subprocess.run(
            command,
            cwd=cwd_str,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            errors="replace",
            shell=False,
            env=dict(env) if env is not None else None,
        )
        return CommandResult(
            returncode=proc.returncode,
            stdout=proc.stdout or "",
            stderr=proc.stderr or "",
            command=command,
            cwd=cwd_str,
        )
    except FileNotFoundError as exc:
        return CommandResult(
            returncode=127,
            stdout="",
            stderr=str(exc),
            command=command,
            cwd=cwd_str,
        )
    except subprocess.TimeoutExpired as exc:
        return CommandResult(
            returncode=124,
            stdout=(exc.stdout or "") if isinstance(exc.stdout, str) else "",
            stderr=(exc.stderr or "") if isinstance(exc.stderr, str) else "command timeout",
            command=command,
            cwd=cwd_str,
        )


def split_command(command: str | list[str] | None) -> list[str] | None:
    """Normalize command config to argv list."""
    if command is None:
        return None
    if isinstance(command, list):
        return [str(x) for x in command]
    text = command.strip()
    if not text:
        return None
    return shlex.split(text, posix=False)
