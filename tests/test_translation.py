import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


class TranslationTests(unittest.TestCase):
    def setUp(self):
        config = types.ModuleType("subtranscribe.config")
        config.LANGUAGE_MAP = {"English": "en", "Hindi": "hi", "Roman": "hinglish"}
        eventlog = types.ModuleType("subtranscribe.backend.eventlog")
        eventlog.log_event = Mock()
        translator = types.ModuleType("deep_translator")
        translator.GoogleTranslator = Mock()
        path = Path(__file__).resolve().parents[1] / "subtranscribe/backend/translate.py"
        spec = importlib.util.spec_from_file_location("subtranscribe.backend.translate", path)
        self.module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {
            "subtranscribe.config": config,
            "subtranscribe.backend.eventlog": eventlog,
            "deep_translator": translator,
        }):
            spec.loader.exec_module(self.module)

    def test_english_selection_reaches_translator(self):
        self.module.GoogleTranslator.return_value.translate.return_value = "Hello"
        translate = self.module.resolve_translate_fn("hi", "English")
        self.assertEqual(translate("नमस्ते"), "Hello")
        self.module.GoogleTranslator.assert_called_once_with(source="auto", target="en")

    def test_no_translation_selected(self):
        self.assertIsNone(self.module.resolve_translate_fn("hi", "None"))

    def test_missing_dependency_is_reported(self):
        self.module.HAS_TRANSLATOR = False
        with self.assertRaisesRegex(RuntimeError, "deep-translator"):
            self.module.resolve_translate_fn("hi", "English")

    def test_unknown_language_is_reported(self):
        with self.assertRaises(ValueError):
            self.module.resolve_translate_fn("hi", "Unknown")

    def test_failed_translation_never_returns_source(self):
        for result in (None, "", self.module._TRANSLATE_ERROR_SIGNATURE):
            with self.subTest(result=result), patch.object(self.module.time, "sleep"):
                translator = Mock()
                translator.translate.return_value = result
                with self.assertRaises(RuntimeError):
                    self.module._translate_with_retry(translator, "नमस्ते", retries=2)
                self.assertEqual(translator.translate.call_count, 2)

    def test_network_exception_is_reported(self):
        translator = Mock()
        translator.translate.side_effect = ConnectionError("offline")
        with patch.object(self.module.time, "sleep"), self.assertRaises(RuntimeError):
            self.module._translate_with_retry(translator, "नमस्ते", retries=2)

    def test_transient_failure_can_recover(self):
        translator = Mock()
        translator.translate.side_effect = [ConnectionError("offline"), "Hello"]
        with patch.object(self.module.time, "sleep"):
            self.assertEqual(self.module._translate_with_retry(translator, "नमस्ते"), "Hello")


if __name__ == "__main__":
    unittest.main()
