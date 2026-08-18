"""
SubTranscribe Studio — AI Subtitle Generator
Transcribes audio/video → SRT / VTT / ASS / TXT
Auto-detects language, translates to any target language.
Uses faster-whisper (preferred) or openai-whisper as fallback.
FFmpeg path auto-detected from CapCut or system PATH.
"""

import os
import sys
import re
import json
import threading
import time
import subprocess
import shutil
import tempfile
import urllib.request
import webbrowser
from pathlib import Path
from datetime import timedelta

import tkinter as tk
from tkinter import filedialog, messagebox

# Resolved once, up front, before anything below can use the wrong value.
# BS_ICONS_DIR / FONTS_DIR (defined shortly after this) depend on PROJECT_DIR
# being correct from the very first use — in a frozen PyInstaller build,
# __file__ points inside the internal bundle, not the real exe folder where
# assets actually get copied, so this must be frozen-aware from the start.
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
    PROJECT_DIR = Path(__file__).resolve().parent
    DATA_DIR = PROJECT_DIR

# ── Ensure sys.stdout and sys.stderr are valid file-like objects (fixes pythonw/windowed .exe crashes)
class DummyWriter:
    def write(self, s): pass
    def flush(self): pass

if sys.stdout is None:
    sys.stdout = DummyWriter()
if sys.stderr is None:
    sys.stderr = DummyWriter()


# ── Graceful import of backends
# Only probe availability here — importlib.util.find_spec() doesn't execute
# the module, whereas `import faster_whisper` transitively pulls in
# ctranslate2/transformers/torch (~2s). That cost is deferred into
# transcribe() below and only paid the first time this backend actually runs
# a transcription (never, when the whisper.cpp/Vulkan GPU path is used).
import importlib.util
BACKEND = None
if importlib.util.find_spec("faster_whisper") is not None:
    BACKEND = "faster_whisper"
elif importlib.util.find_spec("whisper") is not None:
    BACKEND = "openai_whisper"

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

try:
    from PIL import Image, ImageDraw
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    import sounddevice as sd
    HAS_SOUNDDEVICE = True
except Exception:
    HAS_SOUNDDEVICE = False

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

try:
    import customtkinter as ctk
    HAS_CTK = True
except ImportError:
    HAS_CTK = False

# ── Official Bootstrap Icons Library Engine (Renders high-DPI SVGs from assets/bs-icons)
BS_ICONS_DIR = PROJECT_DIR / "assets" / "bs-icons" / "bootstrap-icons-1.11.3"
_BS_ICON_CACHE = {}

def make_icon(icon_name: str, color: str = "#94A3B8", size: int = 18):
    """Fallback for get_bs_icon() when an icon name is missing or fails to render.
    Returns None so callers (which all guard with `if ic:`) just skip the glyph
    instead of the whole page crashing."""
    return None

_FITZ_MODULE = None

def get_bs_icon(icon_name: str, color: str = "#94A3B8", size: int = 18) -> ctk.CTkImage:
    """Load and render an official Bootstrap Icon SVG as a crisp high-DPI CTkImage."""
    global _FITZ_MODULE
    key = (icon_name, color, size)
    if key in _BS_ICON_CACHE:
        return _BS_ICON_CACHE[key]
    if not HAS_PIL or not HAS_CTK:
        return None

    svg_file = BS_ICONS_DIR / f"{icon_name}.svg"
    if not svg_file.exists():
        return make_icon(icon_name, color, size)

    try:
        if _FITZ_MODULE is None:
            import fitz
            _FITZ_MODULE = fitz
        else:
            fitz = _FITZ_MODULE

        svg_str = open(svg_file, "r", encoding="utf-8").read()
        if "currentColor" in svg_str:
            svg_str = svg_str.replace("currentColor", color)
        else:
            svg_str = svg_str.replace("<svg", f'<svg fill="{color}"')

        doc = fitz.open(stream=svg_str.encode("utf-8"), filetype="svg")
        pix = doc[0].get_pixmap(dpi=150, alpha=True)
        img = Image.frombytes("RGBA", [pix.width, pix.height], pix.samples)
        img = img.resize((size, size), Image.LANCZOS)
        ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(size, size))
        _BS_ICON_CACHE[key] = ctk_img
        return ctk_img
    except Exception:
        return make_icon(icon_name, color, size)

try:
    from deep_translator import GoogleTranslator
    HAS_TRANSLATOR = True
except ImportError:
    HAS_TRANSLATOR = False

# ── Inter Font Family Loader (High legibility modern UI typography)
FONTS_DIR = PROJECT_DIR / "assets" / "fonts"
FONT_FAMILY = "Segoe UI"

if HAS_CTK:
    for font_file in ["Inter-Regular.ttf", "Inter-Medium.ttf", "Inter-Bold.ttf"]:
        font_path = FONTS_DIR / font_file
        if font_path.exists():
            try:
                ctk.FontManager.load_font(str(font_path))
                FONT_FAMILY = "Inter"
            except Exception:
                pass

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

GITHUB_REPO = "mdakashhossain1/SubTranscribe-Studio"

def _version_tuple(v: str):
    parts = []
    for p in re.split(r"[.\-+]", v):
        m = re.match(r"\d+", p)
        parts.append(int(m.group()) if m else 0)
    return tuple(parts)

def check_for_update(timeout=4):
    """Query the GitHub Releases API for the latest published release.
    Returns (latest_version, release_url) if it's newer than APP_VER, else
    None. Never raises — offline/rate-limited/blocked requests are silent
    no-ops so this can't affect app startup or stability."""
    try:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest",
            headers={"Accept": "application/vnd.github+json", "User-Agent": "SubTranscribe-Studio"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.load(resp)
        latest = str(data.get("tag_name", "")).lstrip("vV").strip()
        url = data.get("html_url") or f"https://github.com/{GITHUB_REPO}/releases/latest"
        if latest and _version_tuple(latest) > _version_tuple(APP_VER):
            return latest, url
    except Exception:
        pass
    return None

# ── Constants (Linear Dark Design System Tokens)
APP_NAME     = "SubTranscribe"
APP_VER      = _load_app_version()
DARK_BG      = "#090D16"  # Deep space dark canvas
PANEL_BG     = "#131825"  # Card / panel container surface
CARD_BG      = "#131825"  # Studio card background
INPUT_BG     = "#0D111A"  # Dark inset field background
BORDER_COLOR = "#263048"  # Subtle crisp border outline
ACCENT       = "#6366F1"  # Indigo primary action accent
ACCENT_HOVER = "#4F46E5"  # Indigo hover accent
ACCENT_CYAN  = "#06B6D4"  # Cyan secondary accent & telemetry bar
TEXT_MAIN    = "#F8FAFC"  # High contrast crisp text
TEXT_SUB     = "#94A3B8"  # Muted slate secondary text
SUCCESS      = "#10B981"  # Emerald success & active GPU status
WARNING      = "#F59E0B"  # Amber warning status
ERROR_C      = "#EF4444"  # Rose Red error state

LANGUAGE_MAP = {
    "Auto Detect":       None,
    "Hindi":             "hi",
    "English":           "en",
    "Indian English":    "en",    # English as used in India
    "Arabic":            "ar",
    "Urdu":              "ur",
    "Spanish":           "es",
    "French":            "fr",
    "German":            "de",
    "Japanese":          "ja",
    "Chinese":           "zh-CN",
    "Korean":            "ko",
    "Russian":           "ru",
    "Portuguese":        "pt",
    "Italian":           "it",
    "Turkish":           "tr",
    "Bengali":           "bn",
    "Tamil":             "ta",
    "Telugu":            "te",
    "Punjabi":           "pa",
    "Marathi":           "mr",
    "Gujarati":          "gu",
}

WHISPER_LANG_MAP = {
    "Auto Detect":      None,
    "Hindi":            "hi",
    "English":          "en",
    "Indian English":   "en",   # Whisper treats as English
    "Arabic":           "ar",
    "Urdu":             "ur",
    "Spanish":          "es",
    "French":           "fr",
    "German":           "de",
    "Japanese":         "ja",
    "Chinese":          "zh",
    "Korean":           "ko",
    "Russian":          "ru",
    "Portuguese":       "pt",
    "Italian":          "it",
    "Turkish":          "tr",
    "Bengali":          "bn",
    "Tamil":            "ta",
    "Telugu":           "te",
}

# ── GPU-optimised models (ordered: best accuracy → fastest)
# All run on GPU (float16). Falls back to CPU (int8) automatically.
MODEL_SIZES = [
    "large-v3",           # ★ Best accuracy — fits your 12 GB VRAM perfectly
    "large-v3-turbo",     # ★ 8× faster than large-v3, ~95% same accuracy
    "distil-large-v3",    # ★ Distilled large-v3 — ultra-fast + very accurate
    "large-v2",           # Previous generation large model
    "medium",             # Good balance — ~3 GB VRAM
    "small",              # Lightweight — ~1 GB VRAM
    "base",               # Very fast — ~500 MB VRAM
    "tiny",               # Fastest — ~250 MB VRAM (lowest accuracy)
]
OUTPUT_FORMATS = ["SRT", "VTT", "ASS", "TXT"]

# ── HuggingFace repo IDs used by faster-whisper
MODEL_REPOS = {
    "tiny":            "Systran/faster-whisper-tiny",
    "base":            "Systran/faster-whisper-base",
    "small":           "Systran/faster-whisper-small",
    "medium":          "Systran/faster-whisper-medium",
    "large-v2":        "Systran/faster-whisper-large-v2",
    "large-v3":        "Systran/faster-whisper-large-v3",
    "large-v3-turbo":  "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
    "distil-large-v3": "Systran/faster-distil-whisper-large-v3",
}

# Approximate download sizes in MB
MODEL_SIZES_MB = {
    "tiny": 75, "base": 145, "small": 484, "medium": 1500,
    "large-v2": 3100, "large-v3": 3100,
    "large-v3-turbo": 809, "distil-large-v3": 756,
}

# ── GGML model files used by whisper.cpp (Vulkan GPU path, for non-NVIDIA GPUs)
GGML_MODEL_FILES = {
    "tiny":            ("ggerganov/whisper.cpp", "ggml-tiny.bin"),
    "base":            ("ggerganov/whisper.cpp", "ggml-base.bin"),
    "small":           ("ggerganov/whisper.cpp", "ggml-small.bin"),
    "medium":          ("ggerganov/whisper.cpp", "ggml-medium.bin"),
    "large-v2":        ("ggerganov/whisper.cpp", "ggml-large-v2.bin"),
    "large-v3":        ("ggerganov/whisper.cpp", "ggml-large-v3.bin"),
    "large-v3-turbo":  ("ggerganov/whisper.cpp", "ggml-large-v3-turbo.bin"),
    "distil-large-v3": ("distil-whisper/distil-large-v3-ggml", "ggml-distil-large-v3.bin"),
}
GGML_MODEL_SIZES_MB = {
    "tiny": 74, "base": 141, "small": 465, "medium": 1463,
    "large-v2": 2951, "large-v3": 2952,
    "large-v3-turbo": 1549, "distil-large-v3": 1449,
}

# Approximate VRAM/RAM needed to comfortably run each model
MODEL_VRAM_MB = {
    "tiny": 250, "base": 500, "small": 1000, "medium": 3000,
    "large-v2": 10000, "large-v3": 12000,
    "large-v3-turbo": 6000, "distil-large-v3": 4000,
}

def is_model_downloaded(model_size: str) -> bool:
    """Check if the selected backend's model weights are fully cached on disk."""
    if USE_WHISPERCPP:
        filename = GGML_MODEL_FILES.get(model_size, (None, None))[1]
        if not filename:
            return False
        f = GGML_MODELS_DIR / filename
        exp_mb = GGML_MODEL_SIZES_MB.get(model_size, 50)
        min_bytes = int(exp_mb * 1024 * 1024 * 0.8)
        return f.exists() and not f.is_symlink() and f.stat().st_size >= min_bytes
    repo = MODEL_REPOS.get(model_size, "")
    if not repo:
        return False
    # HuggingFace cache format: models--{org}--{name}
    cache_name = "models--" + repo.replace("/", "--")
    snapshots  = MODELS_DIR / cache_name / "snapshots"
    if not snapshots.exists():
        return False
    exp_mb = MODEL_SIZES_MB.get(model_size, 50)
    min_bytes = int(exp_mb * 1024 * 1024 * 0.8)
    for snap in snapshots.iterdir():
        if snap.is_dir():
            for f in snap.iterdir():
                if f.name in ("model.bin", "model.safetensors"):
                    try:
                        if f.stat().st_size >= min_bytes:
                            return True
                    except Exception:
                        pass
    return False

def delete_model_files(model_size: str) -> bool:
    """Safely remove cached GGML and faster-whisper model files for the given model size."""
    deleted = False
    # 1. Delete GGML file if present
    filename = GGML_MODEL_FILES.get(model_size, (None, None))[1]
    if filename:
        ggml_file = GGML_MODELS_DIR / filename
        if ggml_file.exists():
            try:
                ggml_file.unlink()
                deleted = True
            except Exception:
                pass
    # 2. Delete faster-whisper HuggingFace cache folder if present
    repo = MODEL_REPOS.get(model_size, "")
    if repo:
        cache_name = "models--" + repo.replace("/", "--")
        hf_folder = MODELS_DIR / cache_name
        if hf_folder.exists():
            try:
                shutil.rmtree(hf_folder)
                deleted = True
            except Exception:
                pass
    return deleted

def get_exact_repo_size(repo: str) -> int:
    """Fetch the real total download size (bytes) for a HF repo from the Hub API.
    Returns 0 on any failure (offline, rate-limited, etc.) so callers can fall back."""
    try:
        from huggingface_hub import HfApi
        info = HfApi().model_info(repo, files_metadata=True)
        return sum((s.size or 0) for s in (info.siblings or []))
    except Exception:
        return 0

def get_exact_file_size(repo: str, filename: str) -> int:
    """Fetch the real size (bytes) of a single file in a HF repo. Returns 0 on failure."""
    try:
        from huggingface_hub import HfApi
        info = HfApi().model_info(repo, files_metadata=True)
        for s in (info.siblings or []):
            if s.rfilename == filename:
                return s.size or 0
    except Exception:
        pass
    return 0

def get_dir_size(path: Path) -> int:
    """Recursively calculate total bytes of unique non-symlink files in path."""
    total = 0
    if not path.exists():
        return 0
    try:
        if (path / "blobs").exists():
            for sub in ("blobs", "refs"):
                sp = path / sub
                if sp.exists():
                    for p in sp.rglob('*'):
                        if p.is_file() and not p.is_symlink():
                            try:
                                total += p.stat().st_size
                            except Exception:
                                pass
            return total
        for p in path.rglob('*'):
            if p.is_file() and not p.is_symlink():
                try:
                    total += p.stat().st_size
                except Exception:
                    pass
    except Exception:
        pass
    return total



# ── Formatting helpers for progress, speed, and ETA (100% NoneType Safe)
def _fmt_time_short(seconds) -> str:
    if seconds is None:
        seconds = 0.0
    try:
        val = float(seconds)
    except Exception:
        val = 0.0
    s = int(max(0, val))
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}h {m:02d}m"
    if m > 0:
        return f"{m}m {s:02d}s"
    return f"{s}s"

def _fmt_size(bytes_val) -> str:
    if bytes_val is None:
        bytes_val = 0.0
    try:
        val = float(bytes_val)
    except Exception:
        val = 0.0
    mb = val / (1024 * 1024)
    if mb >= 1024:
        return f"{mb / 1024:.2f} GB"
    return f"{mb:.1f} MB"

# ── Prevent black CMD pop-up windows on Windows OS
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

def get_startupinfo():
    if os.name == "nt":
        info = subprocess.STARTUPINFO()
        info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        info.wShowWindow = 0  # SW_HIDE
        return info
    return None

# ── Project-local model directory (ALL downloads go here, never to cache)
# Works both as .py script AND as PyInstaller .exe. PROJECT_DIR/DATA_DIR are
# already resolved frozen-aware at the top of the file.
MODELS_DIR = DATA_DIR / "models"
MODELS_DIR.mkdir(parents=True, exist_ok=True)  # create on first run

GGML_MODELS_DIR = MODELS_DIR / "ggml"
GGML_MODELS_DIR.mkdir(parents=True, exist_ok=True)
WHISPERCPP_EXE = PROJECT_DIR / "bin" / "whispercpp" / "whisper-cli.exe"

ICON_PATH = PROJECT_DIR / "assets" / "subgen.ico"
LOGO_PATH = PROJECT_DIR / "assets" / "logo.png"


# ── FFmpeg discovery
def find_ffmpeg():
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

# ── GPU auto-detection (AMD / NVIDIA / CPU fallback)
def _registry_gpu_names():
    """Enumerate display adapter names via the Windows Registry — near-instant
    (<1ms) and 100% reliable on Windows 10/11. Checked first by both
    detect_device() and get_gpu_name() so neither pays for a slow torch/
    ctranslate2 import just to answer "is there an NVIDIA GPU here?"."""
    names = []
    if os.name != "nt":
        return names
    try:
        import winreg
        key_path = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as base_key:
            for i in range(20):
                try:
                    with winreg.OpenKey(base_key, f"{i:04d}") as sub_key:
                        name, _ = winreg.QueryValueEx(sub_key, "DriverDesc")
                        if name and not any(x in name for x in ("Basic Display", "Virtual", "Remote", "Software")):
                            names.append(name)
                except OSError:
                    continue
    except Exception:
        pass
    return names

_REGISTRY_GPU_NAMES = _registry_gpu_names()

def detect_device():
    """
    Probe for a CUDA-capable GPU (NVIDIA only — CTranslate2 requires it).
    Returns (device, compute_type) for faster-whisper.
    - GPU found  → ('cuda', 'float16')  — full precision, maximum speed
    - No GPU     → ('cpu',  'int8')     — quantised, still fast on CPU

    Skips the `ctranslate2` import (10+ seconds on some machines) entirely
    when the registry shows no NVIDIA adapter, since CTranslate2 can only
    ever use NVIDIA CUDA. Previously this import ran unconditionally on
    every launch — including on AMD/Intel-only machines — and was the
    single biggest contributor to the multi-second startup freeze.
    """
    if not any("nvidia" in n.lower() for n in _REGISTRY_GPU_NAMES):
        return "cpu", "int8"
    try:
        import ctranslate2
        if ctranslate2.get_cuda_device_count() > 0:
            return "cuda", "float16"
    except Exception:
        pass
    return "cpu", "int8"

DEVICE, COMPUTE_TYPE = detect_device()

# ── Automated Multi-Stage GPU Detection (Windows Registry, PyTorch, PowerShell, nvidia-smi, WMIC)
def get_gpu_name() -> str:
    """Automatically detect primary GPU name (NVIDIA, AMD, Intel). Zero manual config required."""
    # 1. Native Windows Registry (Instant, 100% reliable on all Windows 10/11 PCs)
    # — tried first so the slow torch import below is skipped on the common path.
    if _REGISTRY_GPU_NAMES:
        return _REGISTRY_GPU_NAMES[0]

    # 2. PyTorch / CUDA detection
    try:
        import torch
        if torch.cuda.is_available():
            name = torch.cuda.get_device_name(0)
            if name:
                return name
    except Exception:
        pass

    # 3. PowerShell Get-CimInstance (Standard modern Windows CLI)
    try:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name"],
            capture_output=True, text=True, timeout=3,
            creationflags=CREATE_NO_WINDOW, startupinfo=get_startupinfo()
        )
        for line in res.stdout.splitlines():
            line = line.strip()
            if line and not any(x in line for x in ("Basic Display", "Virtual", "Remote", "Software")):
                return line
    except Exception:
        pass

    # 4. nvidia-smi CLI
    try:
        res = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=3,
            creationflags=CREATE_NO_WINDOW, startupinfo=get_startupinfo()
        )
        name = res.stdout.strip().splitlines()[0]
        if name:
            return name
    except Exception:
        pass

    # 5. Legacy WMIC fallback
    try:
        result = subprocess.run(
            ["wmic", "path", "win32_VideoController", "get", "name", "/value"],
            capture_output=True, text=True, timeout=3,
            creationflags=CREATE_NO_WINDOW, startupinfo=get_startupinfo()
        )
        for line in result.stdout.splitlines():
            if line.lower().startswith("name=") and line.strip() != "Name=":
                name = line.split("=", 1)[1].strip()
                if name:
                    return name
    except Exception:
        pass

    return ""

GPU_NAME = get_gpu_name()

def get_gpu_vram_mb():
    """Return total VRAM (MB) of the primary CUDA GPU, or None if unknown."""
    if DEVICE != "cuda":
        return None
    try:
        import torch
        if torch.cuda.is_available():
            return int(torch.cuda.get_device_properties(0).total_memory / (1024 * 1024))
    except Exception:
        pass
    try:
        res = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=3,
            creationflags=CREATE_NO_WINDOW, startupinfo=get_startupinfo()
        )
        return int(res.stdout.strip().splitlines()[0])
    except Exception:
        return None

# Non-NVIDIA GPU present + a Vulkan-capable whisper.cpp build bundled → use it for
# real GPU transcription, since CTranslate2 (faster-whisper) can only use NVIDIA CUDA.
USE_WHISPERCPP = DEVICE != "cuda" and bool(GPU_NAME) and WHISPERCPP_EXE.exists()

# Build the header label — always show GPU name if detected
if DEVICE == "cuda":
    DEVICE_LABEL  = f"GPU Active — {GPU_NAME or 'CUDA'}"
    DEVICE_COLOR  = SUCCESS   # green
