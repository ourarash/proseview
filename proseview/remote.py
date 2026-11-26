"""``proseview --remote``: open this Proseview on your phone over Tailscale.

Proseview opens a second loopback listener just for the phone and runs
``tailscale serve`` in the foreground, pointed at it. Serve gives the phone
an ``https://<laptop>.<tailnet>.ts.net`` address and adds the caller's
Tailscale login to every request (replacing any the caller sent), so the
phone listener only has to check that the login is the laptop's own.

Proseview owns only its own serve mapping: it refuses to start if port 443 is
already served, and stops serve with SIGINT on exit so serve removes its own
mapping. It never runs ``tailscale serve reset`` or ``--bg``.
"""

from __future__ import annotations

import json
import shutil
import signal
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import urlparse

MAC_APP_CLI = "/Applications/Tailscale.app/Contents/MacOS/Tailscale"
LOGIN_HEADER = "Tailscale-User-Login"
ADMIN_MACHINES_URL = "https://login.tailscale.com/admin/machines"

#: Routes that act on the laptop itself (Finder, the default app, a sign-in
#: window, the privacy password), refused from the phone.
LAPTOP_ONLY_PATHS = frozenset({
    "/api/files/reveal",
    "/api/export/open",
    "/api/export/reveal",
    "/api/discuss/claude/login",
    "/api/privacy/password",
})


class RemoteError(RuntimeError):
    """Remote mode cannot start; the message says what to do, in one sentence."""


def find_tailscale(which: Callable[[str], str | None] = shutil.which) -> str:
    found = which("tailscale")
    if found:
        return found
    if Path(MAC_APP_CLI).is_file():
        return MAC_APP_CLI
    raise RemoteError(
        "Tailscale is not installed: install it from tailscale.com/download, "
        "sign in, then run proseview --remote again."
    )


