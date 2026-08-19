"""Help & documentation. Qt port of SubGenApp._render_help (subgen.py:2644-2677)."""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QPlainTextEdit, QScrollArea

from ..config import DARK_BG
from ..widgets.cards import make_card
from ..widgets.styles import TEXTEDIT_STYLE

_HELP_TEXT = """SubTranscribe User Guide & FAQ

1. How to Generate Subtitles:
   • Click 'Browse' on the Transcribe page to select your media file (.mp4, .mkv, .mp3, .wav, etc.)
   • Choose your desired Whisper model (large-v3, large-v3-turbo, distil-large-v3, etc.)
   • Select the Output Format (SRT, VTT, ASS, TXT)
   • Click 'Generate Subtitles'

2. GPU Acceleration Setup:
   • NVIDIA GPUs: Automatically uses CUDA (float16) via faster-whisper.
   • AMD / Intel GPUs: Uses bundled Vulkan GGML engine for fast GPU processing.
   • CPU Fallback: Runs 8-bit quantised inference on CPU if no GPU driver is found.

3. Supported Formats:
   • Video: MP4, MKV, AVI, MOV, WEBM
   • Audio: MP3, WAV, FLAC, OGG, M4A, AAC
   • Subtitle Outputs: SRT, WEBVTT, Advanced SubStation Alpha (ASS), Plain Text (TXT)
"""


class HelpPage(QWidget):
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

        card, body = make_card("Help & User Documentation", icon_name="question-circle-fill")
        help_box = QPlainTextEdit()
        help_box.setReadOnly(True)
        help_box.setMinimumHeight(340)
        help_box.setStyleSheet(TEXTEDIT_STYLE)
        help_box.setPlainText(_HELP_TEXT)
        body.addWidget(help_box)

        layout.addWidget(card)
        layout.addStretch(1)
