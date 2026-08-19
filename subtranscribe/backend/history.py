"""Job history persistence (DATA_DIR/history.json). Hoisted from SubGenApp
methods (subgen.py:2410-2453) which only touched the module-level DATA_DIR,
not `self` — behavior unchanged, just no longer bound to the UI class.
`_clear_history`'s UI half (page-cache invalidation/re-render) stays in the
Qt History page; only the file-wipe here is reused."""
import json

from ..config import DATA_DIR


def get_history():
    hist_file = DATA_DIR / "history.json"
    if hist_file.exists():
        try:
            with open(hist_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def add_history_entry(entry):
    hist_file = DATA_DIR / "history.json"
    hist = get_history()
    hist.insert(0, entry)
    try:
        with open(hist_file, "w", encoding="utf-8") as f:
            json.dump(hist[:100], f, indent=2)
    except Exception:
        pass


def clear_history():
    hist_file = DATA_DIR / "history.json"
    if hist_file.exists():
        try:
            hist_file.unlink()
        except Exception:
            pass


def delete_history_entry(entry_id, match_item=None):
    hist_file = DATA_DIR / "history.json"
    str_eid = str(entry_id) if entry_id is not None else ""
    hist = get_history()
    new_hist = []
    for h in hist:
        h_id = str(h.get("id")) if h.get("id") is not None else ""
        if str_eid and h_id and h_id == str_eid:
            continue
        if match_item:
            if (h.get("media_file") == match_item.get("media_file") and
                h.get("timestamp") == match_item.get("timestamp") and
                h.get("subtitle_path") == match_item.get("subtitle_path")):
                continue
        new_hist.append(h)
    try:
        with open(hist_file, "w", encoding="utf-8") as f:
            json.dump(new_hist, f, indent=2)
    except Exception:
        pass

