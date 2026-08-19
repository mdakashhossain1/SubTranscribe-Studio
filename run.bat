@echo off

:: If local venv doesn't exist, set it up automatically
if not exist "%~dp0subtranscribe\.venv\Scripts\python.exe" (
    echo Setting up SubTranscribe for first-time use...
    echo.

    python --version >nul 2>&1
    if %errorlevel% neq 0 (
        echo ERROR: Python is not installed or not in PATH.
        echo Please install Python 3.10+ from https://python.org
        pause
        exit /b 1
    )

    echo Creating local virtual environment...
    python -m venv "%~dp0subtranscribe\.venv"
    if %errorlevel% neq 0 (
        echo ERROR: Failed to create virtual environment.
        pause
        exit /b 1
    )

    echo Installing required packages (this may take a few minutes^)...
    "%~dp0subtranscribe\.venv\Scripts\pip.exe" install -r "%~dp0subtranscribe\requirements.txt" --quiet
    echo.
    echo Setup complete! Launching SubTranscribe...
)

:: Launch app (detached — no lingering CMD window)
start "" "%~dp0subtranscribe\.venv\Scripts\pythonw.exe" "%~dp0main.py"
