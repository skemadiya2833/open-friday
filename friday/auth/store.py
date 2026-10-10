"""Persistent store for devices, pending pairings, challenges, sessions."""

from __future__ import annotations

import json
import secrets
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from friday.atomic import write_text_atomic
from friday.auth.roles import Role, parse_role

_lock = threading.RLock()
_store: "AuthStore | None" = None


def _now() -> float:
    return time.time()


class AuthStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data: dict[str, Any] = {
            "devices": {},
            "pending": {},
            "enrollment": {},
            "challenges": {},
            "sessions": {},
            "stepup": {},
            "rate": {},
        }
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                self.data.update(json.loads(self.path.read_text(encoding="utf-8")))
            except Exception:  # noqa: BLE001
                pass

    def save(self) -> None:
        write_text_atomic(self.path, json.dumps(self.data, indent=2, ensure_ascii=False))

    # -- rate limit ---------------------------------------------------------
    def rate_hit(self, key: str, *, limit: int = 10, window: float = 60.0) -> bool:
        """Return True if allowed, False if locked out."""
        now = _now()
        bucket = self.data.setdefault("rate", {}).setdefault(key, [])
        bucket[:] = [t for t in bucket if now - t < window]
        if len(bucket) >= limit:
            return False
        bucket.append(now)
        self.save()
        return True

    # -- pairing ------------------------------------------------------------
    def create_pending(self, device_name: str, soft: dict[str, Any]) -> dict[str, Any]:
        code = f"{secrets.randbelow(1000000):06d}"
        pid = str(uuid.uuid4())
        rec = {
            "id": pid,
            "device_name": device_name.strip()[:64] or "unnamed",
            "code": code,
            "soft": soft,
            "created": _now(),
            "expires": _now() + 600,
            "status": "pending",
        }
        self.data.setdefault("pending", {})[pid] = rec
        self.save()
        return rec

    def get_pending(self, pid: str) -> dict[str, Any] | None:
        rec = self.data.get("pending", {}).get(pid)
        if not rec:
            return None
        if rec["expires"] < _now() or rec["status"] not in ("pending", "approved"):
            return None
        return rec

    def list_pending(self) -> list[dict[str, Any]]:
        now = _now()
        out = []
        for rec in self.data.get("pending", {}).values():
            if rec.get("status") == "pending" and rec.get("expires", 0) >= now:
                out.append(rec)
        return sorted(out, key=lambda r: r["created"], reverse=True)

    def approve_pending(self, pid: str, code: str) -> dict[str, Any] | None:
        rec = self.get_pending(pid)
        if not rec or rec["status"] != "pending":
            return None
        if not secrets.compare_digest(rec["code"], code.strip()):
            return None
        token = secrets.token_urlsafe(32)
        rec["status"] = "approved"
        rec["enrollment_token"] = token
        self.data.setdefault("enrollment", {})[token] = {
            "pending_id": pid,
            "device_name": rec["device_name"],
            "expires": _now() + 300,
            "used": False,
        }
        self.save()
        return {"pending": rec, "enrollment_token": token}

    def peek_enrollment(self, token: str) -> dict[str, Any] | None:
        en = self.data.get("enrollment", {}).get(token)
        if not en or en.get("used") or en.get("expires", 0) < _now():
            return None
        return en

    def consume_enrollment(self, token: str) -> dict[str, Any] | None:
        en = self.peek_enrollment(token)
        if not en:
            return None
        en["used"] = True
        self.save()
        return en

    # -- challenges ---------------------------------------------------------
    def put_challenge(self, kind: str, user_handle: str, challenge: str, *, ttl: float = 120.0) -> None:
        self.data.setdefault("challenges", {})[challenge] = {
            "kind": kind,
            "user_handle": user_handle,
            "expires": _now() + ttl,
        }
        self.save()

    def take_challenge(self, challenge: str, kind: str) -> dict[str, Any] | None:
        ch = self.data.get("challenges", {}).pop(challenge, None)
        self.save()
        if not ch or ch.get("kind") != kind or ch.get("expires", 0) < _now():
            return None
        return ch

    # -- devices ------------------------------------------------------------
    def add_device(
        self,
        *,
        credential_id: str,
        public_key: str,
        sign_count: int,
        label: str,
        role: Role = Role.CHAT,
        user_handle: str,
    ) -> dict[str, Any]:
        did = str(uuid.uuid4())
        rec = {
            "id": did,
            "credential_id": credential_id,
            "public_key": public_key,
            "sign_count": int(sign_count),
            "label": label[:64],
            "role": role.value,
            "user_handle": user_handle,
            "created": _now(),
            "last_used": _now(),
            "revoked": False,
        }
        self.data.setdefault("devices", {})[did] = rec
        self.save()
        return rec

    def device_by_credential(self, credential_id: str) -> dict[str, Any] | None:
        for d in self.data.get("devices", {}).values():
            if d.get("credential_id") == credential_id and not d.get("revoked"):
                return d
        return None

    def list_devices(self) -> list[dict[str, Any]]:
        return sorted(
            (d for d in self.data.get("devices", {}).values() if not d.get("revoked")),
            key=lambda d: d.get("last_used", 0),
            reverse=True,
        )

    def update_device(self, did: str, **fields: Any) -> dict[str, Any] | None:
        d = self.data.get("devices", {}).get(did)
        if not d or d.get("revoked"):
            return None
        if "label" in fields and fields["label"] is not None:
            d["label"] = str(fields["label"])[:64]
        if "role" in fields and fields["role"] is not None:
            d["role"] = parse_role(str(fields["role"])).value
        if "sign_count" in fields:
            d["sign_count"] = int(fields["sign_count"])
        if "last_used" in fields:
            d["last_used"] = float(fields["last_used"])
        self.save()
        return d

    def revoke_device(self, did: str) -> bool:
        d = self.data.get("devices", {}).get(did)
        if not d:
            return False
        d["revoked"] = True
        # kill sessions
        for sid, sess in list(self.data.get("sessions", {}).items()):
            if sess.get("device_id") == did:
                self.data["sessions"].pop(sid, None)
        self.save()
        return True

    # -- sessions -----------------------------------------------------------
    def create_session(self, device_id: str, role: str, ttl: int) -> dict[str, Any]:
        sid = secrets.token_urlsafe(32)
        rec = {
            "id": sid,
            "device_id": device_id,
            "role": role,
            "created": _now(),
            "expires": _now() + ttl,
        }
        self.data.setdefault("sessions", {})[sid] = rec
        self.save()
        return rec

    def get_session(self, sid: str) -> dict[str, Any] | None:
        sess = self.data.get("sessions", {}).get(sid)
        if not sess or sess.get("expires", 0) < _now():
            if sess:
                self.data["sessions"].pop(sid, None)
                self.save()
            return None
        return sess

    def delete_session(self, sid: str) -> None:
        self.data.get("sessions", {}).pop(sid, None)
        self.save()

    def mark_stepup(self, session_id: str, ttl: float = 60.0) -> None:
        self.data.setdefault("stepup", {})[session_id] = _now() + ttl
        self.save()

    def stepup_ok(self, session_id: str) -> bool:
        exp = self.data.get("stepup", {}).get(session_id, 0)
        return float(exp) >= _now()


def get_store(path: Path | None = None) -> AuthStore:
    global _store
    with _lock:
        if _store is None:
            from friday.config import DATA_DIR

            _store = AuthStore(path or Path(DATA_DIR) / "auth" / "devices.json")
        return _store


def set_store(store: AuthStore | None) -> None:
    global _store
    with _lock:
        _store = store
