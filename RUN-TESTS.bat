@echo off
setlocal
cd /d "%~dp0"
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
if not errorlevel 1 (
    py -3 -m unittest -v test_audio_rescue
    goto end
)
python -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
if not errorlevel 1 (
    python -m unittest -v test_audio_rescue
    goto end
)
echo Python 3.10 or later is required.
:end
echo.
pause
