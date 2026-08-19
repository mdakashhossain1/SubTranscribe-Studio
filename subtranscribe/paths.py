"""Frozen-aware filesystem paths and small OS-level helpers.

No dependency on anything else in this package — every other module
imports PROJECT_DIR/DATA_DIR from here.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

# Resolved once, up front, before anything below can use the wrong value.
# In a frozen PyInstaller build, __file__ points inside the internal bundle,
# not the real exe folder where assets actually get copied, so this must be
# frozen-aware from the start.
if getattr(sys, "frozen", False):
    # Running inside a compiled .exe — use the folder where SubTranscribeStudio.exe lives
    # for bundled (read-only) resources...
    PROJECT_DIR = Path(sys.executable).parent.resolve()
    # ...but installed builds commonly live under Program Files, which a
    # standard (non-admin) user cannot write to. Keep downloaded models,
    # history, and other mutable state in the per-user AppData folder instead,
    # or every launch crashes with a PermissionError trying to mkdir here.
    DATA_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "SubTranscribe Studio"
else:
    # Running as a normal .py script — keep everything next to the source
    PROJECT_DIR = Path(__file__).resolve().parent.parent
    DATA_DIR = PROJECT_DIR

# assets/ lives inside the subtranscribe/ package in the source repo (so it's
# managed alongside the code that uses it), but CI's "bundle runtime assets"
# step still copies it to a plain top-level `assets/` folder next to the
# built .exe — same layout installer.iss's {app}\assets\... references have
# always expected. So the two contexts resolve to different real paths:
# dev runs use the in-repo location, frozen runs use the flat dist/ layout.
if getattr(sys, "frozen", False):
    ASSETS_DIR = PROJECT_DIR / "assets"
else:
    ASSETS_DIR = PROJECT_DIR / "subtranscribe" / "assets"

# Downloaded Whisper model weights. Frozen builds keep using the per-user
# AppData DATA_DIR from above (unrelated to repo layout — Program Files
# isn't writable). For dev runs the cache now lives inside subtranscribe/
# too, alongside assets/, instead of loose at the repo root.
if getattr(sys, "frozen", False):
    MODELS_DIR = DATA_DIR / "models"
else:
    MODELS_DIR = PROJECT_DIR / "subtranscribe" / "models"

# ── Prevent black CMD pop-up windows on Windows OS
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def get_startupinfo():
    if os.name == "nt":
        info = subprocess.STARTUPINFO()
        info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        info.wShowWindow = 0  # SW_HIDE
        return info
    return None


def _load_app_version() -> str:
    """Single source of truth for the app version: a plain-text VERSION file
    at the project root. CI writes the real release version into it (from the
    git tag) before each build, so this file — not a literal in source — is
    what ever needs updating. Falls back to "dev" for a raw source checkout
    where no VERSION file has been generated yet."""
    try:
        return (PROJECT_DIR / "VERSION").read_text(encoding="utf-8").strip() or "dev"
    except Exception:
        return "dev"


def _version_tuple(v: str):
    parts = []
    for p in re.split(r"[.\-+]", v):
        m = re.match(r"\d+", p)
        parts.append(int(m.group()) if m else 0)
    return tuple(parts)


def find_ffmpeg():
    import shutil
    found = shutil.which("ffmpeg")
    if found:
        return found
    capcut_base = Path(os.environ.get("LOCALAPPDATA", "")) / "CapCut" / "Apps"
    if capcut_base.exists():
        candidates = sorted(capcut_base.glob("*/ffmpeg.exe"), reverse=True)
        if candidates:
            return str(candidates[0])
    for p in [r"C:\ffmpeg\bin\ffmpeg.exe", r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
              r"C:\tmp\ffmpeg-static-tmp\node_modules\ffmpeg-static\ffmpeg.exe"]:
        if os.path.exists(p):
            return p
    return None


FFMPEG_PATH = find_ffmpeg()
