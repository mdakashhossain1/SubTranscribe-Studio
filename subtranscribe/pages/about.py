"""About page. Qt port of SubGenApp._render_about (subgen.py:2679-2812).
The "Check for Updates" button reports version status either way
(_manual_check_for_update's rationale) and, when an update is found, opens
the same UpdateDialog used by the startup badge (main_window.show_update_dialog).
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QGridLayout, QScrollArea

from ..backend.device import GPU_NAME, DEVICE, DEVICE_LABEL
from ..backend.transcribe import BACKEND
from ..backend.device import COMPUTE_TYPE
from ..config import APP_NAME, APP_VER, LOGO_PATH, DARK_BG, CARD_BG, INPUT_BG, BORDER_COLOR, TEXT_MAIN, TEXT_SUB, ACCENT_CYAN, SUCCESS, DATA_DIR
from ..icons import get_bs_icon
from ..paths import FFMPEG_PATH
from ..widgets.cards import make_card
from ..widgets.styles import BTN_SECONDARY_STYLE
from ..workers import UpdateCheckWorker

_FEATURES = [
    ("cpu-fill", "Faster-Whisper & CTranslate2 Engine",
     "Sub-second offline speech recognition using 8-bit and 16-bit quantized Transformer models with zero data telemetry."),
    ("lightning-charge-fill", "Dual GPU Hardware Acceleration",
     "Native CUDA support for NVIDIA GPUs and Vulkan GGML GPU acceleration for AMD Radeon and Intel ARC GPUs."),
    ("translate", "Multi-Language Auto Translation",
     "Automated neural translation across 100+ global spoken languages via integrated deep-translator engine."),
    ("collection-play-fill", "Batch Processing Queue Studio",
     "Queue dozens of video and audio files with automated sequential processing, format export, and row controls."),
    ("bar-chart-line-fill", "Real-Time Telemetry & Progress",
     "Live monitoring of speed multipliers (RTF), memory consumption, segment counts, and transcript preview studio."),
    ("file-earmark-code-fill", "Multi-Format Subtitle Export",
     "Export SRT, WebVTT, ASS (SubStation Alpha), and plain text transcripts formatted cleanly with word timestamps."),
]


class AboutPage(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.worker: UpdateCheckWorker | None = None
        self._update_found = None

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"QScrollArea {{ border: none; background: {DARK_BG}; }}")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        content = QWidget()
        content.setStyleSheet(f"background: {DARK_BG};")
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        layout.addWidget(self._build_hero())
        layout.addWidget(self._build_features())
        layout.addWidget(self._build_tech_stack())

        footer = QLabel(f"{APP_NAME} Studio Enterprise Edition  •  100% Local & Private")
        footer.setAlignment(Qt.AlignCenter)
        footer.setStyleSheet(f"color: {TEXT_SUB}; font-size: 11px; font-weight: 700;")
        layout.addWidget(footer)
        layout.addStretch(1)

    def _build_hero(self) -> QFrame:
        hero = QFrame()
        hero.setStyleSheet(f"background-color: {CARD_BG}; border: 1px solid {BORDER_COLOR}; border-radius: 14px;")
        v = QVBoxLayout(hero)
        v.setContentsMargins(24, 24, 24, 24)

        top = QHBoxLayout()
        if LOGO_PATH.exists():
            logo_lbl = QLabel()
            logo_lbl.setPixmap(QPixmap(str(LOGO_PATH)).scaled(100, 100, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            top.addWidget(logo_lbl)

        brand = QVBoxLayout()
        name_lbl = QLabel(f"{APP_NAME}  v{APP_VER}")
        name_lbl.setStyleSheet(f"color: {TEXT_MAIN}; font-size: 24px; font-weight: 700; border: none;")
        brand.addWidget(name_lbl)
        tagline_lbl = QLabel("Enterprise AI Subtitle Generator, Translator & Audio Intelligence Studio")
        tagline_lbl.setStyleSheet(f"color: {ACCENT_CYAN}; font-size: 13px; font-weight: 700; border: none;")
        brand.addWidget(tagline_lbl)
        desc_lbl = QLabel("Local, private, high-performance transcription powered by faster-whisper, Vulkan GPU acceleration & PySide6.")
        desc_lbl.setWordWrap(True)
        desc_lbl.setStyleSheet(f"color: {TEXT_SUB}; font-size: 12px; border: none;")
        brand.addWidget(desc_lbl)
        top.addLayout(brand, 1)
        v.addLayout(top)

        status_box = QFrame()
        status_box.setStyleSheet(f"background-color: {INPUT_BG}; border: 1px solid {BORDER_COLOR}; border-radius: 8px;")
        sb = QHBoxLayout(status_box)
        gpu_display = GPU_NAME or ("CUDA" if DEVICE == "cuda" else "CPU")
        status_lbl = QLabel(f"Active Compute Mode: {DEVICE_LABEL}   •   Engine: {BACKEND or 'Native'}   •   Precision: {COMPUTE_TYPE}")
        status_lbl.setStyleSheet(f"color: {SUCCESS}; font-size: 12px; font-weight: 700; border: none;")
        sb.addWidget(status_lbl)
        v.addWidget(status_box)

        upd_row = QHBoxLayout()
        self.update_status_lbl = QLabel(f"Current version: v{APP_VER}")
        self.update_status_lbl.setStyleSheet(f"color: {TEXT_SUB}; font-size: 12px; border: none;")
        upd_row.addWidget(self.update_status_lbl)
        self.check_update_btn = QPushButton("  Check for Updates")
        self.check_update_btn.setIcon(get_bs_icon("arrow-repeat", color="#FFFFFF", size=14))
        self.check_update_btn.setStyleSheet(BTN_SECONDARY_STYLE)
        self.check_update_btn.clicked.connect(self._check_for_updates)
        upd_row.addWidget(self.check_update_btn)
        upd_row.addStretch(1)
        v.addLayout(upd_row)

        return hero

    def _build_features(self) -> QFrame:
        card, body = make_card("Core Features & Capabilities", icon_name="rocket-takeoff-fill")
        grid = QGridLayout()
        for idx, (icon_name, title, desc) in enumerate(_FEATURES):
            row, col = divmod(idx, 2)
            box = QFrame()
            box.setStyleSheet(f"background-color: {INPUT_BG}; border: 1px solid {BORDER_COLOR}; border-radius: 10px;")
            bv = QVBoxLayout(box)
            hdr = QHBoxLayout()
            icon = get_bs_icon(icon_name, color=ACCENT_CYAN, size=20)
            if icon:
                icon_lbl = QLabel()
                icon_lbl.setPixmap(icon.pixmap(20, 20))
                icon_lbl.setStyleSheet("border: none;")
                hdr.addWidget(icon_lbl)
            title_lbl = QLabel(title)
            title_lbl.setStyleSheet(f"color: {TEXT_MAIN}; font-size: 14px; font-weight: 700; border: none;")
            hdr.addWidget(title_lbl)
            hdr.addStretch(1)
            bv.addLayout(hdr)
            desc_lbl = QLabel(desc)
            desc_lbl.setWordWrap(True)
            desc_lbl.setStyleSheet(f"color: {TEXT_SUB}; font-size: 12px; border: none;")
            bv.addWidget(desc_lbl)
            grid.addWidget(box, row, col)
            grid.setColumnStretch(col, 1)
        body.addLayout(grid)
        return card

    def _build_tech_stack(self) -> QFrame:
        card, body = make_card("Underlying Technical Architecture", icon_name="gear-wide-connected")
        techs = [
            ("Core Framework", "Python 3.14 + PySide6 (Qt for Python)"),
            ("AI Inference Engine", "faster-whisper (CTranslate2) & whisper.cpp (Vulkan)"),
            ("Media Decoder", f"FFmpeg ({'Auto Detected' if FFMPEG_PATH else 'Missing'})"),
            ("UI Icon Renderer", "Bootstrap Icons v1.11.3 (native Qt SVG)"),
            ("Primary GPU Engine", GPU_NAME or "System Standard"),
            ("Local Workspace", str(DATA_DIR)),
        ]
        for i, (k, val) in enumerate(techs):
            r = QFrame()
            r.setStyleSheet(f"background-color: {'#131825' if i % 2 == 0 else INPUT_BG}; border: 1px solid {BORDER_COLOR}; border-radius: 6px;")
            h = QHBoxLayout(r)
            k_lbl = QLabel(k)
            k_lbl.setFixedWidth(180)
            k_lbl.setStyleSheet(f"color: {ACCENT_CYAN}; font-size: 12px; font-weight: 700; border: none;")
            h.addWidget(k_lbl)
            v_lbl = QLabel(val)
            v_lbl.setStyleSheet(f"color: {TEXT_MAIN}; font-size: 12px; border: none;")
            h.addWidget(v_lbl, 1)
            body.addWidget(r)
        return card

    def _check_for_updates(self):
        if self.worker is not None and self.worker.isRunning():
            return
        self.check_update_btn.setEnabled(False)
        self.update_status_lbl.setText("Checking for updates…")
        self.worker = UpdateCheckWorker()
        self.worker.result.connect(self._on_update_result)
        self.worker.start()

    def _on_update_result(self, found):
        self.check_update_btn.setEnabled(True)
        if found:
            latest, url, notes, assets = found
            self._update_found = found
            self.main_window._update_found = found
            self.main_window.ver_badge_btn.setText(f"Update v{latest} available")
            self.main_window.ver_badge_btn.setVisible(True)
            self.update_status_lbl.setText(f"Update available: v{latest}  (you're on v{APP_VER})")
            self.check_update_btn.setText("View Update")
            try:
                self.check_update_btn.clicked.disconnect()
            except Exception:
                pass
            self.check_update_btn.clicked.connect(lambda: self.main_window.show_update_dialog(*found))
        else:
            self.update_status_lbl.setText(f"You're on the latest version (v{APP_VER}).")
