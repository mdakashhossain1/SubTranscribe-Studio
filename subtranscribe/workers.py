"""QThread workers: the systematic replacement for subgen.py's
`self.root.after(0, fn, *args)` thread->UI marshalling. Every worker emits
plain data only (str/float/dict/list) via Qt signals; a main-thread @Slot
consumes them and touches widgets. Nothing here holds a widget reference.
"""
import os
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from .backend.audio import extract_audio, decode_audio_preview
from .backend.formatting import _fmt_time_short, _fmt_size
from .backend.segmentation import resegment_by_sentence, ClauseBuffer, split_translated_for_display
from .backend.subtitles import WRITERS, write_ass, _fmt_srt
from .backend.transcribe import transcribe
from .backend.translate import resolve_translate_fn
from .backend.history import add_history_entry
from .backend.eventlog import log_event
from .backend.models import build_progress_tracker, poll_download_progress
from .backend.device import USE_WHISPERCPP
from .backend.update import check_for_update, find_installer_asset_url
from .config import LANGUAGE_MAP, WHISPER_LANG_MAP, MODELS_DIR, GGML_MODELS_DIR, DATA_DIR
from .paths import FFMPEG_PATH

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

_AUDIO_EXTS = {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac"}


class TranscribeWorker(QThread):
    """Mechanical port of SubGenApp._pipeline + on_seg/on_done/on_err + _post/_err
    (subgen.py:4148-4360). Same transcribe()/resegment_by_sentence()/WRITERS
    calls, same translate/romanize branching, same RTF/ETA math — only the
    UI-touching half of each closure is replaced with a signal emit.
    """

    segmentReady = Signal(dict)   # one payload per resegmented subtitle chunk
    finished_ok = Signal(str, list)  # (out_path, final_segs)
    error = Signal(str)

    def __init__(self, input_path: str, output_dir: str, model_size: str,
                 src_lang_name: str, tgt_lang_name: str, fmt: str,
                 beam_size: int = 5, temperature: float = 0.0,
                 condition_on_previous_text: bool = False, word_timestamps: bool = True,
                 max_words: int = 3, vocabulary_hint: str = "", parent=None):
        super().__init__(parent)
        self.input_path = input_path
        self.output_dir = output_dir
        self.model_size = model_size
        self.src_lang_name = src_lang_name
        self.tgt_lang_name = tgt_lang_name
        self.fmt = fmt
        self.beam_size = beam_size
        self.temperature = temperature
        self.condition_on_previous_text = condition_on_previous_text
        self.word_timestamps = word_timestamps
        self.max_words = max_words
        self.vocabulary_hint = vocabulary_hint

        self._tmp_wav = None
        self._all_segs = []
        self._start_time = None

    def run(self):
        inp = self.input_path
        log_event(f"Transcription started: {Path(inp).name} (model={self.model_size}, "
                   f"src={self.src_lang_name}, tgt={self.tgt_lang_name}, fmt={self.fmt})")
        try:
            suffix = Path(inp).suffix.lower()
            if suffix == ".wav":
                audio = inp
            elif FFMPEG_PATH:
                self.segmentReady.emit({"status": "Extracting audio with FFmpeg…"})
                self._tmp_wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
                if not extract_audio(inp, self._tmp_wav, FFMPEG_PATH):
                    log_event(f"Transcription failed: {Path(inp).name} — FFmpeg failed to extract audio.")
                    self.error.emit("FFmpeg failed to extract audio.")
                    return
                audio = self._tmp_wav
            elif suffix in _AUDIO_EXTS:
                audio = inp
            else:
                log_event(f"Transcription failed: {Path(inp).name} — FFmpeg not found.")
                self.error.emit("FFmpeg not found. Provide a .wav/.mp3 file directly.")
                return

            sl = WHISPER_LANG_MAP.get(self.src_lang_name)

            self.segmentReady.emit({"status": f"Loading {self.model_size} model…", "progress": 0.05})

            # Resolve translation ONCE up front so each segment can be translated
            # live as it arrives (subgen.py:4189-4200).
            translate_fn = resolve_translate_fn(sl, self.tgt_lang_name)
            if translate_fn:
                log_event(f"Translation active: {Path(inp).name} → {self.tgt_lang_name}")

            self._start_time = time.time()
            self._last_progress = (1.0, 0.0, 0.0, 0.0, 0.0)  # pct, cur, total, speed, eta

            # Accumulates ASR words *across* incoming segments so translation
            # runs on whole clauses instead of whisper.cpp's own small (1-5
            # word) burst boundaries. Grouping within a single incoming seg
            # (the previous approach) can't recover a clause that spans two
            # or more bursts — verified: that still fed Google Translate
            # sub-clause fragments and reproduced the original garbled/
            # mistranslated output even after adding clause-level grouping.
            clause_buffer = ClauseBuffer()

            def _progress_payload(lang, pct, cur_end, total_dur, speed, eta):
                pct_val = float(pct) if pct is not None else 0.0
                cur_val = float(cur_end) if cur_end is not None else 0.0
                tot_val = float(total_dur) if total_dur is not None else 0.0
                spd_val = float(speed) if speed is not None else 0.0
                eta_val = float(eta) if eta is not None else 0.0

                elapsed = time.time() - self._start_time if self._start_time else 0.001
                rtf = elapsed / max(cur_val, 0.001)

                pct_str = f"{int(pct_val * 100)}%"
                cur_str = _fmt_time_short(cur_val)
                tot_str = _fmt_time_short(tot_val)
                speed_str = f"{spd_val:.1f}x"
                eta_str = _fmt_time_short(eta_val)
                rem = max(0, tot_val - cur_val)

                lang_str = f"Detected: {lang}"
                if translate_fn:
                    lang_str += f"  →  {self.tgt_lang_name}"
                status_msg = f"Transcribing… {pct_str} ({cur_str}/{tot_str})  |  {speed_str}  |  ETA: {eta_str}  |  {lang_str}"

                return {
                    "pct": max(0.02, min(pct_val, 0.99)),
                    "pct_str": pct_str,
                    "cur_str": cur_str,
                    "tot_str": tot_str,
                    "speed_str": speed_str,
                    "eta_str": eta_str,
                    "remaining_str": _fmt_time_short(rem),
                    "rtf_str": f"{rtf:.2f}",
                    "status": status_msg,
                }

            def _emit_progress(lang, pct, cur_end, total_dur, speed, eta):
                # Status-only heartbeat, no "chunk" key — safe to call on
                # every incoming segment (including whisper.cpp's live,
                # content-free progress pings during the DTW/JSON decode
                # phase, where real subtitle content only arrives at the end)
                # without it being mistaken for actual output.
                self.segmentReady.emit(_progress_payload(lang, pct, cur_end, total_dur, speed, eta))

            def _emit_chunks(sub_chunks, lang, pct, cur_end, total_dur, speed, eta):
                for chunk in sub_chunks:
                    c_text = str(chunk.get('text', '') or '').strip()
                    if not c_text:
                        continue
                    self._all_segs.append(chunk)
                    seg_num = len(self._all_segs)

                    payload = _progress_payload(lang, pct, cur_end, total_dur, speed, eta)
                    payload["chunk"] = chunk
                    payload["seg_num"] = seg_num
                    payload["log_line"] = (
                        f"[{time.strftime('%H:%M:%S')}] Seg #{seg_num} "
                        f"[{_fmt_srt(chunk['start'])} --> {_fmt_srt(chunk['end'])}]: {chunk['text']}"
                    )
                    self.segmentReady.emit(payload)

            def _translate_clauses(clauses):
                sub_chunks = []
                for clause in clauses:
                    c_text = str(clause.get('text', '') or '').strip()
                    if not c_text:
                        continue
                    try:
                        translated = translate_fn(c_text)
                    except Exception:
                        translated = c_text
                    sub_chunks.extend(split_translated_for_display(
                        translated, clause['words'],
                        max_words=self.max_words, max_duration=2.2))
                return sub_chunks

            def on_seg(seg, lang, pct, cur_end, total_dur, speed, eta):
                self._last_progress = (pct, cur_end, total_dur, speed, eta)
                _emit_progress(lang, pct, cur_end, total_dur, speed, eta)
                if translate_fn:
                    sub_chunks = _translate_clauses(clause_buffer.push(seg))
                else:
                    sub_chunks = resegment_by_sentence([seg], max_words=self.max_words, max_duration=2.2)
                _emit_chunks(sub_chunks, lang, pct, cur_end, total_dur, speed, eta)

            def on_done(segs, lang):
                if translate_fn:
                    tail_chunks = _translate_clauses(clause_buffer.flush_all())
                    if tail_chunks:
                        _emit_chunks(tail_chunks, lang, *self._last_progress)
                self._finish(lang)

            def on_err(msg):
                log_event(f"Transcription failed: {Path(inp).name} — {msg}")
                self.error.emit(msg)

            self.segmentReady.emit({"status": f"Transcribing with {self.model_size}…"})
            transcribe(audio, self.model_size, sl, on_seg, on_done, on_err,
                       beam_size=self.beam_size, temperature=self.temperature,
                       condition_on_previous_text=self.condition_on_previous_text,
                       word_timestamps=self.word_timestamps,
                       initial_prompt=self.vocabulary_hint)
        except Exception as e:
            log_event(f"Transcription failed: {Path(inp).name} — {e}")
            self.error.emit(str(e))
        finally:
            if self._tmp_wav and os.path.exists(self._tmp_wav):
                try:
                    os.unlink(self._tmp_wav)
                except Exception:
                    pass
                self._tmp_wav = None

    def _finish(self, lang):
        """Finalize and write subtitles to disk."""
        segs = list(self._all_segs)
        self._all_segs = segs

        inp = self.input_path
        out_dir = self.output_dir.strip() or str(Path(inp).parent)
        out_path = os.path.join(out_dir, f"{Path(inp).stem}.{self.fmt.lower()}")
        out_lang_code = LANGUAGE_MAP.get(self.tgt_lang_name) or LANGUAGE_MAP.get(self.src_lang_name)
        try:
            if self.fmt == "ASS":
                write_ass(segs, out_path, lang_code=out_lang_code)
            else:
                WRITERS[self.fmt](segs, out_path)
        except Exception as e:
            log_event(f"Transcription failed: {Path(inp).name} — write error: {e}")
            self.error.emit(f"Write error: {e}")
            return

        log_event(f"Transcription completed: {Path(inp).name} → {Path(out_path).name} "
                   f"({len(segs)} segments, {self.fmt})")

        add_history_entry({
            "id": str(int(time.time())),
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "media_file": Path(inp).name,
            "media_path": str(inp),
            "subtitle_path": str(out_path),
            "model": self.model_size,
            "format": self.fmt,
            "status": "Completed",
        })

        self.finished_ok.emit(out_path, segs)


class TelemetryWorker(QThread):
    """Mechanical port of SubGenApp._telemetry_loop (subgen.py:3519-3572) —
    one long-lived polling thread instead of a new thread per tick. `is_busy`
    is a zero-arg callable mirroring the original's `getattr(self, "running", False)`
    check, which drives the simulated GPU-load/temperature estimate.
    """

    stats = Signal(dict)

    def __init__(self, is_busy=lambda: False, parent=None):
        super().__init__(parent)
        self.is_busy = is_busy
        self._running = True

    def stop(self):
        self._running = False

    def run(self):
        while self._running:
            try:
                cpu_val = psutil.cpu_percent(interval=None) if HAS_PSUTIL else 15.0

                if HAS_PSUTIL:
                    vm = psutil.virtual_memory()
                    used_gb = vm.used / (1024 ** 3)
                    tot_gb = vm.total / (1024 ** 3)
                    ram_str = f"{used_gb:.1f}/{tot_gb:.1f} GB ({vm.percent:.0f}%)"
                else:
                    ram_str = "7.2/15.0 GB"

                if HAS_PSUTIL:
                    try:
                        du = psutil.disk_usage(str(DATA_DIR))
                        d_used = du.used / (1024 ** 3)
                        d_tot = du.total / (1024 ** 3)
                        disk_str = f"{d_used:.0f}/{d_tot:.0f} GB ({du.percent:.0f}%)"
                    except Exception:
                        disk_str = "273/450 GB"
                else:
                    disk_str = "273/450 GB"

                if self.is_busy():
                    gpu_pct = min(99, max(55, int(cpu_val * 2.8 + 42)))
                    temp_val = min(78, max(52, int(42 + cpu_val * 0.35)))
                else:
                    gpu_pct = max(2, int(cpu_val * 0.4 + 4))
                    temp_val = max(35, int(38 + cpu_val * 0.15))

                self.stats.emit({
                    "cpu_str": f"{cpu_val:.1f}%",
                    "ram_str": ram_str,
                    "disk_str": disk_str,
                    "gpu_str": f"{gpu_pct}%",
                    "temp_str": f"{temp_val}°C",
                })
            except Exception:
                pass
            self.msleep(1000)


class DownloadWorker(QThread):
    """Mechanical port of SubGenApp._download_thread (subgen.py:3928-4084):
    same disk-polling progress math (backend.models.poll_download_progress),
    same huggingface_hub download calls, run on a QThread with a plain
    Python polling thread underneath (mirroring the original's separate
    poller thread) instead of `root.after(0, ...)`.
    """

    progress = Signal(dict)
    finished_ok = Signal(str)   # model_size
    error = Signal(str)

    def __init__(self, model_size: str, parent=None):
        super().__init__(parent)
        self.model_size = model_size

    def run(self):
        import threading as _threading
        os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
        # Newer huggingface_hub defaults to the Xet accelerated-transfer
        # backend for repos that support it. Xet's native downloader doesn't
        # write the classic growing <hash>.incomplete blob file this class's
        # disk-polling progress tracker relies on — it resolves content
        # through its own pipeline and only produces the final file at the
        # end, so progress reads 0 for the whole download otherwise. The
        # classic HTTP path writes incrementally and is what get_progress()
        # actually observes, so force it.
        os.environ["HF_HUB_DISABLE_XET"] = "1"
        model_size = self.model_size
        get_progress, expected_bytes, repo, filename = build_progress_tracker(model_size)
        base_size = get_progress()
        dl_active = [True]

        def _poll():
            for pct, total_downloaded, effective_total, speed_mb, eta, is_finalizing in poll_download_progress(
                get_progress, base_size, expected_bytes, is_active=lambda: dl_active[0]
            ):
                if not dl_active[0]:
                    break
                dl_str = f"{_fmt_size(total_downloaded)} / {_fmt_size(effective_total)}"
                speed_str = f"{speed_mb:.1f} MB/s"
                eta_str = _fmt_time_short(eta) if eta is not None else "calculating…"
                self.progress.emit({
                    "pct": pct,
                    "pct_str": f"{int(pct * 100)}%",
                    "dl_str": dl_str,
                    "speed_str": speed_str,
                    "eta_str": eta_str,
                    "is_finalizing": is_finalizing,
                    "model_size": model_size,
                })

        poller = _threading.Thread(target=_poll, daemon=True)
        poller.start()

        log_event(f"Model download started: {model_size} ({repo})")
        try:
            self.progress.emit({"pct": 0.02, "status": f"Downloading {model_size} from HuggingFace…"})
            if USE_WHISPERCPP:
                from huggingface_hub import hf_hub_download
                hf_hub_download(repo_id=repo, filename=filename, local_dir=str(GGML_MODELS_DIR))
            else:
                from huggingface_hub import snapshot_download
                snapshot_download(repo_id=repo, cache_dir=str(MODELS_DIR), local_files_only=False)

            dl_active[0] = False
            poller.join(timeout=1.5)
            log_event(f"Model download completed: {model_size}")
            self.finished_ok.emit(model_size)
        except Exception as e:
            dl_active[0] = False
            poller.join(timeout=1.5)
            log_event(f"Model download failed: {model_size} — {e}")
            self.error.emit(str(e))
        finally:
            dl_active[0] = False


class WaveformWorker(QThread):
    """Mechanical port of SubGenApp._extract_waveform_worker — wraps
    backend.audio.decode_audio_preview() on a background thread. Emits
    (samples, sample_rate, peaks) once decoding finishes; samples/sr feed
    AudioPlayer.load(), peaks feed WaveformBar.load_peaks()."""

    peaksReady = Signal(object, int, list)  # (samples ndarray-or-None, sr, peaks)
    error = Signal(str)

    def __init__(self, input_path: str, ffmpeg_path: str, parent=None):
        super().__init__(parent)
        self.input_path = input_path
        self.ffmpeg_path = ffmpeg_path

    def run(self):
        try:
            samples, sr, peaks = decode_audio_preview(self.input_path, self.ffmpeg_path)
            self.peaksReady.emit(samples, sr, peaks or [])
        except Exception as e:
            self.error.emit(str(e))


class UpdateCheckWorker(QThread):
    """Mechanical port of SubGenApp._check_for_update_bg /
    _manual_check_for_update_bg (subgen.py:3260-3267, 3490-3493)."""

    result = Signal(object)  # (latest, url, notes, assets) tuple, or None

    def run(self):
        self.result.emit(check_for_update())


class UpdateDownloadWorker(QThread):
    """Mechanical port of SubGenApp._download_and_run_update (subgen.py:3397-3478):
    same chunked-download-with-progress loop, same installer launch via
    subprocess.Popen. The one behavior difference: the original called
    `self.root.destroy()` itself from the worker (marshalled via root.after);
    here the worker only emits `installerLaunched`, and the main-thread slot
    is responsible for calling QApplication.quit() — Qt app lifecycle calls
    must happen on the main thread.
    """

    progress = Signal(float, str)   # (pct 0..1, status label)
    installerLaunched = Signal()
    error = Signal(str)
    noInstallerFound = Signal(str)  # release_url, so caller can open it in a browser

    def __init__(self, assets: list, version: str, release_url: str, parent=None):
        super().__init__(parent)
        self.assets = assets
        self.version = version
        self.release_url = release_url

    def run(self):
        import tempfile

        exe_url = find_installer_asset_url(self.assets)
        if not exe_url:
            self.noInstallerFound.emit(self.release_url)
            return

        tmp_path = os.path.join(tempfile.gettempdir(), f"SubTranscribeStudio_v{self.version}_setup.exe")
        try:
            self.progress.emit(0.0, f"Downloading v{self.version} installer…")
            req = urllib.request.Request(exe_url, headers={"User-Agent": "SubTranscribe-Studio"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                total = int(resp.headers.get("Content-Length", 0) or 0)
                downloaded = 0
                chunk = 65536
                with open(tmp_path, "wb") as f:
                    while True:
                        buf = resp.read(chunk)
                        if not buf:
                            break
                        f.write(buf)
                        downloaded += len(buf)
                        if total > 0:
                            pct = downloaded / total
                            mb_done = downloaded / 1_048_576
                            mb_tot = total / 1_048_576
                            self.progress.emit(pct, f"Downloading… {mb_done:.1f} / {mb_tot:.1f} MB")

            self.progress.emit(1.0, "Download complete. Installing update…")
            time.sleep(1.0)
            # Silent flags so this runs as an in-place update instead of
            # popping the full first-run wizard (Welcome/License/directory
            # picker), which looked like a fresh install to the user.
            # /CLOSEAPPLICATIONS + /RESTARTAPPLICATIONS let Inno Setup's
            # Restart Manager close this running app (its own exe would
            # otherwise be locked), replace the files, then relaunch it.
            subprocess.Popen(
                [tmp_path, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                 "/SP-", "/CLOSEAPPLICATIONS", "/RESTARTAPPLICATIONS"],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            self.installerLaunched.emit()
        except Exception as exc:
            self.error.emit(f"Download failed: {exc}")
