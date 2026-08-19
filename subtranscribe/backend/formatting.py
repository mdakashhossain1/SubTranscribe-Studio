"""Progress/speed/ETA formatting helpers. Moved verbatim from subgen.py."""


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
