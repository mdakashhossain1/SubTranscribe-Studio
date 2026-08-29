"""Transcribe workspace: file picker, model/language/format selectors,
progress + live log, wired to TranscribeWorker. Qt port of the file-zone +
settings + generate-button + progress + preview composition from
SubGenApp._render_dashboard/_render_transcribe (subgen.py:2000-2085,
2828-3210). Language pickers use widgets.language_select.LanguageSelect
(searchable, flag icons); the full waveform preview widget is a separate
Phase 3 item not yet wired into this page.
"""
from pathlib import Path

from PySide6.QtCore import Qt, Slot, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QComboBox, QProgressBar, QPlainTextEdit, QFileDialog, QMessageBox,
    QScrollArea, QCheckBox, QDoubleSpinBox, QSpinBox,
)

from ..backend.audio import AudioPlayer
from ..backend.formatting import _fmt_time_short
from ..config import (
    MODEL_SIZES, OUTPUT_FORMATS, LANGUAGE_MAP,
    TEXT_MAIN, TEXT_SUB, INPUT_BG, BORDER_COLOR, ACCENT, ACCENT_HOVER,
    SUCCESS, ERROR_C, DARK_BG,
)
from ..icons import get_bs_icon
from ..paths import FFMPEG_PATH
from ..widgets.cards import make_card
from ..widgets.language_select import LanguageSelect
from ..widgets.styles import (
    COMBO_STYLE as _COMBO_STYLE, LINEEDIT_STYLE as _LINEEDIT_STYLE,
    BTN_PRIMARY_STYLE as _BTN_PRIMARY_STYLE, BTN_SECONDARY_STYLE as _BTN_SECONDARY_STYLE,
    PROGRESSBAR_STYLE, TEXTEDIT_STYLE, FIELD_LABEL_STYLE, SCROLLBAR_STYLE, CHECKBOX_STYLE,
)

from ..widgets.waveform import WaveformBar
from ..workers import TranscribeWorker, WaveformWorker


def _field_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(FIELD_LABEL_STYLE)
    return lbl


