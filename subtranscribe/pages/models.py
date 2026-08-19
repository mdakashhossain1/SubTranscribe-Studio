"""Model manager: download/delete/select Whisper model weights. Qt port of
SubGenApp._render_models + _download_specific_model + _delete_specific_model
(subgen.py:2209-2309), wired to DownloadWorker instead of a raw
threading.Thread + root.after(0, ...).
"""
from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QMessageBox, QProgressBar,
)

from ..backend.models import is_model_downloaded, delete_model_files
from ..config import (
    MODEL_SIZES, DARK_BG, CARD_BG, BORDER_COLOR, TEXT_MAIN, TEXT_SUB,
    ACCENT, ACCENT_HOVER, ACCENT_CYAN, SUCCESS, ERROR_C, INPUT_BG,
)
from ..icons import get_bs_icon
from ..widgets.cards import make_card
from ..widgets.styles import BTN_PRIMARY_STYLE, BTN_DANGER_STYLE, PROGRESSBAR_STYLE
from ..workers import DownloadWorker

# (tag, description) per model — same copy as subgen.py:2220-2229; size/VRAM
# strings are derived live from config.MODEL_SIZES_MB/MODEL_VRAM_MB below
# instead of being duplicated as separate literals.
_MODEL_COPY = {
    "large-v3":        ("Best Accuracy", "Recommended for production subtitles & complex multi-speaker audio."),
    "large-v3-turbo":  ("8x Speed + High Accuracy", "Optimized large model for ultra-fast GPU processing."),
    "distil-large-v3": ("Distilled Speed", "Distilled model delivering fast inference with low memory usage."),
    "large-v2":        ("Legacy Large", "Previous generation Whisper large model."),
    "medium":          ("Balanced", "Great balance between accuracy and speed for mid-range GPUs."),
    "small":           ("Lightweight", "Lightweight model for laptops and quick drafts."),
    "base":            ("Very Fast", "Fast low-resource model for simple speech."),
    "tiny":            ("Fastest", "Smallest model footprint for rapid testing."),
}


