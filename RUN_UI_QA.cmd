@echo off
setlocal
cd /d "%~dp0"
REM Optional Qt screenshot/geometry QA. No PowerShell or virtualenv is used.
REM QT_SCALE_FACTOR simulates scale, but real Windows display DPI must also be tested.
set "PYTHON=python"
if not "%~1"=="" set "PYTHON=%~1"
REM Test small, medium and large logical windows at representative scales.
REM These are simulated Qt scales, NOT proof of native Windows DPI compatibility.
set "QT_SCALE_FACTOR=1"
"%PYTHON%" "quality\qa_gui_layout.py" --width 760 --height 480 --scale-label 100_small
if errorlevel 1 goto :failed
set "QT_SCALE_FACTOR=1.25"
"%PYTHON%" "quality\qa_gui_layout.py" --width 900 --height 650 --scale-label 125_compact
if errorlevel 1 goto :failed
set "QT_SCALE_FACTOR=1.5"
"%PYTHON%" "quality\qa_gui_layout.py" --width 1120 --height 760 --scale-label 150_normal
if errorlevel 1 goto :failed
set "QT_SCALE_FACTOR=1.75"
"%PYTHON%" "quality\qa_gui_layout.py" --width 1440 --height 850 --scale-label 175_wide
if errorlevel 1 goto :failed
echo UI screenshot QA completed. Check quality\ui_qa_artifacts.
exit /b 0
:failed
echo UI screenshot QA failed. Review JSON and screenshot.
exit /b 1