class TranscribePage(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.state = main_window.state
        self.worker: TranscribeWorker | None = None
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
        layout = QVBoxLayout(content)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        layout.addWidget(self._build_file_zone())
        layout.addWidget(self._build_audio_preview())
        layout.addWidget(self._build_settings())
        layout.addWidget(self._build_advanced())
        layout.addLayout(self._build_generate_row())
        layout.addWidget(self._build_progress())
        layout.addWidget(self._build_log(), 1)

    # ── File zone ────────────────────────────────────────────────
    def _build_file_zone(self) -> QWidget:
        card, body = make_card("1. Input Media & Output Location")

        body.addWidget(_field_label("Input Media File"))
        row1 = QHBoxLayout()
        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText("Select audio or video file…")
        self.input_edit.setStyleSheet(_LINEEDIT_STYLE)
        self.input_edit.setReadOnly(True)
        row1.addWidget(self.input_edit, 1)
        browse_btn = QPushButton("  Browse")
        browse_ic = get_bs_icon("folder2-open", color="#FFFFFF", size=14)
        if browse_ic:
            browse_btn.setIcon(browse_ic)
        browse_btn.setStyleSheet(_BTN_PRIMARY_STYLE)
        browse_btn.clicked.connect(self._browse_input)
        row1.addWidget(browse_btn)
        body.addLayout(row1)

        body.addWidget(_field_label("Output Folder"))
        row2 = QHBoxLayout()
        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("Same as input directory")
        self.output_edit.setStyleSheet(_LINEEDIT_STYLE)
        self.output_edit.setReadOnly(True)
        row2.addWidget(self.output_edit, 1)
        change_btn = QPushButton("  Change")
        change_ic = get_bs_icon("folder-fill", color=TEXT_SUB, size=14)
        if change_ic:
            change_btn.setIcon(change_ic)
        change_btn.setStyleSheet(_BTN_SECONDARY_STYLE)
        change_btn.clicked.connect(self._browse_output)
        row2.addWidget(change_btn)
        body.addLayout(row2)

        return card

    def _browse_input(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Media File", "",
            "Media Files (*.mp4 *.mkv *.avi *.mov *.mp3 *.wav *.flac *.aac *.m4a);;All Files (*)"
        )
        if path:
            self.state.input_file = path
            self.input_edit.setText(path)
            self._load_waveform(path)

    def _browse_output(self):
        path = QFileDialog.getExistingDirectory(self, "Select Output Folder")
        if path:
            self.state.output_dir = path
            self.output_edit.setText(path)

    # ── Audio preview ────────────────────────────────────────────
    def _build_audio_preview(self) -> QWidget:
        card, body = make_card("Audio Preview")
        controls = QHBoxLayout()

        self.play_btn = QPushButton()
        self.play_btn.setIcon(get_bs_icon("play-fill", color="#FFFFFF", size=16))
        self.play_btn.setFixedWidth(44)
        self.play_btn.setStyleSheet(_BTN_PRIMARY_STYLE)
        self.play_btn.setEnabled(False)
        self.play_btn.clicked.connect(self._toggle_playback)
        controls.addWidget(self.play_btn)

        self.stop_btn = QPushButton()
        self.stop_btn.setIcon(get_bs_icon("stop-fill", color=TEXT_SUB, size=16))
        self.stop_btn.setFixedWidth(44)
        self.stop_btn.setStyleSheet(_BTN_SECONDARY_STYLE)
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop_playback)
        controls.addWidget(self.stop_btn)

        self.audio_time_lbl = QLabel("--:-- / --:--")
        self.audio_time_lbl.setStyleSheet(f"color: {TEXT_SUB}; font-size: 12px;")
        controls.addWidget(self.audio_time_lbl)
        controls.addStretch(1)
        body.addLayout(controls)

        self.waveform = WaveformBar()
        self.waveform.seekRequested.connect(self._on_waveform_seek)
        body.addWidget(self.waveform)

        return card

    def _load_waveform(self, path: str):
        if not FFMPEG_PATH:
            return
        self.play_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        self.waveform.load_peaks([])
        self.waveform_worker = WaveformWorker(path, FFMPEG_PATH)
        self.waveform_worker.peaksReady.connect(self._on_peaks_ready)
        self.waveform_worker.start()

    def _on_peaks_ready(self, samples, sr, peaks):
        self.waveform.load_peaks(peaks)
        if samples is not None and sr:
            self.audio_player.load(samples, sr)
            self.play_btn.setEnabled(True)
            self.stop_btn.setEnabled(True)
            self.audio_time_lbl.setText(f"00:00 / {_fmt_time_short(self.audio_player.duration)}")

    def _toggle_playback(self):
        if self.audio_player.is_playing:
            self.audio_player.pause()
            self.play_btn.setIcon(get_bs_icon("play-fill", color="#FFFFFF", size=16))
            self._playback_timer.stop()
        else:
            if self.audio_player.play():
                self.play_btn.setIcon(get_bs_icon("pause-fill", color="#FFFFFF", size=16))
                self._playback_timer.start()

    def _stop_playback(self):
        self.audio_player.stop()
        self.play_btn.setIcon(get_bs_icon("play-fill", color="#FFFFFF", size=16))
        self._playback_timer.stop()
        self.waveform.set(0.0)
        self.audio_time_lbl.setText(f"00:00 / {_fmt_time_short(self.audio_player.duration)}")

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

    # ── Settings ─────────────────────────────────────────────────
    def _build_settings(self) -> QWidget:
        card, body = make_card("2. Configuration & AI Model")
        row = QHBoxLayout()
        row.setSpacing(12)

        self.model_combo = self._labeled_combo(row, "Whisper Model", MODEL_SIZES)
        self.model_combo.currentTextChanged.connect(lambda v: setattr(self.state, "model", v))

        self.src_combo = self._labeled_lang_select(row, "Source Language", list(LANGUAGE_MAP.keys()))
        self.src_combo.valueChanged.connect(lambda v: setattr(self.state, "src_lang", v))

        self.tgt_combo = self._labeled_lang_select(row, "Translate To", ["None"] + list(LANGUAGE_MAP.keys())[1:])
        self.tgt_combo.valueChanged.connect(lambda v: setattr(self.state, "tgt_lang", v))

        self.fmt_combo = self._labeled_combo(row, "Output Format", OUTPUT_FORMATS)
        self.fmt_combo.currentTextChanged.connect(lambda v: setattr(self.state, "fmt", v))

        body.addLayout(row)
        return card

    def _labeled_combo(self, row: QHBoxLayout, label: str, values: list[str]) -> QComboBox:
        col = QVBoxLayout()
        col.setSpacing(4)
        col.setContentsMargins(0, 0, 0, 0)
        col.addWidget(_field_label(label))
        combo = QComboBox()
        combo.addItems(values)
        combo.setStyleSheet(_COMBO_STYLE)
        col.addWidget(combo)
        row.addLayout(col, 1)
        return combo

    def _labeled_lang_select(self, row: QHBoxLayout, label: str, values: list[str]) -> LanguageSelect:
        col = QVBoxLayout()
        col.setSpacing(4)
        col.setContentsMargins(0, 0, 0, 0)
        col.addWidget(_field_label(label))
        combo = LanguageSelect(values)
        combo.setStyleSheet(_COMBO_STYLE)
        col.addWidget(combo)
        row.addLayout(col, 1)
        return combo

    # ── Advanced settings ────────────────────────────────────────
    def _build_advanced(self) -> QWidget:
        card, body = make_card("3. Advanced Settings")
        row = QHBoxLayout()
        row.setSpacing(16)

        col1 = QVBoxLayout()
        col1.setSpacing(4)
        col1.setContentsMargins(0, 0, 0, 0)
        col1.addWidget(_field_label("Beam Size"))
        self.beam_spin = QSpinBox()
        self.beam_spin.setRange(1, 10)
        self.beam_spin.setValue(self.state.beam_size)
        self.beam_spin.setStyleSheet(_LINEEDIT_STYLE)
        col1.addWidget(self.beam_spin)
        row.addLayout(col1, 1)

        col2 = QVBoxLayout()
        col2.setSpacing(4)
        col2.setContentsMargins(0, 0, 0, 0)
        col2.addWidget(_field_label("Temperature"))
        self.temp_spin = QDoubleSpinBox()
        self.temp_spin.setRange(0.0, 1.0)
        self.temp_spin.setSingleStep(0.1)
        self.temp_spin.setValue(self.state.temperature)
        self.temp_spin.setStyleSheet(_LINEEDIT_STYLE)
        col2.addWidget(self.temp_spin)
        row.addLayout(col2, 1)

        col3 = QVBoxLayout()
        col3.setSpacing(4)
        col3.setContentsMargins(0, 0, 0, 0)
        col3.addWidget(_field_label("Max Words / Chunk"))
        self.max_words_spin = QSpinBox()
        self.max_words_spin.setRange(1, 12)
        self.max_words_spin.setValue(self.state.max_words)
        self.max_words_spin.setStyleSheet(_LINEEDIT_STYLE)
        col3.addWidget(self.max_words_spin)
        row.addLayout(col3, 1)

        col4 = QVBoxLayout()
        col4.setSpacing(4)
        col4.setContentsMargins(0, 0, 0, 0)
        self.cond_prev_check = QCheckBox("Condition on previous text")
        self.cond_prev_check.setStyleSheet(CHECKBOX_STYLE)
        col4.addWidget(self.cond_prev_check)
        self.word_ts_check = QCheckBox("Word-level timestamps")
        self.word_ts_check.setChecked(self.state.word_timestamps)
        self.word_ts_check.setStyleSheet(CHECKBOX_STYLE)
        col4.addWidget(self.word_ts_check)
        row.addLayout(col4, 1)

        body.addLayout(row)

        body.addWidget(_field_label("Vocabulary Hint (optional)"))
        self.vocab_hint_edit = QLineEdit()
        self.vocab_hint_edit.setPlaceholderText(
            "Proper nouns, brand/product names, technical terms the audio uses — "
            "helps the model spell them right instead of guessing from pronunciation, "
            "e.g. \"remove.bg, Curve.photos, CUDA, VPS\""
        )
        self.vocab_hint_edit.setStyleSheet(_LINEEDIT_STYLE)
        self.vocab_hint_edit.setText(self.state.vocabulary_hint)
        self.vocab_hint_edit.textChanged.connect(lambda v: setattr(self.state, "vocabulary_hint", v))
        body.addWidget(self.vocab_hint_edit)

        return card



    # ── Generate button ──────────────────────────────────────────
    def _build_generate_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addStretch(1)
        self.gen_btn = QPushButton("  Generate Subtitles")
        self.gen_btn.setIcon(get_bs_icon("play-fill", color="#FFFFFF", size=18))
        self.gen_btn.setStyleSheet(_BTN_PRIMARY_STYLE)
        self.gen_btn.setMinimumHeight(40)
        self.gen_btn.clicked.connect(self._on_generate_clicked)
        row.addWidget(self.gen_btn)
        return row

    # ── Progress ─────────────────────────────────────────────────
    def _build_progress(self) -> QWidget:
        card, body = make_card("")
        self.status_lbl = QLabel("Ready.")
        self.status_lbl.setStyleSheet(f"color: {TEXT_SUB}; font-size: 12px;")
        body.addWidget(self.status_lbl)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setStyleSheet(PROGRESSBAR_STYLE)
        body.addWidget(self.progress_bar)
        return card

    # ── Log ──────────────────────────────────────────────────────
    def _build_log(self) -> QWidget:
        card, body = make_card("Live Transcript Log")
        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMinimumHeight(220)
        self.log_box.setStyleSheet(TEXTEDIT_STYLE)
        body.addWidget(self.log_box)
        return card

    # ── Generate flow ────────────────────────────────────────────
    def _on_generate_clicked(self):
        if not self.state.input_file:
            QMessageBox.warning(self, "No file selected", "Please select an input media file first.")
            return
        if self.worker is not None and self.worker.isRunning():
            return

        self.gen_btn.setEnabled(False)
        self.gen_btn.setText("Transcribing…")
        self.progress_bar.setValue(0)
        self.log_box.clear()
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
            vocabulary_hint=self.vocab_hint_edit.text(),
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
            if not self.audio_player.is_playing:
                self.waveform.set(pct_float)
        if "cur_str" in payload and "tot_str" in payload:
            if not self.audio_player.is_playing:
                self.audio_time_lbl.setText(f"{payload['cur_str']} / {payload['tot_str']}")
        elif "cur_str" in payload and self.audio_player.duration > 0:
            if not self.audio_player.is_playing:
                self.audio_time_lbl.setText(f"{payload['cur_str']} / {_fmt_time_short(self.audio_player.duration)}")
        if "log_line" in payload:
            self.log_box.appendPlainText(payload["log_line"])

    @Slot(str, list)
    def _on_finished(self, out_path: str, segs: list):
        self.main_window.set_busy(False)
        self._last_out_path = out_path
        self.progress_bar.setValue(100)
        if not self.audio_player.is_playing:
            self.waveform.set(1.0)
            if hasattr(self, "audio_player") and self.audio_player.duration > 0:
                self.audio_time_lbl.setText(f"{_fmt_time_short(self.audio_player.duration)} / {_fmt_time_short(self.audio_player.duration)}")
        self.status_lbl.setText(f"Saved: {Path(out_path).name}")
        self.status_lbl.setStyleSheet(f"color: {SUCCESS}; font-size: 12px;")
        self.log_box.appendPlainText(f"Subtitles complete! Total {len(segs)} segments written to {Path(out_path).name}")
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
        self.progress_bar.setValue(0)
        self.status_lbl.setText(f"Error: {msg[:80]}")
        self.status_lbl.setStyleSheet(f"color: {ERROR_C}; font-size: 12px;")
        self.gen_btn.setEnabled(True)
        self.gen_btn.setText("  Generate Subtitles")
        QMessageBox.critical(self, "Error", msg)
