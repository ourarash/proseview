"""Tests for ``proseview --remote`` (:mod:`proseview.remote`).

Covers:
- reading the laptop's name and login from ``tailscale status --json``, and
  refusing plainly when HTTPS is off, the Mac is tagged or not signed in
- refusing to start when port 443 is already served
- the phone listener's gate: exactly one login header equal to the laptop's,
  the exact ``.ts.net`` Host and Origin, a 403 on ``/`` otherwise
- laptop-only routes refused from the phone, allowed on the laptop
- the page served to the phone and the laptop says remote mode is on
- stopping serve with SIGINT so it removes its own mapping
"""

from __future__ import annotations

import http.client
import json
import shutil

import subprocess
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from proseview import remote as remote_mod  # noqa: E402
from proseview.remote import (  # noqa: E402
    Identity, RemoteError, RemoteGate, RemoteSession, identity_from_status, serve_config_in_use,
)

DNS = "mac.tail1234.ts.net"
LOGIN = "ari@example.com"
DEMO = REPO_ROOT / "fixtures" / "demo-book"


def status(**overrides):
    base = {
        "BackendState": "Running",
        "Self": {"DNSName": DNS.upper() + ".", "UserID": 7, "Tags": None},
        "User": {"7": {"LoginName": "Ari@Example.com"}},
        "CertDomains": [DNS],
    }
    for key, value in overrides.items():
        if key == "Self":
            base["Self"] = {**base["Self"], **value}
        else:
            base[key] = value
    return base


def test_identity_strips_the_trailing_dot_and_lowercases():
    assert identity_from_status(status()) == Identity(DNS, LOGIN)
    assert Identity(DNS, LOGIN).url == f"https://{DNS}"


@pytest.mark.parametrize("overrides, says", [
    ({"CertDomains": []}, "HTTPS is off"),
    ({"Self": {"Tags": ["tag:server"]}}, "tagged"),
    ({"User": {}}, "no login"),
    ({"BackendState": "NeedsLogin"}, "not connected"),
    ({"Self": {"DNSName": ""}}, "MagicDNS"),
])
def test_identity_refuses_plainly(overrides, says):
    with pytest.raises(RemoteError, match=says):
        identity_from_status(status(**overrides))


@pytest.mark.parametrize("config, in_use", [
    ({}, False),
    ({"TCP": {"8443": {"HTTPS": True}}}, False),
    ({"TCP": {"443": {"HTTPS": True}}}, True),
    ({"Web": {f"{DNS}:443": {"Handlers": {}}}}, True),
    ({"Services": {"svc:x": {"TCP": {"443": {}}}}}, True),
])
def test_an_existing_443_mapping_is_never_overwritten(config, in_use):
    assert serve_config_in_use(config) is in_use


def test_missing_tailscale_says_what_to_do(monkeypatch):
    monkeypatch.setattr(remote_mod, "MAC_APP_CLI", "/nonexistent/Tailscale")
    with pytest.raises(RemoteError, match="tailscale.com/download"):
        remote_mod.find_tailscale(which=lambda _name: None)


class Headers(dict):
    """A header map that can hold the same name twice, like the real one."""

    def __init__(self, pairs):
        super().__init__()
        self.pairs = pairs
        for k, v in pairs:
            self[k] = v

    def get_all(self, name):
        found = [v for k, v in self.pairs if k.lower() == name.lower()]
        return found or None


GOOD = [("Host", DNS), ("Tailscale-User-Login", LOGIN)]


@pytest.mark.parametrize("pairs, allowed", [
    (GOOD, True),
    ([("Host", f"{DNS}:443"), ("Tailscale-User-Login", "ARI@example.com")], True),
    ([*GOOD, ("Origin", f"https://{DNS}")], True),
    ([("Host", DNS)], False),  # a tagged device: serve sends no login
    ([("Host", DNS), ("Tailscale-User-Login", "someone@else.com")], False),
    ([*GOOD, ("Tailscale-User-Login", LOGIN)], False),  # two values
    ([("Host", "other.tail1234.ts.net"), ("Tailscale-User-Login", LOGIN)], False),
    ([("Host", f"{DNS}:8080"), ("Tailscale-User-Login", LOGIN)], False),
    ([*GOOD, ("Origin", f"http://{DNS}")], False),
    ([*GOOD, ("Origin", "https://evil.example")], False),
    ([("Host", "127.0.0.1:5000"), ("X-Forwarded-Host", DNS), ("Tailscale-User-Login", LOGIN)], True),
    ([("Host", "127.0.0.1:5000"), ("Tailscale-User-Login", LOGIN)], False),
])
def test_the_gate(pairs, allowed):
    assert RemoteGate(Identity(DNS, LOGIN)).allows(Headers(pairs)) is allowed


# -- the two listeners ----------------------------------------------------------------


@pytest.fixture
def listeners(tmp_path: Path):
    from proseview.discuss import DiscussManager
    from proseview.server import _make_handler

    book = tmp_path / "book"
    shutil.copytree(DEMO, book, ignore=shutil.ignore_patterns("exports", ".proseview"))
    session = RemoteSession("tailscale", Identity(DNS, LOGIN))
    handler = _make_handler(
        lambda: "<!doctype html><html lang=\"en\"><body>book</body></html>", lambda: b"{}",
        lambda *a, **k: None, lambda: None, lambda q: None, lambda p: None,
        str(book), DiscussManager(book), "token",
    )
    handler.remote_session = session

    class Phone(handler):  # type: ignore[misc, valid-type]
        pass
    Phone.remote = session
    servers = [ThreadingHTTPServer(("127.0.0.1", 0), cls) for cls in (handler, Phone)]
    for httpd in servers:
        threading.Thread(target=httpd.serve_forever, daemon=True).start()

    def request(which: str, method: str, path: str, headers: list[tuple[str, str]], body: bytes = b""):
        port = servers[0 if which == "laptop" else 1].server_address[1]
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
        for k, v in headers:
            conn.putheader(k, v)
        if body:
            conn.putheader("Content-Length", str(len(body)))
        conn.endheaders(body or None)
        response = conn.getresponse()
        data = response.read()
        conn.close()
        return response.status, data

    yield request
    for httpd in servers:
        httpd.shutdown()


