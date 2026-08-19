"""In-memory application event log, shared app-wide via a QObject singleton.

Workers (model downloads, transcription jobs) call log_event() directly from
their background thread — Qt signals are thread-safe to emit cross-thread,
so LogsPage's slot still runs on the main thread. The log persists in
`event_log.lines` independent of whether the Logs page has ever been opened,
so events that happened before the user first visits Logs aren't lost.
"""
import time

from PySide6.QtCore import QObject, Signal


class _EventLog(QObject):
    lineAdded = Signal(str)

    def __init__(self):
        super().__init__()
        self.lines: list[str] = []

    def add(self, message: str):
        line = f"[{time.strftime('%H:%M:%S')}] {message}"
        self.lines.append(line)
        self.lineAdded.emit(line)

    def clear(self):
        self.lines.clear()


event_log = _EventLog()


def log_event(message: str):
    event_log.add(message)
