import subprocess, sys
from pathlib import Path
import pytest
import viewport

# --------------------------------------------------------------------------- #
# Fixtures and Helpers
# --------------------------------------------------------------------------- #
OLD, NEW = "a" * 40, "b" * 40

def _result(stdout="", returncode=0, stderr=""):
    return subprocess.CompletedProcess([], returncode, stdout, stderr)

class FakeRun:
    """
    Stands in for subprocess.run. Answers git (and pip) commands by prefix and
    records every call. A list of answers is consumed in order; the last one repeats.
    """
    def __init__(self):
        self.calls = []
        self.answers = {
            "rev-parse --abbrev-ref": [_result("origin/main")],
            "fetch":                  [_result()],
            "rev-list":               [_result("2\n")],
            "ls-files":               [_result("")],
            "rev-parse HEAD":         [_result(OLD), _result(NEW)],
            "merge":                  [_result()],
            "diff":                   [_result("viewport.py\n")],
            "checkout":               [_result()],
            "reset":                  [_result()],
            "pip":                    [_result()],
        }

    def __call__(self, cmd, **kwargs):
        text = " ".join(cmd[3:] if cmd[0] == "git" else cmd)
        self.calls.append(text)
        key = "pip" if "pip" in cmd else next(k for k in self.answers if text.startswith(k))
        answers = self.answers[key]
        answer = answers.pop(0) if len(answers) > 1 else answers[0]
        if isinstance(answer, BaseException):
            raise answer
        return answer

    def ran(self, prefix):
        return any(c.startswith(prefix) for c in self.calls)

@pytest.fixture
def run(monkeypatch, tmp_path):
    fake = FakeRun()
    monkeypatch.setattr(viewport.subprocess, "run", fake)
    monkeypatch.setattr(viewport, "AUTO_UPDATE", True)
    # Empty counts as unset; setenv also removes the variable the handler sets after each test
    monkeypatch.setenv("FAKEVIEWPORT_UPDATED", "")
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(viewport, "_base", tmp_path)
    monkeypatch.setattr(viewport, "config_file", tmp_path / "config.ini")
    monkeypatch.setattr(viewport, "api_status", lambda *a, **k: None)
    monkeypatch.setattr(viewport, "log_error", lambda *a, **k: None)
    monkeypatch.setattr(viewport.sys, "argv", ["viewport.py", "-b"])
    return fake

@pytest.fixture
def execv(monkeypatch):
    calls = []
    monkeypatch.setattr(viewport.os, "execv", lambda *args: calls.append(args))
    return calls
# --------------------------------------------------------------------------- #
# Skipped checks
# --------------------------------------------------------------------------- #
def test_disabled_runs_nothing(run, execv, monkeypatch):
    monkeypatch.setattr(viewport, "AUTO_UPDATE", False)
    viewport.update_handler()
    assert run.calls == [] and execv == []

def test_restart_after_update_does_not_check_again(run, execv, monkeypatch):
    monkeypatch.setenv("FAKEVIEWPORT_UPDATED", "1")
    viewport.update_handler()
    assert run.calls == [] and execv == []

def test_not_a_git_checkout(run, execv, tmp_path):
    (tmp_path / ".git").rmdir()
    viewport.update_handler()
    assert run.calls == [] and execv == []

def test_no_upstream_or_detached_head(run, execv):
    run.answers["rev-parse --abbrev-ref"] = [_result(returncode=128, stderr="fatal: no upstream")]
    viewport.update_handler()
    assert not run.ran("fetch") and execv == []

def test_up_to_date(run, execv):
    run.answers["rev-list"] = [_result("0\n")]
    viewport.update_handler()
    assert run.ran("fetch") and not run.ran("merge") and execv == []
# --------------------------------------------------------------------------- #
# Update applied
# --------------------------------------------------------------------------- #
def test_update_fast_forwards_and_restarts(run, execv):
    viewport.update_handler()
    assert "merge --ff-only @{u}" in run.calls
    assert not run.ran("checkout") and not run.ran(sys.executable)
    script = str(Path(viewport.__file__).resolve())
    assert execv == [(sys.executable, [sys.executable, script, "-b"])]
    assert viewport.os.environ["FAKEVIEWPORT_UPDATED"] == "1"

def test_changed_requirements_are_installed(run, execv):
    run.answers["diff"] = [_result("requirements.txt\nviewport.py\n")]
    viewport.update_handler()
    assert run.ran(f"{sys.executable} -m pip install")
    assert len(execv) == 1

def test_renamed_example_config_is_restored_before_merge(run, execv, tmp_path):
    (tmp_path / "config.ini").touch()
    run.answers["ls-files"] = [_result("config.ini.example\n")]
    viewport.update_handler()
    assert run.calls.index("checkout -- config.ini.example") < run.calls.index("merge --ff-only @{u}")

def test_example_config_left_alone_without_config_ini(run, execv):
    run.answers["ls-files"] = [_result("config.ini.example\n")]
    viewport.update_handler()
    assert not run.ran("checkout")
# --------------------------------------------------------------------------- #
# Failures keep the current version running
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("fetch", [
    _result(returncode=128, stderr="fatal: unable to access 'https://github.com/'"),
    subprocess.TimeoutExpired("git fetch", 30),
    FileNotFoundError("git"),
])
def test_fetch_failure(run, execv, fetch):
    run.answers["fetch"] = [fetch]
    viewport.update_handler()
    assert not run.ran("merge") and execv == []

def test_merge_failure(run, execv):
    run.answers["merge"] = [_result(returncode=128, stderr="fatal: Not possible to fast-forward, aborting.")]
    viewport.update_handler()
    assert not run.ran("diff") and execv == []

@pytest.mark.parametrize("pip", [
    _result(returncode=1, stderr="ERROR: No matching distribution found"),
    subprocess.TimeoutExpired("pip", 300),
])
def test_pip_failure_rolls_back(run, execv, pip):
    run.answers["diff"] = [_result("requirements.txt\n")]
    run.answers["pip"] = [pip]
    viewport.update_handler()
    assert f"reset --keep {OLD}" in run.calls
    assert execv == []