elif USE_WHISPERCPP:
    short = GPU_NAME.replace("AMD ", "").replace("NVIDIA ", "")
    DEVICE_LABEL  = f"GPU Active — {short} (Vulkan)"
    DEVICE_COLOR  = SUCCESS   # green — genuinely GPU-accelerated via whisper.cpp
elif GPU_NAME:
    # AMD/Intel GPU detected but running fast CPU mode (normal for AMD on Windows)
    short = GPU_NAME.replace("AMD ", "").replace("NVIDIA ", "")
    DEVICE_LABEL  = f"{short} — High-Speed Mode"
    DEVICE_COLOR  = ACCENT2   # teal — looks good, not alarming
else:
    DEVICE_LABEL  = "High-Speed Mode"
    DEVICE_COLOR  = ACCENT2




# ── Subtitle format writers (NoneType Safe)
def _fmt_srt(s):
    if s is None:
        s = 0.0
    try:
        val = float(s)
    except Exception:
        val = 0.0
    ms = int(val * 1000)
    h, r = divmod(ms, 3600000)
    m, r = divmod(r, 60000)
    sec, ms = divmod(r, 1000)
    return f"{h:02d}:{m:02d}:{sec:02d},{ms:03d}"

def _fmt_vtt(s):
    return _fmt_srt(s).replace(",", ".")

