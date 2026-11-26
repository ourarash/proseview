"""The privacy screen's password: kept as a hash, checked by the server."""

from __future__ import annotations

import json
import os
import stat
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from proseview import cli, privacy
from proseview.discuss import DiscussManager

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "demo-repo"


@pytest.fixture(autouse=True)
def state_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    return tmp_path / "state"


def test_password_is_stored_as_a_salted_hash_for_this_user_only(state_home: Path):
    path = privacy.set_password("hunter2")
    assert path == state_home / "proseview" / "privacy.json"
    text = path.read_text(encoding="utf-8")
    assert "hunter2" not in text
    record = json.loads(text)
    assert record["algorithm"] == "pbkdf2_sha256" and record["salt"] and record["hash"]
    if os.name != "nt":  # Windows has no owner-only mode bits to set.
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert privacy.has_password()
    assert privacy.check_password("hunter2")
    assert not privacy.check_password("hunter3")
    assert not privacy.check_password("")


def test_the_same_password_is_salted_differently_each_time():
    first = json.loads(privacy.set_password("same").read_text())
    second = json.loads(privacy.set_password("same").read_text())
    assert first["salt"] != second["salt"] and first["hash"] != second["hash"]


def test_clearing_forgets_the_password_and_any_password_then_uncovers():
    privacy.set_password("hunter2")
    assert privacy.clear_password() is True
    assert privacy.clear_password() is False
    assert not privacy.has_password()
    assert privacy.check_password("anything")


def test_an_empty_password_is_refused():
    with pytest.raises(ValueError):
        privacy.set_password("")


def test_a_covered_screen_is_remembered_with_or_without_a_password(state_home: Path):
    lock = privacy.PrivacyLock()
    assert lock.lock() == {"available": True, "password": False, "locked": True, "idle_minutes": 0}
    assert (state_home / "proseview" / "privacy-covered").is_file()
    # No password: anyone uncovers it, as the shortcut does.
    assert lock.unlock("") is True
    assert lock.state()["locked"] is False

    privacy.set_password("pw")
    assert lock.lock() == {"available": True, "password": True, "locked": True, "idle_minutes": 0}
    assert lock.unlock("wrong") is False
    assert lock.state()["locked"] is True
    assert lock.unlock("pw") is True
    assert lock.state() == {"available": True, "password": True, "locked": False, "idle_minutes": 0}


def test_idle_timeout_is_persisted_separately_from_the_password(state_home: Path):
    assert privacy.get_idle_minutes() == 0
    path = privacy.set_idle_minutes(10)
    assert path == state_home / "proseview" / "privacy-settings.json"
    assert privacy.get_idle_minutes() == 10
    assert not privacy.has_password()

    # Setting and clearing a password leaves the idle timeout intact.
    privacy.set_password("pw")
    assert privacy.get_idle_minutes() == 10
    privacy.clear_password()
    assert privacy.get_idle_minutes() == 10

    # Restarted PrivacyLock picks up the persisted timeout.
    assert privacy.PrivacyLock().state()["idle_minutes"] == 10
    assert privacy.PrivacyLock().set_idle_minutes(0)["idle_minutes"] == 0

    for bad in (-1, True, False, "five", 1441, None):
        with pytest.raises(ValueError):
            privacy.parse_idle_minutes(bad)


def test_a_restarted_server_still_finds_the_screen_covered():
    privacy.set_password("pw")
    privacy.PrivacyLock().lock()
    restarted = privacy.PrivacyLock()
    assert restarted.state()["locked"] is True
    assert restarted.unlock("pw") is True
    assert privacy.PrivacyLock().state()["locked"] is False


def test_changing_or_removing_needs_the_current_password():
    lock = privacy.PrivacyLock()
    assert lock.change_password("", "first") is True
    assert privacy.check_password("first")
    assert lock.change_password("wrong", "second") is False
    assert lock.change_password("", "") is False
    assert lock.change_password("first", "second") is True
    assert privacy.check_password("second") and not privacy.check_password("first")
    assert lock.change_password("second", "") is True
    assert not privacy.has_password()


def test_inside_a_browser_tab_there_is_no_password():
    privacy.set_password("pw")
    privacy.set_idle_minutes(5)
    lock = privacy.PrivacyLock(available=False)
    assert lock.lock() == {"available": False, "password": False, "locked": False, "idle_minutes": 0}
    assert not privacy.covered_path().exists()
    assert lock.change_password("pw", "new") is False
    assert privacy.check_password("pw")
    assert lock.set_idle_minutes(15) == {"available": False, "password": False, "locked": False, "idle_minutes": 0}
    assert privacy.get_idle_minutes() == 5


def test_cli_sets_and_clears_the_password(monkeypatch: pytest.MonkeyPatch, capsys):
    answers = iter(["secret", "secret"])
    monkeypatch.setattr("getpass.getpass", lambda prompt="": next(answers))
    assert cli.main(["privacy-password"]) == 0
    assert privacy.check_password("secret") and not privacy.check_password("other")

    answers = iter(["one", "two"])
    assert cli.main(["privacy-password"]) == 1
    assert privacy.check_password("secret")

    assert cli.main(["privacy-password", "--clear"]) == 0
    assert not privacy.has_password()
    assert "removed" in capsys.readouterr().out


