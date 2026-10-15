import importlib, subprocess, logging, types
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
import pytest
import monitoring
import update as uu
import validate_config
# --------------------------------------------------------------------------- # 
# Fixtures
# --------------------------------------------------------------------------- # 
@pytest.fixture
def dummy_repo(tmp_path, monkeypatch):
    # Create an isolated fake repo tree:  api/VERSION  +  .git dir
    (tmp_path / "api").mkdir()
    (tmp_path / "api" / "VERSION").write_text("0.1.0\n")
    (tmp_path / ".git").mkdir()

    importlib.reload(uu)              # ensure constants are rebound

    monkeypatch.setattr(uu, "ROOT", tmp_path)
    monkeypatch.setattr(uu, "VERS", tmp_path / "api" / "VERSION")
    yield tmp_path
    importlib.reload(uu)              # restore globals for other tests

class DummyCM:
    def __enter__(self): return self
    def __exit__(self, *args): pass

@pytest.fixture
def app_client(dummy_repo, monkeypatch):
    # Flask test-client with logging disabled for speed.
    monkeypatch.setattr(monitoring, "configure_logging", lambda *a, **k: None)
    app = monitoring.create_app()
    app.testing = True
    return app.test_client()

def _cfg(log_path: Path) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        log_file=str(log_path),
        LOG_FILE_FLAG=True,
        LOG_CONSOLE=False,
        LOG_DAYS=7,
        DEBUG_LOGGING=False,
    )

# --------------------------------------------------------------------------- # 
# Logging
# --------------------------------------------------------------------------- # 
def test_update_respects_existing_root_handler(monkeypatch, tmp_path):
    root = logging.getLogger()
    original = list(root.handlers)

    log_path = tmp_path / "viewport.log"
    root.handlers.clear()
    fh = logging.FileHandler(log_path)
    fh.setFormatter(logging.Formatter('%(message)s'))
    root.addHandler(fh)

    monkeypatch.setattr(validate_config, "validate_config",
                        lambda *_, **__: _cfg(log_path))

    uu_reloaded = importlib.reload(uu)

    msg = "existing-handler-branch"
    uu_reloaded.logger.info(msg)
    fh.flush()
    assert msg in log_path.read_text()
    assert root.handlers == [fh]          # no extra handler added

    root.removeHandler(fh)
    fh.close()
    for h in original:                    # restore pre-test state
        root.addHandler(h)

def test_update_configures_logging_when_root_empty(monkeypatch, tmp_path):
    root = logging.getLogger()
    original = list(root.handlers)
    for h in list(root.handlers):
        root.removeHandler(h)

    log_path = tmp_path / "viewport.log"
    monkeypatch.setattr(validate_config, "validate_config",
                        lambda *_, **__: _cfg(log_path))

    uu_reloaded = importlib.reload(uu)

    assert root.handlers                  # configure_logging ran

    msg = "no-handler-branch"
    uu_reloaded.logger.info(msg)
    for h in root.handlers:
        if hasattr(h, "flush"): h.flush()

    found = any(
        getattr(h, "baseFilename", None)
        and msg in Path(h.baseFilename).read_text()
        for h in root.handlers
    )
    assert found                          # message reached the file

    for h in list(root.handlers):         # cleanup
        root.removeHandler(h)
        if hasattr(h, "close"): h.close()
    for h in original:
        root.addHandler(h)

# --------------------------------------------------------------------------- # 
# current_version
# --------------------------------------------------------------------------- # 
def test_current_version_reads_file(dummy_repo):
    assert uu.current_version() == "0.1.0"

# --------------------------------------------------------------------------- # 
# Remote checks (viewport.git_updates_available is stubbed)
# --------------------------------------------------------------------------- # 
@pytest.fixture
def behind(monkeypatch):
    """Stub the git check: set ``behind.value``; ``behind.fetches`` records each call's fetch flag."""
    state = types.SimpleNamespace(value=0, fetches=[])
    def fake(fetch=True):
        state.fetches.append(fetch)
        return state.value
    monkeypatch.setattr(uu.viewport, "git_updates_available", fake)
    monkeypatch.setattr(uu, "last_fetched", None)
    return state