def _run_json(cli: str, *args: str) -> Any:
    try:
        done = subprocess.run(
            [cli, *args, "--json"], capture_output=True, text=True, timeout=15, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RemoteError(f"Could not run tailscale {' '.join(args)}: {exc}.") from exc
    if done.returncode != 0:
        detail = (done.stderr or done.stdout).strip().splitlines()
        reason = detail[0] if detail else f"exit code {done.returncode}"
        raise RemoteError(f"tailscale {' '.join(args)} failed ({reason}); is Tailscale running and signed in?")
    try:
        return json.loads(done.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise RemoteError(f"tailscale {' '.join(args)} gave output Proseview could not read.") from exc


@dataclass(frozen=True)
class Identity:
    """The laptop on the tailnet: its HTTPS name and its owner's login."""

    dns_name: str
    login: str

    @property
    def url(self) -> str:
        return f"https://{self.dns_name}"


def identity_from_status(status: Mapping[str, Any]) -> Identity:
    """The laptop's name and login from ``tailscale status --json``, or why remote can't run."""
    if status.get("BackendState") not in (None, "Running"):
        raise RemoteError("Tailscale is not connected: open Tailscale, sign in, then try again.")
    me = status.get("Self") or {}
    if me.get("Tags"):
        raise RemoteError(
            "This Mac is a tagged Tailscale device, so it has no login for the phone "
            "to match: remove its tags in the Tailscale admin console."
        )
    dns = str(me.get("DNSName") or "").rstrip(".").lower()
    if not dns:
        raise RemoteError("Tailscale gave this Mac no name: turn on MagicDNS in the Tailscale admin console.")
    if not status.get("CertDomains"):
        raise RemoteError(
            "HTTPS is off for your tailnet: turn on HTTPS Certificates under DNS "
            "in the Tailscale admin console, then try again."
        )
    users = status.get("User") or {}
    user = users.get(str(me.get("UserID"))) or {}
    login = str(user.get("LoginName") or "").strip().lower()
    if not login:
        raise RemoteError("Tailscale gave no login for this Mac: sign in to Tailscale, then try again.")
    return Identity(dns_name=dns, login=login)


def serve_config_in_use(config: Mapping[str, Any]) -> bool:
    """Whether ``tailscale serve status --json`` shows port 443 already served."""
    if "443" in (config.get("TCP") or {}):
        return True
    if any(str(host).endswith(":443") for host in (config.get("Web") or {})):
        return True
    # Funnel or serve for another node name (a Services setup) still holds 443.
    return any(serve_config_in_use(sub) for sub in (config.get("Services") or {}).values()
               if isinstance(sub, Mapping))


def _authority_host(value: str) -> tuple[str, int | None] | None:
    try:
        parsed = urlparse(value if "://" in value else f"https://{value}")
        port = parsed.port
    except ValueError:
        return None
    return (parsed.hostname or "").lower(), port


class RemoteGate:
    """Decides whether a request on the phone listener may proceed.

    Every request must carry exactly one ``Tailscale-User-Login`` equal to the
    laptop's own login, and name the laptop's ``.ts.net`` address. A missing
    header never counts as the laptop: serve sends none for tagged devices.
    """

    def __init__(self, identity: Identity):
        self.identity = identity

    def _names_laptop(self, value: str, scheme_required: bool) -> bool:
        if scheme_required and not value.lower().startswith("https://"):
            return False
        parsed = _authority_host(value)
        if parsed is None:
            return False
        host, port = parsed
        return host == self.identity.dns_name and port in (None, 443)

    def allows(self, headers: Any) -> bool:
        get_all = getattr(headers, "get_all", None)
        logins = get_all(LOGIN_HEADER) if get_all else (
            [headers[LOGIN_HEADER]] if LOGIN_HEADER in headers else None
        )
        if not logins or len(logins) != 1:
            return False
        if str(logins[0]).strip().lower() != self.identity.login:
            return False
        host = headers.get("Host", "")
        if not self._names_laptop(host, scheme_required=False):
            # Serve may pass its own backend Host and the real one in X-Forwarded-Host.
            forwarded = headers.get("X-Forwarded-Host", "")
            if not forwarded or not self._names_laptop(forwarded, scheme_required=False):
                return False
        origin = headers.get("Origin", "")
        return not origin or self._names_laptop(origin, scheme_required=True)


class RemoteSession:
    """Runs ``tailscale serve`` (and ``caffeinate`` on a Mac) for one Proseview."""

    def __init__(self, cli: str, identity: Identity):
        self.cli = cli
        self.identity = identity
        self.gate = RemoteGate(identity)
        self._serve: subprocess.Popen[bytes] | None = None
        self._awake: subprocess.Popen[bytes] | None = None
        self.phones = 0
        self._lock = threading.Lock()

    @classmethod
    def prepare(cls) -> "RemoteSession":
        """Check Tailscale is ready and 443 is free, without changing anything."""
        cli = find_tailscale()
        identity = identity_from_status(_run_json(cli, "status"))
        if serve_config_in_use(_run_json(cli, "serve", "status")):
            raise RemoteError(
                "Tailscale is already serving something on this Mac (maybe another "
                "proseview --remote): stop it, or see `tailscale serve status`."
            )
        return cls(cli, identity)

    def start(self, backend_port: int) -> None:
        self._serve = subprocess.Popen(
            [self.cli, "serve", "--https=443", f"http://127.0.0.1:{backend_port}"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
        try:
            code = self._serve.wait(timeout=2)
        except subprocess.TimeoutExpired:
            code = None
        if code is not None:
            err = (self._serve.stderr.read().decode("utf-8", "replace") if self._serve.stderr else "").strip()
            self._serve = None
            raise RemoteError(f"tailscale serve stopped at once: {err.splitlines()[0] if err else code}.")
        caffeinate = shutil.which("caffeinate") if sys.platform == "darwin" else None
        if caffeinate:
            import os
            self._awake = subprocess.Popen(
                [caffeinate, "-i", "-w", str(os.getpid())],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )

    def stop(self) -> None:
        serve, self._serve = self._serve, None
        if serve is not None and serve.poll() is None:
            # SIGINT lets serve remove its own mapping; kill only if it hangs.
            serve.send_signal(signal.SIGINT)
            try:
                serve.wait(timeout=5)
            except subprocess.TimeoutExpired:
                serve.kill()
                serve.wait(timeout=5)
        awake, self._awake = self._awake, None
        if awake is not None and awake.poll() is None:
            awake.terminate()

    def phone_connected(self, delta: int) -> int:
        with self._lock:
            self.phones = max(0, self.phones + delta)
            return self.phones
