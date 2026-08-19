"""GitHub-release update checking. check_for_update moved verbatim from
subgen.py; find_installer_asset_url/clean_release_notes are mechanical
extractions from _download_and_run_update/_show_update_popup
(subgen.py:3338-3345, 3415-3428) — identical logic, just named and
importable instead of inline in a UI method."""
import json
import re
import urllib.request

from ..config import APP_VER, GITHUB_REPO
from ..paths import _version_tuple


def check_for_update(timeout=8):
    """Query the GitHub Releases API for the latest published release.
    Returns (latest_version, release_url, release_notes, assets) if it's
    newer than APP_VER, else None.  Never raises — offline / rate-limited
    requests are silent no-ops so this can't affect startup stability."""
    try:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest",
            headers={"Accept": "application/vnd.github+json", "User-Agent": "SubTranscribe-Studio"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.load(resp)
        latest = str(data.get("tag_name", "")).lstrip("vV").strip()
        url    = data.get("html_url") or f"https://github.com/{GITHUB_REPO}/releases/latest"
        notes  = (data.get("body") or "").strip()
        assets = data.get("assets") or []
        if latest and _version_tuple(latest) > _version_tuple(APP_VER):
            return latest, url, notes, assets
    except Exception:
        pass
    return None


def find_installer_asset_url(assets: list) -> str | None:
    """Pick the Windows .exe installer from a GitHub release's assets list.
    Prefers a name containing "setup"; falls back to any .exe asset."""
    for asset in assets:
        name = (asset.get("name") or "").lower()
        if name.endswith(".exe") and "setup" in name:
            return asset.get("browser_download_url")
    for asset in assets:
        name = (asset.get("name") or "").lower()
        if name.endswith(".exe"):
            return asset.get("browser_download_url")
    return None


def clean_release_notes(notes: str) -> str:
    """Strip GitHub markdown down to plain text for display."""
    clean = notes or ""
    clean = re.sub(r'^#{1,6}\s*', '', clean, flags=re.MULTILINE)   # headings
    clean = re.sub(r'\*\*(.+?)\*\*', r'\1', clean)                 # bold
    clean = re.sub(r'\*(.+?)\*', r'\1', clean)                     # italic
    clean = re.sub(r'^[-*]\s+', '• ', clean, flags=re.MULTILINE)  # bullets
    clean = re.sub(r'`(.+?)`', r'\1', clean)                       # inline code
    return clean.strip() or "No release notes available."
