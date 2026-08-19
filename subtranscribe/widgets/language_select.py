"""Searchable language dropdown with flag icons — the Qt replacement for
SearchableLanguageSelect(ctk.CTkFrame) (subgen.py:508-639), which is where
both originally-reported bugs lived:

1. Flags didn't render in the packaged build because get_flag_ctk_image()
   resolved the flags folder via `Path(__file__).resolve().parent`, which
   isn't reliable inside a PyInstaller bundle. Fixed here by construction —
   icons.get_flag_icon() only ever resolves through config.FLAGS_DIR, which
   is PROJECT_DIR-based (frozen-aware) from paths.py.

2. The dropdown "triggered separately" because each widget instance
   registered `variable.trace_add(...)` on a Tk StringVar shared across
   tabs and never removed it on destroy, leaking dead-widget callbacks that
   fired (and errored) on every later value change; the popup also had no
   click-outside-to-dismiss handling. Neither failure mode exists for
   QComboBox: Qt's native popup handles outside-click dismissal for free,
   there is no separate variable-trace mechanism to leak, and Qt's
   parent-child ownership tears down signal connections when the widget is
   destroyed. This class needs no manual popup/lifecycle code at all.
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QStandardItemModel, QStandardItem
from PySide6.QtWidgets import QComboBox, QCompleter

from ..config import FLAG_ICON_MAP
from ..icons import get_flag_icon


class LanguageSelect(QComboBox):
    """Editable, type-to-filter QComboBox with a flag icon per language."""

    valueChanged = Signal(str)

    def __init__(self, values: list[str], parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.NoInsert)

        model = QStandardItemModel(self)
        for name in values:
            item = QStandardItem(name)
            icon = get_flag_icon(FLAG_ICON_MAP.get(name))
            if icon is not None:
                item.setIcon(icon)
            item.setEditable(False)
            model.appendRow(item)
        self.setModel(model)

        completer = QCompleter(model, self)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        completer.setCompletionMode(QCompleter.PopupCompletion)
        self.setCompleter(completer)

        self.currentTextChanged.connect(self.valueChanged.emit)

    def setCurrentValue(self, name: str):
        idx = self.findText(name)
        if idx >= 0:
            self.setCurrentIndex(idx)
        else:
            self.setCurrentText(name)

    def currentValue(self) -> str:
        return self.currentText()
