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


def delete_history_entry(entry_id):
    hist_file = DATA_DIR / "history.json"
    hist = [h for h in get_history() if h.get("id") != entry_id]
    try:
        with open(hist_file, "w", encoding="utf-8") as f:
            json.dump(hist, f, indent=2)
    except Exception:
        pass