class ModelsPage(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.worker: DownloadWorker | None = None
        self._row_widgets = {}  # model_name -> dict of widgets to update live

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

        card, body = make_card("Whisper AI Model Manager")
        desc = QLabel("Download and manage local faster-whisper and GGML model weights for offline GPU & CPU transcription.")
        desc.setStyleSheet(f"color: {TEXT_SUB}; font-size: 12px; border: none;")
        desc.setWordWrap(True)
        body.addWidget(desc)
        layout.addWidget(card)

        for name in MODEL_SIZES:
            layout.addWidget(self._build_model_row(name))

        layout.addStretch(1)

    def _build_model_row(self, name: str) -> QWidget:
        from ..config import MODEL_SIZES_MB, MODEL_VRAM_MB
        from ..backend.formatting import _fmt_size

        tag, desc = _MODEL_COPY.get(name, ("", ""))
        size_str = _fmt_size(MODEL_SIZES_MB.get(name, 0) * 1024 * 1024)
        vram_mb = MODEL_VRAM_MB.get(name, 0)
        vram_str = f"~{vram_mb / 1024:.0f} GB VRAM" if vram_mb >= 1000 else f"~{vram_mb} MB VRAM"

        row_card, body = make_card("")
        row = QHBoxLayout()
        body.addLayout(row)

        left = QVBoxLayout()
        name_lbl = QLabel(name)
        name_lbl.setStyleSheet(f"color: {TEXT_MAIN}; font-size: 15px; font-weight: 700; border: none;")
        left.addWidget(name_lbl)
        meta_lbl = QLabel(f"{tag}  •  Download Size: {size_str}  •  Memory: {vram_str}")
        meta_lbl.setStyleSheet(f"color: {ACCENT_CYAN}; font-size: 12px; font-weight: 700; border: none;")
        left.addWidget(meta_lbl)
        desc_lbl = QLabel(desc)
        desc_lbl.setWordWrap(True)
        desc_lbl.setStyleSheet(f"color: {TEXT_SUB}; font-size: 12px; border: none;")
        left.addWidget(desc_lbl)
        row.addLayout(left, 1)

        right = QHBoxLayout()
        status_lbl = QLabel()
        status_lbl.setStyleSheet(f"font-size: 12px; font-weight: 700; border: none;")
        right.addWidget(status_lbl)

        select_btn = QPushButton("  Select")
        select_btn.setIcon(get_bs_icon("check-circle-fill", color="#FFFFFF", size=14))
        select_btn.setStyleSheet(BTN_PRIMARY_STYLE)
        select_btn.clicked.connect(lambda: self._select_model(name))

        delete_btn = QPushButton("  Delete")
        delete_btn.setIcon(get_bs_icon("trash-fill", color="#EF4444", size=14))
        delete_btn.setStyleSheet(BTN_DANGER_STYLE)
        delete_btn.clicked.connect(lambda: self._delete_model(name))

        download_btn = QPushButton("  Download")
        download_btn.setIcon(get_bs_icon("cloud-download-fill", color="#FFFFFF", size=14))
        download_btn.setStyleSheet(BTN_PRIMARY_STYLE)
        download_btn.clicked.connect(lambda: self._download_model(name))

        right.addWidget(select_btn)
        right.addWidget(delete_btn)
        right.addWidget(download_btn)
        row.addLayout(right)

        progress_bar = QProgressBar()
        progress_bar.setRange(0, 100)
        progress_bar.setStyleSheet(PROGRESSBAR_STYLE)
        progress_bar.setVisible(False)
        body.addWidget(progress_bar)

        progress_lbl = QLabel()
        progress_lbl.setStyleSheet(f"color: {TEXT_SUB}; font-size: 11px; border: none;")
        progress_lbl.setVisible(False)
        body.addWidget(progress_lbl)

        self._row_widgets[name] = {
            "status_lbl": status_lbl, "select_btn": select_btn, "delete_btn": delete_btn,
            "download_btn": download_btn, "progress_bar": progress_bar, "progress_lbl": progress_lbl,
        }
        self._refresh_row(name)
        return row_card

    def _refresh_row(self, name: str):
        w = self._row_widgets[name]
        downloaded = is_model_downloaded(name)
        w["status_lbl"].setText("Downloaded" if downloaded else "")
        w["status_lbl"].setStyleSheet(f"color: {SUCCESS if downloaded else TEXT_SUB}; font-size: 12px; font-weight: 700; border: none;")
        w["select_btn"].setVisible(downloaded)
        w["delete_btn"].setVisible(downloaded)
        w["download_btn"].setVisible(not downloaded)

    def _select_model(self, name: str):
        self.main_window.state.model = name
        self.main_window.switch_page("Transcribe")

    def _delete_model(self, name: str):
        reply = QMessageBox.question(
            self, "Delete Model",
            f"Are you sure you want to delete local model weights for '{name}'?\n\nThis will free up disk space on your PC.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        ok = delete_model_files(name)
        self.main_window.state.set_status(
            f"Model '{name}' deleted from disk." if ok else f"Could not delete model '{name}'.",
            "" if ok else "",
        )
        self._refresh_row(name)

    def _download_model(self, name: str):
        if self.worker is not None and self.worker.isRunning():
            QMessageBox.information(self, "Busy", "Please wait for the current download to finish.")
            return

        w = self._row_widgets[name]
        w["download_btn"].setEnabled(False)
        w["download_btn"].setText("  Downloading…")
        w["progress_bar"].setVisible(True)
        w["progress_bar"].setValue(0)
        w["progress_lbl"].setVisible(True)
        w["progress_lbl"].setText("")

        self.worker = DownloadWorker(model_size=name)
        self.worker.progress.connect(lambda p, n=name: self._on_progress(n, p))
        self.worker.finished_ok.connect(lambda n: self._on_finished(n))
        self.worker.error.connect(lambda msg, n=name: self._on_error(n, msg))
        self.worker.start()

    def _on_progress(self, name: str, payload: dict):
        w = self._row_widgets.get(name)
        if not w:
            return
        pct = payload.get("pct", 0.0)
        w["progress_bar"].setValue(int(pct * 100))
        label = payload.get("dl_str") or payload.get("status") or ""
        speed = payload.get("speed_str")
        if speed:
            label += f"  |  {speed}"
        w["progress_lbl"].setText(label)

    @Slot(str)
    def _on_finished(self, name: str):
        w = self._row_widgets.get(name)
        if w:
            w["download_btn"].setEnabled(True)
            w["download_btn"].setText("  Download")
            w["progress_bar"].setVisible(False)
            w["progress_lbl"].setVisible(False)
        self.main_window.state.set_status(f"{name} downloaded successfully!", "")
        self._refresh_row(name)

    @Slot(str)
    def _on_error(self, name: str, msg: str):
        w = self._row_widgets.get(name)
        if w:
            w["download_btn"].setEnabled(True)
            w["download_btn"].setText("  Download")
            w["progress_bar"].setVisible(False)
            w["progress_lbl"].setVisible(False)
        self.main_window.state.set_status(f"Download failed: {msg}", "")
        QMessageBox.critical(self, "Download Failed", msg)
