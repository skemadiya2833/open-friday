"""Store the Google Calendar secret iCal URL (no OAuth)."""

from __future__ import annotations

import logging
import stat
import warnings
from pathlib import Path
from urllib.parse import urlparse

from friday.config import DATA_DIR, ensure_data_dirs

log = logging.getLogger(__name__)

_KEYRING_SERVICE = "friday"
_KEYRING_USER = "calendar_ical"
_FILE_NAME = "calendar_ical.url"


def _file_path() -> Path:
    ensure_data_dirs()
    return Path(DATA_DIR) / _FILE_NAME


def _keyring_mod():
    try:
        import keyring  # type: ignore[import-untyped]

        return keyring
    except ImportError:
        return None


def redact_url(url: str | None) -> str:
    """Show scheme+host+last4 only; never log the full secret URL."""
    if not url or not url.strip():
        return "(not set)"
    u = url.strip()
    try:
        p = urlparse(u)
        scheme = p.scheme or "?"
        host = p.hostname or p.netloc or "?"
        tail = (p.path or "") + (f"?{p.query}" if p.query else "")
        if len(tail) >= 4:
            last4 = tail[-4:]
        elif u:
            last4 = u[-4:]
        else:
            last4 = "????"
        return f"{scheme}://{host}/…{last4}"
    except Exception:  # noqa: BLE001
        return f"…{u[-4:]}" if len(u) >= 4 else "…????"


def configured() -> bool:
    return bool(get_ical_url())


def get_ical_url() -> str | None:
    kr = _keyring_mod()
    if kr is not None:
        try:
            val = kr.get_password(_KEYRING_SERVICE, _KEYRING_USER)
            if val:
                return val.strip()
        except Exception as exc:  # noqa: BLE001
            log.debug("keyring read failed: %s", redact_url(str(exc)))
    p = _file_path()
    if p.is_file():
        try:
            return p.read_text(encoding="utf-8").strip() or None
        except OSError as exc:
            log.warning("Could not read calendar URL file: %s", exc)
    return None


def _warn_file_permissions(path: Path) -> None:
    try:
        mode = path.stat().st_mode
        if mode & (stat.S_IRGRP | stat.S_IROTH | stat.S_IWGRP | stat.S_IWOTH):
            warnings.warn(
                f"Calendar secret URL file may be world/group readable: {path}. "
                "Restrict permissions (owner-only) or use keyring.",
                stacklevel=3,
            )
    except OSError:
        pass


def set_ical_url(url: str) -> None:
    url = url.strip()
    if not url:
        raise ValueError("URL must be non-empty")
    kr = _keyring_mod()
    if kr is not None:
        try:
            kr.set_password(_KEYRING_SERVICE, _KEYRING_USER, url)
            p = _file_path()
            if p.is_file():
                try:
                    p.unlink()
                except OSError:
                    pass
            log.info("Calendar iCal URL stored in keyring (%s)", redact_url(url))
            return
        except Exception as exc:  # noqa: BLE001
            log.warning("keyring write failed, falling back to file: %s", exc)
    from friday.atomic import write_text_atomic

    p = _file_path()
    write_text_atomic(p, url + "\n")
    _warn_file_permissions(p)
    log.info("Calendar iCal URL stored in file (%s)", redact_url(url))


def clear_ical_url() -> None:
    kr = _keyring_mod()
    if kr is not None:
        try:
            kr.delete_password(_KEYRING_SERVICE, _KEYRING_USER)
        except Exception:  # noqa: BLE001
            pass
    p = _file_path()
    if p.is_file():
        try:
            p.unlink()
        except OSError as exc:
            log.warning("Could not remove calendar URL file: %s", exc)
