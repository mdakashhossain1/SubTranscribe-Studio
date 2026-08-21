"""Dashboard: the full two-column "studio" workspace — Qt port of
SubGenApp._render_dashboard (subgen.py:2000-2028) and its sub-builders
(_settings/_advanced_settings/_progress/_preview, subgen.py:2855-3210).
Visual reference: image/dashboard.png (committed screenshot of the original
app). Left column configures + starts a run; right column shows live
stat-tile telemetry and a segment-by-segment transcript table with an
audio/waveform player — all fed by the same TranscribeWorker/WaveformWorker/
AudioPlayer already proven in pages/transcribe.py, just rendered richer.
"""
from pathlib import Path

from PySide6.QtCore import Qt, Slot, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QComboBox, QProgressBar, QFileDialog, QMessageBox, QScrollArea,
    QCheckBox, QDoubleSpinBox, QSpinBox, QFrame, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView,
)

from ..backend.audio import AudioPlayer
from ..backend.device import (
    DEVICE, USE_WHISPERCPP, DEVICE_LABEL, DEVICE_COLOR, recommend_best_settings,
)
from ..backend.formatting import _fmt_time_short
from ..backend.models import is_model_downloaded
from ..backend.subtitles import WRITERS, write_ass
from ..backend.transcribe import BACKEND
from ..backend.translate import HAS_TRANSLATOR
from ..config import (
    MODEL_SIZES, OUTPUT_FORMATS, LANGUAGE_MAP,
    TEXT_MAIN, TEXT_SUB, INPUT_BG, BORDER_COLOR, ACCENT, ACCENT_CYAN,
    SUCCESS, ERROR_C, WARNING, DARK_BG, CARD_BG,
)
from ..icons import get_bs_icon
from ..paths import FFMPEG_PATH
from ..widgets.cards import make_card, make_stat_tile, LiveStatusIndicator

from ..widgets.language_select import LanguageSelect
from ..widgets.styles import (
    COMBO_STYLE, LINEEDIT_STYLE, BTN_PRIMARY_STYLE, BTN_SECONDARY_STYLE,
    PROGRESSBAR_STYLE, FIELD_LABEL_STYLE, SCROLLBAR_STYLE, CHECKBOX_STYLE,
)


from ..widgets.waveform import WaveformBar
from ..workers import TranscribeWorker, WaveformWorker, DownloadWorker
from .models import _MODEL_COPY


def _field_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(FIELD_LABEL_STYLE)
    return lbl


def _pill(text: str, color: str, icon_name: str | None = None) -> QFrame:
    pill = QFrame()
    pill.setStyleSheet(f"background-color: {INPUT_BG}; border: 1px solid {BORDER_COLOR}; border-radius: 6px;")
    row = QHBoxLayout(pill)
    row.setContentsMargins(10, 5, 10, 5)
    row.setSpacing(6)
    if icon_name:
        icon = get_bs_icon(icon_name, color=color, size=13)
        if icon:
            icon_lbl = QLabel()
            icon_lbl.setPixmap(icon.pixmap(13, 13))
            icon_lbl.setStyleSheet("border: none; background: transparent;")
            row.addWidget(icon_lbl)
    lbl = QLabel(text)
    lbl.setStyleSheet(f"color: {color}; font-size: 11px; font-weight: 700; border: none; background: transparent;")
    row.addWidget(lbl)
    return pill


