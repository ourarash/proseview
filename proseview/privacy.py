"""The privacy screen's optional password.

Cmd+J J (Ctrl+J J) covers the dashboard with a dull spreadsheet. Anyone can
uncover it the same way unless the writer has set a password with
``proseview privacy-password``. The password is kept only as a salted
PBKDF2 hash, in the same per-user folder as the agent conversations, never in
the book: a repository is shared and pushed, and this is nobody else's.

A covered screen is remembered in a small file beside it, so a reload, a
new tab or a restarted server still opens on the spreadsheet until it is
uncovered (with the password, when there is one).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
from pathlib import Path
from typing import Any

from .discuss import _state_path

ITERATIONS = 200_000


def password_path() -> Path:
    return _state_path().with_name("privacy.json")


def covered_path() -> Path:
    return _state_path().with_name("privacy-covered")


def _read() -> dict[str, Any] | None:
    try:
        data = json.loads(password_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not data.get("hash") or not data.get("salt"):
        return None
    return data


def _digest(password: str, salt: bytes, iterations: int) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations).hex()


def has_password() -> bool:
    return _read() is not None


def set_password(password: str) -> Path:
    """Store a hash of *password*, readable by this user only."""
    if not password:
        raise ValueError("the password cannot be empty")
    salt = secrets.token_bytes(16)
    record = {
        "algorithm": "pbkdf2_sha256",
        "iterations": ITERATIONS,
        "salt": salt.hex(),
        "hash": _digest(password, salt, ITERATIONS),
    }
    path = password_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(record, handle)
    os.replace(tmp, path)
    return path


def clear_password() -> bool:
    """Forget the password. Returns whether there was one."""
    try:
        password_path().unlink()
    except FileNotFoundError:
        return False
    return True


def check_password(password: str) -> bool:
    """True when no password is set, or *password* is it."""
    record = _read()
    if record is None:
        return True
    try:
        salt = bytes.fromhex(str(record["salt"]))
        iterations = int(record.get("iterations") or ITERATIONS)
    except (TypeError, ValueError):
        return False
    return hmac.compare_digest(_digest(str(password), salt, iterations), str(record["hash"]))


class PrivacyLock:
    """Whether the screen is covered, as the server remembers it.

    The flag is a file, not memory, so restarting Proseview does not uncover
    the page. ``available=False`` is Proseview running inside a browser tab,
    where there is no user folder: the page keeps the flag itself there, and
    there is no password.
    """

    def __init__(self, available: bool = True) -> None:
        self.available = available
        self._lock = threading.Lock()

    def _covered(self) -> bool:
        return self.available and covered_path().is_file()

    def state(self) -> dict[str, bool]:
        with self._lock:
            return {
                "available": self.available,
                "password": self.available and has_password(),
                "locked": self._covered(),
            }

    def lock(self) -> dict[str, bool]:
        if self.available:
            with self._lock:
                path = covered_path()
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
        return self.state()

    def change_password(self, current: str, new: str) -> bool:
        """Set, change or (with an empty *new*) remove the password.

        The current one is needed to change or remove it, so a page left
        open cannot be given a password its writer does not know.
        """
        if not self.available or not check_password(current):
            return False
        if new:
            set_password(new)
        else:
            clear_password()
        return True

    def unlock(self, password: str) -> bool:
        if not check_password(password):
            return False
        with self._lock:
            covered_path().unlink(missing_ok=True)
        return True
