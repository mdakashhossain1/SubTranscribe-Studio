"""Re-segments Whisper output into short readable subtitle chunks. Moved verbatim from subgen.py."""
import re


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
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        # Use exact acoustic word timestamps if available from Whisper
        raw_words = seg.get("words")
        if raw_words and len(raw_words) > 0:
            for w_obj in raw_words:
                ws = float(w_obj.get("start", 0.0))
                we = float(w_obj.get("end", ws))
                w_str = str(w_obj.get("word", "")).strip()
                if w_str:
                    word_timeline.append((ws, we, w_str))
        else:
            seg_start = float(seg.get("start") or 0.0)
            seg_end   = float(seg.get("end")   or seg_start)
            dur = max(seg_end - seg_start, 0.0)
            words = text.split()
            if not words:
                continue
            w_dur = dur / len(words)
            for j, w in enumerate(words):
                ws = seg_start + j * w_dur
                we = seg_start + (j + 1) * w_dur
                word_timeline.append((ws, we, w))

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
