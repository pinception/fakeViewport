#!/usr/bin/venv python3
import subprocess, logging, sys, re, html, threading
from logging_config import configure_logging
from validate_config import validate_config
from pathlib import Path
from datetime import datetime, timedelta
import viewport
from viewport import log_error

# git fetch is cheap and has no API rate limit, so the remote is checked often
CACHE_DURATION = timedelta(minutes=15)
MAX_CHANGELOG_COMMITS = 50
ROOT  = Path(__file__).resolve().parent
VERS  = ROOT / "api" / "VERSION"
_mon = sys.modules[__name__]
_fetch_lock = threading.Lock()
last_fetched: datetime | None = None
# --------------------------------------------------------------------------- # 
# Config set up
# --------------------------------------------------------------------------- # 
cfg = validate_config(strict=False, print=False)
# pull everything out into locals/globals
for name, val in vars(cfg).items():
    setattr(_mon, name, val)

root_logger = logging.getLogger()
if not root_logger.handlers:
    configure_logging(
        log_file_path=str(log_file),
        log_file=LOG_FILE_FLAG,
        log_console=LOG_CONSOLE,
        log_days=LOG_DAYS,
        Debug_logging=DEBUG_LOGGING
    )
else: pass
logger = logging.getLogger(__name__) 
# --------------------------------------------------------------------------- # 
# Helper functions
# --------------------------------------------------------------------------- # 
def _commits_behind(force: bool = False) -> int | None:
    """
    Count the commits this install is behind its git remote.

    Fetches at most once per ``CACHE_DURATION`` (always with *force*); in
    between, the count is recomputed against the last fetch, so it is right
    again as soon as the install updates itself.

    Args:
        force: Fetch even if the last fetch is recent.

    Returns:
        int | None: Commits behind, or None if that is unknown.
    """
    global last_fetched
    # The dashboard asks for the version and the changelog at the same time;
    # one git fetch at a time avoids ref lock errors
    with _fetch_lock:
        now = datetime.now()
        fetch = force or last_fetched is None or now - last_fetched >= CACHE_DURATION
        behind = viewport.git_updates_available(fetch=fetch)
        if fetch and behind is not None:
            last_fetched = now
        return behind

def _web_url(remote_url: str) -> str:
    """
    Turn a git remote URL into its web page, dropping any credentials.

    Args:
        remote_url: e.g. ``https://github.com/owner/repo.git`` or
            ``git@github.com:owner/repo.git``.

    Returns:
        string: e.g. ``https://github.com/owner/repo``, or ``""``.
    """
    m = re.match(r"^(?:[a-z+]+://)?(?:[^@/]+@)?([^/:]+)[:/](.+?)(?:\.git)?/?$", remote_url.strip())
    return f"https://{m.group(1)}/{m.group(2)}" if m else ""
# --------------------------------------------------------------------------- # 
# API
# --------------------------------------------------------------------------- # 
def current_version() -> str:
    """
    Read the locally installed version string.

    Returns:
        string: Contents of ``api/VERSION`` with surrounding whitespace
        stripped.
    """
    return VERS.read_text().strip()

def latest_version() -> str:
    """
    Return the version available on the git remote.

    The dashboard compares dotted numbers, so new commits on the remote are
    reported as an extra component: ``2.4.3.2`` means two new commits.

    Returns:
        string: The current version when up to date, ``<current>.<commits>``
        when behind, or ``"failed-to-fetch"`` if the remote can't be checked.
    """
    behind = _commits_behind()
    if behind is None:
        return "failed-to-fetch"
    cur = current_version()
    return f"{cur}.{behind}" if behind else cur

def latest_changelog() -> str:
    """
    List the commits waiting on the git remote as Markdown.

    Returns:
        string: A heading and one bullet per commit, or ``""`` if the remote
        can't be checked.
    """
    behind = _commits_behind()
    if behind is None:
        return ""
    if not behind:
        return "Up to date with the git remote."
    try:
        log = viewport.run_git(
            "log", f"--max-count={MAX_CHANGELOG_COMMITS}", "--format=%h%x09%s", "HEAD..@{u}"
        ).stdout
    except (subprocess.TimeoutExpired, OSError):
        return ""
    lines = []
    for entry in log.splitlines():
        sha, _, subject = entry.partition("\t")
        # The dashboard renders this as HTML
        lines.append(f"- {html.escape(subject)} (`{sha}`)")
    more = behind - len(lines)
    if more > 0:
        lines.append(f"- … and {more} more")
    return f"### {behind} new commit{'s' if behind != 1 else ''}\n\n" + "\n".join(lines)

def changelog_url() -> str:
    """
    Link to the waiting commits on the remote's web page.

    Returns:
        string: A compare view when behind, the branch's commit list when up
        to date, or ``""`` if the remote URL is unknown.
    """
    try:
        upstream = viewport.run_git("rev-parse", "--abbrev-ref", "@{u}").stdout.strip()
        remote, _, branch = upstream.partition("/")
        web = _web_url(viewport.run_git("remote", "get-url", remote).stdout) if branch else ""
        if not web:
            return ""
        if _commits_behind():
            head = viewport.run_git("rev-parse", "--short", "HEAD").stdout.strip()
            new = viewport.run_git("rev-parse", "--short", "@{u}").stdout.strip()
            return f"{web}/compare/{head}...{new}"
        return f"{web}/commits/{branch}"
    except (subprocess.TimeoutExpired, OSError):
        return ""

def perform_update() -> str:
    """
    Fast-forward the install to the newest commit on its git remote.

    Uses the same steps as the startup update (``viewport.apply_git_update``):
    no release archives are extracted, so changes that only exist on the
    remote (e.g. a fork) are never overwritten.

    Returns:
        string: Outcome label: ``"already-current"``,
        ``"updated-to-<commit>-via-git"`` or ``"update-failed"``.
    """
    behind = _commits_behind(force=True)
    if behind is None:
        log_error("Update failed: could not check the git remote")
        return "update-failed"
    if not behind:
        logging.info("Already up to date with the git remote")
        return "already-current"
    logging.info(f"Updating {behind} commit(s) from the git remote")
    new = viewport.apply_git_update()
    if new is None:
        log_error("Failed to apply update")
        return "update-failed"
    return f"updated-to-{new[:7]}-via-git"
