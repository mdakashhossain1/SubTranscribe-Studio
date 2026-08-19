"""Audio extraction/decoding + a lightweight playback engine. Moved verbatim
from subgen.py — AudioPlayer's public methods are unchanged; only its
UI-facing callbacks (if any are added later) would be rewired to Qt signals
by the widgets layer, not here."""
import subprocess
import threading

from ..paths import CREATE_NO_WINDOW, get_startupinfo

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

try:
    import sounddevice as sd
    HAS_SOUNDDEVICE = True
except Exception:
    HAS_SOUNDDEVICE = False


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
