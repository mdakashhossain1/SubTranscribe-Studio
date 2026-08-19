"""Small shared layout helpers used across pages — a lightweight Qt analog of
SubGenApp._card (subgen.py:2813-2827)."""
from PySide6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel

from ..config import CARD_BG, BORDER_COLOR, TEXT_MAIN, TEXT_SUB, ACCENT_CYAN, INPUT_BG
from ..icons import get_bs_icon


def make_card(title: str, icon_name: str | None = None) -> tuple[QFrame, QVBoxLayout]:
    """Returns (card_frame, body_layout); caller adds widgets to body_layout.
    icon_name, if given, is a Bootstrap Icons name shown left of the title —
    Qt port of _card's optional icon_name param (subgen.py:2813-2827)."""
    card = QFrame()
    card.setObjectName("cardFrame")
    card.setStyleSheet(f"""
        #cardFrame {{
            background-color: {CARD_BG};
            border: 1px solid {BORDER_COLOR};
            border-radius: 10px;
        }}
        QLabel {{
            border: none;
            background: transparent;
        }}
    """)
    outer = QVBoxLayout(card)
    outer.setContentsMargins(16, 14, 16, 16)
    outer.setSpacing(10)


    if title:
        hdr = QHBoxLayout()
        if icon_name:
            icon = get_bs_icon(icon_name, color=ACCENT_CYAN, size=18)
            if icon:
                icon_lbl = QLabel()
                icon_lbl.setPixmap(icon.pixmap(18, 18))
                icon_lbl.setStyleSheet("border: none;")
                hdr.addWidget(icon_lbl)
        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(f"color: {TEXT_MAIN}; font-size: 15px; font-weight: 700; border: none;")
        hdr.addWidget(title_lbl)
        hdr.addStretch(1)
        outer.addLayout(hdr)

    return card, outer


def make_stat_tile(label: str, value: str = "0", color: str = TEXT_MAIN) -> tuple[QFrame, QLabel]:
    """Compact label-over-big-value tile for stat rows (Overall Progress,
    Processed, Speed, etc. on the Dashboard's telemetry card) — returns
    (tile_frame, value_label) so callers update value_label.setText() live."""
    tile = QFrame()
    tile.setStyleSheet(f"background-color: {INPUT_BG}; border: 1px solid {BORDER_COLOR}; border-radius: 8px;")
    v = QVBoxLayout(tile)
    v.setContentsMargins(12, 10, 12, 10)
    v.setSpacing(2)

    lbl = QLabel(label)
    lbl.setStyleSheet(f"color: {TEXT_SUB}; font-size: 11px; font-weight: 600; border: none;")
    v.addWidget(lbl)

    val_lbl = QLabel(value)
    val_lbl.setStyleSheet(f"color: {color}; font-size: 20px; font-weight: 700; border: none;")
    v.addWidget(val_lbl)

    return tile, val_lbl


class LiveStatusIndicator(QLabel):
    """Pulsing status badge: displays '● Offline' when idle, and an animated pulsing '● Live' when active."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._is_live = False
        self._pulse_state = False
        from PySide6.QtCore import QTimer
        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._on_pulse)
        self._update_appearance()

    def set_live(self, live: bool):
        self._is_live = bool(live)
        if self._is_live:
            self._pulse_state = False
            self._timer.start()
        else:
            self._timer.stop()
        self._update_appearance()

    def _on_pulse(self):
        self._pulse_state = not self._pulse_state
        self._update_appearance()

    def _update_appearance(self):
        from ..config import SUCCESS, TEXT_SUB
        if self._is_live:
            dot_color = SUCCESS if not self._pulse_state else "#6EE7B7"
            self.setText(f'<span style="color: {dot_color}; font-size: 13px;">●</span> <span style="color: {SUCCESS}; font-weight: 700;">Live</span>')
        else:
            self.setText(f'<span style="color: {TEXT_SUB}; font-size: 13px;">●</span> <span style="color: {TEXT_SUB}; font-weight: 600;">Offline</span>')
        self.setStyleSheet("border: none; background: transparent; font-size: 11px;")