def test_the_phone_listener_refuses_without_the_right_login_even_on_the_page(listeners):
    assert listeners("phone", "GET", "/", GOOD)[0] == 200
    assert listeners("phone", "GET", "/", [("Host", DNS)])[0] == 403
    assert listeners("phone", "GET", "/", [("Host", DNS), ("Tailscale-User-Login", "x@y.z")])[0] == 403
    assert listeners("phone", "GET", "/data.json", [("Host", "localhost")])[0] == 403
    # The laptop listener does not accept the tailnet name, header or not.
    assert listeners("laptop", "GET", "/", GOOD)[0] == 403
    assert listeners("laptop", "GET", "/", [("Host", "localhost")])[0] == 200


def test_the_page_says_which_side_it_is_on(listeners):
    _, phone = listeners("phone", "GET", "/", GOOD)
    _, laptop = listeners("laptop", "GET", "/", [("Host", "localhost")])
    assert b'data-remote="phone"' in phone and f'data-remote-url="https://{DNS}"'.encode() in phone
    assert b'data-remote="phone"' not in laptop and f'data-remote-url="https://{DNS}"'.encode() in laptop


@pytest.mark.parametrize("path", sorted(remote_mod.LAPTOP_ONLY_PATHS))
def test_laptop_only_routes_are_refused_from_the_phone(listeners, path):
    body = json.dumps({"path": "x"}).encode()
    headers = [*GOOD, ("X-Proseview-Session", "token"), ("Content-Type", "application/json")]
    code, data = listeners("phone", "POST", path, headers, body)
    assert code == 403 and b"only works on the Mac" in data
    code, data = listeners("laptop", "POST", path, [("Host", "localhost"), *headers[2:]], body)
    assert b"only works on the Mac" not in data


def test_writes_from_the_phone_still_need_the_page_session(listeners):
    body = json.dumps({"path": "story-bible/characters/alice.md", "content": "x", "open_mtime": 0}).encode()
    code, data = listeners("phone", "POST", "/api/files/save", [*GOOD, ("Content-Type", "application/json")], body)
    assert code == 403 and b"Reload the page" in data


# -- supervising serve ----------------------------------------------------------------


def test_stop_sends_sigint_so_serve_removes_its_own_mapping(tmp_path: Path):
    marker = tmp_path / "stopped"
    script = tmp_path / "fake_serve.py"
    script.write_text(
        "import signal, sys, time, pathlib\n"
        f"def stop(*_):\n    pathlib.Path({str(marker)!r}).write_text('sigint')\n    sys.exit(0)\n"
        "signal.signal(signal.SIGINT, stop)\n"
        "while True:\n    time.sleep(0.1)\n",
        encoding="utf-8",
    )
    session = RemoteSession(sys.executable, Identity(DNS, LOGIN))
    session._serve = subprocess.Popen([sys.executable, str(script)])
    import time
    time.sleep(0.5)
    session.stop()
    assert marker.read_text() == "sigint"


def test_start_reports_a_serve_that_exits_at_once(tmp_path: Path, monkeypatch):
    fake = tmp_path / "tailscale"
    fake.write_text("#!/bin/sh\necho 'serve config denied' >&2\nexit 1\n", encoding="utf-8")
    fake.chmod(0o755)
    session = RemoteSession(str(fake), Identity(DNS, LOGIN))
    with pytest.raises(RemoteError, match="serve config denied"):
        session.start(1234)


def test_the_laptop_gets_the_phone_address_as_a_qr_code(listeners):
    code, data = listeners("laptop", "GET", "/api/remote", [("Host", "localhost")])
    payload = json.loads(data)
    assert code == 200 and payload["url"] == f"https://{DNS}" and payload["phones"] == 0
    assert payload["qr"].startswith("<svg") and f"QR code for https://{DNS}" in payload["qr"]


# -- the QR encoder -------------------------------------------------------------------


def test_qr_codes_grow_with_the_text_and_keep_their_finder_patterns():
    from proseview.qr import encode

    small, url, long = encode("hi"), encode(f"https://{DNS}"), encode("y" * 200)
    assert (len(small), len(url), len(long)) == (21, 29, 57)  # versions 1, 3 and 10
    for modules in (small, url, long):
        n = len(modules)
        for x0, y0 in ((0, 0), (n - 7, 0), (0, n - 7)):
            ring = [modules[y0][x0 + i] for i in range(7)] + [modules[y0 + 6][x0 + i] for i in range(7)]
            assert all(ring) and modules[y0 + 3][x0 + 3] and not modules[y0 + 1][x0 + 1]
        assert modules[n - 8][8], "the dark module"
    assert encode(f"https://{DNS}") == url


def test_qr_refuses_text_it_cannot_hold():
    from proseview.qr import encode

    with pytest.raises(ValueError):
        encode("z" * 300)
