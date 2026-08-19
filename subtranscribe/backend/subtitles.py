"""Subtitle format writers (SRT/VTT/ASS/TXT). Moved verbatim from subgen.py."""
from ..config import LANG_FONT_MAP, _DEFAULT_FONT


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


def write_ass(segs, path, lang_code=None):
    """Write an ASS subtitle file.

    lang_code is the GoogleTranslate/ISO-639 code of the *output* language
    (e.g. 'hi', 'bn', 'de').  When provided, the correct Unicode-aware font
    is chosen so Indic/Arabic/CJK scripts actually render instead of showing
    boxes.  Italic is disabled for scripts that don't support it.
    """
    font_name, allow_italic = LANG_FONT_MAP.get(lang_code or "", _DEFAULT_FONT)
    italic_flag = "-1" if allow_italic else "0"   # ASS: -1 = on, 0 = off
    hdr = ("[Script Info]\nScriptType: v4.00+\nPlayResX: 1920\nPlayResY: 1080\n\n"
           "[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,"
           "OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,"
           "Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\n"
           f"Style: Default,{font_name},48,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,"
           f"-1,{italic_flag},0,0,100,100,0,0,1,2,2,2,10,10,20,1\n\n"
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
