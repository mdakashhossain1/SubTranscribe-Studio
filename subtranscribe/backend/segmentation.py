"""Re-segments Whisper output into short readable subtitle chunks. Moved verbatim from subgen.py."""
import re

_SENT_END_RE = re.compile(r'[.?!]["\')\]]*$')
_COMMA_END_RE = re.compile(r'[,;:]$')


def _seg_word_timeline(seg):
    """Extract a per-word (start, end, word) timeline from one ASR segment,
    using exact acoustic word timestamps if Whisper provided them, else an
    even linear split across the segment's duration."""
    text = (seg.get("text") or "").strip()
    if not text:
        return []
    raw_words = seg.get("words")
    timeline = []
    if raw_words:
        for w_obj in raw_words:
            ws = float(w_obj.get("start", 0.0))
            we = float(w_obj.get("end", ws))
            w_str = str(w_obj.get("word", "")).strip()
            if w_str:
                timeline.append((ws, we, w_str))
    else:
        seg_start = float(seg.get("start") or 0.0)
        seg_end = float(seg.get("end") or seg_start)
        dur = max(seg_end - seg_start, 0.0)
        words = text.split()
        if words:
            w_dur = dur / len(words)
            for j, w in enumerate(words):
                timeline.append((seg_start + j * w_dur, seg_start + (j + 1) * w_dur, w))
    return timeline


def resegment_by_sentence(segs, max_words=3, max_duration=2.2):
    """Re-segment Whisper output using true acoustic word timestamps with millisecond precision,
    ensuring subtitles are broken into dynamic 1-2 second (2-4 words) readable chunks.

    Priority order for splitting:
      1. Acoustic word timestamps if provided by Whisper model.
      2. Sentence & clause boundaries (. ? ! , ; :)
      3. Hard duration cap (max_duration ~2.2s) & hard word cap (max_words)
    """
    if not segs:
        return segs

    # -- Step 1: build a per-word timeline with acoustic timestamps --
    word_timeline = []  # [(start_sec, end_sec, word_str), ...]
    for seg in segs:
        word_timeline.extend(_seg_word_timeline(seg))

    if not word_timeline:
        return segs

    # -- Step 2: group words into dynamic short subtitle blocks --
    _SENT_END  = re.compile(r'[.?!]["\')\]]*$')
    _COMMA_END = re.compile(r'[,;:]$')

    sentences = []
    buf_words = []
    buf_start = word_timeline[0][0]
    prev_end = word_timeline[0][1]

    def _flush(end_time):
        if buf_words:
            sentences.append({
                "start": buf_start,
                "end":   end_time,
                "text":  " ".join(buf_words),
            })
            del buf_words[:]

    for (ws, we, word) in word_timeline:
        # Split across natural silence pauses >= 0.5s so subtitles don't hang over pauses
        if buf_words and (ws - prev_end >= 0.5):
            _flush(prev_end)

        if not buf_words:
            buf_start = ws
        buf_words.append(word)
        prev_end = we

        n = len(buf_words)
        curr_dur = we - buf_start

        if _SENT_END.search(word):
            _flush(we)
        elif _COMMA_END.search(word) and (n >= 2 or curr_dur >= 1.2):
            _flush(we)
        elif n >= max_words or curr_dur >= max_duration:
            _flush(we)

    # -- Step 3: flush any trailing words --
    if buf_words:
        _flush(prev_end)

    return sentences if sentences else segs


class ClauseBuffer:
    """Accumulates ASR word timestamps *across* incoming segments and yields
    complete clauses for translation — not fragments.

    Whisper.cpp's own chunker (transcribe.py's _emit_chunk) already flushes
    "segments" as small as 1-5 words on every short pause, well before a full
    clause is spoken. Grouping words *within* a single incoming segment (the
    previous approach) can't recover a clause that spans two or more of those
    small bursts — it was still handing the translator sub-clause fragments,
    which is what silently reproduced the original garbled-translation bug
    (verified: Google Translate returns a clean, correctly-ordered result for
    a full clause like "रिमूव करते हैं और यह कमाल का रिमूव करता है", but
    degrades — sometimes to its rate-limit error page — on isolated
    fragments/single words).

    push() buffers new words and returns only clauses closed by a *confirmed*
    boundary already inside the buffer (a pause between two known words,
    sentence-ending punctuation, or the hard word/duration cap below as a
    last resort for long unpunctuated runs). The boundary right after the
    newest word is never assumed — the next on_seg call might continue the
    same clause — so the trailing partial clause stays buffered until either
    a real boundary arrives or flush_all() is called at end of stream.
    """

    def __init__(self, max_words=40, max_duration=12.0):
        self.buffer = []  # [(start, end, word), ...]
        self.max_words = max_words
        self.max_duration = max_duration

    def push(self, seg):
        self.buffer.extend(_seg_word_timeline(seg))
        return self._pull()

    def flush_all(self):
        if not self.buffer:
            return []
        clause = _make_clause(self.buffer)
        self.buffer = []
        return [clause]

    def _pull(self):
        clauses = []
        buf = []
        buf_start = None
        prev_end = None
        consumed = 0

        for i, (ws, we, word) in enumerate(self.buffer):
            if buf and (ws - prev_end >= 0.5):
                clauses.append(_make_clause(buf))
                consumed = i
                buf = []

            if not buf:
                buf_start = ws
            buf.append((ws, we, word))
            prev_end = we

            n = len(buf)
            dur = we - buf_start
            if (_SENT_END_RE.search(word)
                    or (_COMMA_END_RE.search(word) and (n >= 2 or dur >= 1.2))
                    or n >= self.max_words or dur >= self.max_duration):
                clauses.append(_make_clause(buf))
                consumed = i + 1
                buf = []

        self.buffer = self.buffer[consumed:]
        return clauses


