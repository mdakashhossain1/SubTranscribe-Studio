"""Transcription backends (faster-whisper / openai-whisper / whisper.cpp).
Moved verbatim from subgen.py — callback contract unchanged:
  on_segment(seg_dict, detected_lang, pct, seg_end, total_duration, speed, eta)
  on_done(list_of_seg_dicts, detected_lang)
  on_error(message_str)
"""
import importlib.util
import re
import subprocess
import time

from ..config import GGML_MODEL_FILES, GGML_MODELS_DIR, MODELS_DIR, WHISPERCPP_EXE
from ..paths import CREATE_NO_WINDOW, get_startupinfo
from .device import DEVICE, COMPUTE_TYPE, USE_WHISPERCPP

BACKEND = None
if importlib.util.find_spec("faster_whisper") is not None:
    BACKEND = "faster_whisper"
elif importlib.util.find_spec("whisper") is not None:
    BACKEND = "openai_whisper"

# ── whisper.cpp + Vulkan transcription (GPU path for non-NVIDIA GPUs)
_WHISPERCPP_SEG_RE = re.compile(r"^\[(\d\d:\d\d:\d\d\.\d\d\d)\s*-->\s*(\d\d:\d\d:\d\d\.\d\d\d)\]\s*(.*)$")
_WHISPERCPP_DURATION_RE = re.compile(r",\s*([\d.]+)\s*sec\)")
_WHISPERCPP_LANG_RE = re.compile(r"auto-detected language:\s*(\w+)")
_SENT_END = re.compile(r'[.?!]["\')\]]*$')


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

    # -mc 0 disables cross-chunk text context.
    # -ml 1 -sow forces word-by-word token segmentation, yielding millisecond-accurate
    # acoustic timestamps for every single word without linear division distortion.
    cmd = [
        str(WHISPERCPP_EXE),
        "-m", str(model_path),
        "-f", str(audio_path),
        "-l", lang,
        "-mc", "0",
        "-ml", "1",
        "-sow",
    ]
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
    current_words = []

    def _emit_chunk():
        if not current_words:
            return
        seg_start = current_words[0]["start"]
        seg_end = current_words[-1]["end"]
        seg_text = " ".join(w["word"] for w in current_words)
        s = {
            "start": seg_start,
            "end": seg_end,
            "text": seg_text,
            "words": list(current_words),
        }
        result.append(s)
        del current_words[:]

        elapsed = max(0.001, time.time() - t0)
        speed = (seg_end / elapsed) if (elapsed > 0 and seg_end > 0) else 0.0
        eta = ((total_duration - seg_end) / speed) if (speed > 0 and total_duration > seg_end) else 0.0
        pct = (seg_end / total_duration) if total_duration > 0 else 0.0
        on_segment(s, detected_lang, pct, seg_end, total_duration, speed, eta)

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
            w_start = _parse_whispercpp_ts(m.group(1))
            w_end = _parse_whispercpp_ts(m.group(2))
            w_text = m.group(3).strip()
            if w_end <= w_start or not w_text:
                continue

            if current_words:
                prev_end = current_words[-1]["end"]
                # Flush burst if pause >= 0.5s, sentence-ending punctuation, or 5+ words buffered
                if (w_start - prev_end >= 0.5) or _SENT_END.search(current_words[-1]["word"]) or (len(current_words) >= 5):
                    _emit_chunk()

            current_words.append({"start": w_start, "end": w_end, "word": w_text})

    _emit_chunk()

    returncode = proc.wait()
    if returncode != 0:
        on_error(f"whisper.cpp exited with code {returncode}")
        return
    if not result and decode_error:
        on_error(f"whisper.cpp could not process this audio file: {decode_error}")
        return
    on_done(result, detected_lang)


def transcribe(audio_path, model_size, source_lang, on_segment, on_done, on_error,
               beam_size=5, temperature=0.0, condition_on_previous_text=False, word_timestamps=True):
    try:
        if USE_WHISPERCPP:
            transcribe_whispercpp(audio_path, model_size, source_lang, on_segment, on_done, on_error)
        elif BACKEND == "faster_whisper":
            from faster_whisper import WhisperModel
            model = WhisperModel(
                model_size,
                device=DEVICE,                   # <- auto: 'cuda' (GPU) or 'cpu'
                compute_type=COMPUTE_TYPE,       # <- float16 on GPU, int8 on CPU
                download_root=str(MODELS_DIR),   # <- always saves to project/models/
                cpu_threads=4,
            )
            t0 = time.time()
            segs, info = model.transcribe(
                audio_path,
                language=source_lang,
                vad_filter=True,
                beam_size=beam_size,
                temperature=temperature,
                condition_on_previous_text=condition_on_previous_text,
                word_timestamps=word_timestamps
            )
            det = getattr(info, "language", "unknown") or "unknown"
            raw_dur = getattr(info, "duration", 0.0)
            total_duration = float(raw_dur) if raw_dur is not None else 0.0
            result = []
            for seg in segs:
                seg_start = float(getattr(seg, "start", 0.0) or 0.0)
                seg_end   = float(getattr(seg, "end", 0.0) or 0.0)
                seg_text  = str(getattr(seg, "text", "") or "")
                seg_words = []
                if hasattr(seg, "words") and seg.words:
                    for w in seg.words:
                        seg_words.append({
                            "start": float(getattr(w, "start", 0.0) or 0.0),
                            "end": float(getattr(w, "end", 0.0) or 0.0),
                            "word": str(getattr(w, "word", "") or "").strip()
                        })
                s = {"start": seg_start, "end": seg_end, "text": seg_text, "words": seg_words}
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
                download_root=str(MODELS_DIR),   # <- always saves to project/models/
            )
            result = model.transcribe(
                audio_path,
                language=source_lang,
                verbose=False,
                beam_size=beam_size,
                temperature=temperature,
                condition_on_previous_text=condition_on_previous_text,
                word_timestamps=word_timestamps
            )
            det = result.get("language", "unknown") or "unknown"
            raw_segs = result.get("segments", []) or []
            segs = []
            for r in raw_segs:
                st = float(r.get("start", 0.0) or 0.0)
                en = float(r.get("end", 0.0) or 0.0)
                tx = str(r.get("text", "") or "")
                raw_w = r.get("words", []) or []
                seg_words = [{"start": float(w.get("start", 0.0)), "end": float(w.get("end", 0.0)), "word": str(w.get("word", "")).strip()} for w in raw_w]
                segs.append({"start": st, "end": en, "text": tx, "words": seg_words})
            total_dur = segs[-1]["end"] if segs else 1.0
            for i, s in enumerate(segs, 1):
                pct = i / len(segs)
                on_segment(s, det, pct, s["end"], total_dur, 1.0, 0.0)
            on_done(segs, det)
        else:
            on_error("No backend. Run: pip install faster-whisper")
    except Exception as e:
        on_error(str(e))
