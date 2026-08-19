"""Audio waveform seek bar. Qt port of WaveformBar(tk.Canvas)
(subgen.py:1541-1662) — same peak-rendering, progress/zoom, and
click/drag-to-seek behavior, redrawn with QPainter on a QWidget instead of
Tk Canvas line items. A deliberate visual upgrade (antialiasing, smoother
playhead) per the "make it proper" ask, but the interaction contract
(load_peaks/set/set_zoom/on_seek) is unchanged so callers port 1:1.
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPainter, QColor, QPen
from PySide6.QtWidgets import QWidget

from ..config import ACCENT, BORDER_COLOR, INPUT_BG

MAX_ZOOM = 8.0


class WaveformBar(QWidget):
    seekRequested = Signal(float)  # fraction 0.0-1.0, mirrors on_seek(fraction)

    def __init__(self, parent=None, height=48,
                 played_color=ACCENT, unplayed_color=BORDER_COLOR, bg_color=INPUT_BG):
        super().__init__(parent)
        self.setFixedHeight(height)
        self.setMouseTracking(True)
        self.peaks: list[float] = []
        self.progress = 0.0
        self.zoom = 1.0
        self.view_center = 0.0
        self.played_color = QColor(played_color)
        self.unplayed_color = QColor(unplayed_color)
        self.bg_color = QColor(bg_color)
        self._dragging = False

    def load_peaks(self, peaks):
        self.peaks = peaks or []
        self.update()

    def set(self, pct: float):
        new_progress = max(0.0, min(float(pct), 1.0))
        vs, ve = self._view_range()
        if not (vs <= new_progress <= ve):
            self.view_center = new_progress
        self.progress = new_progress
        self.update()

    def set_zoom(self, zoom: float):
        self.zoom = max(1.0, min(float(zoom), MAX_ZOOM))
        self.view_center = self.progress
        self.update()

    def _view_range(self):
        if self.zoom <= 1.0:
            return 0.0, 1.0
        half = 0.5 / self.zoom
        center = min(max(self.view_center, half), 1.0 - half)
        return center - half, center + half

    def mousePressEvent(self, event):
        self._dragging = True
        self._seek_to_x(event.position().x())

    def mouseMoveEvent(self, event):
        if self._dragging:
            self._seek_to_x(event.position().x())

    def mouseReleaseEvent(self, event):
        self._dragging = False

    def _seek_to_x(self, x: float):
        w = self.width()
        if w <= 1:
            return
        frac = max(0.0, min(x / w, 1.0))
        vs, ve = self._view_range()
        abs_frac = vs + frac * (ve - vs)
        self.progress = abs_frac
        self.view_center = abs_frac
        self.update()
        self.seekRequested.emit(abs_frac)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        painter.fillRect(0, 0, w, h, self.bg_color)
        mid = h / 2.0

        if not self.peaks:
            pen = QPen(self.unplayed_color, 1, Qt.DashLine)
            painter.setPen(pen)
            painter.drawLine(0, int(mid), w, int(mid))
            painter.end()
            return

        vs, ve = self._view_range()
        n = len(self.peaks)
        i0 = max(0, min(int(vs * n), n - 1))
        i1 = max(i0 + 1, min(int(ve * n) + 1, n))
        visible = self.peaks[i0:i1]
        vn = len(visible)
        if vn == 0:
            painter.end()
            return
        bar_w = w / vn
        split_x = ((self.progress - vs) / (ve - vs)) * w if ve > vs else -1

        for i, amp in enumerate(visible):
            x = i * bar_w + bar_w / 2.0
            bar_h = max(2.0, amp * (h * 0.42))
            color = self.played_color if x <= split_x else self.unplayed_color
            pen = QPen(color, max(1.0, bar_w * 0.6), Qt.SolidLine, Qt.RoundCap)
            painter.setPen(pen)
            painter.drawLine(int(x), int(mid - bar_h), int(x), int(mid + bar_h))

        if 0 <= split_x <= w:
            pen = QPen(self.played_color, 2)
            painter.setPen(pen)
            painter.drawLine(int(split_x), 3, int(split_x), h - 3)
            painter.setBrush(self.played_color)
            painter.drawEllipse(int(split_x) - 4, int(mid) - 4, 8, 8)

        painter.end()
