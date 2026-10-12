"""Single-instance guard so two Friday processes do not fight over the e-stop hotkey."""

from __future__ import annotations

import atexit
import os
import sys
from pathlib import Path


class SingleInstanceError(RuntimeError):
    pass


_lock_fh = None


def _lock_path() -> Path:
    from friday.config import DATA_DIR, ensure_data_dirs

    ensure_data_dirs()
    return Path(DATA_DIR) / "friday_instance.lock"


def acquire_instance_lock(*, force: bool = False) -> Path:
    """Acquire an exclusive lock file. Raises SingleInstanceError if another live Friday holds it."""
    global _lock_fh
    if os.getenv("FRIDAY_ALLOW_MULTI", "").strip().lower() in ("1", "true", "yes", "on"):
        return _lock_path()
    path = _lock_path()
    if force:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
    # Stale lock: if PID is dead, take over.
    if path.is_file() and not force:
        try:
            old = int(path.read_text(encoding="utf-8").strip().split()[0])
        except (ValueError, IndexError, OSError):
            old = 0
        if old and old != os.getpid() and _pid_alive(old):
            raise SingleInstanceError(
                f"Another Friday instance is already running (pid {old}). "
                f"Stop it before starting a second copy, or set FRIDAY_ALLOW_MULTI=true for tests."
            )
    try:
        fh = open(path, "a+", encoding="utf-8")
        if sys.platform == "win32":
            import msvcrt

            fh.seek(0)
            try:
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                fh.close()
                raise SingleInstanceError(
                    "Another Friday instance is already running (lock held). "
                    "Close the other Control Center / server before starting again."
                ) from exc
        else:
            import fcntl

            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                fh.close()
                raise SingleInstanceError(
                    "Another Friday instance is already running (lock held)."
                ) from exc
        fh.seek(0)
        fh.truncate()
        fh.write(f"{os.getpid()} {time_iso()}\n")
        fh.flush()
        _lock_fh = fh
        atexit.register(release_instance_lock)
        return path
    except SingleInstanceError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise SingleInstanceError(f"Could not acquire instance lock: {exc}") from exc


def time_iso() -> str:
    import time

    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def release_instance_lock() -> None:
    global _lock_fh
    fh = _lock_fh
    _lock_fh = None
    if fh is None:
        return
    try:
        if sys.platform == "win32":
            import msvcrt

            fh.seek(0)
            try:
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
        fh.close()
    except Exception:
        pass