class DashboardPage(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.state = main_window.state
        self.worker: TranscribeWorker | None = None
        self.download_worker: DownloadWorker | None = None
        self.all_segs: list[dict] = []
        self._last_out_path = None

        self.audio_player = AudioPlayer()
        self.waveform_worker: WaveformWorker | None = None
        self._playback_timer = QTimer(self)
        self._playback_timer.setInterval(80)
        self._playback_timer.timeout.connect(self._tick_playback)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(f"QScrollArea {{ border: none; background: {DARK_BG}; }} {SCROLLBAR_STYLE}")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        content = QWidget()
        content.setStyleSheet(f"background: {DARK_BG};")
        scroll.setWidget(content)
        columns = QHBoxLayout(content)
        columns.setContentsMargins(20, 20, 20, 20)
        columns.setSpacing(16)

        left_col = QVBoxLayout()
        left_col.setSpacing(16)
        left_col.addWidget(self._build_config_card())
        left_col.addWidget(self._build_advanced_card())
        left_col.addLayout(self._build_generate_row())
        left_col.addStretch(1)
        columns.addLayout(left_col, 2)

        right_col = QVBoxLayout()
        right_col.setSpacing(16)
        right_col.addWidget(self._build_telemetry_card())
        right_col.addWidget(self._build_transcript_card(), 1)
        columns.addLayout(right_col, 3)

        self._refresh_model_status()

    # ── 1. Configuration & AI Model ─────────────────────────────────
    def _build_config_card(self) -> QWidget:
        card, body = make_card("1. Configuration & AI Model", icon_name="gear-wide-connected")

        row1 = QHBoxLayout()

        row1.setSpacing(12)
        self.model_combo = self._labeled_combo(row1, "Whisper Model", MODEL_SIZES)
        self.model_combo.currentTextChanged.connect(self._on_model_changed)
        self.src_combo = self._labeled_lang_select(row1, "Source Language", list(LANGUAGE_MAP.keys()))
        self.src_combo.valueChanged.connect(lambda v: setattr(self.state, "src_lang", v))
        body.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(12)
        self.tgt_combo = self._labeled_lang_select(row2, "Translate To", ["None"] + list(LANGUAGE_MAP.keys())[1:])
        self.tgt_combo.valueChanged.connect(lambda v: setattr(self.state, "tgt_lang", v))
        self.fmt_combo = self._labeled_combo(row2, "Output Format", OUTPUT_FORMATS)
        self.fmt_combo.currentTextChanged.connect(lambda v: setattr(self.state, "fmt", v))
        body.addLayout(row2)

        pills_row = QHBoxLayout()
        pills_row.setSpacing(8)
        tag, _ = _MODEL_COPY.get(self.state.model, ("Best Accuracy", ""))
        self.accuracy_pill_lbl = self._pill_label(pills_row, f"Accuracy: {tag}", ACCENT_CYAN)
        hw_label = "GPU (CUDA)" if DEVICE == "cuda" else ("GPU (Vulkan)" if USE_WHISPERCPP else "CPU")
        pills_row.addWidget(_pill(f"Hardware: {hw_label}", WARNING, "cpu-fill"))
        pills_row.addStretch(1)
        body.addLayout(pills_row)

        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        self.model_status_lbl = QLabel("")
        self.model_status_lbl.setStyleSheet("border: none;")
        status_row.addWidget(self.model_status_lbl)
        status_row.addStretch(1)
        self.model_action_btn = QPushButton("Select")
        self.model_action_btn.setStyleSheet(BTN_PRIMARY_STYLE)
        self.model_action_btn.clicked.connect(self._on_model_action)
        status_row.addWidget(self.model_action_btn)
        body.addLayout(status_row)

        ok_row = QHBoxLayout()
        ok_row.setSpacing(8)
        ok_row.addWidget(_pill("Translator — OK" if HAS_TRANSLATOR else "Translator — Missing",
                                SUCCESS if HAS_TRANSLATOR else WARNING, "check-circle-fill"))
        ok_row.addWidget(_pill("FFmpeg — OK" if FFMPEG_PATH else "FFmpeg — Missing",
                                SUCCESS if FFMPEG_PATH else WARNING, "check-circle-fill"))
        ok_row.addWidget(_pill("Backend — OK" if BACKEND else "Backend — Missing",
                                SUCCESS if BACKEND else WARNING, "check-circle-fill"))
        ok_row.addStretch(1)
        body.addLayout(ok_row)

        return card

    def _labeled_combo(self, row: QHBoxLayout, label: str, values: list[str]) -> QComboBox:
        col = QVBoxLayout()
        col.setSpacing(4)
        col.setContentsMargins(0, 0, 0, 0)
        col.addWidget(_field_label(label))
        combo = QComboBox()
        combo.addItems(values)
        combo.setStyleSheet(COMBO_STYLE)
        col.addWidget(combo)
        row.addLayout(col, 1)
        return combo

    def _labeled_lang_select(self, row: QHBoxLayout, label: str, values: list[str]) -> LanguageSelect:
        col = QVBoxLayout()
        col.setSpacing(4)
        col.setContentsMargins(0, 0, 0, 0)
        col.addWidget(_field_label(label))
        combo = LanguageSelect(values)
        combo.setStyleSheet(COMBO_STYLE)
        col.addWidget(combo)
        row.addLayout(col, 1)
        return combo


    def _pill_label(self, row: QHBoxLayout, text: str, color: str) -> QLabel:
        """Same visual as _pill() but keeps a direct reference to the text
        label (not via findChild, which would ambiguously match the icon
        QLabel too) so callers can update it live."""
        pill = QFrame()
        pill.setStyleSheet(f"background-color: {INPUT_BG}; border: 1px solid {BORDER_COLOR}; border-radius: 6px;")
        inner = QHBoxLayout(pill)
        inner.setContentsMargins(10, 5, 10, 5)
        inner.setSpacing(6)
        icon = get_bs_icon("star-fill", color=color, size=13)
        if icon:
            icon_lbl = QLabel()
            icon_lbl.setPixmap(icon.pixmap(13, 13))
            icon_lbl.setStyleSheet("border: none; background: transparent;")
            inner.addWidget(icon_lbl)
        text_lbl = QLabel(text)
        text_lbl.setStyleSheet(f"color: {color}; font-size: 11px; font-weight: 700; border: none; background: transparent;")
        inner.addWidget(text_lbl)
        row.addWidget(pill)
        return text_lbl

    def _on_model_changed(self, model_name: str):
        self.state.model = model_name
        tag, _ = _MODEL_COPY.get(model_name, ("", ""))
        self.accuracy_pill_lbl.setText(f"Accuracy: {tag}")
        self._refresh_model_status()

    def _refresh_model_status(self):
        name = self.model_combo.currentText()
        downloaded = is_model_downloaded(name)
        if downloaded:
            self.model_status_lbl.setText(f"{name} — Downloaded")
            self.model_status_lbl.setStyleSheet(f"color: {SUCCESS}; font-size: 12px; font-weight: 700; border: none;")
            self.model_action_btn.setText("Ready")
            self.model_action_btn.setEnabled(False)
        else:
            self.model_status_lbl.setText(f"{name} — Not downloaded")
            self.model_status_lbl.setStyleSheet(f"color: {TEXT_SUB}; font-size: 12px; font-weight: 700; border: none;")
            self.model_action_btn.setText("Download")
            self.model_action_btn.setEnabled(True)

    def _on_model_action(self):
        name = self.model_combo.currentText()
        if self.download_worker is not None and self.download_worker.isRunning():
            return
        self.model_action_btn.setEnabled(False)
        self.model_action_btn.setText("Downloading…")
        self.download_worker = DownloadWorker(model_size=name)
        self.download_worker.progress.connect(self._on_model_download_progress)
        self.download_worker.finished_ok.connect(lambda n: self._refresh_model_status())
        self.download_worker.error.connect(lambda msg: (self._refresh_model_status(), QMessageBox.critical(self, "Download Failed", msg)))
        self.download_worker.start()

    def _on_model_download_progress(self, payload: dict):
        pct = payload.get("pct", 0.0)
        self.model_action_btn.setText(f"{int(pct * 100)}%…")

    # ── 2. Advanced Settings ─────────────────────────────────────────
    def _build_advanced_card(self) -> QWidget:
        card, body = make_card("2. Advanced Settings", icon_name="lightning-charge-fill")
        hdr = card.layout().itemAt(0).layout()

        reset_btn = QPushButton("  Reset to Best (Auto)")
        reset_btn.setIcon(get_bs_icon("stars", color=ACCENT, size=14))
        reset_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {CARD_BG}; color: {ACCENT}; border: 1px solid {ACCENT};
                border-radius: 6px; padding: 6px 12px; font-weight: 700; font-size: 11px;
            }}
            QPushButton:hover {{ background-color: {INPUT_BG}; }}
        """)
        reset_btn.clicked.connect(self._reset_to_best)
        hdr.addWidget(reset_btn)

        row1 = QHBoxLayout()

        row1.setSpacing(12)
        self.compute_combo = self._labeled_combo(row1, "Compute Type",
            ["float16", "int8", "int8_float16", "float32"] if DEVICE == "cuda" else ["int8", "float32"])

        col_beam = QVBoxLayout()
        col_beam.setSpacing(4)
        col_beam.setContentsMargins(0, 0, 0, 0)
        col_beam.addWidget(_field_label("Beam Size"))
        self.beam_spin = QSpinBox()
        self.beam_spin.setRange(1, 10)
        self.beam_spin.setValue(self.state.beam_size)
        self.beam_spin.setStyleSheet(LINEEDIT_STYLE)
        col_beam.addWidget(self.beam_spin)
        row1.addLayout(col_beam, 1)

        col_bestof = QVBoxLayout()
        col_bestof.setSpacing(4)
        col_bestof.setContentsMargins(0, 0, 0, 0)
        col_bestof.addWidget(_field_label("Best Of"))
        self.bestof_spin = QSpinBox()
        self.bestof_spin.setRange(1, 10)
        self.bestof_spin.setValue(self.state.best_of)
        self.bestof_spin.setStyleSheet(LINEEDIT_STYLE)
        col_bestof.addWidget(self.bestof_spin)
        row1.addLayout(col_bestof, 1)

        col_temp = QVBoxLayout()
        col_temp.setSpacing(4)
        col_temp.setContentsMargins(0, 0, 0, 0)
        col_temp.addWidget(_field_label("Temperature"))
        self.temp_spin = QDoubleSpinBox()
        self.temp_spin.setRange(0.0, 1.0)
        self.temp_spin.setSingleStep(0.1)
        self.temp_spin.setValue(self.state.temperature)
        self.temp_spin.setStyleSheet(LINEEDIT_STYLE)
        col_temp.addWidget(self.temp_spin)
        row1.addLayout(col_temp, 1)
        body.addLayout(row1)

        row2 = QHBoxLayout()
        col_words = QVBoxLayout()
        col_words.setSpacing(4)
        col_words.setContentsMargins(0, 0, 0, 0)
        col_words.addWidget(_field_label("Words / Subtitle"))
        self.max_words_spin = QSpinBox()
        self.max_words_spin.setRange(1, 12)
        self.max_words_spin.setValue(self.state.max_words)
        self.max_words_spin.setStyleSheet(LINEEDIT_STYLE)
        col_words.addWidget(self.max_words_spin)
        row2.addLayout(col_words, 1)
        body.addLayout(row2)


        tog_row = QHBoxLayout()
        tog_row.setSpacing(16)
        self.cond_prev_check = QCheckBox("Condition On Previous Text")
        self.cond_prev_check.setStyleSheet(CHECKBOX_STYLE)
        tog_row.addWidget(self.cond_prev_check)
        self.word_ts_check = QCheckBox("Word Timestamps")
        self.word_ts_check.setChecked(self.state.word_timestamps)
        self.word_ts_check.setStyleSheet(CHECKBOX_STYLE)
        tog_row.addWidget(self.word_ts_check)
        tog_row.addStretch(1)
        body.addLayout(tog_row)


        return card

    def _reset_to_best(self):
        """Mechanical port of SubGenApp._reset_advanced_to_best via
        backend.device.recommend_best_settings() — same hardware-budget math."""
        rec = recommend_best_settings()
        self.model_combo.setCurrentText(rec["model"])
        idx = self.compute_combo.findText(rec["compute_type"])
        if idx >= 0:
            self.compute_combo.setCurrentIndex(idx)
        self.beam_spin.setValue(rec["beam_size"])
        self.bestof_spin.setValue(rec["best_of"])
        self.temp_spin.setValue(rec["temperature"])
        self.cond_prev_check.setChecked(rec["condition_on_previous_text"])
        self.word_ts_check.setChecked(rec["word_timestamps"])
        self.max_words_spin.setValue(rec["max_words"])

    # ── Generate button ──────────────────────────────────────────────
    def _build_generate_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(12)

        browse_btn = QPushButton("  Select Media File")
        browse_btn.setIcon(get_bs_icon("folder2-open", color="#FFFFFF", size=16))
        browse_btn.setStyleSheet(BTN_SECONDARY_STYLE)
        browse_btn.setFixedHeight(44)
        browse_btn.clicked.connect(self._browse_file)
        row.addWidget(browse_btn, 1)

        self.gen_btn = QPushButton("  Generate Subtitles")
        self.gen_btn.setIcon(get_bs_icon("play-fill", color="#FFFFFF", size=16))
        self.gen_btn.setStyleSheet(BTN_PRIMARY_STYLE)
        self.gen_btn.setFixedHeight(44)
        self.gen_btn.clicked.connect(self._on_generate_clicked)
        row.addWidget(self.gen_btn, 1)
        return row


    def _browse_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Media File", "",
            "Media Files (*.mp4 *.mkv *.avi *.mov *.mp3 *.wav *.flac *.aac *.m4a);;All Files (*)"
        )
        if path:
            self.state.input_file = path
            self.status_lbl.setText(f"Loaded file: {Path(path).name}")
            self.status_lbl.setStyleSheet(f"color: {TEXT_MAIN}; font-size: 12px; border: none;")
            self._load_waveform(path)


    # ── 3. Real-Time Progress & Telemetry ────────────────────────────
    def _build_telemetry_card(self) -> QWidget:
        card, body = make_card("Real-Time Progress & Telemetry", icon_name="activity")
        hdr = card.layout().itemAt(0).layout()

        clear_btn = QPushButton("Clear")
        clear_btn.setStyleSheet(BTN_SECONDARY_STYLE)
        clear_btn.clicked.connect(self._clear_telemetry)
        hdr.addWidget(clear_btn)
        self.live_indicator = LiveStatusIndicator()
        hdr.addWidget(self.live_indicator)



        tiles_row = QHBoxLayout()
        tiles_row.setSpacing(8)
        tile, self.tile_progress = make_stat_tile("Overall Progress", "0%")
        tiles_row.addWidget(tile)
        tile, self.tile_processed = make_stat_tile("Processed", "00:00:00")
        tiles_row.addWidget(tile)
        tile, self.tile_remaining = make_stat_tile("Remaining", "00:00:00")
        tiles_row.addWidget(tile)
        tile, self.tile_speed = make_stat_tile("Speed", "0.0x", ACCENT_CYAN)
        tiles_row.addWidget(tile)
        tile, self.tile_segments = make_stat_tile("Segments", "0", ACCENT)
        tiles_row.addWidget(tile)
        tile, self.tile_rtf = make_stat_tile("RTF", "0.00", WARNING)
        tiles_row.addWidget(tile)
        body.addLayout(tiles_row)

        self.status_lbl = QLabel("Ready.")
        self.status_lbl.setStyleSheet(f"color: {TEXT_SUB}; font-size: 12px; border: none;")
        self.status_lbl.setWordWrap(True)
        body.addWidget(self.status_lbl)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setStyleSheet(PROGRESSBAR_STYLE)
        body.addWidget(self.progress_bar)

        return card

    def _clear_telemetry(self):
        if hasattr(self, "live_indicator"):
            self.live_indicator.set_live(False)
        self.tile_progress.setText("0%")

        self.tile_processed.setText("00:00:00")
        self.tile_remaining.setText("00:00:00")
        self.tile_speed.setText("0.0x")
        self.tile_segments.setText("0")
        self.tile_rtf.setText("0.00")
        self.status_lbl.setText("Ready.")
        self.status_lbl.setStyleSheet(f"color: {TEXT_SUB}; font-size: 12px; border: none;")
        self.progress_bar.setValue(0)
        self.table.setRowCount(0)
        self.all_segs = []

    # ── 4. Live Transcript Studio ────────────────────────────────────
    def _build_transcript_card(self) -> QWidget:
        card, body = make_card("Live Transcript Studio", icon_name="translate")

        hdr = card.layout().itemAt(0).layout()

        save_btn = QPushButton("  Save Corrections")
        save_btn.setIcon(get_bs_icon("check-circle-fill", color=SUCCESS, size=14))
        save_btn.setStyleSheet(BTN_SECONDARY_STYLE)
        save_btn.clicked.connect(self._save_corrections)
        hdr.addWidget(save_btn)

        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filter transcript text…")
        self.filter_edit.setStyleSheet(LINEEDIT_STYLE)
        self.filter_edit.setFixedHeight(34)
        self.filter_edit.textChanged.connect(self._apply_filter)
        body.addWidget(self.filter_edit)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Start", "End", "Duration", "Text"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setMinimumHeight(240)
        self.table.setStyleSheet(f"""
            QTableWidget {{
                background-color: {INPUT_BG};
                color: {TEXT_MAIN};
                border: 1px solid {BORDER_COLOR};
                border-radius: 8px;
                gridline-color: {BORDER_COLOR};
                font-size: 12px;
            }}
            QHeaderView::section {{
                background-color: {CARD_BG};
                color: {TEXT_SUB};
                border: none;
                border-bottom: 1px solid {BORDER_COLOR};
                padding: 8px 10px;
                font-weight: 700;
                font-size: 11px;
            }}
            QTableWidget::item {{
                padding: 6px 8px;
            }}
            QTableWidget::item:selected {{
                background-color: {ACCENT};
                color: #FFFFFF;
            }}
            {SCROLLBAR_STYLE}
        """)
        self.table.cellDoubleClicked.connect(self._on_row_double_clicked)
        body.addWidget(self.table, 1)

        body.addWidget(self._build_audio_preview())

        return card

    def _apply_filter(self, text: str):
        text = text.lower().strip()
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 3)
            match = (not text) or (item and text in item.text().lower())
            self.table.setRowHidden(row, not match)

    def _on_row_double_clicked(self, row: int, col: int):
        if 0 <= row < len(self.all_segs):
            start = self.all_segs[row].get("start", 0.0)
            if self.audio_player.available:
                self.audio_player.seek(start)
                self._update_time_label()
            dur = self.audio_player.duration
            if dur:
                self.waveform.set(start / dur)

    def _save_corrections(self):
        if not self.all_segs or not self._last_out_path:
            QMessageBox.information(self, "Nothing to save", "Generate subtitles first.")
            return
        fmt = self.fmt_combo.currentText()
        try:
            if fmt == "ASS":
                out_lang_code = LANGUAGE_MAP.get(self.tgt_combo.currentText()) or LANGUAGE_MAP.get(self.src_combo.currentText())
                write_ass(self.all_segs, self._last_out_path, lang_code=out_lang_code)
            else:
                WRITERS[fmt](self.all_segs, self._last_out_path)
            self.status_lbl.setText(f"Corrections saved to {Path(self._last_out_path).name}")
            self.status_lbl.setStyleSheet(f"color: {SUCCESS}; font-size: 12px; border: none;")
        except Exception as e:
            QMessageBox.critical(self, "Save Failed", str(e))

    # ── Audio preview (same AudioPlayer/WaveformBar pattern as
    #    pages/transcribe.py, plus zoom controls) ──────────────────────
    def _build_audio_preview(self) -> QWidget:
        wrap = QFrame()
        wrap.setStyleSheet("border: none; background: transparent;")
        outer = QVBoxLayout(wrap)
        outer.setContentsMargins(0, 4, 0, 0)
        outer.setSpacing(6)

        controls = QHBoxLayout()
        controls.setSpacing(8)

        self.play_btn = QPushButton()
        self.play_btn.setIcon(get_bs_icon("play-fill", color="#FFFFFF", size=16))
        self.play_btn.setFixedSize(36, 32)
        self.play_btn.setStyleSheet(BTN_PRIMARY_STYLE)
        self.play_btn.setEnabled(False)
        self.play_btn.clicked.connect(self._toggle_playback)
        controls.addWidget(self.play_btn)

        self.mute_btn = QPushButton()
        self.mute_btn.setIcon(get_bs_icon("volume-up-fill", color=TEXT_SUB, size=16))
        self.mute_btn.setFixedSize(36, 32)
        self.mute_btn.setStyleSheet(BTN_SECONDARY_STYLE)
        self.mute_btn.clicked.connect(self._toggle_mute)
        controls.addWidget(self.mute_btn)

        self.audio_time_lbl = QLabel("00:00:00 / 0s")
        self.audio_time_lbl.setStyleSheet(f"color: {TEXT_SUB}; font-size: 12px; font-weight: 600; border: none;")
        controls.addWidget(self.audio_time_lbl)
        controls.addStretch(1)

        for icon_name, handler in (
            ("arrow-clockwise", lambda: self.waveform.set_zoom(1.0)),
            ("zoom-out", lambda: self.waveform.set_zoom(self.waveform.zoom / 1.5)),
            ("zoom-in", lambda: self.waveform.set_zoom(self.waveform.zoom * 1.5)),
        ):
            btn = QPushButton()
            ic = get_bs_icon(icon_name, color=TEXT_SUB, size=14)
            if ic:
                btn.setIcon(ic)
            btn.setFixedSize(32, 32)
            btn.setStyleSheet(BTN_SECONDARY_STYLE)
            btn.clicked.connect(handler)
            controls.addWidget(btn)

        outer.addLayout(controls)

        self.waveform = WaveformBar()
        self.waveform.setMinimumHeight(44)
        self.waveform.seekRequested.connect(self._on_waveform_seek)
        outer.addWidget(self.waveform)

        return wrap


        return wrap

    def _toggle_mute(self):
        muted = self.audio_player.toggle_mute()
        self.mute_btn.setIcon(get_bs_icon("volume-mute-fill" if muted else "volume-up-fill", color=TEXT_SUB, size=16))

    def _load_waveform(self, path: str):
        if not FFMPEG_PATH:
            return
        self.play_btn.setEnabled(False)
        self.waveform.load_peaks([])
        self.waveform_worker = WaveformWorker(path, FFMPEG_PATH)
        self.waveform_worker.peaksReady.connect(self._on_peaks_ready)
        self.waveform_worker.start()

    def _on_peaks_ready(self, samples, sr, peaks):
        self.waveform.load_peaks(peaks)
        if samples is not None and sr:
            self.audio_player.load(samples, sr)
            self.play_btn.setEnabled(True)
            self.audio_time_lbl.setText(f"00:00 / {_fmt_time_short(self.audio_player.duration)}")

    def _toggle_playback(self):
        if self.audio_player.is_playing:
            self.audio_player.pause()
            self.play_btn.setIcon(get_bs_icon("play-fill", color="#FFFFFF", size=16))
            self._playback_timer.stop()
        elif self.audio_player.play():
            self.play_btn.setIcon(get_bs_icon("pause-fill", color="#FFFFFF", size=16))
            self._playback_timer.start()

    def _on_waveform_seek(self, fraction: float):
        if self.audio_player.available:
            self.audio_player.seek(fraction * self.audio_player.duration)
            self._update_time_label()

    def _tick_playback(self):
        if not self.audio_player.is_playing:
            self._playback_timer.stop()
            self.play_btn.setIcon(get_bs_icon("play-fill", color="#FFFFFF", size=16))
            return
        dur = self.audio_player.duration
        pos = self.audio_player.position
        self.waveform.set(pos / dur if dur else 0.0)
        self._update_time_label()

    def _update_time_label(self):
        dur = self.audio_player.duration
        pos = self.audio_player.position
        self.audio_time_lbl.setText(f"{_fmt_time_short(pos)} / {_fmt_time_short(dur)}")

    # ── Generate flow (same TranscribeWorker wiring as pages/transcribe.py,
    #    rendered into stat tiles + table instead of a plain log box) ────
    def _on_generate_clicked(self):
        if not self.state.input_file:
            QMessageBox.warning(self, "No file selected", "Please select an input media file first.")
            return
        if self.worker is not None and self.worker.isRunning():
            return

        self.gen_btn.setEnabled(False)
        self.gen_btn.setText("  Transcribing…")
        self._clear_telemetry()
        if hasattr(self, "live_indicator"):
            self.live_indicator.set_live(True)
        self.main_window.set_busy(True)

        self.worker = TranscribeWorker(
            input_path=self.state.input_file,
            output_dir=self.state.output_dir,
            model_size=self.model_combo.currentText(),
            src_lang_name=self.src_combo.currentText(),
            tgt_lang_name=self.tgt_combo.currentText(),
            fmt=self.fmt_combo.currentText(),
            beam_size=self.beam_spin.value(),
            temperature=self.temp_spin.value(),
            condition_on_previous_text=self.cond_prev_check.isChecked(),
            word_timestamps=self.word_ts_check.isChecked(),
            max_words=self.max_words_spin.value(),
        )
        self.worker.segmentReady.connect(self._on_segment)
        self.worker.finished_ok.connect(self._on_finished)
        self.worker.error.connect(self._on_error)
        self.worker.start()

    @Slot(dict)
    def _on_segment(self, payload: dict):
        if "status" in payload:
            self.status_lbl.setText(payload["status"])
        pct = payload.get("progress", payload.get("pct"))
        if pct is not None:
            pct_float = float(pct)
            self.progress_bar.setValue(int(pct_float * 100))
            self.tile_progress.setText(payload.get("pct_str", f"{int(pct_float * 100)}%"))
            if not self.audio_player.is_playing:
                self.waveform.set(pct_float)
        if "cur_str" in payload:
            self.tile_processed.setText(payload["cur_str"])
        if "remaining_str" in payload:
            self.tile_remaining.setText(payload["remaining_str"])
        if "speed_str" in payload:
            self.tile_speed.setText(payload["speed_str"])
        if "seg_num" in payload:
            self.tile_segments.setText(str(payload["seg_num"]))
        if "rtf_str" in payload:
            self.tile_rtf.setText(payload["rtf_str"])
        if "cur_str" in payload and "tot_str" in payload:
            if not self.audio_player.is_playing:
                self.audio_time_lbl.setText(f"{payload['cur_str']} / {payload['tot_str']}")
        elif "cur_str" in payload and self.audio_player.duration > 0:
            if not self.audio_player.is_playing:
                self.audio_time_lbl.setText(f"{payload['cur_str']} / {_fmt_time_short(self.audio_player.duration)}")
        if "chunk" in payload:
            self._add_transcript_row(payload["chunk"])

    def _add_transcript_row(self, chunk: dict):
        self.all_segs.append(chunk)
        row = self.table.rowCount()
        self.table.insertRow(row)
        start, end = chunk.get("start", 0.0), chunk.get("end", 0.0)
        for col, text in enumerate((_fmt_time_short(start), _fmt_time_short(end), _fmt_time_short(end - start))):
            item = QTableWidgetItem(text)
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, col, item)
        text_item = QTableWidgetItem(str(chunk.get("text", "")).strip())
        text_item.setFlags(text_item.flags() & ~Qt.ItemIsEditable)
        self.table.setItem(row, 3, text_item)
        self.table.scrollToBottom()

    @Slot(str, list)
    def _on_finished(self, out_path: str, segs: list):
        self.main_window.set_busy(False)
        if hasattr(self, "live_indicator"):
            self.live_indicator.set_live(False)
        self._last_out_path = out_path
        self.all_segs = segs
        self.progress_bar.setValue(100)
        self.tile_progress.setText("100%")
        if not self.audio_player.is_playing:
            self.waveform.set(1.0)
            if hasattr(self, "audio_player") and self.audio_player.duration > 0:
                self.audio_time_lbl.setText(f"{_fmt_time_short(self.audio_player.duration)} / {_fmt_time_short(self.audio_player.duration)}")
        self.status_lbl.setText(f"Saved: {Path(out_path).name}")
        self.status_lbl.setStyleSheet(f"color: {SUCCESS}; font-size: 12px; border: none;")
        self.gen_btn.setEnabled(True)
        self.gen_btn.setText("  Generate Subtitles")
        self.main_window.invalidate_page("History")

        reply = QMessageBox.question(
            self, "Done!", f"Subtitle saved:\n{out_path}\n\nOpen folder?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self._open_folder(out_path)

    def _open_folder(self, path: str):
        import os
        import subprocess
        import sys
        folder = str(Path(path).parent)
        if sys.platform == "win32":
            os.startfile(folder)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", folder])
        else:
            subprocess.Popen(["xdg-open", folder])

    @Slot(str)
    def _on_error(self, msg: str):
        self.main_window.set_busy(False)
        if hasattr(self, "live_indicator"):
            self.live_indicator.set_live(False)
        self.progress_bar.setValue(0)
        self.status_lbl.setText(f"Error: {msg[:80]}")
        self.status_lbl.setStyleSheet(f"color: {ERROR_C}; font-size: 12px; border: none;")
        self.gen_btn.setEnabled(True)
        self.gen_btn.setText("  Generate Subtitles")
        QMessageBox.critical(self, "Error", msg)
