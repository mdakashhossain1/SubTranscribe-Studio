"""Model cache lookup/deletion/sizing + download-progress polling. Moved verbatim
from subgen.py, plus poll_download_progress() mechanically extracted from the
SubGenApp._download_thread nested `poll_progress` closure (identical math)."""
import os
import shutil
import time
from pathlib import Path

from ..config import (
    MODELS_DIR, GGML_MODELS_DIR, PROJECT_DIR,
    MODEL_REPOS, MODEL_SIZES_MB, GGML_MODEL_FILES, GGML_MODEL_SIZES_MB,
)
from .device import USE_WHISPERCPP


def is_model_downloaded(model_size: str) -> bool:
    """Check if the selected backend's model weights are fully cached on disk."""
    candidate_model_dirs = [
        MODELS_DIR,
        PROJECT_DIR / "models",
        Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "SubTranscribe Studio" / "models"
    ]
    # Deduplicate candidate directories
    seen = set()
    unique_dirs = []
    for d in candidate_model_dirs:
        resolved = str(d.resolve()) if d.exists() else str(d)
        if resolved not in seen:
            seen.add(resolved)
            unique_dirs.append(d)

    if USE_WHISPERCPP:
        filename = GGML_MODEL_FILES.get(model_size, (None, None))[1]
        if not filename:
            return False
        exp_mb = GGML_MODEL_SIZES_MB.get(model_size, 50)
        min_bytes = int(exp_mb * 1024 * 1024 * 0.7)
        for base_dir in unique_dirs:
            f = base_dir / "ggml" / filename
            if f.exists() and not f.is_symlink():
                try:
                    if f.stat().st_size >= min_bytes:
                        return True
                except Exception:
                    pass
        return False

    repo = MODEL_REPOS.get(model_size, "")
    if not repo:
        return False
    # HuggingFace cache format: models--{org}--{name}
    cache_name = "models--" + repo.replace("/", "--")
    exp_mb = MODEL_SIZES_MB.get(model_size, 50)
    min_bytes = int(exp_mb * 1024 * 1024 * 0.7)

    for base_dir in unique_dirs:
        repo_dir = base_dir / cache_name
        if not repo_dir.exists():
            continue
        snapshots = repo_dir / "snapshots"
        if snapshots.exists():
            for snap in snapshots.iterdir():
                if snap.is_dir():
                    for f in snap.iterdir():
                        if f.name in ("model.bin", "model.safetensors"):
                            try:
                                if f.stat().st_size >= min_bytes:
                                    return True
                            except Exception:
                                pass
        blobs = repo_dir / "blobs"
        if blobs.exists():
            for b in blobs.iterdir():
                if b.is_file():
                    try:
                        if b.stat().st_size >= min_bytes:
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


def build_progress_tracker(model_size: str):
    """Return (get_progress, expected_bytes, repo, filename) for `model_size`,
    where get_progress() is a zero-arg callable that walks disk and returns
    bytes downloaded so far. Mechanically extracted from
    SubGenApp._download_thread's two `get_progress` closures (verbatim glob
    logic), just parameterized instead of capturing `model_size` from an
    enclosing scope.

    The `.incomplete`/`.tmp` staging-file matches below are additionally
    gated on mtime >= session_start. Without that, a *stale* leftover temp
    file from an earlier interrupted/crashed download (any model — the
    extension match alone doesn't know which model a staging file belongs
    to) gets permanently counted into every future download's progress
    total, making the bar jump to a false "100%" almost immediately while
    the real download is still running underneath it.
    """
    session_start = time.time()

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
                        is_staging = f.name.endswith(".incomplete") or f.name.endswith(".tmp")
                        if filename and (filename in f.name or is_staging):
                            try:
                                if is_staging and f.stat().st_mtime < session_start:
                                    continue  # stale leftover from an earlier session — not this download
                                tot += f.stat().st_size
                            except Exception:
                                pass
            dl_dir = MODELS_DIR / "downloads"
            if dl_dir.exists():
                for f in dl_dir.rglob("*"):
                    if f.is_file() and not f.is_symlink():
                        is_staging = f.name.endswith(".incomplete")
                        if filename and (filename in f.name or is_staging):
                            try:
                                if is_staging and f.stat().st_mtime < session_start:
                                    continue
                                tot += f.stat().st_size
                            except Exception:
                                pass
            return tot
    else:
        repo = MODEL_REPOS.get(model_size, "")
        filename = None
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
                        is_staging = f.name.endswith(".incomplete") or f.name.endswith(".tmp")
                        try:
                            if is_staging and f.stat().st_mtime < session_start:
                                continue
                            tot += f.stat().st_size
                        except Exception:
                            pass
            return tot

    return get_progress, expected_bytes, repo, filename


def poll_download_progress(get_progress, base_size, expected_bytes, is_active, interval=0.35):
    """Generator, mechanically extracted from SubGenApp._download_thread's
    nested `poll_progress` closure (identical math). Sleeps `interval`
    seconds, then yields one
    (pct, total_downloaded, effective_total, speed_mb_s, eta_seconds_or_None, is_finalizing)
    tuple per tick, until `is_active()` returns False.

    get_progress: zero-arg callable, bytes downloaded so far (from build_progress_tracker)
    base_size: bytes already on disk before this download session started
    expected_bytes: best-known total size for this model
    is_active: zero-arg callable; generator stops once this returns False
    """
    t0 = time.time()
    while is_active():
        time.sleep(interval)
        if not is_active():
            return
        total_downloaded = get_progress()
        session_downloaded = max(0, total_downloaded - base_size)

        effective_total = max(expected_bytes, total_downloaded)
        elapsed = max(0.1, time.time() - t0)
        speed = session_downloaded / elapsed
        speed_mb = speed / (1024 * 1024)
        rem_bytes = max(0, effective_total - total_downloaded)
        eta = (rem_bytes / speed) if speed > 1024 else None

        is_finalizing = effective_total > 0 and total_downloaded >= effective_total * 0.999
        pct = 1.0 if is_finalizing else max(0.0, min(1.0, (total_downloaded / effective_total) if effective_total > 0 else 0.0))

        yield pct, total_downloaded, effective_total, speed_mb, eta, is_finalizing
