"""Locating and running FFmpeg / FFprobe."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)


class ToolError(RuntimeError):
    """Raised when an external tool is missing or fails."""


def _find(name: str, env_var: str) -> str:
    override = os.environ.get(env_var)
    if override:
        if not Path(override).exists():
            raise ToolError(f"{env_var} points to {override}, which does not exist")
        return override
    found = shutil.which(name)
    if not found:
        raise ToolError(
            f"{name} was not found. Install FFmpeg and add its bin folder to PATH, "
            f"or set {env_var} to the full path of {name}."
        )
    return found


def ffmpeg_bin() -> str:
    return _find("ffmpeg", "ELIXIR_FFMPEG")


def ffprobe_bin() -> str:
    return _find("ffprobe", "ELIXIR_FFPROBE")


def run(cmd: list[str], cwd: Path | None = None, timeout: float | None = None) -> subprocess.CompletedProcess:
    """Run a command, capturing output as text. Raises ToolError on failure."""
    log.debug("run: %s", " ".join(cmd))
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise ToolError(f"Timed out after {timeout}s: {cmd[0]}") from exc
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-15:])
        raise ToolError(f"{Path(cmd[0]).name} failed (exit {proc.returncode}):\n{tail}")
    return proc


def ffprobe_json(path: Path) -> dict:
    proc = run(
        [ffprobe_bin(), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)]
    )
    return json.loads(proc.stdout)