@pytest.fixture
def server():
    from proseview.server import _make_handler

    events: list[dict] = []
    handler = _make_handler(
        lambda: '<!DOCTYPE html>\n<html lang="en"><body>prose</body></html>', lambda: b"{}",
        lambda *a, **k: None, lambda: None, lambda q: None, events.append,
        str(FIXTURE), DiscussManager(FIXTURE), "token",
    )
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"

    def call(path: str, body: dict | None = None, token: str = "token"):
        data = None if body is None else json.dumps(body).encode()
        headers = {"Content-Type": "application/json", "X-Proseview-Session": token}
        request = urllib.request.Request(base + path, data=data, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                raw = response.read()
                return response.status, raw if path == "/" else json.loads(raw)
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read() or b"{}")

    call.events = events
    yield call
    httpd.shutdown()


def test_route_without_a_password_still_keeps_a_reload_covered(server):
    state = {"ok": True, "available": True, "password": False, "locked": False, "idle_minutes": 0}
    assert server("/api/privacy") == (200, state)
    assert server("/api/privacy/lock", {}) == (200, {**state, "locked": True})
    assert server.events == [{"type": "privacy", "locked": True, "password": False}]
    _, html = server("/")
    assert b'<html data-privacy="locked" lang="en">' in html
    assert server("/api/privacy/unlock", {"password": ""})[0] == 200
    assert server.events[-1] == {"type": "privacy", "locked": False}
    _, html = server("/")
    assert b"data-privacy" not in html


def test_route_sets_and_broadcasts_idle_timeout(server):
    assert server("/api/privacy/idle", {"idle_minutes": 5}, token="nope")[0] == 403
    assert server("/api/privacy")[1]["idle_minutes"] == 0

    assert server("/api/privacy/idle", {"idle_minutes": -5})[0] == 400
    assert server("/api/privacy/idle", {"idle_minutes": "bad"})[0] == 400

    status, body = server("/api/privacy/idle", {"idle_minutes": 5})
    assert status == 200 and body["idle_minutes"] == 5
    assert server.events[-1] == {"type": "privacy", "idle_minutes": 5}
    assert server("/api/privacy")[1]["idle_minutes"] == 5

    status, body = server("/api/privacy/idle", {"idle_minutes": 0})
    assert status == 200 and body["idle_minutes"] == 0
    assert server.events[-1] == {"type": "privacy", "idle_minutes": 0}


def test_route_needs_the_session_token(server):
    privacy.set_password("pw")
    assert server("/api/privacy/lock", {}, token="nope")[0] == 403
    assert server("/api/privacy")[1]["locked"] is False


def test_route_with_a_password_holds_the_lock_until_it_is_given(server):
    privacy.set_password("pw")
    status, state = server("/api/privacy/lock", {})
    assert status == 200 and state["locked"] is True
    assert server.events == [{"type": "privacy", "locked": True, "password": True}]
    # A reload is covered before first paint, and the hash never reaches it.
    _, html = server("/")
    assert b'<html data-privacy="locked" data-privacy-password="1" lang="en">' in html
    assert b"pbkdf2" not in html

    status, body = server("/api/privacy/unlock", {"password": "wrong"})
    assert status == 403 and body["ok"] is False
    assert server("/api/privacy")[1]["locked"] is True

    status, body = server("/api/privacy/unlock", {"password": "pw"})
    assert status == 200 and body["locked"] is False
    assert server.events[-1] == {"type": "privacy", "locked": False}
    _, html = server("/")
    assert b"data-privacy" not in html


def test_route_sets_changes_and_removes_the_password_from_settings(server):
    status, body = server("/api/privacy/password", {"current": "", "password": "first"})
    assert status == 200 and body["password"] is True
    assert "first" not in privacy.password_path().read_text()

    status, body = server("/api/privacy/password", {"current": "nope", "password": "second"})
    assert status == 403 and body["ok"] is False
    assert privacy.check_password("first")
    assert server("/api/privacy/password", {"current": "first", "password": ""}, token="nope")[0] == 403

    status, body = server("/api/privacy/password", {"current": "first", "password": "second"})
    assert status == 200 and privacy.check_password("second")
    status, body = server("/api/privacy/password", {"current": "second", "password": ""})
    assert status == 200 and body["password"] is False
    assert not privacy.has_password()


def test_browser_mode_has_no_password_route():
    from proseview import browser

    # Even with a password or idle timeout on this computer, the in-browser book has none.
    privacy.set_password("pw")
    privacy.set_idle_minutes(10)
    reply = browser.request("GET", "/api/privacy")
    assert json.loads(reply["body"]) == {
        "ok": True, "available": False, "password": False, "locked": False, "idle_minutes": 0,
    }
    reply = browser.request(
        "POST", "/api/privacy/password", json.dumps({"current": "pw", "password": "x"}).encode(),
        {"Content-Type": "application/json", "X-Proseview-Session": browser.SESSION},
    )
    assert reply["status"] == 404
    assert privacy.check_password("pw")
    reply = browser.request(
        "POST", "/api/privacy/idle", json.dumps({"idle_minutes": 5}).encode(),
        {"Content-Type": "application/json", "X-Proseview-Session": browser.SESSION},
    )
    assert reply["status"] == 404
    assert privacy.get_idle_minutes() == 10


def test_an_idle_cover_waits_while_another_page_is_in_use(monkeypatch):
    from proseview import privacy as privacy_mod
    from proseview.privacy import PrivacyLock

    now = [1000.0]
    monkeypatch.setattr(privacy_mod.time, "monotonic", lambda: now[0])
    lock = PrivacyLock()
    now[0] += 50
    lock.touch()  # the phone, in use
    now[0] += 30
    state = lock.idle_lock(60)
    assert state["busy"] and not state["locked"] and state["idle_seconds"] == 30
    now[0] += 31
    state = lock.idle_lock(60)
    assert state["locked"] and "busy" not in state
