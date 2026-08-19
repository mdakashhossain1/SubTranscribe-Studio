"""System hardware & acceleration telemetry. Qt port of
SubGenApp._render_telemetry_page (subgen.py:2543-2591), fed by the
shared TelemetryWorker (main_window.telemetry_worker) instead of a
per-tick root.after(0, ...) callback.
"""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QScrollArea

from ..backend.device import GPU_NAME, DEVICE
from ..backend.models import get_dir_size
from ..backend.transcribe import BACKEND
from ..config import DARK_BG, INPUT_BG, BORDER_COLOR, TEXT_MAIN, TEXT_SUB, ACCENT, ACCENT_CYAN, SUCCESS, WARNING, ERROR_C, MODELS_DIR
from ..icons import get_bs_icon
from ..paths import FFMPEG_PATH
from ..widgets.cards import make_card


class TelemetryPage(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window

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
        layout.setSpacing(10)

        card, body = make_card("System Hardware & Acceleration Telemetry", icon_name="activity")

        static_row = QHBoxLayout()
        gpu_val = GPU_NAME or ("CUDA Available" if DEVICE == "cuda" else "High-Speed CPU Engine")
        static_row.addWidget(self._tel_card("cpu-fill", "Primary GPU", gpu_val, "Device 0", SUCCESS))
        static_row.addWidget(self._tel_card("gear-fill", "Compute Backend", BACKEND or "None", f"Device: {DEVICE}", ACCENT))
        static_row.addWidget(self._tel_card(
            "film", "FFmpeg Binary", FFMPEG_PATH.split("\\")[-1].split("/")[-1] if FFMPEG_PATH else "Missing",
            "Audio Decoding Engine", WARNING))
        static_row.addWidget(self._tel_card(
            "database-fill", "Model Local Storage", f"{get_dir_size(MODELS_DIR) / (1024 ** 2):.1f} MB",
            "Local Cache Directory", ACCENT_CYAN))
        body.addLayout(static_row)

        live_title = QLabel("Live System Load")
        live_title.setStyleSheet(f"color: {TEXT_MAIN}; font-size: 14px; font-weight: 700; border: none;")
        body.addWidget(live_title)

        live_row = QHBoxLayout()
        self.cpu_val_lbl = self._tel_value_only(live_row, "cpu-fill", "CPU Usage", ACCENT_CYAN)
        self.ram_val_lbl = self._tel_value_only(live_row, "hdd-fill", "RAM Usage", SUCCESS)
        self.gpu_val_lbl = self._tel_value_only(live_row, "gpu-card", "GPU Load", ACCENT)
        self.disk_val_lbl = self._tel_value_only(live_row, "device-hdd-fill", "Disk Usage", WARNING)
        self.temp_val_lbl = self._tel_value_only(live_row, "thermometer-half", "Temperature", ERROR_C)
        body.addLayout(live_row)

        layout.addWidget(card)
        layout.addStretch(1)

        main_window.telemetry_worker.stats.connect(self._on_stats)

    def _tel_header(self, v: QVBoxLayout, icon_name: str, label: str):
        hdr = QHBoxLayout()
        icon = get_bs_icon(icon_name, color=ACCENT_CYAN, size=16)
        if icon:
            icon_lbl = QLabel()
            icon_lbl.setPixmap(icon.pixmap(16, 16))
            icon_lbl.setStyleSheet("border: none;")
            hdr.addWidget(icon_lbl)
        lbl = QLabel(label)
        lbl.setStyleSheet(f"color: {TEXT_SUB}; font-size: 12px; font-weight: 700; border: none;")
        hdr.addWidget(lbl)
        hdr.addStretch(1)
        v.addLayout(hdr)

    def _tel_card(self, icon_name: str, label: str, value: str, subtext: str, color: str) -> QFrame:
        f = QFrame()
        f.setStyleSheet(f"background-color: {INPUT_BG}; border: 1px solid {BORDER_COLOR}; border-radius: 10px;")
        v = QVBoxLayout(f)
        v.setContentsMargins(14, 12, 14, 12)
        self._tel_header(v, icon_name, label)
        val_lbl = QLabel(value)
        val_lbl.setStyleSheet(f"color: {color}; font-size: 20px; font-weight: 700; border: none;")
        v.addWidget(val_lbl)
        sub_lbl = QLabel(subtext)
        sub_lbl.setStyleSheet(f"color: {TEXT_SUB}; font-size: 11px; border: none;")
        v.addWidget(sub_lbl)
        return f

    def _tel_value_only(self, row: QHBoxLayout, icon_name: str, label: str, color: str) -> QLabel:
        f = QFrame()
        f.setStyleSheet(f"background-color: {INPUT_BG}; border: 1px solid {BORDER_COLOR}; border-radius: 10px;")
        v = QVBoxLayout(f)
        v.setContentsMargins(14, 12, 14, 12)
        self._tel_header(v, icon_name, label)
        val_lbl = QLabel("—")
        val_lbl.setStyleSheet(f"color: {color}; font-size: 20px; font-weight: 700; border: none;")
        v.addWidget(val_lbl)
        sub_lbl = QLabel("Live")
        sub_lbl.setStyleSheet(f"color: {TEXT_SUB}; font-size: 11px; border: none;")
        v.addWidget(sub_lbl)
        row.addWidget(f)
        return val_lbl

    def _on_stats(self, s: dict):
        self.cpu_val_lbl.setText(s.get("cpu_str", "—"))
        self.ram_val_lbl.setText(s.get("ram_str", "—"))
        self.gpu_val_lbl.setText(s.get("gpu_str", "—"))
        self.disk_val_lbl.setText(s.get("disk_str", "—"))
        self.temp_val_lbl.setText(s.get("temp_str", "—"))