@pytest.mark.parametrize("value, expected", [(None, "failed-to-fetch"), (0, "0.1.0"), (3, "0.1.0.3")])
def test_latest_version(dummy_repo, behind, value, expected):
    behind.value = value
    assert uu.latest_version() == expected

def test_commits_behind_fetches_once_per_cache_duration(behind, monkeypatch):
    uu._commits_behind()
    uu._commits_behind()
    assert behind.fetches == [True, False]
    monkeypatch.setattr(uu, "last_fetched", datetime.now() - uu.CACHE_DURATION)
    uu._commits_behind()
    assert behind.fetches[-1] is True

def test_commits_behind_force_fetches(behind):
    uu._commits_behind()
    uu._commits_behind(force=True)
    assert behind.fetches == [True, True]

def test_commits_behind_failed_fetch_is_retried(behind):
    behind.value = None
    uu._commits_behind()
    assert uu.last_fetched is None
    behind.value = 0
    uu._commits_behind()
    assert behind.fetches == [True, True]
# --------------------------------------------------------------------------- # 
# latest_changelog / changelog_url
# --------------------------------------------------------------------------- # 
def _git_answers(monkeypatch, answers):
    """Stub viewport.run_git: answer by the first matching command prefix."""
    def fake(*args, timeout=30):
        cmd = " ".join(args)
        out = next((v for k, v in answers.items() if cmd.startswith(k)), "")
        return subprocess.CompletedProcess(args, 0, out, "")
    monkeypatch.setattr(uu.viewport, "run_git", fake)

@pytest.mark.parametrize("value, expected", [(None, ""), (0, "Up to date with the git remote.")])
def test_latest_changelog_without_new_commits(behind, value, expected):
    behind.value = value
    assert uu.latest_changelog() == expected

def test_latest_changelog_lists_commits_escaped(behind, monkeypatch):
    behind.value = 2
    _git_answers(monkeypatch, {"log": "abc1234\tfix: <b>bold</b>\ndef5678\tfeat: new option\n"})
    assert uu.latest_changelog() == (
        "### 2 new commits\n\n"
        "- fix: &lt;b&gt;bold&lt;/b&gt; (`abc1234`)\n"
        "- feat: new option (`def5678`)"
    )

def test_latest_changelog_truncates(behind, monkeypatch):
    behind.value = uu.MAX_CHANGELOG_COMMITS + 10
    log = "".join(f"{i:07x}\tcommit {i}\n" for i in range(uu.MAX_CHANGELOG_COMMITS))
    _git_answers(monkeypatch, {"log": log})
    assert uu.latest_changelog().endswith("- … and 10 more")

@pytest.mark.parametrize("remote, expected", [
    ("https://github.com/pinception/fakeViewport.git", "https://github.com/pinception/fakeViewport"),
    ("https://github.com/pinception/fakeViewport", "https://github.com/pinception/fakeViewport"),
    ("https://user:token@github.com/pinception/fakeViewport.git\n", "https://github.com/pinception/fakeViewport"),
    ("git@github.com:pinception/fakeViewport.git", "https://github.com/pinception/fakeViewport"),
    ("ssh://git@github.com/pinception/fakeViewport.git", "https://github.com/pinception/fakeViewport"),
    ("", ""),
])
def test_web_url(remote, expected):
    assert uu._web_url(remote) == expected

@pytest.mark.parametrize("value, expected", [
    (2, "https://github.com/pinception/fakeViewport/compare/aaaaaaa...bbbbbbb"),
    (0, "https://github.com/pinception/fakeViewport/commits/main"),
])
def test_changelog_url(behind, monkeypatch, value, expected):
    behind.value = value
    _git_answers(monkeypatch, {
        "rev-parse --abbrev-ref @{u}": "origin/main\n",
        "remote get-url origin": "git@github.com:pinception/fakeViewport.git\n",
        "rev-parse --short HEAD": "aaaaaaa\n",
        "rev-parse --short @{u}": "bbbbbbb\n",
    })
    assert uu.changelog_url() == expected

def test_changelog_url_without_upstream(behind, monkeypatch):
    _git_answers(monkeypatch, {})
    assert uu.changelog_url() == ""
