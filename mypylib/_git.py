from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from urllib.parse import urlparse

from ._network import get_request
from ._types import Dict
from ._utils import run_subprocess


def _run_git(args: list[str], cwd: str, timeout: float = 3) -> str:
    """Run a git command in *cwd* and return stripped stdout.

    :param args: Git subcommand arguments (without the leading ``"git"``).
    :param cwd: Working directory for the command.
    :param timeout: Seconds before the command is aborted.
    :return: Decoded stdout stripped of whitespace.
    :raises RuntimeError: If git failed, timed out, or is not installed.
    """
    try:
        return run_subprocess(["git", *args], timeout=timeout, cwd=cwd).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        raise RuntimeError(f"git {' '.join(args)} failed: {e}") from e


def get_git_hash(git_path: str, short: bool = False) -> str:
    """Return the current HEAD commit hash.

    :param git_path: Path to the git repository.
    :param short: If ``True``, return the abbreviated hash.
    :return: Commit hash string.
    :raises RuntimeError: If git failed or the path is not a repository.
    """
    args = ["rev-parse"]
    if short:
        args.append("--short")
    args.append("HEAD")
    return _run_git(args, cwd=git_path)


def get_git_url(git_path: str) -> str:
    """Return the ``origin`` remote URL (fetch).

    :param git_path: Path to the git repository.
    :return: Remote URL string.
    :raises RuntimeError: If git failed, the path is not a repository,
        or the ``origin`` remote is not configured.
    """
    output = _run_git(["remote", "-v"], cwd=git_path)
    for line in output.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == "origin":
            return parts[1]
    raise RuntimeError(f"No 'origin' remote found in {git_path}")


def fetch_remote_branch_head(
    author: str,
    repo: str,
    branch: str,
    with_days_ago: bool = False,
) -> str | tuple[str, int]:
    """Fetch the latest commit SHA of a branch directly via GitHub API.

    Unlike :func:`get_git_last_remote_commit`, this function does not
    require a local git clone — it queries GitHub by ``author``/``repo``
    directly. Useful when the package is installed without a working
    tree (e.g. via ``pip install`` from a git URL).

    :param author: Repository owner.
    :param repo: Repository name.
    :param branch: Remote branch name.
    :param with_days_ago: If ``True``, also return days since the
        commit's author date.
    :return: Commit SHA string, or ``(sha, days_ago)`` tuple.
    :raises RuntimeError: If the GitHub API call failed.
    """
    api_url = f"https://api.github.com/repos/{author}/{repo}/branches/{branch}"
    data = Dict(json.loads(get_request(api_url)))
    sha = str(data.commit.sha)
    if not with_days_ago:
        return sha
    commit_date = datetime.strptime(data.commit.commit.author.date, "%Y-%m-%dT%H:%M:%S%z")
    days_ago = (datetime.now(timezone.utc) - commit_date).days
    return sha, days_ago


def get_git_last_remote_commit(
    git_path: str, branch: str = "master", with_days_ago: bool = False
) -> str | tuple[str, int]:
    """Fetch the latest commit SHA from GitHub API for the given branch.

    Thin wrapper around :func:`fetch_remote_branch_head` that resolves
    ``author``/``repo`` from the ``origin`` remote of a local git clone.

    :param git_path: Path to the git repository (used to resolve
        author/repo from the origin URL).
    :param branch: Remote branch name.
    :param with_days_ago: If ``True``, also return days since the commit.
    :return: Commit SHA string, or ``(sha, days_ago)`` tuple.
    :raises RuntimeError: If git failed or the GitHub API call failed.
    :raises ValueError: If the origin URL is not a recognizable GitHub URL.
    """
    origin_url = get_git_url(git_path)
    author, repo, _ = parse_github_url(origin_url)
    return fetch_remote_branch_head(author, repo, branch, with_days_ago)


def get_git_branch(git_path: str) -> str:
    """Return the name of the currently checked-out branch.

    :param git_path: Path to the git repository.
    :return: Branch name.
    :raises RuntimeError: If git failed, the path is not a repository,
        or no branch is checked out (detached HEAD).
    """
    output = _run_git(["branch", "--show-current"], cwd=git_path)
    if not output:
        raise RuntimeError(f"No branch checked out in {git_path} (detached HEAD?)")
    return output


def check_git_update(git_path: str) -> bool | None:
    """Check whether the local HEAD differs from the remote branch tip.

    :param git_path: Path to the git repository.
    :return: ``True`` if an update is available, ``False`` if up to date,
        or ``None`` if the check could not be performed.
    """
    try:
        branch = get_git_branch(git_path)
        new_hash = get_git_last_remote_commit(git_path, branch)
        old_hash = get_git_hash(git_path)
    except (RuntimeError, ValueError):
        return None
    return old_hash != new_hash


def validate_github_repo(author: str, repo: str, branch: str = "HEAD") -> None:
    """Validate that a GitHub repository (and optionally a branch) exists.

    :param author: Repository owner.
    :param repo: Repository name.
    :param branch: Branch name to validate.  ``"HEAD"`` (default) skips
        the branch check.
    :raises ValueError: If the repository or branch does not exist.
    :raises RuntimeError: If the check could not be performed.
    """
    url = f"https://github.com/{author}/{repo}.git"

    result = subprocess.run(
        ["git", "ls-remote", url],
        capture_output=True,
        check=False,
        timeout=10,
    )
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8").strip()
        if "not found" in stderr.lower() or "repository" in stderr.lower():
            raise ValueError(f"Repository does not exist: {url}\nGit error: {stderr}")
        raise RuntimeError(f"Failed to check repository: {url}\nGit error: {stderr}")

    if branch == "HEAD":
        return

    result = subprocess.run(
        ["git", "ls-remote", "--exit-code", "--heads", url, branch],
        capture_output=True,
        check=False,
        timeout=10,
    )
    if result.returncode == 0:
        return
    stderr = result.stderr.decode("utf-8").strip()
    if result.returncode == 2:
        raise ValueError(f"Branch does not exist: {url} (branch={branch})\nGit error: {stderr}")
    raise RuntimeError(f"Failed to check branch: {url} (branch={branch})\nGit error: {stderr}")


def parse_github_url(url: str) -> tuple[str, str, str]:
    """Parse a GitHub URL into author, repository and branch.

    :param url: GitHub repository URL (HTTPS or scheme-less).
    :return: ``(author, repo, branch)`` tuple.  *branch* defaults to
        ``"HEAD"`` when not present in the URL.
    :raises ValueError: If the URL does not contain at least ``/author/repo``.
    """
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    parts = [p for p in urlparse(url).path.split("/") if p]
    if len(parts) < 2:
        raise ValueError(f"Invalid github url: {url}")
    author = parts[0]
    repo = parts[1].removesuffix(".git")
    branch = parts[3] if len(parts) >= 4 and parts[2] == "tree" else "HEAD"
    return author, repo, branch


def get_github_release(author: str, repo: str, tag: str | None = None) -> Dict:
    """Fetch a GitHub release.

    :param author: Repository owner.
    :param repo: Repository name.
    :param tag: Release tag (e.g. ``"v2.0.0"``).  If ``None``, fetches
        the latest release.
    :return: Release data with ``tag_name``, ``name``, ``published_at``,
        etc.
    :raises RuntimeError: If the GitHub API call failed.
    """
    suffix = "latest" if tag is None else f"tags/{tag}"
    url = f"https://api.github.com/repos/{author}/{repo}/releases/{suffix}"
    return Dict(json.loads(get_request(url)))
