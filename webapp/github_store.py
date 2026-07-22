"""
Minimal wrapper around the GitHub Contents API.

Used so profile data (name, bio, email, avatar) can live directly inside
the project's own GitHub repo instead of Render's ephemeral disk — every
save becomes a small commit, so it survives redeploys/restarts for free.

To keep profile-edit commits from triggering a full Render redeploy every
time someone saves their bio, data is written to a SEPARATE branch
(GITHUB_DATA_BRANCH, default "app-data") rather than the branch Render
watches for deploys. That branch is created automatically (branched off
the repo's default branch) the first time it's needed.

Required environment variables (set on Render, "Environment" tab):
  GITHUB_TOKEN        - a GitHub Personal Access Token with "Contents:
                         Read and write" permission on the repo
  GITHUB_REPO         - "owner/repo-name", e.g. "faysal123/visual-team-console"
Optional:
  GITHUB_DATA_BRANCH  - branch to store data on (default: "app-data")

If these aren't set, every function here is a no-op / returns None, and
profiles.py falls back to local disk (fine for local testing only).
"""
import base64
import os

import requests

API_ROOT = "https://api.github.com"
_branch_ready = False


def _configured():
    return bool(os.environ.get("GITHUB_TOKEN") and os.environ.get("GITHUB_REPO"))


def _headers():
    return {
        "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _repo():
    return os.environ["GITHUB_REPO"]


def _data_branch():
    return os.environ.get("GITHUB_DATA_BRANCH", "app-data")


def _ensure_data_branch():
    """Create the data branch (off the repo's default branch) if it doesn't exist yet."""
    global _branch_ready
    if _branch_ready or not _configured():
        return
    branch = _data_branch()
    ref_url = f"{API_ROOT}/repos/{_repo()}/git/ref/heads/{branch}"
    r = requests.get(ref_url, headers=_headers(), timeout=15)
    if r.status_code == 200:
        _branch_ready = True
        return

    repo_info = requests.get(f"{API_ROOT}/repos/{_repo()}", headers=_headers(), timeout=15)
    repo_info.raise_for_status()
    default_branch = repo_info.json()["default_branch"]

    base_ref = requests.get(
        f"{API_ROOT}/repos/{_repo()}/git/ref/heads/{default_branch}",
        headers=_headers(), timeout=15,
    )
    base_ref.raise_for_status()
    sha = base_ref.json()["object"]["sha"]

    create = requests.post(
        f"{API_ROOT}/repos/{_repo()}/git/refs",
        headers=_headers(),
        json={"ref": f"refs/heads/{branch}", "sha": sha},
        timeout=15,
    )
    # 422 = branch already exists (created by a racing request) — fine either way.
    if create.status_code not in (201, 422):
        create.raise_for_status()
    _branch_ready = True


def get_file(path):
    """Return (content_bytes, sha), or (None, None) if the file doesn't exist."""
    if not _configured():
        return None, None
    _ensure_data_branch()
    url = f"{API_ROOT}/repos/{_repo()}/contents/{path}"
    resp = requests.get(url, headers=_headers(), params={"ref": _data_branch()}, timeout=15)
    if resp.status_code == 404:
        return None, None
    resp.raise_for_status()
    data = resp.json()
    content = base64.b64decode(data["content"])
    return content, data["sha"]


def put_file(path, content_bytes, message):
    """Create or update a file in the repo's data branch."""
    if not _configured():
        raise RuntimeError("GITHUB_TOKEN / GITHUB_REPO not configured")
    _ensure_data_branch()
    _, sha = get_file(path)
    url = f"{API_ROOT}/repos/{_repo()}/contents/{path}"
    payload = {
        "message": message,
        "content": base64.b64encode(content_bytes).decode("ascii"),
        "branch": _data_branch(),
    }
    if sha:
        payload["sha"] = sha
    resp = requests.put(url, headers=_headers(), json=payload, timeout=20)
    resp.raise_for_status()
    return resp.json()