# --------------------------------------------------------------------------- # 
# perform_update
# --------------------------------------------------------------------------- # 
@pytest.mark.parametrize("value, applied, expected", [
    (None, None,     "update-failed"),
    (0,    None,     "already-current"),
    (2,    "b" * 40, "updated-to-bbbbbbb-via-git"),
    (2,    None,     "update-failed"),
])
def test_perform_update(behind, monkeypatch, value, applied, expected):
    behind.value = value
    calls = []
    monkeypatch.setattr(uu.viewport, "apply_git_update", lambda: calls.append(1) or applied)
    assert uu.perform_update() == expected
    assert len(calls) == (1 if value else 0)

def test_perform_update_fetches_despite_fresh_cache(behind, monkeypatch):
    monkeypatch.setattr(uu, "last_fetched", datetime.now())
    uu.perform_update()
    assert behind.fetches == [True]
# --------------------------------------------------------------------------- # 
# End to end against a real git remote
# --------------------------------------------------------------------------- # 
def _git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                   check=True, capture_output=True)

def test_update_from_real_git_remote(tmp_path, monkeypatch):
    remote, install = tmp_path / "remote", tmp_path / "install"
    (remote / "api").mkdir(parents=True)
    (remote / "api" / "VERSION").write_text("2.4.3\n")
    _git(remote, "init", "-q", "-b", "main")
    _git(remote, "add", ".")
    _git(remote, "commit", "-q", "-m", "first")
    _git(tmp_path, "clone", "-q", str(remote), str(install))
    (remote / "new.txt").write_text("new")
    _git(remote, "add", ".")
    _git(remote, "commit", "-q", "-m", "feat: something new")

    monkeypatch.setattr(uu.viewport, "_base", install)
    monkeypatch.setattr(uu.viewport, "config_file", install / "config.ini")
    monkeypatch.setattr(uu, "VERS", install / "api" / "VERSION")
    monkeypatch.setattr(uu, "last_fetched", None)

    assert uu.latest_version() == "2.4.3.1"
    assert "- feat: something new (`" in uu.latest_changelog()
    assert uu.perform_update().startswith("updated-to-")
    assert (install / "new.txt").read_text() == "new"
    assert uu.latest_version() == "2.4.3"
    assert uu.perform_update() == "already-current"
# --------------------------------------------------------------------------- # 
# Monitoring API endpoints
# --------------------------------------------------------------------------- # 
@patch.object(monitoring.update, "latest_version", lambda: "0.1.0.2")
def test_update_info_endpoint(app_client):
    r = app_client.get("/api/update")
    assert r.status_code == 200
    assert r.get_json()["data"] == {"current": "0.1.0", "latest": "0.1.0.2"}

def test_update_info_endpoint_error(app_client, monkeypatch, caplog):
    def boom(): raise RuntimeError("git broke")
    monkeypatch.setattr(uu, "latest_version", boom)
    caplog.set_level("ERROR")
    resp = app_client.get("/api/update")
    assert resp.status_code == 500
    assert "An internal error has occurred." in resp.get_json()["message"]
    assert "version check failed" in caplog.text

def test_update_apply_endpoint(app_client, monkeypatch):
    monkeypatch.setattr(monitoring.update, "perform_update", lambda: "updated-to-bbbbbbb-via-git")
    r = app_client.post("/api/update/apply")
    assert r.status_code == 202
    assert r.get_json()["data"]["outcome"] == "updated-to-bbbbbbb-via-git"

def test_update_changelog_endpoint_success(app_client, monkeypatch):
    monkeypatch.setattr(monitoring.update, "latest_changelog", lambda: "### 1 new commit")
    monkeypatch.setattr(monitoring.update, "changelog_url", lambda: "https://github.com/o/r/compare/a...b")
    response = app_client.get("/api/update/changelog")
    assert response.status_code == 200
    assert response.get_json()["data"] == {
        "changelog": "### 1 new commit",
        "release_url": "https://github.com/o/r/compare/a...b",
    }

def test_update_changelog_endpoint_error(app_client, monkeypatch, caplog):
    caplog.set_level("ERROR")
    monkeypatch.setattr(
        monitoring.update,
        "latest_changelog",
        lambda: (_ for _ in ()).throw(RuntimeError("git broke"))
    )
    response = app_client.get("/api/update/changelog")
    assert response.status_code == 500
    data = response.get_json()
    assert data["status"] == "error"
    assert "An internal error has occurred." in data["message"]
    assert "changelog fetch failed" in caplog.text
