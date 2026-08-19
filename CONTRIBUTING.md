# Contributing to SubTranscribe Studio

Thank you for your interest in contributing to **SubTranscribe Studio**! 🎉

Whether you are fixing a bug, adding a new feature, improving documentation, or optimizing GPU/CPU performance, your contributions are warmly welcomed.

---

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [How Can I Contribute?](#how-can-i-contribute)
  - [Reporting Bugs](#reporting-bugs)
  - [Suggesting Enhancements](#suggesting-enhancements)
  - [Pull Requests](#pull-requests)
- [Local Development Setup](#local-development-setup)
- [Project Architecture](#project-architecture)
- [Coding Standards](#coding-standards)

---

## Code of Conduct

This project adheres to the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md). By participating, you are expected to uphold this code. Please report unacceptable behavior to `hossainakash22958@gmail.com`.

---

## How Can I Contribute?

### Reporting Bugs

Before creating a bug report, please check the [existing issues](https://github.com/mdakashhossain1/SubTranscribe-Studio/issues) to avoid duplicates.

When filing a bug report, please include:
- A clear and descriptive title.
- Steps to reproduce the problem.
- Your OS version (Windows 10/11) and GPU model (NVIDIA CUDA / AMD Vulkan / CPU).
- Relevant log output from the **Logs** tab in the app.

### Suggesting Enhancements

Feature requests are tracked as GitHub issues. When suggesting a feature:
- Explain **why** this feature would be useful to users.
- Describe **how** you envision it working in the app.
- Provide mockups or screenshots if applicable.

### Pull Requests

1. **Fork** the repository and create your feature branch:
   ```bash
   git checkout -b feature/my-awesome-feature
   ```
2. Make your changes and test locally (`python main.py`).
3. Commit your changes with clear, descriptive commit messages.
4. Push to your branch and open a **Pull Request** against `main`.

---

## Local Development Setup

1. **Clone the repository**:
   ```bash
   git clone https://github.com/mdakashhossain1/SubTranscribe-Studio.git
   cd SubTranscribe-Studio
   ```

2. **Create a virtual environment**:
   ```bash
   python -m venv subtranscribe/.venv
   subtranscribe\.venv\Scripts\activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r subtranscribe/requirements.txt
   ```

4. **Run the application**:
   ```bash
   python main.py
   ```

---

## Project Architecture

- **`main.py`**: Thin entry point (`from subtranscribe.app import main`) — this is the literal script PyInstaller/CI build from, so it stays at the repo root.
- **`subtranscribe/`**: The application package (PySide6 / Qt for Python).
  - **`app.py`**: `QApplication` bootstrap.
  - **`main_window.py`**: Main window, sidebar navigation, and the persistent header/footer chrome (backend/GPU status, live system telemetry).
  - **`backend/`**: Pure business logic with no UI dependencies — transcription (`faster-whisper` / `whisper.cpp`), translation, subtitle export (SRT/VTT/ASS/TXT), model download/management, device detection, update checking. Unit-testable in isolation.
  - **`pages/`**: One file per sidebar screen (`dashboard.py`, `transcribe.py`, `batch.py`, `models.py`, `history.py`, `telemetry.py`, `logs.py`, `settings.py`, `help.py`, `about.py`).
  - **`widgets/`**: Reusable UI components (searchable language picker, waveform player, card/stat-tile helpers, shared stylesheets, themed dialogs).
  - **`workers.py`**: `QThread` background workers (transcription, model downloads, live telemetry, update checks) that marshal results back to the UI thread via Qt signals.
  - **`config.py` / `paths.py` / `icons.py`**: Theme/config constants, frozen-aware filesystem paths (dev vs. packaged `.exe`), and icon loading (native Qt SVG rendering).
  - **`assets/`**: Icons, Bootstrap SVG vector icons, fonts, flags, and brand assets — colocated with the code that uses them.
  - **`requirements.txt`**, **`.venv/`**: Python dependencies and the local virtual environment, also colocated inside the package.
- **`bin/`**: Vendored `whisper.cpp` binaries and runtime DLLs for Vulkan / CPU fallback processing.
- **`installer.iss`**: Inno Setup installer script for Windows distribution.
- **`build.bat`** / **`run.bat`**: Windows PyInstaller bundling script and first-run launcher.
- **`.github/workflows/build-desktop.yml`**: Multi-platform (Windows/Linux/macOS/Raspberry Pi/Docker) build and release automation.

---

## Coding Standards

- Follow **PEP 8** style guidelines for Python code.
- Maintain non-blocking background threads for long-running AI inference and audio processing.
- Keep UI responsive and follow modern dark mode design patterns.
- Keep commit messages concise and descriptive.

---

Thank you for helping make SubTranscribe Studio better for everyone! 🚀
