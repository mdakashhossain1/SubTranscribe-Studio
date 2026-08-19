"""
SubTranscribe Studio — entry point.

The application lives in the subtranscribe/ package (PySide6/Qt UI on top
of the same transcription/translation/export backend). This file is the
literal script PyInstaller/build.bat/build-desktop.yml/Dockerfile build
from — a Python package alone can't be handed to PyInstaller as an entry
point the way that tooling is written, so a root-level script has to exist.
"""
from subtranscribe.app import main

if __name__ == "__main__":
    main()
