@echo off
setlocal
cd /d "%~dp0"
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
if not errorlevel 1 (
    py -3 audio_rescue.py
    goto end
)
python -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
if not errorlevel 1 (
    python audio_rescue.py
    goto end
)
echo Audio Rescue requires Python 3.10 or newer.
echo Download Python from https://www.python.org/downloads/
echo Check the Add python.exe to PATH option during installation.
:end
echo.
echo Audio Rescue has closed. Press any key to dismiss.
pause >nul
