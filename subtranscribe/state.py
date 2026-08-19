"""Shared app state as a QObject with per-field signals.

Replaces the ctk StringVar/BooleanVar/DoubleVar sprawl (subgen.py:1681-1735)
with one consistent mechanism: widgets read/write these properties and
connect to the matching `*Changed` signal instead of tracing a Tk variable.
"""
from PySide6.QtCore import QObject, Signal


class AppState(QObject):
    inputFileChanged = Signal(str)
    outputDirChanged = Signal(str)
    modelChanged = Signal(str)
    srcLangChanged = Signal(str)
    tgtLangChanged = Signal(str)
    fmtChanged = Signal(str)
    progressChanged = Signal(float)
    statusChanged = Signal(str, str)  # (message, color_hex)

    def __init__(self, model_default: str, parent=None):
        super().__init__(parent)
        self._input_file = ""
        self._output_dir = ""
        self._model = model_default
        self._src_lang = "Auto Detect"
        self._tgt_lang = "None"
        self._fmt = "SRT"
        self._progress = 0.0

        # Advanced transcription settings (subgen.py:1687-1693 equivalents)
        self.compute_type = "float16"
        self.beam_size = 5
        self.best_of = 5
        self.temperature = 0.0
        self.condition_on_previous_text = False
        self.word_timestamps = True
        self.max_words = 3

    @property
    def input_file(self):
        return self._input_file

    @input_file.setter
    def input_file(self, val):
        self._input_file = val
        self.inputFileChanged.emit(val)

    @property
    def output_dir(self):
        return self._output_dir

    @output_dir.setter
    def output_dir(self, val):
        self._output_dir = val
        self.outputDirChanged.emit(val)

    @property
    def model(self):
        return self._model

    @model.setter
    def model(self, val):
        self._model = val
        self.modelChanged.emit(val)

    @property
    def src_lang(self):
        return self._src_lang

    @src_lang.setter
    def src_lang(self, val):
        self._src_lang = val
        self.srcLangChanged.emit(val)

    @property
    def tgt_lang(self):
        return self._tgt_lang

    @tgt_lang.setter
    def tgt_lang(self, val):
        self._tgt_lang = val
        self.tgtLangChanged.emit(val)

    @property
    def fmt(self):
        return self._fmt

    @fmt.setter
    def fmt(self, val):
        self._fmt = val
        self.fmtChanged.emit(val)

    @property
    def progress(self):
        return self._progress

    @progress.setter
    def progress(self, val):
        self._progress = val
        self.progressChanged.emit(val)

    def set_status(self, message: str, color: str = ""):
        self.statusChanged.emit(message, color)
