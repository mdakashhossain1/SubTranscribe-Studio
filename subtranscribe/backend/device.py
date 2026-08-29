"""GPU/CPU device detection. Moved verbatim from subgen.py."""
import os
import subprocess

from ..config import SUCCESS, ACCENT2, WHISPERCPP_EXE
from ..paths import CREATE_NO_WINDOW, get_startupinfo


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
    DEVICE_LABEL = f"GPU Active — {GPU_NAME or 'CUDA'}"
    DEVICE_COLOR = SUCCESS   # green
elif USE_WHISPERCPP:
    short = GPU_NAME.replace("AMD ", "").replace("NVIDIA ", "")
    DEVICE_LABEL = f"GPU Active — {short} (Vulkan)"
    DEVICE_COLOR = SUCCESS   # green — genuinely GPU-accelerated via whisper.cpp
elif GPU_NAME:
    # AMD/Intel GPU detected but running fast CPU mode (normal for AMD on Windows)
    short = GPU_NAME.replace("AMD ", "").replace("NVIDIA ", "")
    DEVICE_LABEL = f"{short} — High-Speed Mode"
    DEVICE_COLOR = ACCENT2   # teal — looks good, not alarming
else:
    DEVICE_LABEL = "High-Speed Mode"
    DEVICE_COLOR = ACCENT2


def recommend_best_settings() -> dict:
    """Auto-detect this PC's hardware and dial every advanced setting to the
    highest quality it can actually run — biggest model that fits, best
    precision, widest search. Mechanical port of SubGenApp._reset_advanced_to_best
    (subgen.py:2998-3024); compute_type/best_of are UI-only in the original
    too (never actually passed to transcribe()), kept here for the same
    visual parity, not because the backend consumes them."""
    from ..config import MODEL_SIZES, MODEL_VRAM_MB

    vram = get_gpu_vram_mb()

    if DEVICE == "cuda":
        budget = vram * 0.85 if vram else 4000
    elif USE_WHISPERCPP:
        budget = 4000  # non-NVIDIA GPU via Vulkan — no reliable VRAM readout
    else:
        try:
            import psutil
            ram_mb = psutil.virtual_memory().total / (1024 * 1024)
        except ImportError:
            ram_mb = 8000
        budget = ram_mb * 0.4  # CPU-only: leave headroom for the OS + ffmpeg

    best_model = MODEL_SIZES[-1]
    for m in MODEL_SIZES:
        if MODEL_VRAM_MB.get(m, 99999) <= budget:
            best_model = m
            break

    return {
        "model": best_model,
        "compute_type": "float16" if DEVICE == "cuda" else "int8",
        "beam_size": 8 if (DEVICE == "cuda" and vram and vram >= 8000) else 5,
        "best_of": 5,
        "temperature": 0.0,
        "condition_on_previous_text": True,
        "word_timestamps": True,
        "max_words": 6,
        "vram_mb": vram,
    }
