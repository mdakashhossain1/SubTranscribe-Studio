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
2. Make your changes and test locally (`python subgen.py`).
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
   python -m venv .venv
   .venv\Scripts\activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Run the application**:
   ```bash
   python subgen.py
   ```

---

## Project Architecture

- **`subgen.py`**: Main Tkinter / CustomTkinter application source code containing UI screens, Whisper AI engine orchestration, waveform rendering, and background worker threads.
- **`assets/`**: Icons, Bootstrap SVG vector icons, fonts, and brand assets.
- **`bin/`**: Vendored `whisper.cpp` binaries and runtime DLLs for Vulkan / CPU fallback processing.
- **`installer.iss`**: Inno Setup installer script for Windows distribution.
- **`build.bat`**: Windows PyInstaller bundling script.
- **`.github/workflows/build-windows.yml`**: Continuous integration build and release automation.

---

## Coding Standards

- Follow **PEP 8** style guidelines for Python code.
- Maintain non-blocking background threads for long-running AI inference and audio processing.
- Keep UI responsive and follow modern dark mode design patterns.
- Keep commit messages concise and descriptive.

---

Thank you for helping make SubTranscribe Studio better for everyone! 🚀
