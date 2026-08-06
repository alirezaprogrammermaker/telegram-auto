"""Ensure only one app instance uses the Telegram session."""
from __future__ import annotations

import atexit
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class ProcessLock:
    """PID-file lock with stale-lock recovery."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._held = False

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            try:
                old_pid = int(self.path.read_text(encoding="utf-8").strip())
            except ValueError:
                old_pid = -1

            if _pid_alive(old_pid):
                raise RuntimeError(
                    f"Another instance is already running (pid={old_pid}, lock={self.path}). "
                    "Stop it before starting again to avoid session conflicts."
                )
            logger.warning("Removing stale lock from pid=%s", old_pid)
            try:
                self.path.unlink(missing_ok=True)
            except OSError as exc:
                raise RuntimeError(f"Cannot remove stale lock {self.path}: {exc}") from exc

        try:
            fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise RuntimeError(f"Lock already exists: {self.path}") from exc

        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(str(os.getpid()))

        self._held = True
        atexit.register(self.release)
        logger.info("Acquired process lock (%s)", self.path.name)

    def release(self) -> None:
        if not self._held:
            return
        self._held = False
        try:
            if self.path.exists():
                current = self.path.read_text(encoding="utf-8").strip()
                if current == str(os.getpid()):
                    self.path.unlink(missing_ok=True)
                    logger.info("Released process lock")
        except OSError as exc:
            logger.warning("Failed to release lock: %s", exc)