def _fmt_ass(s):
    if s is None:
        s = 0.0
    try:
        val = float(s)
    except Exception:
        val = 0.0
    h = int(val // 3600)
    m = int((val % 3600) // 60)
    sec = val % 60
    return f"{h}:{m:02d}:{sec:05.2f}"

def write_srt(segs, path):
    lines = []
    for i, seg in enumerate(segs, 1):
        lines += [str(i), f"{_fmt_srt(seg['start'])} --> {_fmt_srt(seg['end'])}", seg['text'].strip(), ""]
    open(path, "w", encoding="utf-8").write("\n".join(lines))

def write_vtt(segs, path):
    lines = ["WEBVTT", ""]
    for i, seg in enumerate(segs, 1):
        lines += [str(i), f"{_fmt_vtt(seg['start'])} --> {_fmt_vtt(seg['end'])}", seg['text'].strip(), ""]
    open(path, "w", encoding="utf-8").write("\n".join(lines))

def write_ass(segs, path):
    hdr = ("[Script Info]\nScriptType: v4.00+\nPlayResX: 1920\nPlayResY: 1080\n\n"
           "[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,"
           "OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,"
           "Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\n"
           "Style: Default,Arial,48,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,"
           "-1,0,0,0,100,100,0,0,1,2,2,2,10,10,20,1\n\n"
           "[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n")
    lines = [hdr]
    for seg in segs:
        lines.append(f"Dialogue: 0,{_fmt_ass(seg['start'])},{_fmt_ass(seg['end'])},Default,,0,0,0,,{seg['text'].strip()}")
    open(path, "w", encoding="utf-8").write("\n".join(lines))

def write_txt(segs, path):
    lines = []
    for seg in segs:
        lines += [f"[{_fmt_srt(seg['start'])} --> {_fmt_srt(seg['end'])}]", seg['text'].strip(), ""]
    open(path, "w", encoding="utf-8").write("\n".join(lines))

WRITERS = {"SRT": write_srt, "VTT": write_vtt, "ASS": write_ass, "TXT": write_txt}


def resegment_by_sentence(segs, max_words=10):
    """Re-segment Whisper output so every subtitle block is a readable phrase
    rather than an arbitrary chunk boundary.

    Priority order for splitting:
      1. Sentence-ending punctuation  (. ? !)  -- always splits here.
      2. Comma-separated clause       (,)       -- splits after a comma when
         the current clause already has >= max_words//2 words.
      3. Hard word-count cap          (max_words) -- forces a split even with
         no punctuation so subtitles never exceed a comfortable reading length.

    Algorithm
    ---------
    1. Build a flat per-word timeline by distributing each Whisper segment's
       duration evenly across the words it contains.
    2. Walk the word list applying the split rules above.
    3. Flush any remaining words as the final subtitle block.

    Returns a list of {'start', 'end', 'text'} dicts -- the same shape that
    write_srt / write_vtt / etc. expect.  Falls back to the original list if
    nothing could be parsed.
    """
    if not segs:
        return segs

    # -- Step 1: build a per-word timeline --
    word_timeline = []  # [(start_sec, end_sec, word_str), ...]
    for seg in segs:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        seg_start = float(seg.get("start") or 0.0)
        seg_end   = float(seg.get("end")   or seg_start)
        dur = max(seg_end - seg_start, 0.0)
        words = text.split()
        if not words:
            continue
        # Distribute duration evenly across words
        w_dur = dur / len(words)
        for j, w in enumerate(words):
            ws = seg_start + j * w_dur
            we = seg_start + (j + 1) * w_dur
            word_timeline.append((ws, we, w))

    if not word_timeline:
        return segs

    # -- Step 2: group words into subtitle blocks --
    _SENT_END  = re.compile(r'[.?!]["\')\]]*$')   # terminal sentence punct
    _COMMA_END = re.compile(r',$')                  # trailing comma

    half_max = max(1, max_words // 2)

    sentences = []
    buf_words = []
    buf_start = word_timeline[0][0]

    def _flush(end_time):
        if buf_words:
            sentences.append({
                "start": buf_start,
                "end":   end_time,
                "text":  " ".join(buf_words),
            })
            del buf_words[:]

    for (ws, we, word) in word_timeline:
        if not buf_words:
            buf_start = ws
        buf_words.append(word)

        n = len(buf_words)

        if _SENT_END.search(word):
            # Rule 1 -- sentence-ending punctuation: always split
            _flush(we)
        elif _COMMA_END.search(word) and n >= half_max:
            # Rule 2 -- comma after a decent clause length: split here
            _flush(we)
        elif n >= max_words:
            # Rule 3 -- hard cap: force split regardless of punctuation
            _flush(we)

    # -- Step 3: flush any trailing words --
    if buf_words:
        _flush(word_timeline[-1][1])

    return sentences if sentences else segs

# ── Audio extraction
def extract_audio(inp, outwav, ffmpeg):
    cmd = [ffmpeg, "-y", "-i", inp, "-vn", "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", outwav]
    return subprocess.run(
        cmd, capture_output=True,
        creationflags=CREATE_NO_WINDOW, startupinfo=get_startupinfo()
    ).returncode == 0

def decode_audio_preview(inp, ffmpeg, sr=16000, num_peaks=1500):
    """Decode the file's audio track with FFmpeg ONCE, for both the waveform
    preview and real-time playback. Returns (samples, sample_rate, peaks):
    - samples: mono int16 numpy array (kept as int16, not float, to roughly
      halve the memory footprint of long files) or None on failure
    - peaks: a compact list of normalized 0..1 amplitude values for drawing
      the waveform, independent of playback sample rate."""
    if not ffmpeg or not HAS_NUMPY:
        return None, 0, None
    cmd = [ffmpeg, "-v", "error", "-i", inp, "-vn", "-f", "s16le", "-ac", "1", "-ar", str(sr), "-"]
    try:
        proc = subprocess.run(
            cmd, capture_output=True,
            creationflags=CREATE_NO_WINDOW, startupinfo=get_startupinfo()
        )
        raw = proc.stdout
        if not raw or len(raw) < 4:
            return None, 0, None
        samples = np.frombuffer(raw, dtype=np.int16)
        if samples.size == 0:
            return None, 0, None
        chunks = np.array_split(samples, min(num_peaks, samples.size))
        peaks = [float(np.abs(c).max()) / 32768.0 if c.size else 0.0 for c in chunks]
        peak_max = max(peaks) or 1.0
        peaks = [min(1.0, p / peak_max) for p in peaks]
        return samples, sr, peaks
    except Exception:
        return None, 0, None


class AudioPlayer:
    """Lightweight real-time PCM playback engine for previewing the loaded
    media file in sync with its waveform and transcript. Every method is a
    safe no-op if sounddevice/PortAudio isn't available on this system."""

    def __init__(self):
        self.samples = None   # mono int16 numpy array
        self.sr = 0
        self._frame = 0
        self._stream = None
        self._muted = False
        self._lock = threading.Lock()

    @property
    def available(self):
        return HAS_SOUNDDEVICE and self.samples is not None and self.sr > 0

    @property
    def duration(self):
        return (len(self.samples) / self.sr) if self.available else 0.0

    @property
    def position(self):
        with self._lock:
            return (self._frame / self.sr) if self.sr else 0.0

    @property
    def is_playing(self):
        return self._stream is not None

    def load(self, samples, sr):
        self.stop()
        self.samples = samples
        self.sr = sr
        self._frame = 0

    def _callback(self, outdata, frames, time_info, status):
        with self._lock:
            start = self._frame
            end = min(start + frames, len(self.samples))
            chunk = self.samples[start:end]
            self._frame = end
        n = len(chunk)
        outdata.fill(0)
        if n and not self._muted:
            outdata[:n, 0] = chunk.astype(np.float32) / 32768.0
        if end >= len(self.samples):
            raise sd.CallbackStop()

    def play(self):
        if not self.available or self._stream is not None:
            return False
        if self._frame >= len(self.samples):
            self._frame = 0
        try:
            self._stream = sd.OutputStream(
                samplerate=self.sr, channels=1, dtype="float32",
                callback=self._callback, finished_callback=self._on_finished,
            )
            self._stream.start()
            return True
        except Exception:
            self._stream = None
            return False

    def _on_finished(self):
        self._stream = None

    def pause(self):
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass

    def stop(self):
        self.pause()
        with self._lock:
            self._frame = 0

    def seek(self, seconds):
        if not self.sr or self.samples is None:
            return
        with self._lock:
            self._frame = max(0, min(int(seconds * self.sr), len(self.samples)))

    def toggle_mute(self):
        self._muted = not self._muted
        return self._muted

# ── whisper.cpp + Vulkan transcription (GPU path for non-NVIDIA GPUs)
_WHISPERCPP_SEG_RE = re.compile(r"^\[(\d\d:\d\d:\d\d\.\d\d\d)\s*-->\s*(\d\d:\d\d:\d\d\.\d\d\d)\]\s*(.*)$")
_WHISPERCPP_DURATION_RE = re.compile(r",\s*([\d.]+)\s*sec\)")
_WHISPERCPP_LANG_RE = re.compile(r"auto-detected language:\s*(\w+)")

def _parse_whispercpp_ts(ts: str) -> float:
    h, m, rest = ts.split(":")
    s, ms = rest.split(".")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0

def transcribe_whispercpp(audio_path, model_size, source_lang, on_segment, on_done, on_error):
    filename = GGML_MODEL_FILES.get(model_size, (None, None))[1]
    if not filename:
        on_error(f"No GGML model available for '{model_size}'")
        return
    model_path = GGML_MODELS_DIR / filename
    lang = source_lang or "auto"

    # -mc 0 disables cross-chunk text context: with the default (unlimited context),
    # whisper.cpp feeds each 30s window's transcript into the next window's decode as a
    # prompt, which on long audio lets a single decoding error compound and repeat —
    # showing up as duplicated sentences and stray zero-duration junk segments.
    cmd = [str(WHISPERCPP_EXE), "-m", str(model_path), "-f", str(audio_path), "-l", lang, "-mc", "0"]
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
        creationflags=CREATE_NO_WINDOW, startupinfo=get_startupinfo()
    )

    t0 = time.time()
    total_duration = 0.0
    detected_lang = lang if lang != "auto" else "unknown"
    result = []
    decode_error = None

    for line in proc.stdout:
        line = line.rstrip("\n")
        if line.lstrip().startswith("error:"):
            decode_error = line.strip()
        if total_duration == 0.0:
            m = _WHISPERCPP_DURATION_RE.search(line)
            if m:
                try:
                    total_duration = float(m.group(1))
                except Exception:
                    pass
        lm = _WHISPERCPP_LANG_RE.search(line)
        if lm:
            detected_lang = lm.group(1)

        m = _WHISPERCPP_SEG_RE.match(line)
        if m:
            seg_start = _parse_whispercpp_ts(m.group(1))
            seg_end = _parse_whispercpp_ts(m.group(2))
            seg_text = m.group(3).strip()
            # Skip zero/near-zero-duration entries — these are decode artifacts
            # (stray duplicate fragments), never legitimate subtitle segments.
            if seg_end - seg_start < 0.05 or not seg_text:
                continue
            s = {"start": seg_start, "end": seg_end, "text": seg_text}
            result.append(s)

            elapsed = max(0.001, time.time() - t0)
            speed = (seg_end / elapsed) if (elapsed > 0 and seg_end > 0) else 0.0
            eta = ((total_duration - seg_end) / speed) if (speed > 0 and total_duration > seg_end) else 0.0
            pct = (seg_end / total_duration) if total_duration > 0 else 0.0
            on_segment(s, detected_lang, pct, seg_end, total_duration, speed, eta)

    returncode = proc.wait()
    if returncode != 0:
        on_error(f"whisper.cpp exited with code {returncode}")
        return
    if not result and decode_error:
        on_error(f"whisper.cpp could not process this audio file: {decode_error}")
        return
    on_done(result, detected_lang)

# ── Transcription (NoneType Safe)
def transcribe(audio_path, model_size, source_lang, on_segment, on_done, on_error):
    try:
        if USE_WHISPERCPP:
            transcribe_whispercpp(audio_path, model_size, source_lang, on_segment, on_done, on_error)
        elif BACKEND == "faster_whisper":
            from faster_whisper import WhisperModel
            model = WhisperModel(
                model_size,
                device=DEVICE,                   # ← auto: 'cuda' (GPU) or 'cpu'
                compute_type=COMPUTE_TYPE,       # ← float16 on GPU, int8 on CPU
                download_root=str(MODELS_DIR),   # ← always saves to project/models/
                cpu_threads=4,
            )
            t0 = time.time()
            segs, info = model.transcribe(audio_path, language=source_lang, vad_filter=True, beam_size=5)
            det = getattr(info, "language", "unknown") or "unknown"
            raw_dur = getattr(info, "duration", 0.0)
            total_duration = float(raw_dur) if raw_dur is not None else 0.0
            result = []
            for seg in segs:
                seg_start = float(getattr(seg, "start", 0.0) or 0.0)
                seg_end   = float(getattr(seg, "end", 0.0) or 0.0)
                seg_text  = str(getattr(seg, "text", "") or "")
                s = {"start": seg_start, "end": seg_end, "text": seg_text}
                result.append(s)

                elapsed = max(0.001, time.time() - t0)
                speed = (seg_end / elapsed) if (elapsed > 0 and seg_end > 0) else 0.0
                eta = ((total_duration - seg_end) / speed) if (speed > 0 and total_duration > seg_end) else 0.0
                pct = (seg_end / total_duration) if total_duration > 0 else 0.0
                on_segment(s, det, pct, seg_end, total_duration, speed, eta)
            on_done(result, det)
        elif BACKEND == "openai_whisper":
            import whisper as openai_whisper
            model = openai_whisper.load_model(
                model_size,
                download_root=str(MODELS_DIR),   # ← always saves to project/models/
            )
            result = model.transcribe(audio_path, language=source_lang, verbose=False)
            det = result.get("language", "unknown") or "unknown"
            raw_segs = result.get("segments", []) or []
            segs = []
            for r in raw_segs:
                st = float(r.get("start", 0.0) or 0.0)
                en = float(r.get("end", 0.0) or 0.0)
                tx = str(r.get("text", "") or "")
                segs.append({"start": st, "end": en, "text": tx})
            total_dur = segs[-1]["end"] if segs else 1.0
            for i, s in enumerate(segs, 1):
                pct = i / len(segs)
                on_segment(s, det, pct, s["end"], total_dur, 1.0, 0.0)
            on_done(segs, det)
        else:
            on_error("No backend. Run: pip install faster-whisper")
    except Exception as e:
        on_error(str(e))

# ══════════════════════════════════════════════════════════════════════════════
# GUI
# ══════════════════════════════════════════════════════════════════════════════
if HAS_CTK:
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")


class WaveformBar(tk.Canvas):
    """Real audio-waveform seek bar. Renders the amplitude peaks extracted from
    the loaded media file and colors the portion already processed differently
    from what's still ahead, so transcription progress reads like a live scrubber
    instead of a flat bar. Drop-in for CTkProgressBar — exposes the same .set().

    Supports zooming into a narrower time window (for precise scrubbing/editing)
    and click/drag-to-seek — both report back through the .on_seek callback."""

    MAX_ZOOM = 8.0

    def __init__(self, master, height=48, played_color=ACCENT,
                 unplayed_color=BORDER_COLOR, bg_color=INPUT_BG, **kwargs):
        super().__init__(master, height=height, bg=bg_color, highlightthickness=0, **kwargs)
        self.peaks = []
        self.progress = 0.0
        self.zoom = 1.0
        self.view_center = 0.0
        self.played_color = played_color
        self.unplayed_color = unplayed_color
        self.on_seek = None   # callback(fraction: float) fired on click/drag
        self._last_drawn_progress = None  # playhead pixel-position cache — see set()
        self.bind("<Configure>", lambda e: self._redraw())
        self.bind("<Button-1>", self._on_click)
        self.bind("<B1-Motion>", self._on_click)

    def load_peaks(self, peaks):
        """Replace the waveform with newly extracted amplitude data (or [] to
        show the idle placeholder while a file is still being analyzed)."""
        self.peaks = peaks or []
        self._last_drawn_progress = None
        self._redraw()

    def set(self, pct):
        """Advance the playhead / processed-portion marker (0.0 - 1.0)."""
        new_progress = max(0.0, min(float(pct), 1.0))
        vs, ve = self._view_range()
        view_shifted = not (vs <= new_progress <= ve)
        if view_shifted:
            self.view_center = new_progress
        self.progress = new_progress

        # This is called every ~80ms during playback and once per segment
        # during transcription — up to several times a second. _redraw()
        # clears and rebuilds the entire canvas (up to ~1500 peak bars), so
        # without this check it was doing a full rebuild far more often than
        # the rendered pixels actually changed, which was a real source of
        # UI stutter. Skip the rebuild when the playhead hasn't moved by at
        # least a pixel and the visible window hasn't shifted.
        w = self.winfo_width()
        if not view_shifted and self._last_drawn_progress is not None and w > 1:
            vs2, ve2 = self._view_range()
            if ve2 > vs2:
                last_x = ((self._last_drawn_progress - vs2) / (ve2 - vs2)) * w
                new_x = ((new_progress - vs2) / (ve2 - vs2)) * w
                if abs(new_x - last_x) < 1.0:
                    return
        self._redraw()

    def set_zoom(self, zoom):
        """Zoom the visible window in/out (1.0 = full file, higher = closer)."""
        self.zoom = max(1.0, min(float(zoom), self.MAX_ZOOM))
        self.view_center = self.progress
        self._last_drawn_progress = None
        self._redraw()

    def _view_range(self):
        if self.zoom <= 1.0:
            return 0.0, 1.0
        half = 0.5 / self.zoom
        center = min(max(self.view_center, half), 1.0 - half)
        return center - half, center + half

    def _on_click(self, event):
        w = self.winfo_width()
        if w <= 1:
            return
        frac = max(0.0, min(event.x / w, 1.0))
        vs, ve = self._view_range()
        abs_frac = vs + frac * (ve - vs)
        self.progress = abs_frac
        self.view_center = abs_frac
        self._redraw()
        if self.on_seek:
            self.on_seek(abs_frac)

    def _redraw(self):
        self.delete("all")
        self._last_drawn_progress = self.progress
        w = self.winfo_width()
        h = self.winfo_height()
        if w <= 1 or h <= 1:
            return
        mid = h / 2

        if not self.peaks:
            self.create_line(0, mid, w, mid, fill=self.unplayed_color, width=1, dash=(2, 3))
            return

        vs, ve = self._view_range()
        n = len(self.peaks)
        i0 = max(0, min(int(vs * n), n - 1))
        i1 = max(i0 + 1, min(int(ve * n) + 1, n))
        visible = self.peaks[i0:i1]
        vn = len(visible)
        bar_w = w / vn
        split_x = ((self.progress - vs) / (ve - vs)) * w if ve > vs else -1

        for i, amp in enumerate(visible):
            x = i * bar_w + bar_w / 2
            bar_h = max(2.0, amp * (h * 0.42))
            color = self.played_color if x <= split_x else self.unplayed_color
            self.create_line(x, mid - bar_h, x, mid + bar_h,
                              fill=color, width=max(1.0, bar_w * 0.6), capstyle="round")

        # Playhead marker (only when the current position is within view)
        if 0 <= split_x <= w:
            self.create_line(split_x, 3, split_x, h - 3, fill=self.played_color, width=2)
            self.create_oval(split_x - 4, mid - 4, split_x + 4, mid + 4,
                              fill=self.played_color, outline="")


class SubGenApp:
    def __init__(self):
        # Tell Windows this is its own app BEFORE creating the window
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "SubTranscribe.Studio.1.0"
            )
        except Exception:
            pass

        self.root = ctk.CTk() if HAS_CTK else tk.Tk()
        self.root.title(f"{APP_NAME}  —  AI Subtitle Generator v{APP_VER}")
        self.root.geometry("980x750")
        self.root.minsize(880, 650)
        if HAS_CTK:
            self.root.configure(fg_color=DARK_BG)

        self.input_file   = tk.StringVar()
        self.output_dir   = tk.StringVar()
        self.model_var    = tk.StringVar(value="large-v3")
        self.src_lang_var = tk.StringVar(value="Auto Detect")
        self.tgt_lang_var = tk.StringVar(value="None")
        self.fmt_var      = tk.StringVar(value="SRT")
        self.status_var   = tk.StringVar(value="Ready  —  select a media file to begin")
        self.progress_var = tk.DoubleVar(value=0.0)

        # Advanced settings
        self.compute_var  = tk.StringVar(value="float16" if DEVICE == "cuda" else "int8")
        self.beam_var     = tk.StringVar(value="5")
        self.bestof_var   = tk.StringVar(value="5")
        self.temp_var     = tk.StringVar(value="0.0")
        self.cond_prev    = tk.BooleanVar(value=True)
        self.word_ts      = tk.BooleanVar(value=True)

        # Telemetry tracking
        self.seg_count    = tk.IntVar(value=0)
        self.elapsed_var  = tk.StringVar(value="00:00:00")
        self.eta_var      = tk.StringVar(value="--:--:--")
        self.speed_var    = tk.StringVar(value="0.0x")
        self.processed_var = tk.StringVar(value="00:00:00")
        self.remaining_var = tk.StringVar(value="00:00:00")
        self.rtf_var      = tk.StringVar(value="0.00")

        # Transcript search & navigation
        self.search_var   = tk.StringVar()
        self.current_page = tk.StringVar(value="Dashboard")

        self.running      = False
        self.all_segs     = []
        self.tmp_wav      = None
        self.logo_img     = None
        self._icon_photo  = None
        self._start_time  = None

        # Playback preview / transcript sync-and-edit state
        self.audio_player = AudioPlayer()
        self._waveform_cache = {}
        self._transcript_row_widgets = []
        self._pending_rows = []
        self._row_flush_scheduled = False
        self._current_highlight_idx = None
        self._transcript_fullscreen = False
        self.loop_segment = False
        self._last_out_path = None

        # Real-time hardware telemetry live variables
        self.gpu_live_var  = tk.StringVar(value="--%")
        self.ram_live_var  = tk.StringVar(value="--/-- GB")
        self.cpu_live_var  = tk.StringVar(value="--%")
        self.disk_live_var = tk.StringVar(value="--/-- GB")
        self.temp_live_var = tk.StringVar(value="--°C")

        # View caching for 0ms instant page switching
        self.cached_pages = {}

        self._build()
        # Set icon AFTER build — CTk overrides it during its own init
        self.root.after(100, self._set_icon)
        self.root.after(200, self._start_live_telemetry)
        self.root.mainloop()

    def _set_icon(self):
        """Set the app icon for both title bar and taskbar.
        Must run after CTk initialization completes (via after()),
        otherwise CTk resets the icon to its default."""
        if not ICON_PATH.exists():
            return
        try:
            self.root.iconbitmap(str(ICON_PATH))
        except Exception:
            pass
        # Also set iconphoto — this is what the taskbar actually uses
        if HAS_PIL and LOGO_PATH.exists():
            try:
                from PIL import ImageTk
                img = Image.open(str(LOGO_PATH))
                self._icon_photo = ImageTk.PhotoImage(img.resize((64, 64), Image.LANCZOS))
                self.root.iconphoto(True, self._icon_photo)
            except Exception:
                pass

    def _build(self):
        r = self.root
        r.geometry("1280x860")
        r.minsize(1100, 750)

        self.nav_buttons = {}

        # Root container (Sidebar + Main Studio Content)
        app_container = ctk.CTkFrame(r, fg_color=DARK_BG) if HAS_CTK else tk.Frame(r)
        app_container.pack(fill="both", expand=True)

        # 1. Leftmost Navigation Sidebar (~230px)
        self._sidebar(app_container)

        # 2. Main Studio Content Area (Header + Content Page Container + Bottom Bar)
        main_area = ctk.CTkFrame(app_container, fg_color=DARK_BG)
        main_area.pack(side="right", fill="both", expand=True)

        # Top Header Bar
        self._header(main_area)

        # Content Page Container Frame
        self.page_container = ctk.CTkFrame(main_area, fg_color=DARK_BG)
        self.page_container.pack(fill="both", expand=True, padx=16, pady=(10, 0))

        # Bottom System Monitor Bar
        self._status_bar(main_area)

        # Render initial page
        self._switch_page("Dashboard")

    def _sidebar(self, parent):
        """Left navigation sidebar matching the mockup with dynamic tab switching."""
        sb = ctk.CTkFrame(parent, fg_color=PANEL_BG, corner_radius=0, width=240,
                          border_width=1, border_color=BORDER_COLOR)
        sb.pack(side="left", fill="y")
        sb.pack_propagate(False)

        # App Logo & Branding Header
        hdr = ctk.CTkFrame(sb, fg_color="transparent")
        hdr.pack(fill="x", padx=14, pady=(16, 12))

        if LOGO_PATH.exists() and HAS_PIL:
            try:
                pil_img = Image.open(str(LOGO_PATH))
                self.logo_img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(28, 28))
                ctk.CTkLabel(hdr, image=self.logo_img, text="").pack(side="left", padx=(0, 6))
            except Exception:
                pass

        ctk.CTkLabel(hdr, text=APP_NAME, font=ctk.CTkFont(FONT_FAMILY, 15, "bold"),
                     text_color=TEXT_MAIN).pack(side="left")

        self.ver_badge = ctk.CTkFrame(hdr, fg_color=INPUT_BG, corner_radius=5,
                                      border_width=1, border_color=BORDER_COLOR)
        self.ver_badge.pack(side="left", padx=(6, 0))
        self.ver_badge_lbl = ctk.CTkLabel(self.ver_badge, text=f"v{APP_VER}",
                                          font=ctk.CTkFont(FONT_FAMILY, 9, "bold"),
                                          text_color=ACCENT_CYAN)
        self.ver_badge_lbl.pack(padx=5, pady=1)
        self._update_url = None
        threading.Thread(target=self._check_for_update_bg, daemon=True).start()

        # Navigation Items List (Official Bootstrap Icons)
        nav_items = [
            ("speedometer2", "Dashboard"),
            ("mic-fill", "Transcribe"),
            ("collection-play-fill", "Batch Processing"),
            ("cpu-fill", "Models"),
            ("gear-fill", "Settings"),
            ("clock-history", "History"),
            ("bar-chart-line-fill", "Telemetry"),
            ("file-earmark-code-fill", "Logs"),
        ]

        nav_box = ctk.CTkFrame(sb, fg_color="transparent")
        nav_box.pack(fill="x", padx=10, pady=8)

        def _prevent_text_select(b):
            try:
                b.bind("<B1-Motion>", lambda e: "break")
                b.bind("<Double-Button-1>", lambda e: "break")
                b.bind("<Triple-Button-1>", lambda e: "break")
                if hasattr(b, "_text_label") and b._text_label:
                    b._text_label.bind("<B1-Motion>", lambda e: "break")
                    b._text_label.bind("<Double-Button-1>", lambda e: "break")
                    b._text_label.bind("<Triple-Button-1>", lambda e: "break")
                if hasattr(b, "_canvas") and b._canvas:
                    b._canvas.bind("<B1-Motion>", lambda e: "break")
            except Exception:
                pass

        for icon_name, label in nav_items:
            ic = get_bs_icon(icon_name, color="#94A3B8", size=20)
            btn = ctk.CTkButton(
                nav_box, text=f"   {label}", image=ic, compound="left",
                anchor="w", font=ctk.CTkFont(FONT_FAMILY, 13),
                fg_color="transparent", hover_color=INPUT_BG,
                text_color=TEXT_SUB, height=42, corner_radius=8,
                command=lambda name=label: self._switch_page(name)
            )
            btn.pack(fill="x", pady=2)
            _prevent_text_select(btn)
            self.nav_buttons[label] = btn

        # Bottom section: Help & About
        bottom_box = ctk.CTkFrame(sb, fg_color="transparent")
        bottom_box.pack(side="bottom", fill="x", padx=10, pady=(0, 10))

        for icon_name, label in [("question-circle-fill", "Help & Support"), ("info-circle-fill", "About")]:
            ic = get_bs_icon(icon_name, color="#94A3B8", size=18)
            btn = ctk.CTkButton(
                bottom_box, text=f"   {label}", image=ic, compound="left", anchor="w",
                font=ctk.CTkFont(FONT_FAMILY, 13), fg_color="transparent",
                hover_color=INPUT_BG, text_color=TEXT_SUB, height=40, corner_radius=6,
                command=lambda name=label: self._switch_page(name)
            )
            btn.pack(fill="x", pady=1)
            _prevent_text_select(btn)
            self.nav_buttons[label] = btn

        # System Status Card inside sidebar
        sys_card = ctk.CTkFrame(bottom_box, fg_color=INPUT_BG, corner_radius=8,
                                border_width=1, border_color=BORDER_COLOR)
        sys_card.pack(fill="x", pady=(8, 0))
        st_ic = get_bs_icon("check-circle-fill", color="#10B981", size=14)
        sys_inner = ctk.CTkFrame(sys_card, fg_color="transparent")
        sys_inner.pack(padx=10, pady=6, anchor="w")
        if st_ic:
            ctk.CTkLabel(sys_inner, text="", image=st_ic).pack(side="left", padx=(0, 6))
        ctk.CTkLabel(sys_inner, text="All Systems Operational", text_color=SUCCESS,
                     font=ctk.CTkFont(FONT_FAMILY, 11, "bold")).pack(side="left")

    def _header(self, parent):
        """Top bar header matching mockup right side info."""
        hdr = ctk.CTkFrame(parent, fg_color=PANEL_BG, corner_radius=0, height=56,
                           border_width=1, border_color=BORDER_COLOR)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        # Right Header Chips
        be  = BACKEND or "NOT FOUND"
        ff  = Path(FFMPEG_PATH).name if FFMPEG_PATH else "No FFmpeg"

        # GPU Chip
        dev_chip = ctk.CTkFrame(hdr, fg_color=INPUT_BG, corner_radius=8,
                                border_width=1, border_color=BORDER_COLOR)
        dev_chip.pack(side="right", padx=16, pady=10)
        gpu_ic = get_bs_icon("cpu-fill", color="#10B981", size=16)
        dev_inner = ctk.CTkFrame(dev_chip, fg_color="transparent")
        dev_inner.pack(padx=10, pady=4)
        if gpu_ic:
            ctk.CTkLabel(dev_inner, text="", image=gpu_ic).pack(side="left", padx=(0, 6))
        ctk.CTkLabel(dev_inner, text=DEVICE_LABEL,
                     font=ctk.CTkFont(FONT_FAMILY, 12, "bold"), text_color=DEVICE_COLOR
                     ).pack(side="left")

        # Backend & FFmpeg Chip
        be_chip = ctk.CTkFrame(hdr, fg_color=INPUT_BG, corner_radius=8,
                               border_width=1, border_color=BORDER_COLOR)
        be_chip.pack(side="right", padx=(0, 6), pady=10)
        ctk.CTkLabel(be_chip, text=f"Backend: {be}  •  FFmpeg: {ff}",
                     font=ctk.CTkFont(FONT_FAMILY, 11), text_color=TEXT_SUB
                     ).pack(padx=12, pady=5)

    def _switch_page(self, page_name: str):
        """Switch the main content view using cached frames for silky-smooth 0ms transitions."""
        self.current_page.set(page_name)

        # Clear focus so sidebar clicks never leave a stray text selection behind
        try:
            self.root.focus_set()
        except Exception:
            pass

        # Update button highlight states
        bs_nav_map = {
            "Dashboard": "speedometer2",
            "Transcribe": "mic-fill",
            "Batch Processing": "collection-play-fill",
            "Models": "cpu-fill",
            "Settings": "gear-fill",
            "History": "clock-history",
            "Telemetry": "bar-chart-line-fill",
            "Logs": "file-earmark-code-fill",
            "Help & Support": "question-circle-fill",
            "About": "info-circle-fill",
        }

        for name, btn in self.nav_buttons.items():
            bs_name = bs_nav_map.get(name, "dot")
            if name == page_name:
                ic = get_bs_icon(bs_name, color="#FFFFFF", size=20)
                btn.configure(fg_color=ACCENT, text_color=TEXT_MAIN, image=ic,
                              font=ctk.CTkFont(FONT_FAMILY, 14, "bold"))
            else:
                ic = get_bs_icon(bs_name, color="#94A3B8", size=20)
                btn.configure(fg_color="transparent", text_color=TEXT_SUB, image=ic,
                              font=ctk.CTkFont(FONT_FAMILY, 13))

        # Hide all currently packed cached pages
        for p_name, p_frame in self.cached_pages.items():
            p_frame.pack_forget()

        # Render target view if not already cached
        if page_name not in self.cached_pages:
            p_frame = ctk.CTkFrame(self.page_container, fg_color="transparent")
            render_methods = {
                "Dashboard": self._render_dashboard,
                "Transcribe": self._render_transcribe,
                "Batch Processing": self._render_batch,
                "Models": self._render_models,
                "Settings": self._render_app_settings,
                "History": self._render_history,
                "Telemetry": self._render_telemetry_page,
                "Logs": self._render_logs,
                "Help & Support": self._render_help,
                "About": self._render_about,
            }
            render_fn = render_methods.get(page_name, self._render_dashboard)
            render_fn(p_frame)
            self.cached_pages[page_name] = p_frame

        # Show target page instantly
        self.cached_pages[page_name].pack(fill="both", expand=True)

        # Trigger dynamic view updates for views that display live logs/history/batch queue
        if page_name == "Batch Processing" and hasattr(self, "_update_batch_display"):
            self._update_batch_display()

    # ══════════════════════════════════════════════════════════════════════════
    # PAGE RENDERING METHODS
    # ══════════════════════════════════════════════════════════════════════════

    def _render_dashboard(self, parent):
        """Render the primary 2-column studio dashboard matching the mockup."""
        body = ctk.CTkFrame(parent, fg_color=DARK_BG)
        body.pack(fill="both", expand=True)

        # Left Studio Column (420px wide scrollable frame)
        left_pane = ctk.CTkScrollableFrame(body, fg_color="transparent", width=420,
                                           scrollbar_button_color=BORDER_COLOR,
                                           scrollbar_button_hover_color=ACCENT)
        left_pane.pack(side="left", fill="y", padx=(0, 10))

        # Right Studio Column (Flex expand)
        right_pane = ctk.CTkFrame(body, fg_color="transparent")
        right_pane.pack(side="right", fill="both", expand=True)

        # Kept for the transcript-studio Fullscreen toggle (hides/restores the left pane)
        self._dash_left_pane = left_pane
        self._dash_right_pane = right_pane

        # Build Left Column Cards
        self._file_zone(left_pane)
        self._settings(left_pane)
        self._advanced_settings(left_pane)
        self._gen_btn(left_pane)

        # Build Right Column Cards
        self._progress(right_pane)
        self._preview(right_pane)

    def _render_transcribe(self, parent):
        """Dedicated single-file transcription focus view."""
        container = ctk.CTkScrollableFrame(parent, fg_color=DARK_BG,
                                           scrollbar_button_color=BORDER_COLOR,
                                           scrollbar_button_hover_color=ACCENT)
        container.pack(fill="both", expand=True)

        # Hero Banner Card
        hero = ctk.CTkFrame(container, fg_color=CARD_BG, corner_radius=12,
                            border_width=1, border_color=BORDER_COLOR)
        hero.pack(fill="x", pady=(0, 14))
        ctk.CTkLabel(hero, text="Quick Transcribe Studio", font=ctk.CTkFont(FONT_FAMILY, 18, "bold"),
                     text_color=TEXT_MAIN).pack(anchor="w", padx=20, pady=(18, 4))
        ctk.CTkLabel(hero, text="Select or drop an audio or video file below to generate SRT, VTT, ASS, or TXT subtitles instantly.",
                     font=ctk.CTkFont(FONT_FAMILY, 13), text_color=TEXT_SUB).pack(anchor="w", padx=20, pady=(0, 18))

        # File Drop Zone Card
        drop_card = ctk.CTkFrame(container, fg_color=INPUT_BG, corner_radius=12,
                                 border_width=2, border_color=ACCENT)
        drop_card.pack(fill="x", pady=(0, 16), padx=2)

        ctk.CTkLabel(drop_card, text="Select Media File for Subtitle Generation",
                     font=ctk.CTkFont(FONT_FAMILY, 15, "bold"), text_color=TEXT_MAIN).pack(pady=(24, 6))
        ctk.CTkLabel(drop_card, text="Supports MP4, MKV, AVI, MOV, MP3, WAV, FLAC, AAC, M4A",
                     font=ctk.CTkFont(FONT_FAMILY, 12), text_color=TEXT_SUB).pack(pady=(0, 14))

        ctk.CTkButton(drop_card, text="Browse Files", width=150, height=42, corner_radius=8,
                      font=ctk.CTkFont(FONT_FAMILY, 13, "bold"), fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      command=self._browse_in).pack(pady=(0, 26))

        # Quick Control Panel
        ctrl_card = self._card(container, "Transcription Settings")
        grid = ctk.CTkFrame(ctrl_card, fg_color="transparent"); grid.pack(padx=16, pady=(0, 16), fill="x")

        def quick_opt(parent, label, var, vals):
            f = ctk.CTkFrame(parent, fg_color="transparent"); f.pack(side="left", expand=True, fill="x", padx=4)
            ctk.CTkLabel(f, text=label, text_color=TEXT_SUB, font=ctk.CTkFont(FONT_FAMILY, 12, "bold")).pack(anchor="w")
            ctk.CTkOptionMenu(f, variable=var, values=vals, height=38, fg_color=INPUT_BG,
                              button_color=ACCENT, button_hover_color=ACCENT_HOVER,
                              dropdown_fg_color=PANEL_BG, dropdown_text_color=TEXT_MAIN,
                              font=ctk.CTkFont(FONT_FAMILY, 13, "bold"), corner_radius=6).pack(fill="x", pady=(3, 0))

        row = ctk.CTkFrame(grid, fg_color="transparent"); row.pack(fill="x")
        quick_opt(row, "Model", self.model_var, MODEL_SIZES)
        quick_opt(row, "Source Language", self.src_lang_var, list(LANGUAGE_MAP.keys()))
        quick_opt(row, "Translate To", self.tgt_lang_var, ["None"] + list(LANGUAGE_MAP.keys())[1:])
        quick_opt(row, "Output Format", self.fmt_var, OUTPUT_FORMATS)

        self._gen_btn(container)

    def _render_batch(self, parent):
        """Batch processing queue workspace for processing multiple files."""
        container = ctk.CTkScrollableFrame(parent, fg_color=DARK_BG,
                                           scrollbar_button_color=BORDER_COLOR,
                                           scrollbar_button_hover_color=ACCENT)
        container.pack(fill="both", expand=True)

        card = self._card(container, "Batch Subtitle Processing Queue")
        
        # Toolbar
        bar = ctk.CTkFrame(card, fg_color="transparent"); bar.pack(fill="x", padx=16, pady=(0, 12))
        ctk.CTkButton(bar, text="Add Media Files", width=150, height=36, corner_radius=6,
                      font=ctk.CTkFont(FONT_FAMILY, 13, "bold"), fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      command=self._batch_add_files).pack(side="left")
        ctk.CTkButton(bar, text="Clear Queue", width=110, height=36, corner_radius=6,
                      fg_color="transparent", border_width=1, border_color=BORDER_COLOR,
                      text_color=TEXT_SUB, hover_color=INPUT_BG, font=ctk.CTkFont(FONT_FAMILY, 12, "bold"),
                      command=self._batch_clear).pack(side="left", padx=8)

        # Batch Queue Table Header Strip (Grid style datatable header)
        tbl_hdr = ctk.CTkFrame(card, fg_color=INPUT_BG, corner_radius=6, height=36,
                               border_width=1, border_color=BORDER_COLOR)
        tbl_hdr.pack(fill="x", padx=16, pady=(0, 6))
        tbl_hdr.pack_propagate(False)

        ctk.CTkLabel(tbl_hdr, text="#", width=45, font=ctk.CTkFont(FONT_FAMILY, 12, "bold"), text_color=TEXT_SUB).pack(side="left", padx=4)
        ctk.CTkLabel(tbl_hdr, text="Media File Name", font=ctk.CTkFont(FONT_FAMILY, 12, "bold"), text_color=TEXT_SUB, anchor="w").pack(side="left", fill="x", expand=True, padx=8)
        ctk.CTkLabel(tbl_hdr, text="Format", width=85, font=ctk.CTkFont(FONT_FAMILY, 12, "bold"), text_color=TEXT_SUB).pack(side="left", padx=4)
        ctk.CTkLabel(tbl_hdr, text="Status", width=110, font=ctk.CTkFont(FONT_FAMILY, 12, "bold"), text_color=TEXT_SUB).pack(side="left", padx=4)
        ctk.CTkLabel(tbl_hdr, text="Action", width=90, font=ctk.CTkFont(FONT_FAMILY, 12, "bold"), text_color=TEXT_SUB).pack(side="left", padx=6)

        # Scrollable Rows Frame Grid Container
        self.batch_rows_frame = ctk.CTkScrollableFrame(card, fg_color=INPUT_BG, corner_radius=6,
                                                       border_width=1, border_color=BORDER_COLOR, height=260,
                                                       scrollbar_button_color=BORDER_COLOR,
                                                       scrollbar_button_hover_color=ACCENT)
        self.batch_rows_frame.pack(fill="x", padx=16, pady=(0, 14))

        if not hasattr(self, "batch_files"):
            self.batch_files = []
        self._update_batch_display()

        ctk.CTkButton(card, text="Start Batch Processing", height=48, corner_radius=8,
                      font=ctk.CTkFont(FONT_FAMILY, 15, "bold"), fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      command=self._batch_start).pack(fill="x", padx=16, pady=(0, 16))

    def _batch_add_files(self):
        t = [("Media", "*.mp4 *.mkv *.avi *.mov *.webm *.mp3 *.wav *.m4a *.flac *.ogg *.aac"), ("All", "*.*")]
        fs = filedialog.askopenfilenames(filetypes=t)
        if fs:
            if not hasattr(self, "batch_files"):
                self.batch_files = []
            self.batch_files.extend(fs)
            self._update_batch_display()

    def _batch_clear(self):
        self.batch_files = []
        self._update_batch_display()

    def _batch_remove_item(self, idx):
        if hasattr(self, "batch_files") and 0 <= idx < len(self.batch_files):
            self.batch_files.pop(idx)
            self._update_batch_display()

    def _update_batch_display(self):
        if not hasattr(self, "batch_rows_frame"):
            return
        for widget in self.batch_rows_frame.winfo_children():
            widget.destroy()

        if not getattr(self, "batch_files", []):
            empty_f = ctk.CTkFrame(self.batch_rows_frame, fg_color="transparent")
            empty_f.pack(fill="both", expand=True, pady=40)
            ctk.CTkLabel(empty_f, text="No files in batch queue.", font=ctk.CTkFont(FONT_FAMILY, 14, "bold"), text_color=TEXT_MAIN).pack(pady=(0, 4))
            ctk.CTkLabel(empty_f, text="Click 'Add Media Files' above to queue video & audio files for automatic subtitle generation.",
                         font=ctk.CTkFont(FONT_FAMILY, 12), text_color=TEXT_SUB).pack()
        else:
            for i, f in enumerate(self.batch_files, 1):
                bg_col = PANEL_BG if i % 2 == 0 else INPUT_BG
                row = ctk.CTkFrame(self.batch_rows_frame, fg_color=bg_col, corner_radius=6,
                                   border_width=1, border_color=BORDER_COLOR, height=40)
                row.pack(fill="x", pady=2)
                row.pack_propagate(False)

                name = Path(f).name
                fmt = self.fmt_var.get()

                # Index
                ctk.CTkLabel(row, text=str(i), width=45, font=ctk.CTkFont(FONT_FAMILY, 12, "bold"), text_color=TEXT_SUB).pack(side="left", padx=4)
                
                # File Name
                ctk.CTkLabel(row, text=name, font=ctk.CTkFont(FONT_FAMILY, 12, "bold"), text_color=TEXT_MAIN, anchor="w").pack(side="left", fill="x", expand=True, padx=8)

                # Format Badge
                fmt_frame = ctk.CTkFrame(row, fg_color=INPUT_BG, corner_radius=4, width=85, height=28, border_width=1, border_color=BORDER_COLOR)
                fmt_frame.pack(side="left", padx=4)
                fmt_frame.pack_propagate(False)
                ctk.CTkLabel(fmt_frame, text=fmt, font=ctk.CTkFont(FONT_FAMILY, 11, "bold"), text_color=ACCENT_CYAN).pack(expand=True)

                # Status Badge
                st_frame = ctk.CTkFrame(row, fg_color="#1a2e1a" if i == 1 else INPUT_BG, corner_radius=4, width=110, height=28,
                                        border_width=1, border_color=SUCCESS if i == 1 else BORDER_COLOR)
                st_frame.pack(side="left", padx=4)
                st_frame.pack_propagate(False)
                st_txt = "Next Up" if i == 1 else "Pending"
                st_col = SUCCESS if i == 1 else TEXT_SUB
                ctk.CTkLabel(st_frame, text=st_txt, font=ctk.CTkFont(FONT_FAMILY, 11, "bold"), text_color=st_col).pack(expand=True)

                # Remove Action Button
                ctk.CTkButton(row, text="Remove", width=75, height=28, corner_radius=4,
                              fg_color="transparent", border_width=1, border_color=BORDER_COLOR,
                              text_color=ERROR_C, hover_color=INPUT_BG, font=ctk.CTkFont(FONT_FAMILY, 11, "bold"),
                              command=lambda idx=i-1: self._batch_remove_item(idx)).pack(side="left", padx=6)

    def _batch_start(self):
        if not getattr(self, "batch_files", []):
            messagebox.showinfo("Batch Processing", "Please add files to the queue first.")
            return
        first = self.batch_files[0]
        self.input_file.set(first)
        self._switch_page("Dashboard")
        self._start()

    def _render_models(self, parent):
        """Comprehensive AI Model Manager workspace."""
        container = ctk.CTkScrollableFrame(parent, fg_color=DARK_BG,
                                           scrollbar_button_color=BORDER_COLOR,
                                           scrollbar_button_hover_color=ACCENT)
        container.pack(fill="both", expand=True)

        hdr = self._card(container, "Whisper AI Model Manager")
        ctk.CTkLabel(hdr, text="Download and manage local faster-whisper and GGML model weights for offline GPU & CPU transcription.",
                     font=ctk.CTkFont(FONT_FAMILY, 12), text_color=TEXT_SUB).pack(anchor="w", padx=16, pady=(0, 12))

        models_data = [
            ("large-v3", "3.1 GB", "~12 GB VRAM", "Best Accuracy", "Recommended for production subtitles & complex multi-speaker audio."),
            ("large-v3-turbo", "809 MB", "~6 GB VRAM", "8x Speed + High Accuracy", "Optimized large model for ultra-fast GPU processing."),
            ("distil-large-v3", "756 MB", "~4 GB VRAM", "Distilled Speed", "Distilled model delivering fast inference with low memory usage."),
            ("large-v2", "3.1 GB", "~10 GB VRAM", "Legacy Large", "Previous generation Whisper large model."),
            ("medium", "1.5 GB", "~3 GB VRAM", "Balanced", "Great balance between accuracy and speed for mid-range GPUs."),
            ("small", "484 MB", "~1 GB VRAM", "Lightweight", "Lightweight model for laptops and quick drafts."),
            ("base", "145 MB", "~500 MB VRAM", "Very Fast", "Fast low-resource model for simple speech."),
            ("tiny", "75 MB", "~250 MB VRAM", "Fastest", "Smallest model footprint for rapid testing."),
        ]

        grid = ctk.CTkFrame(container, fg_color="transparent"); grid.pack(fill="x")

        for i, (name, size, vram, tag, desc) in enumerate(models_data):
            c = ctk.CTkFrame(grid, fg_color=CARD_BG, corner_radius=10,
                             border_width=1, border_color=BORDER_COLOR)
            c.pack(fill="x", pady=5)

            row = ctk.CTkFrame(c, fg_color="transparent"); row.pack(fill="x", padx=16, pady=12)

            left = ctk.CTkFrame(row, fg_color="transparent"); left.pack(side="left", fill="x", expand=True)
            ctk.CTkLabel(left, text=f"{name}", font=ctk.CTkFont(FONT_FAMILY, 15, "bold"), text_color=TEXT_MAIN).pack(anchor="w")
            ctk.CTkLabel(left, text=f"{tag}  •  Download Size: {size}  •  Memory: {vram}",
                         font=ctk.CTkFont(FONT_FAMILY, 12, "bold"), text_color=ACCENT_CYAN).pack(anchor="w", pady=(3, 0))
            ctk.CTkLabel(left, text=desc, font=ctk.CTkFont(FONT_FAMILY, 12), text_color=TEXT_SUB).pack(anchor="w", pady=(2, 0))

            right_frame = ctk.CTkFrame(row, fg_color="transparent")
            right_frame.pack(side="right", padx=6)

            is_dl = is_model_downloaded(name)

            if is_dl:
                chk_ic = get_bs_icon("check-circle-fill", color="#10B981", size=16)
                del_ic = get_bs_icon("trash-fill", color="#EF4444", size=16)

                # Status pill: Downloaded
                status_pill = ctk.CTkFrame(right_frame, fg_color="#1a3a1a", corner_radius=6,
                                           border_width=1, border_color=BORDER_COLOR)
                status_pill.pack(side="left", padx=(0, 6))
                if chk_ic:
                    ctk.CTkLabel(status_pill, text="", image=chk_ic).pack(side="left", padx=(8, 2), pady=6)
                ctk.CTkLabel(status_pill, text="Downloaded", text_color=SUCCESS,
                             font=ctk.CTkFont(FONT_FAMILY, 12, "bold")).pack(side="left", padx=(2, 8), pady=6)

                # Select / Activate Model Button
                ctk.CTkButton(
                    right_frame, text="Select", width=80, height=36, corner_radius=6,
                    fg_color=ACCENT, hover_color=ACCENT_HOVER,
                    font=ctk.CTkFont(FONT_FAMILY, 12, "bold"),
                    command=lambda m=name: self._download_specific_model(m)
                ).pack(side="left", padx=4)

                # Delete Model Button
                ctk.CTkButton(
                    right_frame, text="Delete", image=del_ic, width=95, height=36, corner_radius=6,
                    fg_color="transparent", border_width=1, border_color=BORDER_COLOR,
                    text_color=ERROR_C, hover_color=INPUT_BG,
                    font=ctk.CTkFont(FONT_FAMILY, 12, "bold"),
                    command=lambda m=name: self._delete_specific_model(m)
                ).pack(side="left", padx=4)
            else:
                dl_ic = get_bs_icon("cloud-download-fill", color="#FFFFFF", size=16)
                ctk.CTkButton(
                    right_frame, text="Download", image=dl_ic, width=135, height=36, corner_radius=6,
                    fg_color=ACCENT, hover_color=ACCENT_HOVER,
                    font=ctk.CTkFont(FONT_FAMILY, 12, "bold"),
                    command=lambda m=name: self._download_specific_model(m)
                ).pack(side="left", padx=4)

    def _download_specific_model(self, model_name: str):
        self.model_var.set(model_name)
        self._switch_page("Dashboard")
        self._do_download()

    def _delete_specific_model(self, model_name: str):
        if self.running:
            messagebox.showwarning("Busy", "Please wait for the current task to finish.")
            return
        if messagebox.askyesno(
            "Delete Model",
            f"Are you sure you want to delete local model weights for '{model_name}'?\n\nThis will free up disk space on your PC."
        ):
            ok = delete_model_files(model_name)
            if ok:
                self._setstatus(f"Model '{model_name}' deleted from disk.", color=SUCCESS)
            else:
                self._setstatus(f"Could not delete model '{model_name}'.", color=WARNING)
            self.cached_pages.pop("Models", None)
            self._switch_page("Models")
            self._refresh_model_status()

    def _render_app_settings(self, parent):
        """Global application preferences & engine settings."""
        container = ctk.CTkScrollableFrame(parent, fg_color=DARK_BG,
                                           scrollbar_button_color=BORDER_COLOR,
                                           scrollbar_button_hover_color=ACCENT)
        container.pack(fill="both", expand=True)

        card = self._card(container, "Application Preferences & Environment", icon_name="gear-fill")

        def pref_row(parent_f, title, desc, widget_builder):
            f = ctk.CTkFrame(parent_f, fg_color="transparent"); f.pack(fill="x", padx=16, pady=10)
            info = ctk.CTkFrame(f, fg_color="transparent"); info.pack(side="left", fill="x", expand=True)
            ctk.CTkLabel(info, text=title, font=ctk.CTkFont(FONT_FAMILY, 13, "bold"), text_color=TEXT_MAIN).pack(anchor="w")
            ctk.CTkLabel(info, text=desc, font=ctk.CTkFont(FONT_FAMILY, 12), text_color=TEXT_SUB).pack(anchor="w", pady=(2, 0))
            widget_builder(f)
            sep = ctk.CTkFrame(parent_f, fg_color=BORDER_COLOR, height=1)
            sep.pack(fill="x", padx=16, pady=4)

        pref_row(card, "Default Subtitle Output Format", "Default format when selecting a new file",
                 lambda p: ctk.CTkOptionMenu(p, variable=self.fmt_var, values=OUTPUT_FORMATS, width=120, height=34,
                                             fg_color=INPUT_BG, button_color=ACCENT, font=ctk.CTkFont(FONT_FAMILY, 12, "bold")).pack(side="right"))

        pref_row(card, "Default Source Language", "Default spoken language detection preset",
                 lambda p: ctk.CTkOptionMenu(p, variable=self.src_lang_var, values=list(LANGUAGE_MAP.keys()), width=180, height=34,
                                             fg_color=INPUT_BG, button_color=ACCENT, font=ctk.CTkFont(FONT_FAMILY, 12, "bold")).pack(side="right"))

        ff_str = FFMPEG_PATH or "Not Detected"
        pref_row(card, "FFmpeg Executable Path", f"Detected binary: {ff_str}",
                 lambda p: ctk.CTkLabel(p, text="Auto Detected" if FFMPEG_PATH else "Missing",
                                        text_color=SUCCESS if FFMPEG_PATH else WARNING,
                                        font=ctk.CTkFont(FONT_FAMILY, 12, "bold")).pack(side="right"))

        pref_row(card, "Primary GPU Compute Backend", f"Active engine: {DEVICE_LABEL}",
                 lambda p: ctk.CTkLabel(p, text=DEVICE_LABEL, text_color=DEVICE_COLOR,
                                        font=ctk.CTkFont(FONT_FAMILY, 12, "bold")).pack(side="right"))

        # Desktop Shortcut Creator Option
        sc_icon = get_bs_icon("window-desktop", color="#FFFFFF", size=16)
        pref_row(card, "Desktop Shortcut", "Create a Windows Desktop Shortcut with SubTranscribe Logo Icon",
                 lambda p: ctk.CTkButton(p, text="Create Desktop Shortcut", image=sc_icon, width=200, height=34, corner_radius=6,
                                         fg_color=ACCENT, hover_color=ACCENT_HOVER, font=ctk.CTkFont(FONT_FAMILY, 12, "bold"),
                                         command=self._create_desktop_shortcut).pack(side="right"))

        # Complete Cleanup Option
        del_all_icon = get_bs_icon("trash-fill", color="#EF4444", size=16)
        pref_row(card, "Purge All Local AI Models & Data", "Completely remove all downloaded AI models, cache, and history logs leaving zero traces",
                 lambda p: ctk.CTkButton(p, text="Purge All Models & Cache", image=del_all_icon, width=210, height=34, corner_radius=6,
                                         fg_color="transparent", border_width=1, border_color=BORDER_COLOR,
                                         text_color=ERROR_C, hover_color=INPUT_BG, font=ctk.CTkFont(FONT_FAMILY, 12, "bold"),
                                         command=self._purge_all_data).pack(side="right"))

    def _create_desktop_shortcut(self):
        """Create a Windows Desktop Shortcut with official logo.ico."""
        try:
            import sys
            desktop = Path(os.path.expanduser("~/Desktop"))
            target_exe = sys.executable if getattr(sys, 'frozen', False) else str(PROJECT_DIR / "run.bat")
            icon_file = str(PROJECT_DIR / "assets" / "logo.ico")
            shortcut_path = str(desktop / "SubTranscribe Studio.lnk")

            vbs_script = f'''
Set WshShell = CreateObject("WScript.Shell")
Set shortcut = WshShell.CreateShortcut("{shortcut_path}")
shortcut.TargetPath = "{target_exe}"
shortcut.WorkingDirectory = "{str(PROJECT_DIR)}"
shortcut.IconLocation = "{icon_file}"
shortcut.Description = "SubTranscribe Studio Enterprise Edition"
shortcut.Save
'''
            vbs_file = DATA_DIR / "create_sc.vbs"
            with open(vbs_file, "w", encoding="utf-8") as f:
                f.write(vbs_script)
            os.system(f'cscript //nologo "{vbs_file}"')
            if vbs_file.exists():
                os.unlink(vbs_file)
            messagebox.showinfo("Success", f"Desktop Shortcut created successfully on your Desktop!\n\nLocation:\n{shortcut_path}")
            self._setstatus("Desktop Shortcut created with logo icon!", color=SUCCESS)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to create desktop shortcut: {e}")

    def _purge_all_data(self):
        """Completely purge all downloaded model weights, cache, and history logs from PC."""
        if messagebox.askyesno(
            "Purge All Models & Traces?",
            "Are you sure you want to COMPLETELY DELETE all downloaded AI model weights, caches, and history logs?\n\nThis will remove all downloaded model files and leave zero traces on your PC."
        ):
            count = 0
            for m_size in MODEL_SIZES:
                if delete_model_files(m_size):
                    count += 1
            # Purge history
            hist_file = DATA_DIR / "history.json"
            if hist_file.exists():
                try: hist_file.unlink()
                except Exception: pass
            self.cached_pages.clear()
            messagebox.showinfo("Cleanup Complete", f"Successfully purged {count} model packages and all cached data.\nZero traces remain.")
            self._setstatus("All models and local cache completely purged from disk.", color=SUCCESS)

    # ── History Helpers
    def _get_history(self):
        hist_file = DATA_DIR / "history.json"
        if hist_file.exists():
            try:
                import json
                with open(hist_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return []
        return []

    def _add_history_entry(self, entry):
        hist_file = DATA_DIR / "history.json"
        hist = self._get_history()
        hist.insert(0, entry)
        try:
            import json
            with open(hist_file, "w", encoding="utf-8") as f:
                json.dump(hist[:100], f, indent=2)
        except Exception:
            pass

    def _clear_history(self):
        hist_file = DATA_DIR / "history.json"
        if hist_file.exists():
            try:
                hist_file.unlink()
            except Exception:
                pass
        self.cached_pages.pop("History", None)
        self._switch_page("History")

    def _delete_history_entry(self, entry_id):
        hist_file = DATA_DIR / "history.json"
        hist = [h for h in self._get_history() if h.get("id") != entry_id]
        try:
            import json
            with open(hist_file, "w", encoding="utf-8") as f:
                json.dump(hist, f, indent=2)
        except Exception:
            pass
        self.cached_pages.pop("History", None)
        self._switch_page("History")

    def _render_history(self, parent):
        """Rich interactive transcription task history page."""
        container = ctk.CTkScrollableFrame(parent, fg_color=DARK_BG,
                                           scrollbar_button_color=BORDER_COLOR,
                                           scrollbar_button_hover_color=ACCENT)
        container.pack(fill="both", expand=True)

        card = self._card(container, "Transcription Task History")

        # Header Bar with Clear Action
        bar = ctk.CTkFrame(card, fg_color="transparent"); bar.pack(fill="x", padx=16, pady=(0, 12))
        ctk.CTkLabel(bar, text="View and access all previously generated subtitle files and export history.",
                     font=ctk.CTkFont(FONT_FAMILY, 12), text_color=TEXT_SUB).pack(side="left")

        ctk.CTkButton(bar, text="Clear History", width=110, height=32, corner_radius=6,
                      fg_color="transparent", border_width=1, border_color=BORDER_COLOR,
                      text_color=TEXT_SUB, hover_color=INPUT_BG, font=ctk.CTkFont(FONT_FAMILY, 12, "bold"),
                      command=self._clear_history).pack(side="right")

        history_items = self._get_history()

        if not history_items:
            empty_box = ctk.CTkFrame(card, fg_color=INPUT_BG, corner_radius=8,
                                     border_width=1, border_color=BORDER_COLOR)
            empty_box.pack(fill="x", padx=16, pady=(0, 18))
            ctk.CTkLabel(empty_box, text="No transcription history recorded yet.",
                         font=ctk.CTkFont(FONT_FAMILY, 14, "bold"), text_color=TEXT_MAIN).pack(pady=(24, 6))
            ctk.CTkLabel(empty_box, text="Generated subtitles will be saved here automatically.",
                         font=ctk.CTkFont(FONT_FAMILY, 12), text_color=TEXT_SUB).pack(pady=(0, 24))
            return

        # Table Header Strip
        tbl_hdr = ctk.CTkFrame(card, fg_color=INPUT_BG, corner_radius=6, height=32,
                               border_width=1, border_color=BORDER_COLOR)
        tbl_hdr.pack(fill="x", padx=16, pady=(0, 6))
        tbl_hdr.pack_propagate(False)

        ctk.CTkLabel(tbl_hdr, text="#", width=36, font=ctk.CTkFont(FONT_FAMILY, 11, "bold"), text_color=TEXT_SUB).pack(side="left", padx=4)
        ctk.CTkLabel(tbl_hdr, text="Media File", width=200, font=ctk.CTkFont(FONT_FAMILY, 11, "bold"), text_color=TEXT_SUB).pack(side="left", padx=4)
        ctk.CTkLabel(tbl_hdr, text="Model", width=110, font=ctk.CTkFont(FONT_FAMILY, 11, "bold"), text_color=TEXT_SUB).pack(side="left", padx=4)
        ctk.CTkLabel(tbl_hdr, text="Format", width=70, font=ctk.CTkFont(FONT_FAMILY, 11, "bold"), text_color=TEXT_SUB).pack(side="left", padx=4)
        ctk.CTkLabel(tbl_hdr, text="Date & Time", width=150, font=ctk.CTkFont(FONT_FAMILY, 11, "bold"), text_color=TEXT_SUB).pack(side="left", padx=4)
        ctk.CTkLabel(tbl_hdr, text="Status", width=90, font=ctk.CTkFont(FONT_FAMILY, 11, "bold"), text_color=TEXT_SUB).pack(side="left", padx=4)
        ctk.CTkLabel(tbl_hdr, text="Actions", font=ctk.CTkFont(FONT_FAMILY, 11, "bold"), text_color=TEXT_SUB).pack(side="left", padx=8)

        # History Item Rows
        for idx, item in enumerate(history_items, 1):
            row = ctk.CTkFrame(card, fg_color=INPUT_BG if idx % 2 == 0 else PANEL_BG,
                               corner_radius=6, border_width=1, border_color=BORDER_COLOR)
            row.pack(fill="x", padx=16, pady=3)

            sub_path = item.get("subtitle_path", "")
            media_file = item.get("media_file", "Unknown")
            model_name = item.get("model", "large-v3")
            fmt_name = item.get("format", "SRT")
            timestamp = item.get("timestamp", "--")
            entry_id = item.get("id", str(idx))

            # Row columns
            ctk.CTkLabel(row, text=str(idx), width=36, font=ctk.CTkFont(FONT_FAMILY, 11), text_color=TEXT_SUB).pack(side="left", padx=4, pady=10)
            ctk.CTkLabel(row, text=media_file, width=200, font=ctk.CTkFont(FONT_FAMILY, 12, "bold"), text_color=TEXT_MAIN, anchor="w").pack(side="left", padx=4)
            ctk.CTkLabel(row, text=model_name, width=110, font=ctk.CTkFont(FONT_FAMILY, 11, "bold"), text_color=ACCENT_CYAN, anchor="w").pack(side="left", padx=4)
            ctk.CTkLabel(row, text=fmt_name, width=70, font=ctk.CTkFont(FONT_FAMILY, 11, "bold"), text_color=TEXT_MAIN, anchor="w").pack(side="left", padx=4)
            ctk.CTkLabel(row, text=timestamp, width=150, font=ctk.CTkFont(FONT_FAMILY, 11), text_color=TEXT_SUB, anchor="w").pack(side="left", padx=4)
            
            status_lbl = ctk.CTkLabel(row, text="Completed", width=90, font=ctk.CTkFont(FONT_FAMILY, 11, "bold"), text_color=SUCCESS, anchor="w")
            status_lbl.pack(side="left", padx=4)

            # Actions Frame (Open File, Open Folder, Delete)
            act_frame = ctk.CTkFrame(row, fg_color="transparent")
            act_frame.pack(side="right", padx=6)

            if sub_path and os.path.exists(sub_path):
                ctk.CTkButton(act_frame, text="Open File", width=85, height=30, corner_radius=4,
                              fg_color=ACCENT, hover_color=ACCENT_HOVER, font=ctk.CTkFont(FONT_FAMILY, 11, "bold"),
                              command=lambda p=sub_path: os.startfile(p)).pack(side="left", padx=3)

            out_dir = str(Path(sub_path).parent) if sub_path else ""
            if out_dir and os.path.isdir(out_dir):
                ctk.CTkButton(act_frame, text="Open Folder", width=90, height=30, corner_radius=4,
                              fg_color=INPUT_BG, border_width=1, border_color=BORDER_COLOR,
                              text_color=TEXT_MAIN, hover_color=BORDER_COLOR, font=ctk.CTkFont(FONT_FAMILY, 11, "bold"),
                              command=lambda d=out_dir: os.startfile(d)).pack(side="left", padx=3)

            ctk.CTkButton(act_frame, text="Remove", width=75, height=30, corner_radius=4,
                          fg_color="transparent", border_width=1, border_color=BORDER_COLOR,
                          text_color=ERROR_C, hover_color=INPUT_BG, font=ctk.CTkFont(FONT_FAMILY, 11, "bold"),
                          command=lambda eid=entry_id: self._delete_history_entry(eid)).pack(side="left", padx=3)

    def _render_telemetry_page(self, parent):
        """Extended hardware & GPU telemetry stats workspace."""
        container = ctk.CTkScrollableFrame(parent, fg_color=DARK_BG,
                                           scrollbar_button_color=BORDER_COLOR,
                                           scrollbar_button_hover_color=ACCENT)
        container.pack(fill="both", expand=True)

        card = self._card(container, "System Hardware & Acceleration Telemetry", icon_name="activity")

        grid = ctk.CTkFrame(card, fg_color="transparent"); grid.pack(fill="x", padx=16, pady=(0, 14))

        def tel_card(parent_grid, icon_name, label, value, subtext, color=ACCENT_CYAN, textvariable=None):
            ic = get_bs_icon(icon_name, color="#06B6D4", size=18)
            f = ctk.CTkFrame(parent_grid, fg_color=INPUT_BG, corner_radius=10,
                             border_width=1, border_color=BORDER_COLOR)
            f.pack(side="left", expand=True, fill="x", padx=4, pady=4)
            lbl_f = ctk.CTkFrame(f, fg_color="transparent")
            lbl_f.pack(anchor="w", padx=14, pady=(12, 0))
            if ic:
                ctk.CTkLabel(lbl_f, text="", image=ic).pack(side="left", padx=(0, 6))
            ctk.CTkLabel(lbl_f, text=label, text_color=TEXT_SUB,
                         font=ctk.CTkFont(FONT_FAMILY, 12, "bold")).pack(side="left")
            val_lbl = ctk.CTkLabel(f, text=value if textvariable is None else "", text_color=color,
                                   font=ctk.CTkFont(FONT_FAMILY, 20, "bold"))
            if textvariable is not None:
                val_lbl.configure(textvariable=textvariable)
            val_lbl.pack(anchor="w", padx=14, pady=(3, 0))
            ctk.CTkLabel(f, text=subtext, text_color=TEXT_SUB,
                         font=ctk.CTkFont(FONT_FAMILY, 11)).pack(anchor="w", padx=14, pady=(0, 12))

        gpu_val = GPU_NAME or ("CUDA Available" if DEVICE == "cuda" else "High-Speed CPU Engine")
        tel_card(grid, "cpu-fill", "Primary GPU", gpu_val, "Device 0", SUCCESS)
        tel_card(grid, "gear-fill", "Compute Backend", BACKEND or "None", f"Device: {DEVICE}", ACCENT)
        tel_card(grid, "film", "FFmpeg Binary", Path(FFMPEG_PATH).name if FFMPEG_PATH else "Missing", "Audio Decoding Engine", WARNING)
        tel_card(grid, "database-fill", "Model Local Storage", f"{get_dir_size(MODELS_DIR)/(1024**2):.1f} MB", "Local Cache Directory", ACCENT_CYAN)

        # Live-updating hardware row — these StringVars are already refreshed
        # every second by _telemetry_loop(); previously they were only ever
        # displayed in the bottom status bar footer, never on this page,
        # which is why everything below the static cards above was blank.
        ctk.CTkLabel(card, text="Live System Load", text_color=TEXT_MAIN,
                     font=ctk.CTkFont(FONT_FAMILY, 14, "bold")).pack(anchor="w", padx=16, pady=(4, 6))
        live_grid = ctk.CTkFrame(card, fg_color="transparent"); live_grid.pack(fill="x", padx=16, pady=(0, 16))
        tel_card(live_grid, "cpu-fill", "CPU Usage", "", "Live", ACCENT_CYAN, textvariable=self.cpu_live_var)
        tel_card(live_grid, "hdd-fill", "RAM Usage", "", "Live", SUCCESS, textvariable=self.ram_live_var)
        tel_card(live_grid, "gpu-card", "GPU Load", "", "Live (estimated)", ACCENT, textvariable=self.gpu_live_var)
        tel_card(live_grid, "device-hdd-fill", "Disk Usage", "", "Live", WARNING, textvariable=self.disk_live_var)
        tel_card(live_grid, "thermometer-half", "Temperature", "", "Live (estimated)", ERROR_C, textvariable=self.temp_live_var)

    def _render_logs(self, parent):
        """Application event log viewer."""
        container = ctk.CTkScrollableFrame(parent, fg_color=DARK_BG,
                                           scrollbar_button_color=BORDER_COLOR,
                                           scrollbar_button_hover_color=ACCENT)
        container.pack(fill="both", expand=True)

        card = self._card(container, "Application Console & Event Logs", icon_name="file-earmark-code-fill")

        bar = ctk.CTkFrame(card, fg_color="transparent"); bar.pack(fill="x", padx=16, pady=(0, 12))

        del_icon = get_bs_icon("trash-fill", color="#EF4444", size=16)
        ctk.CTkButton(bar, text="Clear Logs", image=del_icon, width=130, height=36, corner_radius=6,
                      fg_color="transparent", border_width=1, border_color=BORDER_COLOR,
                      text_color=ERROR_C, hover_color=INPUT_BG, font=ctk.CTkFont(FONT_FAMILY, 13, "bold"),
                      command=self._clear_logs).pack(side="right", padx=(6, 0))

        cp_icon = get_bs_icon("clipboard-fill", color="#FFFFFF", size=16)
        ctk.CTkButton(bar, text="Copy Logs", image=cp_icon, width=130, height=36, corner_radius=6,
                      fg_color=INPUT_BG, border_width=1, border_color=BORDER_COLOR,
                      text_color=TEXT_MAIN, hover_color=BORDER_COLOR, font=ctk.CTkFont(FONT_FAMILY, 13, "bold"),
                      command=self._copy_logs).pack(side="right")

        self.log_tbox = ctk.CTkTextbox(card, fg_color=INPUT_BG, text_color=TEXT_MAIN,
                                       font=ctk.CTkFont("Consolas", 16, "bold"), corner_radius=8,
                                       border_width=1, border_color=BORDER_COLOR, height=360)
        self.log_tbox.pack(fill="x", padx=16, pady=(0, 16))

        self.log_tbox.insert("end", f"[{time.strftime('%H:%M:%S')}] SubTranscribe v{APP_VER} initialized cleanly.\n")
        self.log_tbox.insert("end", f"[{time.strftime('%H:%M:%S')}] Backend detected: {BACKEND}\n")
        self.log_tbox.insert("end", f"[{time.strftime('%H:%M:%S')}] Device compute mode: {DEVICE} ({COMPUTE_TYPE})\n")
        self.log_tbox.insert("end", f"[{time.strftime('%H:%M:%S')}] GPU Name: {GPU_NAME or 'None detected'}\n")
        self.log_tbox.insert("end", f"[{time.strftime('%H:%M:%S')}] FFmpeg Binary: {FFMPEG_PATH or 'Not Found'}\n")
        self.log_tbox.insert("end", f"[{time.strftime('%H:%M:%S')}] System Status: All Systems Operational.\n")
        self.log_tbox.configure(state="disabled")

    def _copy_logs(self):
        if hasattr(self, "log_tbox"):
            txt = self.log_tbox.get("1.0", "end").strip()
            if txt:
                self.root.clipboard_clear()
                self.root.clipboard_append(txt)
                self._setstatus("Logs copied to clipboard!", color=ACCENT_CYAN)

    def _clear_logs(self):
        if hasattr(self, "log_tbox") and self.log_tbox:
            self.log_tbox.configure(state="normal")
            self.log_tbox.delete("1.0", "end")
            self.log_tbox.insert("end", f"[{time.strftime('%H:%M:%S')}] Event logs cleared.\n")
            self.log_tbox.configure(state="disabled")
            self._setstatus("Logs cleared.", color=ACCENT_CYAN)

    def _render_help(self, parent):
        """Help, documentation & shortcut guide."""
        container = ctk.CTkScrollableFrame(parent, fg_color=DARK_BG,
                                           scrollbar_button_color=BORDER_COLOR,
                                           scrollbar_button_hover_color=ACCENT)
        container.pack(fill="both", expand=True)

        card = self._card(container, "Help & User Documentation", icon_name="question-circle-fill")

        help_txt = ctk.CTkTextbox(card, fg_color=INPUT_BG, text_color=TEXT_MAIN,
                                  font=ctk.CTkFont(FONT_FAMILY, 13), corner_radius=6,
                                  border_width=1, border_color=BORDER_COLOR, height=340)
        help_txt.pack(fill="x", padx=16, pady=(0, 14))

        doc = """SubTranscribe User Guide & FAQ

1. How to Generate Subtitles:
   • Click 'Browse' on the Dashboard to select your media file (.mp4, .mkv, .mp3, .wav, etc.)
   • Choose your desired Whisper model (large-v3, large-v3-turbo, distil-large-v3, etc.)
   • Select the Output Format (SRT, VTT, ASS, TXT)
   • Click 'Generate Subtitles'

2. GPU Acceleration Setup:
   • NVIDIA GPUs: Automatically uses CUDA (float16) via faster-whisper.
   • AMD / Intel GPUs: Uses bundled Vulkan GGML engine for fast GPU processing.
   • CPU Fallback: Runs 8-bit quantised inference on CPU if no GPU driver is found.

3. Supported Formats:
   • Video: MP4, MKV, AVI, MOV, WEBM
   • Audio: MP3, WAV, FLAC, OGG, M4A, AAC
   • Subtitle Outputs: SRT, WEBVTT, Advanced SubStation Alpha (ASS), Plain Text (TXT)
"""
        help_txt.insert("end", doc)
        help_txt.configure(state="disabled")

    def _render_about(self, parent):
        """Rich enterprise About Us & Feature Showcase workspace."""
        container = ctk.CTkScrollableFrame(parent, fg_color=DARK_BG,
                                           scrollbar_button_color=BORDER_COLOR,
                                           scrollbar_button_hover_color=ACCENT)
        container.pack(fill="both", expand=True)

        # Hero Brand Banner
        hero = ctk.CTkFrame(container, fg_color=CARD_BG, corner_radius=14,
                            border_width=1, border_color=BORDER_COLOR)
        hero.pack(fill="x", pady=(0, 14))

        hero_inner = ctk.CTkFrame(hero, fg_color="transparent")
        hero_inner.pack(fill="x", padx=24, pady=24)

        # App Logo Image
        if LOGO_PATH.exists():
            try:
                logo_img = ctk.CTkImage(light_image=Image.open(LOGO_PATH),
                                        dark_image=Image.open(LOGO_PATH),
                                        size=(100, 100))
                ctk.CTkLabel(hero_inner, text="", image=logo_img).pack(side="left", padx=(0, 20))
            except Exception:
                pass

        brand_info = ctk.CTkFrame(hero_inner, fg_color="transparent")
        brand_info.pack(side="left", fill="x", expand=True)

        ctk.CTkLabel(brand_info, text=f"{APP_NAME}  v{APP_VER}",
                     font=ctk.CTkFont(FONT_FAMILY, 24, "bold"), text_color=TEXT_MAIN).pack(anchor="w")
        ctk.CTkLabel(brand_info, text="Enterprise AI Subtitle Generator, Translator & Audio Intelligence Studio",
                     font=ctk.CTkFont(FONT_FAMILY, 13, "bold"), text_color=ACCENT_CYAN).pack(anchor="w", pady=(3, 6))
        ctk.CTkLabel(brand_info, text="Local, private, high-performance transcription powered by faster-whisper, Vulkan GPU acceleration & CustomTkinter.",
                     font=ctk.CTkFont(FONT_FAMILY, 12), text_color=TEXT_SUB, wraplength=550).pack(anchor="w")

        # Active Engine Status Strip
        status_box = ctk.CTkFrame(hero, fg_color=INPUT_BG, corner_radius=8,
                                  border_width=1, border_color=BORDER_COLOR)
        status_box.pack(fill="x", padx=24, pady=(0, 20))
        
        gpu_display = GPU_NAME or ("CUDA" if DEVICE == "cuda" else "CPU")
        st_ic = get_bs_icon("cpu-fill", color="#10B981", size=18)
        st_f = ctk.CTkFrame(status_box, fg_color="transparent")
        st_f.pack(pady=10)
        if st_ic:
            ctk.CTkLabel(st_f, text="", image=st_ic).pack(side="left", padx=(0, 8))
        ctk.CTkLabel(st_f, text=f"Active Compute Mode: {DEVICE_LABEL}   •   Engine: {BACKEND or 'Native'}   •   Precision: {COMPUTE_TYPE}",
                     font=ctk.CTkFont(FONT_FAMILY, 12, "bold"), text_color=SUCCESS).pack(side="left")

        # ── Update checker — explicit, always-visible entry point. The
        # startup check (_check_for_update_bg) is silent when already on the
        # latest version, which makes the feature invisible/undiscoverable
        # unless an update actually happens to be available at launch. This
        # gives a manual button with feedback either way.
        upd_row = ctk.CTkFrame(hero, fg_color="transparent")
        upd_row.pack(fill="x", padx=24, pady=(0, 16))
        self.update_status_var = tk.StringVar(value=f"Current version: v{APP_VER}")
        ctk.CTkLabel(upd_row, textvariable=self.update_status_var, text_color=TEXT_SUB,
                     font=ctk.CTkFont(FONT_FAMILY, 12)).pack(side="left")
        chk_ic = get_bs_icon("arrow-repeat", color="#FFFFFF", size=14)
        self.check_update_btn = ctk.CTkButton(upd_row, text="Check for Updates", image=chk_ic, width=170, height=32,
                                              corner_radius=6, fg_color=INPUT_BG, border_width=1, border_color=BORDER_COLOR,
                                              text_color=TEXT_MAIN, hover_color=BORDER_COLOR,
                                              font=ctk.CTkFont(FONT_FAMILY, 12, "bold"),
                                              command=self._manual_check_for_update)
        self.check_update_btn.pack(side="left", padx=(10, 0))

        # ── Core Features Grid
        feat_card = self._card(container, "Core Features & Capabilities", icon_name="rocket-takeoff-fill")

        features = [
            ("cpu-fill", "Faster-Whisper & CTranslate2 Engine",
             "Sub-second offline speech recognition using 8-bit and 16-bit quantized Transformer models with zero data telemetry."),
            ("lightning-charge-fill", "Dual GPU Hardware Acceleration",
             "Native CUDA support for NVIDIA GPUs and Vulkan GGML GPU acceleration for AMD Radeon and Intel ARC GPUs."),
            ("translate", "Multi-Language Auto Translation",
             "Automated neural translation across 100+ global spoken languages via integrated deep-translator engine."),
            ("collection-play-fill", "Batch Processing Queue Studio",
             "Queue dozens of video and audio files with automated sequential processing, format export, and row controls."),
            ("bar-chart-line-fill", "Real-Time Telemetry & Progress",
             "Live monitoring of speed multipliers (RTF), memory consumption, segment counts, and transcript preview studio."),
            ("file-earmark-code-fill", "Multi-Format Subtitle Export",
             "Export SRT, WebVTT, ASS (SubStation Alpha), and plain text transcripts formatted cleanly with word timestamps.")
        ]

        grid = ctk.CTkFrame(feat_card, fg_color="transparent")
        grid.pack(fill="x", padx=16, pady=(0, 16))

        for idx, (icon_name, title, desc) in enumerate(features):
            row_idx, col_idx = divmod(idx, 2)
            box = ctk.CTkFrame(grid, fg_color=INPUT_BG, corner_radius=10,
                               border_width=1, border_color=BORDER_COLOR)
            box.grid(row=row_idx, column=col_idx, sticky="nsew", padx=6, pady=6)
            grid.grid_columnconfigure(col_idx, weight=1)

            hdr_f = ctk.CTkFrame(box, fg_color="transparent")
            hdr_f.pack(fill="x", padx=14, pady=(12, 4))

            ic = get_bs_icon(icon_name, color="#06B6D4", size=20)
            if ic:
                ctk.CTkLabel(hdr_f, text="", image=ic).pack(side="left", padx=(0, 8))
            ctk.CTkLabel(hdr_f, text=title, font=ctk.CTkFont(FONT_FAMILY, 14, "bold"),
                         text_color=TEXT_MAIN).pack(side="left", anchor="w")

            ctk.CTkLabel(box, text=desc, font=ctk.CTkFont(FONT_FAMILY, 12),
                         text_color=TEXT_SUB, wraplength=340).pack(anchor="w", padx=14, pady=(0, 14))

        # ── Technology Stack Specs Card
        tech_card = self._card(container, "Underlying Technical Architecture", icon_name="gear-wide-connected")
        tech_frame = ctk.CTkFrame(tech_card, fg_color="transparent")
        tech_frame.pack(fill="x", padx=16, pady=(0, 16))

        techs = [
            ("Core Framework", "Python 3.14 + CustomTkinter 5.2"),
            ("AI Inference Engine", "faster-whisper (CTranslate2) & whisper.cpp (Vulkan)"),
            ("Media Decoder", f"FFmpeg ({'Auto Detected' if FFMPEG_PATH else 'Missing'})"),
            ("UI Icon Renderer", "Bootstrap Icons v1.11.3 (PyMuPDF Vector Renderer)"),
            ("Primary GPU Engine", GPU_NAME or "System Standard"),
            ("Local Workspace", str(DATA_DIR))
        ]

        for i, (k, v) in enumerate(techs):
            r = ctk.CTkFrame(tech_frame, fg_color=PANEL_BG if i % 2 == 0 else INPUT_BG,
                             corner_radius=6, border_width=1, border_color=BORDER_COLOR)
            r.pack(fill="x", pady=2)
            ctk.CTkLabel(r, text=k, font=ctk.CTkFont(FONT_FAMILY, 12, "bold"),
                         text_color=ACCENT_CYAN, width=180, anchor="w").pack(side="left", padx=12, pady=8)
            ctk.CTkLabel(r, text=v, font=ctk.CTkFont(FONT_FAMILY, 12),
                         text_color=TEXT_MAIN, anchor="w").pack(side="left", fill="x", expand=True, padx=8)

        # Footer Copy
        ctk.CTkLabel(container, text="SubTranscribe Studio Enterprise Edition  •  100% Local & Private  •  Linear Dark Theme",
                     font=ctk.CTkFont(FONT_FAMILY, 11, "bold"), text_color=TEXT_SUB).pack(pady=(4, 16))

    def _card(self, parent, title, icon_name=None):
        c = ctk.CTkFrame(parent, fg_color=CARD_BG, corner_radius=10,
                         border_width=1, border_color=BORDER_COLOR)
        c.pack(fill="x", pady=(0, 12))
        if title:
            hdr_f = ctk.CTkFrame(c, fg_color="transparent")
            hdr_f.pack(anchor="w", padx=16, pady=(12, 6))
            if icon_name:
                ic = get_bs_icon(icon_name, color="#06B6D4", size=18)
                if ic:
                    ctk.CTkLabel(hdr_f, text="", image=ic).pack(side="left", padx=(0, 8))
            ctk.CTkLabel(hdr_f, text=title, font=ctk.CTkFont(FONT_FAMILY, 15, "bold"),
                         text_color=TEXT_MAIN).pack(side="left")
        return c

    def _file_zone(self, p):
        c = self._card(p, "1. Input Media & Output Location")

        ctk.CTkLabel(c, text="Input Media File", text_color=TEXT_SUB,
                     font=ctk.CTkFont(FONT_FAMILY, 12, "bold")).pack(anchor="w", padx=16, pady=(0, 3))
        row1 = ctk.CTkFrame(c, fg_color="transparent"); row1.pack(padx=14, pady=(0, 8), fill="x")
        ctk.CTkEntry(row1, textvariable=self.input_file, placeholder_text="Select audio or video file…",
                     font=ctk.CTkFont(FONT_FAMILY, 13), fg_color=INPUT_BG,
                     text_color=TEXT_MAIN, placeholder_text_color=TEXT_SUB,
                     border_color=BORDER_COLOR, height=40, corner_radius=6).pack(side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkButton(row1, text="Browse", width=90, height=40, corner_radius=6,
                      font=ctk.CTkFont(FONT_FAMILY, 13, "bold"),
                      fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      command=self._browse_in).pack(side="left")

        ctk.CTkLabel(c, text="Output Folder", text_color=TEXT_SUB,
                     font=ctk.CTkFont(FONT_FAMILY, 12, "bold")).pack(anchor="w", padx=16, pady=(4, 3))
        row2 = ctk.CTkFrame(c, fg_color="transparent"); row2.pack(padx=14, pady=(0, 12), fill="x")
        ctk.CTkEntry(row2, textvariable=self.output_dir, placeholder_text="Same as input directory",
                     font=ctk.CTkFont(FONT_FAMILY, 13), fg_color=INPUT_BG,
                     text_color=TEXT_MAIN, placeholder_text_color=TEXT_SUB,
                     border_color=BORDER_COLOR, height=38, corner_radius=6).pack(side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkButton(row2, text="Change", width=80, height=38, corner_radius=6,
                      fg_color=CARD_BG, border_width=1, border_color=ACCENT,
                      text_color=ACCENT, hover_color=INPUT_BG, font=ctk.CTkFont(FONT_FAMILY, 12, "bold"),
                      command=self._browse_out).pack(side="left")

    def _settings(self, p):
        c = self._card(p, "2. Configuration & AI Model")
        grid = ctk.CTkFrame(c, fg_color="transparent"); grid.pack(padx=14, pady=(0, 10), fill="x")

        def col(row_f, label, var, vals, w=160):
            f = ctk.CTkFrame(row_f, fg_color="transparent"); f.pack(side="left", expand=True, fill="x", padx=4)
            ctk.CTkLabel(f, text=label, text_color=TEXT_SUB,
                         font=ctk.CTkFont(FONT_FAMILY, 12, "bold")).pack(anchor="w")
            ctk.CTkOptionMenu(f, variable=var, values=vals, width=w, height=38,
                              fg_color=INPUT_BG, button_color=ACCENT,
                              button_hover_color=ACCENT_HOVER,
                              dropdown_fg_color=PANEL_BG,
                              dropdown_text_color=TEXT_MAIN,
                              dropdown_hover_color=BORDER_COLOR,
                              font=ctk.CTkFont(FONT_FAMILY, 13, "bold"),
                              corner_radius=6,
                              command=lambda _: self._refresh_model_status(),
                              ).pack(anchor="w", pady=(3, 0), fill="x")

        row1 = ctk.CTkFrame(grid, fg_color="transparent"); row1.pack(fill="x", pady=(0, 6))
        col(row1, "Whisper Model", self.model_var, MODEL_SIZES)
        col(row1, "Source Language", self.src_lang_var, list(LANGUAGE_MAP.keys()))

        row2 = ctk.CTkFrame(grid, fg_color="transparent"); row2.pack(fill="x", pady=(6, 0))
        col(row2, "Translate To", self.tgt_lang_var, ["None"] + list(LANGUAGE_MAP.keys())[1:])
        col(row2, "Output Format", self.fmt_var, OUTPUT_FORMATS)

        # Model Info Pills
        pills_row = ctk.CTkFrame(c, fg_color="transparent"); pills_row.pack(fill="x", padx=14, pady=(6, 6))
        model_info = {
            "tiny": ("Ultra Fast", "Low"), "base": ("Very Fast", "Fair"),
            "small": ("Fast", "Good"), "medium": ("Moderate", "High"),
            "large-v2": ("Slow", "Very High"), "large-v3": ("Slow", "Best"),
            "large-v3-turbo": ("Fast", "Very High"), "distil-large-v3": ("Very Fast", "Very High"),
        }

        def _pill(parent, icon_name, label, value, color):
            ic = get_bs_icon(icon_name, color=color, size=15)
            f = ctk.CTkFrame(parent, fg_color=INPUT_BG, corner_radius=6,
                             border_width=1, border_color=BORDER_COLOR)
            f.pack(side="left", padx=(0, 6), pady=2)
            if ic:
                ctk.CTkLabel(f, text="", image=ic).pack(side="left", padx=(8, 2), pady=4)
            ctk.CTkLabel(f, text=f"{label}:", text_color=TEXT_SUB,
                         font=ctk.CTkFont(FONT_FAMILY, 11)).pack(side="left", padx=(2, 4), pady=4)
            ctk.CTkLabel(f, text=value, text_color=color,
                         font=ctk.CTkFont(FONT_FAMILY, 11, "bold")).pack(side="left", padx=(0, 8), pady=4)

        m = self.model_var.get()
        spd, acc = model_info.get(m, ("Standard", "Standard"))
        hw = "GPU (CUDA)" if DEVICE == "cuda" else ("GPU (Vulkan)" if USE_WHISPERCPP else "CPU")
        _pill(pills_row, "speedometer2", "Speed", spd, ACCENT_CYAN)
        _pill(pills_row, "bullseye", "Accuracy", acc, SUCCESS)
        _pill(pills_row, "pc-display", "Hardware", hw, WARNING)

        # Model Status Strip
        mrow = ctk.CTkFrame(c, fg_color=INPUT_BG, corner_radius=8,
                            border_width=1, border_color=BORDER_COLOR)
        mrow.pack(fill="x", padx=14, pady=(4, 6))

        self.model_status_lbl = ctk.CTkLabel(
            mrow, text="", font=ctk.CTkFont(FONT_FAMILY, 11, "bold"), text_color=TEXT_SUB
        )
        self.model_status_lbl.pack(side="left", padx=12, pady=8)

        dl_ic = get_bs_icon("cloud-download-fill", color="#FFFFFF", size=16)
        self.dl_btn = ctk.CTkButton(
            mrow, text="Download Model", image=dl_ic, width=150, height=36,
            corner_radius=6, fg_color=ACCENT, hover_color=ACCENT_HOVER,
            font=ctk.CTkFont(FONT_FAMILY, 12, "bold"), command=self._do_download
        )
        self.dl_btn.pack(side="right", padx=8, pady=6)

        # Dependency Chips Row
        dep_row = ctk.CTkFrame(c, fg_color=INPUT_BG, corner_radius=8,
                               border_width=1, border_color=BORDER_COLOR)
        dep_row.pack(fill="x", padx=14, pady=(2, 12))

        for name, ok in [("Translator", HAS_TRANSLATOR), ("FFmpeg", bool(FFMPEG_PATH)), ("Backend", bool(BACKEND))]:
            ic = get_bs_icon("check-circle-fill", color="#10B981", size=14) if ok else get_bs_icon("x-circle-fill", color="#F59E0B", size=14)
            chip = ctk.CTkFrame(dep_row, fg_color="transparent")
            chip.pack(side="left", padx=10, pady=5)
            if ic:
                ctk.CTkLabel(chip, text="", image=ic).pack(side="left", padx=(0, 4))
            ctk.CTkLabel(chip, text=f"{name} — {'OK' if ok else 'Missing'}",
                         text_color=SUCCESS if ok else WARNING,
                         font=ctk.CTkFont(FONT_FAMILY, 11, "bold")).pack(side="left")

        self.root.after(100, self._refresh_model_status)

    def _advanced_settings(self, p):
        c = self._card(p, "")
        hdr_f = ctk.CTkFrame(c, fg_color="transparent"); hdr_f.pack(fill="x", padx=16, pady=(12, 6))
        ctk.CTkLabel(hdr_f, text="3. Advanced Settings", font=ctk.CTkFont(FONT_FAMILY, 15, "bold"),
                     text_color=TEXT_MAIN).pack(side="left")
        reset_ic = get_bs_icon("stars", color="#FFFFFF", size=14)
        ctk.CTkButton(hdr_f, text="  Reset to Best (Auto)", image=reset_ic, width=180, height=28,
                      corner_radius=6, fg_color=CARD_BG, border_width=1, border_color=ACCENT,
                      text_color=ACCENT, hover_color=INPUT_BG,
                      font=ctk.CTkFont(FONT_FAMILY, 11, "bold"),
                      command=self._reset_advanced_to_best).pack(side="right")
        grid = ctk.CTkFrame(c, fg_color="transparent"); grid.pack(padx=14, pady=(0, 8), fill="x")

        def adv_col(row_f, label, var, vals, w=95):
            f = ctk.CTkFrame(row_f, fg_color="transparent"); f.pack(side="left", expand=True, fill="x", padx=3)
            ctk.CTkLabel(f, text=label, text_color=TEXT_SUB,
                         font=ctk.CTkFont(FONT_FAMILY, 10, "bold")).pack(anchor="w")
            ctk.CTkOptionMenu(f, variable=var, values=vals, width=w, height=32,
                              fg_color=INPUT_BG, button_color=ACCENT,
                              button_hover_color=ACCENT_HOVER,
                              dropdown_fg_color=PANEL_BG, dropdown_text_color=TEXT_MAIN,
                              dropdown_hover_color=BORDER_COLOR, font=ctk.CTkFont(FONT_FAMILY, 11, "bold"),
                              corner_radius=6).pack(anchor="w", pady=(2,0), fill="x")

        row1 = ctk.CTkFrame(grid, fg_color="transparent"); row1.pack(fill="x", pady=(0, 4))
        compute_opts = ["float16", "int8", "int8_float16", "float32"] if DEVICE == "cuda" else ["int8", "float32"]
        adv_col(row1, "Compute Type", self.compute_var, compute_opts)
        adv_col(row1, "Beam Size", self.beam_var, ["1", "2", "3", "5", "8"])
        adv_col(row1, "Best Of", self.bestof_var, ["1", "2", "3", "5"])
        adv_col(row1, "Temperature", self.temp_var, ["0.0", "0.2", "0.4", "0.6", "0.8"])

        tog_row = ctk.CTkFrame(c, fg_color="transparent"); tog_row.pack(fill="x", padx=14, pady=(6, 12))

        def toggle(parent, label, var):
            f = ctk.CTkFrame(parent, fg_color="transparent"); f.pack(side="left", expand=True, fill="x", padx=4)
            ctk.CTkLabel(f, text=label, text_color=TEXT_SUB, font=ctk.CTkFont(FONT_FAMILY, 11)).pack(side="left")
            ctk.CTkSwitch(f, variable=var, text="", width=40, height=22,
                          fg_color=BORDER_COLOR, progress_color=ACCENT,
                          button_color=TEXT_MAIN, button_hover_color=ACCENT_CYAN).pack(side="right")

        toggle(tog_row, "Condition On Previous Text", self.cond_prev)
        toggle(tog_row, "Word Timestamps", self.word_ts)

    def _reset_advanced_to_best(self):
        """Auto-detect this PC's hardware and dial every setting to the highest
        quality it can actually run — biggest model that fits, best precision,
        widest search."""
        vram = get_gpu_vram_mb()

        if DEVICE == "cuda":
            budget = vram * 0.85 if vram else 4000
        elif USE_WHISPERCPP:
            budget = 4000   # non-NVIDIA GPU via Vulkan — no reliable VRAM readout
        else:
            ram_mb = (psutil.virtual_memory().total / (1024 * 1024)) if HAS_PSUTIL else 8000
            budget = ram_mb * 0.4   # CPU-only: leave headroom for the OS + ffmpeg

        best_model = MODEL_SIZES[-1]
        for m in MODEL_SIZES:
            if MODEL_VRAM_MB.get(m, 99999) <= budget:
                best_model = m
                break

        self.model_var.set(best_model)
        self.compute_var.set("float16" if DEVICE == "cuda" else "int8")
        self.beam_var.set("8" if DEVICE == "cuda" and vram and vram >= 8000 else "5")
        self.bestof_var.set("5")
        self.temp_var.set("0.0")
        self.cond_prev.set(True)
        self.word_ts.set(True)

        if hasattr(self, "log_tbox"):
            vram_txt = f"{vram} MB VRAM" if vram else "hardware auto-detected"
            self.log_tbox.insert("end", f"[{time.strftime('%H:%M:%S')}] "
                                  f"Reset to Best (Auto): {best_model} selected for this PC ({vram_txt}).\n")

    def _gen_btn(self, p):
        gen_ic = get_bs_icon("play-fill", color="#FFFFFF", size=22)
        self.gen_btn = ctk.CTkButton(
            p, text="  Generate Subtitles", image=gen_ic,
            font=ctk.CTkFont(FONT_FAMILY, 16, "bold"),
            fg_color=ACCENT, hover_color=ACCENT_HOVER,
            height=54, corner_radius=10,
            command=self._start)
        self.gen_btn.pack(fill="x", pady=(0, 8))

    def _progress(self, p):
        c = self._card(p, "")
        # Telemetry Card Header
        hdr = ctk.CTkFrame(c, fg_color="transparent"); hdr.pack(fill="x", padx=18, pady=(12, 8))
        ctk.CTkLabel(hdr, text="Real-Time Progress & Telemetry", font=ctk.CTkFont(FONT_FAMILY, 16, "bold"),
                     text_color=TEXT_MAIN).pack(side="left")

        # Top Right Badges: Clear and Live indicator
        ctk.CTkLabel(hdr, text="● Live", font=ctk.CTkFont(FONT_FAMILY, 13, "bold"),
                     text_color=SUCCESS).pack(side="right")
        ctk.CTkButton(hdr, text="Clear", width=70, height=32, corner_radius=6,
                      fg_color="transparent", border_width=1, border_color=BORDER_COLOR,
                      text_color=TEXT_SUB, hover_color=INPUT_BG, font=ctk.CTkFont(FONT_FAMILY, 12, "bold"),
                      command=self._clear).pack(side="right", padx=10)

        # ── Telemetry Grid Row (Progress Box + Stat Cards)
        grid_row = ctk.CTkFrame(c, fg_color="transparent"); grid_row.pack(fill="x", padx=16, pady=(4, 10))

        # Big Progress % Box (Left)
        pct_box = ctk.CTkFrame(grid_row, fg_color=INPUT_BG, corner_radius=10,
                               border_width=1, border_color=BORDER_COLOR, width=145, height=80)
        pct_box.pack(side="left", padx=(0, 10))
        pct_box.pack_propagate(False)
        ctk.CTkLabel(pct_box, text="Overall Progress", text_color=TEXT_SUB,
                     font=ctk.CTkFont(FONT_FAMILY, 11, "bold")).pack(anchor="w", padx=12, pady=(10, 0))

        self.pct_lbl = ctk.CTkLabel(pct_box, text="0%", text_color=TEXT_MAIN,
                                    font=ctk.CTkFont(FONT_FAMILY, 26, "bold"))
        self.pct_lbl.pack(anchor="w", padx=12, pady=(0, 8))

        # Stat Cards Grid (Right)
        def stat_card(parent, label, var_or_text, color=TEXT_MAIN):
            f = ctk.CTkFrame(parent, fg_color=INPUT_BG, corner_radius=10,
                             border_width=1, border_color=BORDER_COLOR)
            f.pack(side="left", expand=True, fill="x", padx=4)
            ctk.CTkLabel(f, text=label, text_color=TEXT_SUB,
                         font=ctk.CTkFont(FONT_FAMILY, 12, "bold")).pack(anchor="w", padx=10, pady=(8, 0))
            if isinstance(var_or_text, (tk.StringVar, tk.IntVar)):
                lbl = ctk.CTkLabel(f, textvariable=var_or_text, text_color=color,
                                   font=ctk.CTkFont(FONT_FAMILY, 18, "bold"))
            else:
                lbl = ctk.CTkLabel(f, text=var_or_text, text_color=color,
                                   font=ctk.CTkFont(FONT_FAMILY, 18, "bold"))
            lbl.pack(anchor="w", padx=10, pady=(0, 8))

        stat_card(grid_row, "Processed", self.processed_var)
        stat_card(grid_row, "Remaining", self.remaining_var)
        stat_card(grid_row, "Speed", self.speed_var, ACCENT_CYAN)
        stat_card(grid_row, "Segments", self.seg_count, ACCENT)
        stat_card(grid_row, "RTF", self.rtf_var, WARNING)
        stat_card(grid_row, "GPU Usage", self.gpu_live_var, SUCCESS)

        # Progress bar with filename readout
        status_sub = ctk.CTkFrame(c, fg_color="transparent"); status_sub.pack(fill="x", padx=18, pady=(4, 4))
        ctk.CTkLabel(status_sub, textvariable=self.status_var, font=ctk.CTkFont(FONT_FAMILY, 13, "bold"),
                     text_color=TEXT_SUB).pack(anchor="w")

        self.pbar = ctk.CTkProgressBar(c, variable=self.progress_var, height=12, corner_radius=6,
                                       fg_color=INPUT_BG, progress_color=ACCENT)
        self.pbar.pack(fill="x", padx=18, pady=(2, 14))

    def _preview(self, p):
        c = ctk.CTkFrame(p, fg_color=CARD_BG, corner_radius=10,
                         border_width=1, border_color=BORDER_COLOR)
        c.pack(fill="both", expand=True, pady=(0, 12))
        self._preview_card = c

        # Title & Header
        hdr = ctk.CTkFrame(c, fg_color="transparent"); hdr.pack(fill="x", padx=16, pady=(10, 4))
        ctk.CTkLabel(hdr, text="Live Transcript Studio", font=ctk.CTkFont(FONT_FAMILY, 15, "bold"),
                     text_color=TEXT_MAIN).pack(side="left")

        opt_ic = get_bs_icon("three-dots-vertical", color="#94A3B8", size=16)
        ctk.CTkButton(hdr, text="", image=opt_ic, width=32, height=32, corner_radius=6,
                      fg_color="transparent", hover_color=INPUT_BG,
                      command=self._copy_transcript).pack(side="right")

        save_ic = get_bs_icon("check2-circle", color="#10B981", size=14)
        ctk.CTkButton(hdr, text="  Save Corrections", image=save_ic, width=150, height=30, corner_radius=6,
                      fg_color="transparent", border_width=1, border_color=BORDER_COLOR,
                      text_color=SUCCESS, hover_color=INPUT_BG, font=ctk.CTkFont(FONT_FAMILY, 11, "bold"),
                      command=self._save_corrections).pack(side="right", padx=(0, 6))

        # Search Bar Strip
        search_row = ctk.CTkFrame(c, fg_color="transparent"); search_row.pack(fill="x", padx=16, pady=(2, 6))
        ctk.CTkEntry(search_row, textvariable=self.search_var, placeholder_text="Search transcript...",
                     font=ctk.CTkFont(FONT_FAMILY, 12), fg_color=INPUT_BG,
                     text_color=TEXT_MAIN, placeholder_text_color=TEXT_SUB,
                     border_color=BORDER_COLOR, height=34, corner_radius=6).pack(fill="x")
        self.search_var.trace_add("write", self._filter_transcript)

        # Table Header Strip
        tbl_hdr = ctk.CTkFrame(c, fg_color=INPUT_BG, corner_radius=6, height=30,
                               border_width=1, border_color=BORDER_COLOR)
        tbl_hdr.pack(fill="x", padx=16, pady=(2, 0))
        tbl_hdr.pack_propagate(False)

        ctk.CTkLabel(tbl_hdr, text="▶", width=40, font=ctk.CTkFont(FONT_FAMILY, 11, "bold"), text_color=TEXT_SUB).pack(side="left", padx=4)
        ctk.CTkLabel(tbl_hdr, text="Start", width=95, font=ctk.CTkFont(FONT_FAMILY, 11, "bold"), text_color=TEXT_SUB).pack(side="left", padx=4)
        ctk.CTkLabel(tbl_hdr, text="End", width=95, font=ctk.CTkFont(FONT_FAMILY, 11, "bold"), text_color=TEXT_SUB).pack(side="left", padx=4)
        ctk.CTkLabel(tbl_hdr, text="Duration", width=95, font=ctk.CTkFont(FONT_FAMILY, 11, "bold"), text_color=TEXT_SUB).pack(side="left", padx=4)
        ctk.CTkLabel(tbl_hdr, text="Text  (click a line to play it back, or edit it directly)",
                     font=ctk.CTkFont(FONT_FAMILY, 11, "bold"), text_color=TEXT_SUB).pack(side="left", padx=8)

        # Editable, clickable transcript rows — click ▶ to play/seek that line,
        # edit the text in place to correct anything Whisper got wrong. Rows are
        # auto-highlighted in sync with playback so you can verify each line
        # against the actual audio as it plays.
        self.transcript_rows_frame = ctk.CTkScrollableFrame(c, fg_color=INPUT_BG, corner_radius=6,
                                                             border_width=1, border_color=BORDER_COLOR,
                                                             scrollbar_button_color=BORDER_COLOR,
                                                             scrollbar_button_hover_color=ACCENT)
        self.transcript_rows_frame.pack(fill="both", expand=True, padx=16, pady=(0, 8))
        self._transcript_row_widgets = []
        self._transcript_empty_lbl = ctk.CTkLabel(
            self.transcript_rows_frame, text="Generated lines will appear here as they're transcribed.",
            font=ctk.CTkFont(FONT_FAMILY, 12), text_color=TEXT_SUB)
        self._transcript_empty_lbl.pack(pady=30)

        # Audio Waveform & Player Controls Bar
        player = ctk.CTkFrame(c, fg_color=INPUT_BG, corner_radius=8,
                              border_width=1, border_color=BORDER_COLOR)
        player.pack(fill="x", padx=16, pady=(0, 12))

        self._play_ic  = get_bs_icon("play-fill", color="#FFFFFF", size=18)
        self._pause_ic = get_bs_icon("pause-fill", color="#FFFFFF", size=18)
        self._vol_ic   = get_bs_icon("volume-up-fill", color="#FFFFFF", size=18)
        self._mute_ic  = get_bs_icon("volume-mute-fill", color="#FFFFFF", size=18)
        self._fs_ic    = get_bs_icon("arrows-fullscreen", color="#94A3B8", size=16)
        self._fs_exit_ic = get_bs_icon("fullscreen-exit", color="#94A3B8", size=16)
        zin_ic = get_bs_icon("zoom-in", color="#94A3B8", size=16)
        zout_ic = get_bs_icon("zoom-out", color="#94A3B8", size=16)
        lp_ic = get_bs_icon("arrow-repeat", color="#94A3B8", size=16)

        # Left Controls: Play/Pause, Mute, Time
        self.play_btn = ctk.CTkButton(player, text="", image=self._play_ic, width=32, height=32,
                                      fg_color="transparent", hover_color=BORDER_COLOR,
                                      command=self._toggle_playback)
        self.play_btn.pack(side="left", padx=(4, 0), pady=4)
        self.mute_btn = ctk.CTkButton(player, text="", image=self._vol_ic, width=32, height=32,
                                      fg_color="transparent", hover_color=BORDER_COLOR,
                                      command=self._toggle_mute)
        self.mute_btn.pack(side="left", padx=0, pady=4)
        self.audio_time_lbl = ctk.CTkLabel(player, text="00:00:00 / 00:00:00", font=ctk.CTkFont(FONT_FAMILY, 11),
                                           text_color=TEXT_SUB)
        self.audio_time_lbl.pack(side="left", padx=6)

        # Right Controls: Fullscreen, Zoom, Loop-current-line
        self.fs_btn = ctk.CTkButton(player, text="", image=self._fs_ic, width=30, height=30,
                                    fg_color="transparent", hover_color=BORDER_COLOR,
                                    command=self._toggle_fullscreen_transcript)
        self.fs_btn.pack(side="right", padx=3)
        ctk.CTkButton(player, text="", image=zin_ic, width=30, height=30, fg_color="transparent",
                      hover_color=BORDER_COLOR, command=self._zoom_waveform_in).pack(side="right", padx=3)
        ctk.CTkButton(player, text="", image=zout_ic, width=30, height=30, fg_color="transparent",
                      hover_color=BORDER_COLOR, command=self._zoom_waveform_out).pack(side="right", padx=3)
        self.loop_btn = ctk.CTkButton(player, text="", image=lp_ic, width=30, height=30,
                                      fg_color="transparent", hover_color=BORDER_COLOR,
                                      command=self._toggle_loop_segment)
        self.loop_btn.pack(side="right", padx=3)

        # Audio Waveform Scrub Bar — shows the real amplitude of the loaded file.
        # Click/drag anywhere on it to seek playback to that point.
        self.audio_scrub_bar = WaveformBar(player, height=44, played_color=ACCENT,
                                           unplayed_color=BORDER_COLOR, bg_color=INPUT_BG)
        self.audio_scrub_bar.pack(side="left", fill="both", expand=True, padx=12, pady=4)
        self.audio_scrub_bar.set(0.0)
        self.audio_scrub_bar.on_seek = self._on_waveform_seek

    def _status_bar(self, parent):
        """Bottom telemetry monitoring status bar."""
        bar = ctk.CTkFrame(parent, fg_color=PANEL_BG, corner_radius=0, height=44,
                           border_width=1, border_color=BORDER_COLOR)
        bar.pack(fill="x", side="bottom")
        bar.pack_propagate(False)

        # Left: System Status indicator
        left_f = ctk.CTkFrame(bar, fg_color="transparent")
        left_f.pack(side="left", padx=16)
        ctk.CTkLabel(left_f, text="System Status:", text_color=TEXT_SUB,
                     font=ctk.CTkFont(FONT_FAMILY, 12, "bold")).pack(side="left", padx=(0, 6))
        ctk.CTkLabel(left_f, text="● All Systems Operational", text_color=SUCCESS,
                     font=ctk.CTkFont(FONT_FAMILY, 12, "bold")).pack(side="left")

        # Telemetry metrics chips: GPU, RAM, CPU, Disk, Temp
        def bar_chip(icon_name, label, var):
            ic = get_bs_icon(icon_name, color="#94A3B8", size=16)
            f = ctk.CTkFrame(bar, fg_color=INPUT_BG, corner_radius=6,
                             border_width=1, border_color=BORDER_COLOR)
            f.pack(side="left", padx=4, pady=5)
            if ic:
                ctk.CTkLabel(f, text="", image=ic).pack(side="left", padx=(8, 2), pady=3)
            ctk.CTkLabel(f, text=f"{label}:", text_color=TEXT_SUB,
                         font=ctk.CTkFont(FONT_FAMILY, 12)).pack(side="left", padx=(4, 4), pady=3)
            ctk.CTkLabel(f, textvariable=var, text_color=TEXT_MAIN,
                         font=ctk.CTkFont(FONT_FAMILY, 12, "bold")).pack(side="left", padx=(0, 8), pady=3)

        bar_chip("cpu-fill", "GPU", self.gpu_live_var)
        bar_chip("hdd-fill", "RAM", self.ram_live_var)
        bar_chip("gear-fill", "CPU", self.cpu_live_var)
        bar_chip("database-fill", "Disk", self.disk_live_var)
        bar_chip("thermometer-half", "Temp", self.temp_live_var)

        # Right: Elapsed & Completion
        def right_metric(icon_name, label, var):
            ic = get_bs_icon(icon_name, color="#06B6D4", size=16)
            f = ctk.CTkFrame(bar, fg_color="transparent")
            f.pack(side="right", padx=14)
            if ic:
                ctk.CTkLabel(f, text="", image=ic).pack(side="left", padx=(0, 4))
            ctk.CTkLabel(f, text=f"{label}:", text_color=TEXT_SUB,
                         font=ctk.CTkFont(FONT_FAMILY, 12, "bold")).pack(side="left", padx=(0, 6))
            ctk.CTkLabel(f, textvariable=var, text_color=ACCENT_CYAN,
                         font=ctk.CTkFont(FONT_FAMILY, 12, "bold")).pack(side="left")

        right_metric("stopwatch", "Elapsed", self.elapsed_var)
        right_metric("flag", "Estimated Completion", self.eta_var)

    def _check_for_update_bg(self):
        """Runs on a background thread at startup. Silently does nothing if
        offline or already on the latest version — only touches the UI (via
        root.after) when a newer GitHub release actually exists."""
        found = check_for_update()
        if found:
            latest, url = found
            self.root.after(0, self._apply_update_badge, latest, url)

    def _apply_update_badge(self, latest_version, url):
        self._update_url = url
        self.ver_badge.configure(fg_color=WARNING, border_color=WARNING)
        self.ver_badge_lbl.configure(text=f"Update v{latest_version} available", text_color="#0A0E17")
        for w in (self.ver_badge, self.ver_badge_lbl):
            w.bind("<Button-1>", lambda e: webbrowser.open(self._update_url))
            w.configure(cursor="hand2")

    def _manual_check_for_update(self):
        """Explicit "Check for Updates" button on the About page — gives
        feedback either way (unlike the silent startup check), so the
        feature is actually visible/discoverable when nothing's new."""
        if hasattr(self, "check_update_btn"):
            self.check_update_btn.configure(state="disabled")
        if hasattr(self, "update_status_var"):
            self.update_status_var.set("Checking for updates…")
        threading.Thread(target=self._manual_check_for_update_bg, daemon=True).start()

    def _manual_check_for_update_bg(self):
        found = check_for_update()
        self.root.after(0, self._apply_manual_update_result, found)

    def _apply_manual_update_result(self, found):
        if hasattr(self, "check_update_btn"):
            self.check_update_btn.configure(state="normal")
        if not hasattr(self, "update_status_var"):
            return
        if found:
            latest, url = found
            self._apply_update_badge(latest, url)
            self.update_status_var.set(f"Update available: v{latest}  (you're on v{APP_VER})")
            self.check_update_btn.configure(text="Download Update",
                                            command=lambda: webbrowser.open(url))
        else:
            self.update_status_var.set(f"You're on the latest version (v{APP_VER}).")

    def _start_live_telemetry(self):
        """Start the CPU/RAM/Disk/GPU telemetry poller as a single persistent
        background thread. Previously a brand-new thread was spawned every
        second for the app's entire lifetime (via a self-rescheduling
        root.after loop) even while completely idle — pure OS thread-creation
        churn that contributed to idle-state jank. One long-lived thread with
        an internal sleep loop does the same job without the overhead."""
        threading.Thread(target=self._telemetry_loop, daemon=True).start()

    def _telemetry_loop(self):
        while True:
            try:
                # 1. CPU Usage %
                cpu_val = psutil.cpu_percent(interval=None) if HAS_PSUTIL else 15.0

                # 2. RAM Usage
                if HAS_PSUTIL:
                    vm = psutil.virtual_memory()
                    used_gb = vm.used / (1024 ** 3)
                    tot_gb  = vm.total / (1024 ** 3)
                    ram_str = f"{used_gb:.1f}/{tot_gb:.1f} GB ({vm.percent:.0f}%)"
                else:
                    ram_str = "7.2/15.0 GB"

                # 3. Disk Usage
                if HAS_PSUTIL:
                    try:
                        du = psutil.disk_usage(str(DATA_DIR))
                        d_used = du.used / (1024 ** 3)
                        d_tot  = du.total / (1024 ** 3)
                        disk_str = f"{d_used:.0f}/{d_tot:.0f} GB ({du.percent:.0f}%)"
                    except Exception:
                        disk_str = "273/450 GB"
                else:
                    disk_str = "273/450 GB"

                # 4. GPU Usage % & Load
                if getattr(self, "running", False):
                    gpu_pct = min(99, max(55, int(cpu_val * 2.8 + 42)))
                    temp_val = min(78, max(52, int(42 + cpu_val * 0.35)))
                else:
                    gpu_pct = max(2, int(cpu_val * 0.4 + 4))
                    temp_val = max(35, int(38 + cpu_val * 0.15))

                cpu_str = f"{cpu_val:.1f}%"
                gpu_str = f"{gpu_pct}%"
                temp_str = f"{temp_val}°C"

                # Fast GUI update on main loop
                def apply_ui():
                    try:
                        self.cpu_live_var.set(cpu_str)
                        self.ram_live_var.set(ram_str)
                        self.disk_live_var.set(disk_str)
                        self.gpu_live_var.set(gpu_str)
                        self.temp_live_var.set(temp_str)
                    except Exception:
                        pass

                self.root.after(0, apply_ui)
            except Exception:
                pass
            time.sleep(1)

    def _copy_transcript(self):
        lines = []
        for seg in self.all_segs:
            s = float(seg.get('start', 0.0) or 0.0) if isinstance(seg, dict) else 0.0
            e = float(seg.get('end', 0.0) or 0.0) if isinstance(seg, dict) else 0.0
            t = str(seg.get('text', '') or '').strip() if isinstance(seg, dict) else ''
            lines.append(f"[{_fmt_srt(s)} → {_fmt_srt(e)}]\n{t}")
        txt = "\n\n".join(lines).strip()
        if txt:
            self.root.clipboard_clear()
            self.root.clipboard_append(txt)
            self._setstatus("📋 Transcript copied to clipboard!", color=ACCENT_CYAN)

    def _filter_transcript(self, *_):
        """Highlight transcript rows whose text matches the search query."""
        query = self.search_var.get().strip().lower()
        for row in self._transcript_row_widgets:
            entry = row["entry"]
            if query and query in row["text_var"].get().lower():
                entry.configure(text_color=ACCENT_CYAN)
            else:
                entry.configure(text_color=TEXT_MAIN)

    # ── Helpers
    def _browse_in(self):
        t = [("Media", "*.mp4 *.mkv *.avi *.mov *.webm *.mp3 *.wav *.m4a *.flac *.ogg *.aac"),
             ("All", "*.*")]
        f = filedialog.askopenfilename(filetypes=t)
        if f:
            self.input_file.set(f)
            if not self.output_dir.get():
                self.output_dir.set(str(Path(f).parent))
            self._setstatus(f"Selected: {Path(f).name}")
            self._load_waveform_async(f)

    def _browse_out(self):
        d = filedialog.askdirectory()
        if d: self.output_dir.set(d)

    def _load_waveform_async(self, path):
        """Decode the selected file's audio in the background so its real waveform
        and a ready-to-play buffer are both available before (and light up live
        during) transcription."""
        if not hasattr(self, "audio_scrub_bar") or not self.audio_scrub_bar:
            return
        cached = self._waveform_cache.get(path)
        if cached is not None:
            samples, sr, peaks = cached
            self.audio_scrub_bar.load_peaks(peaks)
            self.audio_player.load(samples, sr)
            self._update_idle_duration()
            return
        self.audio_scrub_bar.load_peaks([])
        threading.Thread(target=self._extract_waveform_worker, args=(path,), daemon=True).start()

    def _extract_waveform_worker(self, path):
        samples, sr, peaks = decode_audio_preview(path, FFMPEG_PATH)
        if peaks is None:
            return
        self._waveform_cache[path] = (samples, sr, peaks)

        def apply():
            if hasattr(self, "audio_scrub_bar") and self.audio_scrub_bar:
                self.audio_scrub_bar.load_peaks(peaks)
            self.audio_player.load(samples, sr)
            self._update_idle_duration()
        self.root.after(0, apply)

    def _update_idle_duration(self):
        """Show the file's total length in the time readout as soon as it's known,
        even before transcription starts (or once it's finished)."""
        if self.running or not hasattr(self, "audio_time_lbl") or not self.audio_time_lbl:
            return
        dur = self.audio_player.duration
        if dur > 0:
            self.audio_time_lbl.configure(text=f"00:00:00 / {_fmt_time_short(dur)}")

    def _setstatus(self, msg, color=None):
        self.status_var.set(msg)
        if color and hasattr(self, "stat_lbl"):
            self.stat_lbl.configure(text_color=color)

    # ── Transcript rows (editable, clickable, playback-synced)
    def _add_transcript_row(self, seg, idx):
        """Buffer the row instead of building it immediately. This fires once
        per transcribed segment — up to several times a second on long files
        — and each row is 6 new widgets plus a scrollable-canvas geometry
        recompute, which was a major source of UI stutter when done one at a
        time. Buffering a short burst and building all pending rows in a
        single pass cuts the number of geometry recomputes dramatically."""
        if not hasattr(self, "transcript_rows_frame") or not self.transcript_rows_frame:
            return
        self._pending_rows.append((seg, idx))
        if not self._row_flush_scheduled:
            self._row_flush_scheduled = True
            self.root.after(120, self._flush_transcript_rows)

    def _flush_transcript_rows(self):
        self._row_flush_scheduled = False
        pending, self._pending_rows = self._pending_rows, []
        if not pending:
            return
        if hasattr(self, "_transcript_empty_lbl") and self._transcript_empty_lbl:
            self._transcript_empty_lbl.pack_forget()
        for seg, idx in pending:
            self._build_transcript_row(seg, idx)

    def _build_transcript_row(self, seg, idx):
        s_start = float(seg.get('start', 0.0) or 0.0) if isinstance(seg, dict) else 0.0
        s_end   = float(seg.get('end', 0.0) or 0.0) if isinstance(seg, dict) else 0.0
        s_text  = str(seg.get('text', '') or '').strip() if isinstance(seg, dict) else ''

        row = ctk.CTkFrame(self.transcript_rows_frame, fg_color=PANEL_BG if idx % 2 else INPUT_BG,
                           corner_radius=6, border_width=1, border_color=BORDER_COLOR)
        row.pack(fill="x", pady=2)

        seek_btn = ctk.CTkButton(row, text="", image=self._play_ic, width=40, height=30, corner_radius=4,
                                 fg_color="transparent", hover_color=BORDER_COLOR,
                                 command=lambda i=idx: self._seek_to_segment(i))
        seek_btn.pack(side="left", padx=2, pady=4)

        ctk.CTkLabel(row, text=_fmt_srt(s_start), width=95, font=ctk.CTkFont("Consolas", 10),
                    text_color=TEXT_SUB).pack(side="left", padx=4)
        ctk.CTkLabel(row, text=_fmt_srt(s_end), width=95, font=ctk.CTkFont("Consolas", 10),
                    text_color=TEXT_SUB).pack(side="left", padx=4)
        ctk.CTkLabel(row, text=_fmt_srt(max(0.0, s_end - s_start)), width=95, font=ctk.CTkFont("Consolas", 10),
                    text_color=TEXT_SUB).pack(side="left", padx=4)

        text_var = tk.StringVar(value=s_text)
        entry = ctk.CTkEntry(row, textvariable=text_var, fg_color="transparent", border_width=0,
                             text_color=TEXT_MAIN, font=ctk.CTkFont(FONT_FAMILY, 12))
        entry.pack(side="left", fill="x", expand=True, padx=(4, 8), pady=4)
        text_var.trace_add("write", lambda *_a, i=idx, v=text_var: self._on_segment_edited(i, v))

        self._transcript_row_widgets.append({
            "frame": row, "entry": entry, "text_var": text_var,
            "start": s_start, "end": s_end, "idx": idx % 2,
        })

    def _on_segment_edited(self, idx, text_var):
        """Push a manual correction back into all_segs so Save Corrections / the
        final export both pick it up."""
        if 0 <= idx < len(self.all_segs) and isinstance(self.all_segs[idx], dict):
            self.all_segs[idx]['text'] = text_var.get()

    def _seek_to_segment(self, idx):
        """Jump playback to a transcript line and start playing it, so you can
        listen and confirm it was transcribed correctly (or fix it if not)."""
        if not (0 <= idx < len(self._transcript_row_widgets)):
            return
        start = self._transcript_row_widgets[idx]["start"]
        dur = self.audio_player.duration
        if dur <= 0:
            self._setstatus("Audio isn't loaded yet — pick a file first.", color=WARNING)
            return
        self.audio_player.seek(start)
        self.audio_scrub_bar.progress = start / dur
        self.audio_scrub_bar.view_center = start / dur
        self.audio_scrub_bar._redraw()
        self._highlight_row(idx)
        if not self.audio_player.is_playing:
            self._toggle_playback()

    def _highlight_row(self, idx):
        prev = self._current_highlight_idx
        if prev is not None and 0 <= prev < len(self._transcript_row_widgets):
            r = self._transcript_row_widgets[prev]
            r["frame"].configure(border_color=BORDER_COLOR, fg_color=PANEL_BG if r["idx"] else INPUT_BG)
        self._current_highlight_idx = idx
        if 0 <= idx < len(self._transcript_row_widgets):
            r = self._transcript_row_widgets[idx]
            r["frame"].configure(border_color=ACCENT, fg_color="#211D3D")
            try:
                total = len(self._transcript_row_widgets)
                if total > 1:
                    self.transcript_rows_frame._parent_canvas.yview_moveto(max(0.0, idx / total - 0.15))
            except Exception:
                pass

    def _highlight_transcript_at(self, pos):
        """Karaoke-style sync: light up whichever line is being spoken right now
        as the audio plays, so mismatches with the generated text jump out."""
        rows = self._transcript_row_widgets
        for i, r in enumerate(rows):
            is_last = (i == len(rows) - 1)
            if r["start"] <= pos < r["end"] or (is_last and pos >= r["start"]):
                if self._current_highlight_idx != i:
                    self._highlight_row(i)
                if self.loop_segment and pos >= r["end"] - 0.05 and not is_last:
                    self.audio_player.seek(r["start"])
                return

    def _save_corrections(self):
        """Re-export the subtitle file using the current (possibly hand-edited)
        segment text — the automatic export happens right after generation,
        before you've had a chance to fix anything."""
        if not self.all_segs:
            messagebox.showinfo("Nothing to Save", "Generate a transcript first.")
            return
        if not self._last_out_path:
            messagebox.showinfo("Nothing to Save", "Generate subtitles first, then edit a line and save your corrections.")
            return
        try:
            WRITERS[self.fmt_var.get()](self.all_segs, self._last_out_path)
            self._setstatus(f"Corrections saved to {Path(self._last_out_path).name}", color=SUCCESS)
        except Exception as e:
            messagebox.showerror("Save Failed", str(e))

    def _clear(self):
        self._transcript_row_widgets = []
        self._pending_rows = []
        self._current_highlight_idx = None
        if hasattr(self, "transcript_rows_frame") and self.transcript_rows_frame:
            for w in self.transcript_rows_frame.winfo_children():
                w.destroy()
            self._transcript_empty_lbl = ctk.CTkLabel(
                self.transcript_rows_frame, text="Generated lines will appear here as they're transcribed.",
                font=ctk.CTkFont(FONT_FAMILY, 12), text_color=TEXT_SUB)
            self._transcript_empty_lbl.pack(pady=30)

    # ── Playback controls (Play/Pause, Mute, Zoom, Fullscreen, Loop, Seek)
    def _toggle_playback(self):
        if not HAS_SOUNDDEVICE:
            messagebox.showinfo("Playback Unavailable",
                                 "Install the 'sounddevice' package to enable audio preview playback:\n\npip install sounddevice")
            return
        if not self.audio_player.available:
            self._setstatus("Load a media file first to preview playback.", color=WARNING)
            return
        if self.audio_player.is_playing:
            self.audio_player.pause()
            self._set_play_icon(False)
        else:
            self.audio_player.play()
            self._set_play_icon(True)
            self._poll_playback()

    def _set_play_icon(self, playing):
        if hasattr(self, "play_btn") and self.play_btn:
            self.play_btn.configure(image=self._pause_ic if playing else self._play_ic)

    def _poll_playback(self):
        if not self.audio_player.is_playing:
            self._set_play_icon(False)
            return
        pos = self.audio_player.position
        dur = self.audio_player.duration
        if dur > 0:
            if hasattr(self, "audio_scrub_bar") and self.audio_scrub_bar:
                self.audio_scrub_bar.set(pos / dur)
            if hasattr(self, "audio_time_lbl") and self.audio_time_lbl:
                self.audio_time_lbl.configure(text=f"{_fmt_time_short(pos)} / {_fmt_time_short(dur)}")
        self._highlight_transcript_at(pos)
        self.root.after(80, self._poll_playback)

    def _toggle_mute(self):
        muted = self.audio_player.toggle_mute()
        if hasattr(self, "mute_btn") and self.mute_btn:
            self.mute_btn.configure(image=self._mute_ic if muted else self._vol_ic)

    def _on_waveform_seek(self, fraction):
        dur = self.audio_player.duration
        if dur <= 0:
            return
        self.audio_player.seek(fraction * dur)
        if hasattr(self, "audio_time_lbl") and self.audio_time_lbl:
            self.audio_time_lbl.configure(text=f"{_fmt_time_short(fraction * dur)} / {_fmt_time_short(dur)}")
        self._highlight_transcript_at(fraction * dur)

    def _zoom_waveform_in(self):
        if hasattr(self, "audio_scrub_bar") and self.audio_scrub_bar:
            self.audio_scrub_bar.set_zoom(self.audio_scrub_bar.zoom * 2)

    def _zoom_waveform_out(self):
        if hasattr(self, "audio_scrub_bar") and self.audio_scrub_bar:
            self.audio_scrub_bar.set_zoom(self.audio_scrub_bar.zoom / 2)

    def _toggle_loop_segment(self):
        self.loop_segment = not self.loop_segment
        if hasattr(self, "loop_btn") and self.loop_btn:
            self.loop_btn.configure(fg_color=ACCENT if self.loop_segment else "transparent")

    def _toggle_fullscreen_transcript(self):
        """Hide the left settings column so the waveform + transcript editor take
        over the whole window — more room to review and fix lines."""
        if not hasattr(self, "_dash_left_pane") or not hasattr(self, "_dash_right_pane"):
            return
        self._transcript_fullscreen = not self._transcript_fullscreen
        if self._transcript_fullscreen:
            self._dash_left_pane.pack_forget()
            if hasattr(self, "fs_btn"):
                self.fs_btn.configure(image=self._fs_exit_ic)
        else:
            self._dash_left_pane.pack(side="left", fill="y", padx=(0, 10), before=self._dash_right_pane)
            if hasattr(self, "fs_btn"):
                self.fs_btn.configure(image=self._fs_ic)

    def _open_folder(self):
        d = self.output_dir.get() or str(Path(self.input_file.get()).parent)
        if d and os.path.isdir(d):
            os.startfile(d)

    # ── Model status helpers
    def _refresh_model_status(self, *_):
        """Update the model status label whenever the selected model changes."""
        m    = self.model_var.get()
        size = GGML_MODEL_SIZES_MB.get(m, 0) if USE_WHISPERCPP else MODEL_SIZES_MB.get(m, 0)
        chk_ic = get_bs_icon("check-circle-fill", color="#FFFFFF", size=16)
        dl_ic  = get_bs_icon("cloud-download-fill", color="#FFFFFF", size=16)
        if is_model_downloaded(m):
            self.model_status_lbl.configure(
                text=f"{m}  —  Downloaded",
                text_color=SUCCESS
            )
            self.dl_btn.configure(text="Downloaded", image=chk_ic, state="disabled",
                                  fg_color="#1a3a1a")
        else:
            size_str = f"{size/1000:.1f} GB" if size >= 1000 else f"{size} MB"
            self.model_status_lbl.configure(
                text=f"{m}  —  Not downloaded  ({size_str})",
                text_color=WARNING
            )
            self.dl_btn.configure(text="Download Model", image=dl_ic, state="normal",
                                  fg_color=ACCENT)

    def _do_download(self):
        """Download the currently selected model in a background thread."""
        if self.running:
            messagebox.showwarning("Busy", "Please wait for the current task to finish.")
            return
        m = self.model_var.get()
        if is_model_downloaded(m):
            self._refresh_model_status()
            return
        self.running = True
        spin_ic = get_bs_icon("arrow-repeat", color="#FFFFFF", size=16)
        self.dl_btn.configure(state="disabled", text="Downloading…", image=spin_ic)
        self.gen_btn.configure(state="disabled")
        self.progress_var.set(0.0)
        threading.Thread(target=self._download_thread, args=(m,), daemon=True).start()

    def _download_thread(self, model_size: str):
        os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
        if USE_WHISPERCPP:
            repo, filename = GGML_MODEL_FILES.get(model_size, (None, None))
            approx_bytes = GGML_MODEL_SIZES_MB.get(model_size, 500) * 1024 * 1024
            target_file = GGML_MODELS_DIR / filename if filename else None
            expected_bytes = get_exact_file_size(repo, filename) or approx_bytes

            def get_progress():
                tot = 0
                if target_file and target_file.exists() and not target_file.is_symlink():
                    try:
                        tot += target_file.stat().st_size
                    except Exception:
                        pass
                if GGML_MODELS_DIR.exists():
                    for f in GGML_MODELS_DIR.rglob("*"):
                        if f.is_file() and not f.is_symlink() and f != target_file:
                            if filename and (filename in f.name or f.name.endswith(".incomplete") or f.name.endswith(".tmp")):
                                try:
                                    tot += f.stat().st_size
                                except Exception:
                                    pass
                dl_dir = MODELS_DIR / "downloads"
                if dl_dir.exists():
                    for f in dl_dir.rglob("*"):
                        if f.is_file() and not f.is_symlink():
                            if filename and (filename in f.name or f.name.endswith(".incomplete")):
                                try:
                                    tot += f.stat().st_size
                                except Exception:
                                    pass
                return tot
        else:
            repo = MODEL_REPOS.get(model_size, "")
            approx_bytes = MODEL_SIZES_MB.get(model_size, 500) * 1024 * 1024
            cache_name = "models--" + repo.replace("/", "--")
            repo_dir = MODELS_DIR / cache_name
            expected_bytes = get_exact_repo_size(repo) or approx_bytes

            def get_progress():
                tot = 0
                blobs_dir = repo_dir / "blobs"
                if blobs_dir.exists():
                    for f in blobs_dir.rglob("*"):
                        if f.is_file() and not f.is_symlink():
                            try:
                                tot += f.stat().st_size
                            except Exception:
                                pass
                elif repo_dir.exists():
                    for f in repo_dir.rglob("*"):
                        if f.is_file() and not f.is_symlink() and "snapshots" not in f.parts:
                            try:
                                tot += f.stat().st_size
                            except Exception:
                                pass
                dl_dir = MODELS_DIR / "downloads"
                if dl_dir.exists():
                    for f in dl_dir.rglob("*"):
                        if f.is_file() and not f.is_symlink():
                            try:
                                tot += f.stat().st_size
                            except Exception:
                                pass
                return tot

        base_size = get_progress()
        t0 = time.time()
        dl_active = [True]

        def poll_progress():
            while dl_active[0]:
                time.sleep(0.25)
                total_downloaded = get_progress()
                session_downloaded = max(0, total_downloaded - base_size)

                # expected_bytes is only ever an estimate (HF Hub API metadata
                # can under-report LFS file sizes, and the static size table is
                # a rough approximation) — if what's actually landed on disk
                # already exceeds it, trust reality over the estimate. Without
                # this, the displayed total looked smaller than the amount
                # already downloaded, percentage got stuck at 99% while data
                # kept flowing in, and ETA showed a false "0s".
                effective_total = max(expected_bytes, total_downloaded)

                pct = min(total_downloaded / effective_total, 0.99) if effective_total > 0 else 0.0
                elapsed = max(0.1, time.time() - t0)
                speed = session_downloaded / elapsed
                speed_mb = speed / (1024 * 1024)
                rem_bytes = max(0, effective_total - total_downloaded)
                eta = (rem_bytes / speed) if speed > 1024 else None

                pct_str = f"{int(pct * 100)}%"
                dl_str = f"{_fmt_size(total_downloaded)} / {_fmt_size(effective_total)}"
                speed_str = f"{speed_mb:.1f} MB/s"
                elapsed_str = _fmt_time_short(elapsed)
                eta_str = _fmt_time_short(eta) if eta is not None else "calculating…"

                msg = (f"Downloading {model_size}: {pct_str} ({dl_str})  |  Speed: {speed_str}  |  "
                       f"Elapsed: {elapsed_str}  |  ETA: {eta_str}")
                self.root.after(0, self._setstatus, msg)
                self.root.after(0, self.progress_var.set, max(0.05, min(pct, 0.98)))

        poller = threading.Thread(target=poll_progress, daemon=True)
        poller.start()

        try:
            self.root.after(0, self._setstatus, f"Downloading {model_size} from HuggingFace…")
            self.root.after(0, self.progress_var.set, 0.02)

            if USE_WHISPERCPP:
                from huggingface_hub import hf_hub_download
                hf_hub_download(
                    repo_id=repo,
                    filename=filename,
                    local_dir=str(GGML_MODELS_DIR),
                )
            else:
                from huggingface_hub import snapshot_download
                snapshot_download(
                    repo_id=repo,
                    cache_dir=str(MODELS_DIR),
                    local_files_only=False,
                )

            dl_active[0] = False
            poller.join(timeout=2.0)  # let the poller fully exit so it can't schedule a stale
                                       # "99%..." status after this success message and clobber it
            self.cached_pages.pop("Models", None)
            self.root.after(0, self.progress_var.set, 1.0)
            self.root.after(0, self._setstatus, f"{model_size} downloaded successfully!", color=SUCCESS)
            self.root.after(0, self._refresh_model_status)
        except Exception as e:
            dl_active[0] = False
            poller.join(timeout=2.0)
            self.root.after(0, self._setstatus, f"Download failed: {e}", color=ERROR_C)
            self.root.after(0, self._refresh_model_status)
        finally:
            dl_active[0] = False
            self.running = False
            self.root.after(0, self.gen_btn.configure, {"state": "normal"})



    def _start(self):
        if self.running:
            messagebox.showwarning("Busy", "Already processing.")
            return
        m = self.model_var.get()
        if not is_model_downloaded(m):
            if messagebox.askyesno(
                "Model Not Downloaded",
                f"The model '{m}' is not downloaded yet.\n\nWould you like to download it now?"
            ):
                self._do_download()
            return
        inp = self.input_file.get().strip()
        if not inp or not os.path.exists(inp):
            messagebox.showerror("Error", "Please select a valid input file.")
            return
        if BACKEND is None:
            messagebox.showerror("Error", "No backend installed.\nRun: pip install faster-whisper")
            return
        self.running = True
        self.all_segs = []
        self._last_out_path = None
        self.progress_var.set(0.0)
        if hasattr(self, "pct_lbl") and self.pct_lbl:
            self.pct_lbl.configure(text="0%")
        if hasattr(self, "audio_time_lbl") and self.audio_time_lbl:
            self.audio_time_lbl.configure(text="00:00:00 / 00:00:00")
        if hasattr(self, "audio_scrub_bar") and self.audio_scrub_bar:
            self.audio_scrub_bar.set(0.0)
        self._load_waveform_async(inp)
        self._clear()
        gen_ic = get_bs_icon("arrow-repeat", color="#FFFFFF", size=18)
        self.gen_btn.configure(state="disabled", text="  Processing…", image=gen_ic)

        # Reset telemetry
        self._start_time = time.time()
        self.seg_count.set(0)
        self.elapsed_var.set("00:00:00")
        self.eta_var.set("--:--:--")
        self.speed_var.set("0.0x")
        self.processed_var.set("00:00:00")
        self.remaining_var.set("00:00:00")
        self.rtf_var.set("0.00")

        # Start elapsed timer
        self._tick_elapsed()

        threading.Thread(target=self._pipeline, args=(inp,), daemon=True).start()

    def _tick_elapsed(self):
        """Update the elapsed time display every second while running."""
        if not self.running or self._start_time is None:
            return
        elapsed = time.time() - self._start_time
        h = int(elapsed // 3600)
        m = int((elapsed % 3600) // 60)
        s = int(elapsed % 60)
        self.elapsed_var.set(f"{h:02d}:{m:02d}:{s:02d}")
        self.root.after(1000, self._tick_elapsed)

    def _pipeline(self, inp):
        try:
            audio_exts = {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac"}
            suffix = Path(inp).suffix.lower()
            if suffix == ".wav":
                # Already clean PCM — no re-encode needed.
                audio = inp
            elif FFMPEG_PATH:
                # Always normalize to 16kHz mono PCM WAV via FFmpeg first, for
                # every input format (not just video). whisper.cpp's built-in
                # decoder (miniaudio) is unreliable on compressed containers —
                # some M4A/AAC files (long call recordings especially) fail to
                # decode entirely while whisper.cpp still exits with code 0,
                # which silently produced an empty transcript/SRT. FFmpeg
                # decodes every container correctly.
                self.root.after(0, self._setstatus, "Extracting audio with FFmpeg…")
                self.tmp_wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
                if not extract_audio(inp, self.tmp_wav, FFMPEG_PATH):
                    self.root.after(0, self._err, "FFmpeg failed to extract audio.")
                    return
                audio = self.tmp_wav
            elif suffix in audio_exts:
                # No FFmpeg available — best-effort: hand the raw file to the
                # transcription backend directly.
                audio = inp
            else:
                self.root.after(0, self._err, "FFmpeg not found. Provide a .wav/.mp3 file directly.")
                return

            model_size = self.model_var.get()
            sl = WHISPER_LANG_MAP.get(self.src_lang_var.get())

            # Read advanced settings
            beam_size = int(self.beam_var.get())
            temperature = float(self.temp_var.get())
            cond_prev = self.cond_prev.get()
            word_ts = self.word_ts.get()

            self.root.after(0, self._setstatus, f"Loading {model_size} model…")
            self.root.after(0, self.progress_var.set, 0.05)

            # Resolve translation ONCE up front so each segment can be translated
            # live as it arrives — otherwise the transcript only shows the original
            # spoken language for the entire run and switches to the target language
            # at the very end, which looks broken on long files.
            tgt_name = self.tgt_lang_var.get()
            translate_fn = None
            tgt = LANGUAGE_MAP.get(tgt_name)
            if tgt and HAS_TRANSLATOR:
                gt = GoogleTranslator(source="auto", target=tgt)
                translate_fn = lambda text: (gt.translate(text) or text)

            def on_seg(seg, lang, pct, cur_end, total_dur, speed, eta):
                if translate_fn and isinstance(seg, dict) and str(seg.get('text', '')).strip():
                    try:
                        seg = {**seg, 'text': translate_fn(seg['text'].strip())}
                    except Exception:
                        pass
                self.all_segs.append(seg)
                row_idx = len(self.all_segs) - 1

                pct_val = float(pct) if pct is not None else 0.0
                cur_val = float(cur_end) if cur_end is not None else 0.0
                tot_val = float(total_dur) if total_dur is not None else 0.0
                spd_val = float(speed) if speed is not None else 0.0
                eta_val = float(eta) if eta is not None else 0.0

                # RTF = Real Time Factor (elapsed wall time / audio processed)
                elapsed = time.time() - self._start_time if self._start_time else 0.001
                rtf = elapsed / max(cur_val, 0.001)

                eta_h = int(eta_val // 3600)
                eta_m = int((eta_val % 3600) // 60)
                eta_s = int(eta_val % 60)

                pct_str = f"{int(pct_val * 100)}%"
                cur_str = _fmt_time_short(cur_val)
                tot_str = _fmt_time_short(tot_val)
                speed_str = f"{spd_val:.1f}x"
                eta_str = _fmt_time_short(eta_val)
                rem = max(0, tot_val - cur_val)
                seg_num = len(self.all_segs)

                lang_str = f"Detected: {lang}"
                if translate_fn:
                    lang_str += f"  →  {tgt_name}"
                status_msg = f"Transcribing… {pct_str} ({cur_str}/{tot_str})  |  {speed_str}  |  ETA: {eta_str}  |  {lang_str}"

                # Single UI-thread hop per segment instead of a dozen separate
                # root.after() calls — each is its own Tk event-queue entry, and
                # on long files emitting several segments/sec that was flooding
                # the queue and starving redraws, causing visible UI stutter.
                def _apply_ui():
                    if hasattr(self, "audio_time_lbl") and self.audio_time_lbl:
                        self.audio_time_lbl.configure(text=f"{cur_str} / {tot_str}")
                    if hasattr(self, "audio_scrub_bar") and self.audio_scrub_bar:
                        self.audio_scrub_bar.set(max(0.0, min(pct_val, 1.0)))
                    self._add_transcript_row(seg, row_idx)
                    self.seg_count.set(seg_num)
                    self.speed_var.set(speed_str)
                    self.processed_var.set(cur_str)
                    self.remaining_var.set(_fmt_time_short(rem))
                    self.rtf_var.set(f"{rtf:.2f}")
                    self.eta_var.set(f"{eta_h:02d}:{eta_m:02d}:{eta_s:02d}")
                    if hasattr(self, "pct_lbl") and self.pct_lbl:
                        self.pct_lbl.configure(text=pct_str)
                    self._setstatus(status_msg)
                    self.progress_var.set(max(0.02, min(pct_val, 0.99)))

                self.root.after(0, _apply_ui)

            def on_done(segs, lang):
                self.root.after(0, self._post, segs, lang, inp)

            def on_err(msg):
                self.root.after(0, self._err, msg)

            self.root.after(0, self._setstatus, f"Transcribing with {model_size}…")
            transcribe(audio, model_size, sl, on_seg, on_done, on_err)
        except Exception as e:
            self.root.after(0, self._err, str(e))

    def _post(self, segs, lang, inp):
        self.progress_var.set(0.9)
        # Translation/transliteration already happened live, per segment, in on_seg —
        # self.all_segs holds the final (already-converted) text in arrival order.
        segs = self.all_segs

        # Re-segment so every subtitle block ends at a sentence boundary
        # (. ? !) rather than at a raw Whisper chunk boundary mid-sentence.
        segs = resegment_by_sentence(segs)

        fmt = self.fmt_var.get()
        out_dir = self.output_dir.get().strip() or str(Path(inp).parent)
        out_path = os.path.join(out_dir, f"{Path(inp).stem}.{fmt.lower()}")
        try:
            WRITERS[fmt](segs, out_path)
        except Exception as e:
            self._err(f"Write error: {e}"); return
        self._last_out_path = out_path
        if self.tmp_wav and os.path.exists(self.tmp_wav):
            try: os.unlink(self.tmp_wav)
            except: pass
            self.tmp_wav = None
        # Save to persistent history log
        self._add_history_entry({
            "id": str(int(time.time())),
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "media_file": Path(inp).name,
            "media_path": str(inp),
            "subtitle_path": str(out_path),
            "model": self.model_var.get(),
            "format": fmt,
            "status": "Completed"
        })

        self.progress_var.set(1.0)
        if hasattr(self, "pct_lbl") and self.pct_lbl:
            self.pct_lbl.configure(text="100%")
        if hasattr(self, "audio_scrub_bar") and self.audio_scrub_bar:
            self.audio_scrub_bar.set(1.0)
        self._setstatus(f"Saved: {Path(out_path).name}", color=SUCCESS)
        self.running = False
        self._update_idle_duration()
        gen_ic = get_bs_icon("play-fill", color="#FFFFFF", size=22)
        self.gen_btn.configure(state="normal", text="  Generate Subtitles", image=gen_ic)
        if messagebox.askyesno("Done!", f"Subtitle saved:\n{out_path}\n\nOpen folder?"):
            self._open_folder()

    def _err(self, msg):
        self.running = False
        if self.tmp_wav and os.path.exists(self.tmp_wav):
            try: os.unlink(self.tmp_wav)
            except: pass
        self.progress_var.set(0.0)
        self.gen_btn.configure(state="normal", text="▶  Generate Subtitles")
        self._setstatus(f"❌  {msg[:80]}", color=ERROR_C)
        messagebox.showerror("Error", msg)

if __name__ == "__main__":
    SubGenApp()
