@echo off
title SubTranscribe Studio - Building Windows Executable & Installer
echo ============================================
echo  SubTranscribe Studio - Building Windows Executable & Setup
echo ============================================
echo.

set VENV=%~dp0.venv
set PIP=%VENV%\Scripts\pip.exe
set PYTHON=%VENV%\Scripts\python.exe
set PYINSTALLER=%VENV%\Scripts\pyinstaller.exe

:: Version comes from the VERSION file (single source of truth — see
:: subgen.py's _load_app_version() and installer.iss's MyAppVersion, which
:: reads this same file directly).
set VER=dev
if exist "%~dp0VERSION" set /p VER=<"%~dp0VERSION"

:: Install PyInstaller if missing
if not exist "%PYINSTALLER%" (
    echo Installing PyInstaller into local venv...
    "%PIP%" install pyinstaller --quiet
)

:: Ensure logo.ico is generated from logo.png
"%PYTHON%" -c "from PIL import Image; img=Image.open('assets/logo.png'); img.save('assets/logo.ico', format='ICO', sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])" 2>nul

:: Clean previous build
if exist "%~dp0dist" (
    echo Cleaning previous build...
    rmdir /s /q "%~dp0dist"
)
if exist "%~dp0build" (
    rmdir /s /q "%~dp0build"
)

echo.
echo Building SubTranscribeStudio.exe with logo icon...
echo.

"%PYINSTALLER%" ^
    --name "SubTranscribeStudio" ^
    --windowed ^
    --onedir ^
    --icon "%~dp0assets\logo.ico" ^
    --collect-all customtkinter ^
    --collect-all faster_whisper ^
    --collect-all ctranslate2 ^
    --collect-all deep_translator ^
    --collect-all tiktoken ^
    --collect-all tokenizers ^
    --collect-all sounddevice ^
    --collect-all pymupdf ^
    --hidden-import tkinter ^
    --hidden-import tkinter.filedialog ^
    --hidden-import tkinter.messagebox ^
    --hidden-import faster_whisper ^
    --hidden-import ctranslate2 ^
    --clean ^
    --noconfirm ^
    "%~dp0subgen.py"

if %errorlevel% neq 0 (
    echo.
    echo ============================================
    echo  BUILD FAILED. Check the output above.
    echo ============================================
    pause
    exit /b 1
)

:: Copy required runtime directories to dist\SubTranscribeStudio
:: (models are NOT bundled here - they're downloaded on demand into the
:: per-user AppData folder at runtime, since Program Files isn't writable
:: by standard users - see DATA_DIR in subgen.py)
echo Copying assets and binaries...
xcopy /E /I /Y "%~dp0assets" "%~dp0dist\SubTranscribeStudio\assets" >nul 2>&1
if exist "%~dp0bin" xcopy /E /I /Y "%~dp0bin" "%~dp0dist\SubTranscribeStudio\bin" >nul 2>&1
if exist "%~dp0whisper.cpp" xcopy /E /I /Y "%~dp0whisper.cpp" "%~dp0dist\SubTranscribeStudio\whisper.cpp" >nul 2>&1
copy /Y "%~dp0VERSION" "%~dp0dist\SubTranscribeStudio\VERSION" >nul 2>&1

:: Create Desktop Shortcut helper VBScript in dist\SubTranscribeStudio
(
echo Set WshShell = CreateObject^("WScript.Shell"^^)^
echo desktop = WshShell.SpecialFolders^("Desktop"^)^
echo Set shortcut = WshShell.CreateShortcut^(desktop ^& "\SubTranscribe Studio.lnk"^)^
echo shortcut.TargetPath = "%~dp0dist\SubTranscribeStudio\SubTranscribeStudio.exe"^
echo shortcut.WorkingDirectory = "%~dp0dist\SubTranscribeStudio"^
echo shortcut.IconLocation = "%~dp0dist\SubTranscribeStudio\assets\logo.ico"^
echo shortcut.Description = "SubTranscribe Studio Enterprise Edition"^
echo shortcut.Save
) > "%~dp0dist\SubTranscribeStudio\Create_Desktop_Shortcut.vbs"

:: Create Uninstaller & Complete Cleanup helper script in dist\SubTranscribeStudio
(
echo @echo off
echo title SubTranscribe Studio - Uninstaller
echo =========================================================
echo  SubTranscribe Studio - Complete Application Cleanup
echo =========================================================
echo.
echo CHOICE /C YN /M "Do you want to COMPLETELY DELETE all downloaded AI models, cache, and history logs?"
echo if errorlevel 2 goto KeepModels
echo.
echo Purging all downloaded AI models and cache...
echo rmdir /s /q "%%LOCALAPPDATA%%\SubTranscribe Studio" 2^>nul
echo echo All models and cache purged cleanly. Zero traces remain.
echo goto End
echo :KeepModels
echo keeping downloaded AI model files...
echo :End
echo.
echo Uninstall complete.
echo pause
) > "%~dp0dist\SubTranscribeStudio\Uninstall_SubTranscribe.bat"

:: Attempt Inno Setup compilation if ISCC.exe is available
set ISCC="C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if not exist %ISCC% set ISCC="C:\Program Files\Inno Setup 6\ISCC.exe"

if exist %ISCC% (
    echo.
    echo Compiling Inno Setup Installer SubTranscribe_Studio_Setup_v%VER%.exe...
    %ISCC% "%~dp0installer.iss"
)

echo.
echo ============================================
echo  BUILD COMPLETE!
echo.
echo  1. Standalone Executable Folder:
echo     dist\SubTranscribeStudio\SubTranscribeStudio.exe
echo
echo  2. Desktop Shortcut Creator:
echo     dist\SubTranscribeStudio\Create_Desktop_Shortcut.vbs
echo
echo  3. Complete Uninstall & Model Cleanup Script:
echo     dist\SubTranscribeStudio\Uninstall_SubTranscribe.bat
if exist %ISCC% (
echo  4. Windows Setup Installer (With Desktop Icon Checkbox & Full Cleanup Prompt):
echo     dist\SubTranscribe_Studio_Setup_v%VER%.exe
)
echo ============================================
pause