def _make_clause(buf):
    return {
        "start": buf[0][0],
        "end": buf[-1][1],
        "text": " ".join(w for _, _, w in buf),
        "words": list(buf),  # (start, end, word) tuples — kept for pause-aware display splitting
    }


def _pause_windows(clause_words, min_pause=0.25):
    """Split a clause's *source* word timeline into sub-windows at the
    clause's own natural micro-pauses (brief breath/beat points between
    words) — the same spots a human transcriber would break a subtitle at.
    Distinct from ClauseBuffer's 0.5s threshold, which decides whole-clause
    (translation) boundaries and must stay conservative to keep enough
    context for correct translation; this is purely a display concern run
    *after* translation, so a smaller pause is fine to split on here.
    Always returns at least one window (the whole clause, if no internal
    pause is found).
    """
    if not clause_words:
        return []
    windows = []
    w_start = clause_words[0][0]
    for i, (ws, we, word) in enumerate(clause_words):
        is_last = (i == len(clause_words) - 1)
        gap_after = (clause_words[i + 1][0] - we) if not is_last else None
        if is_last or (gap_after is not None and gap_after >= min_pause):
            windows.append((w_start, we))
            if not is_last:
                w_start = clause_words[i + 1][0]
    return windows


def _evenly_split(words, start, end, max_words, max_duration):
    """Fallback splitter for a single pause-window that's still too long/
    wordy for one subtitle line — divides it evenly since there's no further
    natural pause left to align to."""
    total = len(words)
    if total == 0:
        return []
    duration = max(end - start, 0.01)
    n_by_words = -(-total // max(1, max_words))
    n_by_duration = -(-duration // max(0.01, max_duration))
    n_chunks = max(1, min(total, int(max(n_by_words, n_by_duration))))

    base, rem = divmod(total, n_chunks)
    chunks = []
    idx = 0
    t = start
    for i in range(n_chunks):
        cnt = base + (1 if i < rem else 0)
        if cnt <= 0:
            continue
        chunk_words = words[idx: idx + cnt]
        idx += cnt
        is_last = (idx >= total)
        c_end = end if is_last else t + duration * (len(chunk_words) / total)
        chunks.append({"start": t, "end": c_end, "text": " ".join(chunk_words)})
        t = c_end
    return chunks


def split_translated_for_display(text, clause_words, max_words=3, max_duration=2.2, min_pause=0.25):
    """Re-flow an already-translated clause into on-screen subtitle chunks,
    timed to the clause's own natural pauses in the source audio rather than
    blindly dividing the translated text by word count — a fixed-size split
    cuts wherever the count runs out, which routinely lands mid-phrase even
    though the speaker actually paused somewhere else nearby.

    Translation changes word count/order relative to the source, so
    translated words can't map one-to-one to source words; instead, each
    pause-bounded window gets a share of the translated text proportional to
    that window's fraction of the clause's total duration, and keeps the
    window's own (real, pause-aligned) start/end. max_words/max_duration are
    a fallback cap only, applied within a window when no closer natural
    pause exists to split on.
    """
    words = text.split()
    if not clause_words:
        return [{"start": 0.0, "end": 0.0, "text": text}] if words else []

    c_start, c_end = clause_words[0][0], clause_words[-1][1]
    if not words:
        return [{"start": c_start, "end": c_end, "text": text}]

    windows = _pause_windows(clause_words, min_pause=min_pause)
    total_dur = max(c_end - c_start, 0.01)
    total_words = len(words)

    chunks = []
    idx = 0
    for wi, (ws, we) in enumerate(windows):
        is_last_window = (wi == len(windows) - 1)
        if is_last_window:
            cnt = total_words - idx
        else:
            share = (we - ws) / total_dur
            cnt = min(max(1, round(total_words * share)), total_words - idx)
        if cnt <= 0:
            continue
        window_words = words[idx: idx + cnt]
        idx += cnt
        chunks.extend(_evenly_split(window_words, ws, we, max_words, max_duration))

    if idx < total_words:
        # Rounding leftover (rare) — append to the last chunk rather than drop it.
        if chunks:
            chunks[-1]["text"] += " " + " ".join(words[idx:])
        else:
            chunks.append({"start": c_start, "end": c_end, "text": " ".join(words[idx:])})
    return chunks
