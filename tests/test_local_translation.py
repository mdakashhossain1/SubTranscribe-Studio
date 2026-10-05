import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


class LocalTranslationTests(unittest.TestCase):
    def setUp(self):
        config = types.ModuleType("subtranscribe.config")
        config.GGML_MODEL_FILES = {"large-v3": ("repo", "ggml-large-v3.bin")}
        config.GGML_MODELS_DIR = Path("models/ggml")
        config.MODELS_DIR = Path("models")
        config.WHISPERCPP_EXE = Path("whisper-cli.exe")
        paths = types.ModuleType("subtranscribe.paths")
        paths.CREATE_NO_WINDOW = 0
        paths.get_startupinfo = lambda: None
        device = types.ModuleType("subtranscribe.backend.device")
        device.DEVICE = "cpu"
        device.COMPUTE_TYPE = "int8"
        device.USE_WHISPERCPP = False
        path = Path(__file__).resolve().parents[1] / "subtranscribe/backend/transcribe.py"
        spec = importlib.util.spec_from_file_location("subtranscribe.backend.transcribe", path)
        self.module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {
            "subtranscribe.config": config,
            "subtranscribe.paths": paths,
            "subtranscribe.backend.device": device,
        }), patch.object(importlib.util, "find_spec", return_value=None):
            spec.loader.exec_module(self.module)
        self.on_segment = Mock()
        self.on_done = Mock()
        self.on_error = Mock()

    def run_backend(self, task="translate", model="large-v3"):
        self.module.transcribe("audio.wav", model, "hi", self.on_segment,
                               self.on_done, self.on_error, task=task)

    def test_faster_whisper_translates_with_cached_model(self):
        backend = types.ModuleType("faster_whisper")
        backend.WhisperModel = Mock()
        segment = types.SimpleNamespace(start=0, end=2, text="Hello everyone", words=[])
        info = types.SimpleNamespace(language="hi", duration=2)
        backend.WhisperModel.return_value.transcribe.return_value = ([segment], info)
        self.module.BACKEND = "faster_whisper"
        with patch.dict(sys.modules, {"faster_whisper": backend}):
            self.run_backend()
        self.assertTrue(backend.WhisperModel.call_args.kwargs["local_files_only"])
        options = backend.WhisperModel.return_value.transcribe.call_args.kwargs
        self.assertEqual(options["task"], "translate")
        self.assertEqual(options["language"], "hi")
        self.assertEqual(self.on_segment.call_args.args[0]["text"], "Hello everyone")
        self.on_error.assert_not_called()
        self.on_done.assert_called_once()

    def test_transcription_keeps_original_task(self):
        backend = types.ModuleType("faster_whisper")
        backend.WhisperModel = Mock()
        backend.WhisperModel.return_value.transcribe.return_value = (
            [], types.SimpleNamespace(language="hi", duration=2))
        self.module.BACKEND = "faster_whisper"
        with patch.dict(sys.modules, {"faster_whisper": backend}):
            self.run_backend(task="transcribe")
        self.assertEqual(backend.WhisperModel.return_value.transcribe.call_args.kwargs["task"], "transcribe")

    def test_openai_whisper_receives_translation_task(self):
        backend = types.ModuleType("whisper")
        backend.load_model = Mock()
        backend.load_model.return_value.transcribe.return_value = {
            "language": "hi", "segments": [{"start": 0, "end": 2, "text": "Hello"}]}
        self.module.BACKEND = "openai_whisper"
        with patch.dict(sys.modules, {"whisper": backend}):
            self.run_backend()
        self.assertEqual(backend.load_model.return_value.transcribe.call_args.kwargs["task"], "translate")
        self.on_error.assert_not_called()

    def test_vulkan_backend_receives_translation_flag(self):
        self.module.USE_WHISPERCPP = True
        process = Mock()
        process.stdout = ["[00:00:00.000 --> 00:00:02.000] Hello everyone\n"]
        process.wait.return_value = 0
        with patch.object(self.module.subprocess, "Popen", return_value=process) as popen:
            self.run_backend()
        command = popen.call_args.args[0]
        self.assertIn("--translate", command)
        self.assertEqual(command[command.index("-l") + 1], "hi")
        self.assertEqual(self.on_segment.call_args.args[0]["text"], "Hello everyone")
        self.on_error.assert_not_called()

    def test_unsupported_translation_models_fail_before_loading(self):
        for model in ("small.en", "large-v3-turbo", "distil-large-v3"):
            with self.subTest(model=model):
                self.on_error.reset_mock()
                self.run_backend(model=model)
                self.assertIn("multilingual model", self.on_error.call_args.args[0])
                self.on_done.assert_not_called()


if __name__ == "__main__":
    unittest.main()
