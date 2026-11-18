@echo off
setlocal EnableExtensions DisableDelayedExpansion
pushd "%~dp0" || exit /b 1
set "PYTHONUTF8=1"
set "PY_RUN="
where py >nul 2>nul
if not errorlevel 1 (
    py -3 "build\preflight.py" python >nul 2>nul
    if not errorlevel 1 set "PY_RUN=py -3"
)
if not defined PY_RUN (
    where python >nul 2>nul
    if not errorlevel 1 (
        python "build\preflight.py" python >nul 2>nul
        if not errorlevel 1 set "PY_RUN=python"
    )
)
if not defined PY_RUN (
    echo [ERROR] Windows x64 Python 3.11+ not found.
    popd
    exit /b 1
)
set "TARGET=dist\Sunrise Drawing Editor.exe"
if not "%~1"=="" set "TARGET=%~1"
set "REPORT=quality\onefile_size\ONEFILE_SIZE.json"
if not "%~2"=="" set "REPORT=%~2"
if not exist "%TARGET%" (
    echo [ERROR] Existing EXE not found: "%TARGET%"
    echo [INFO] Supply the existing EXE path as the first argument. No rebuild is required.
    popd
    exit /b 1
)
if exist "%REPORT%" (
    echo [ERROR] Report already exists. Supply a new JSON path as second argument.
    popd
    exit /b 1
)
%PY_RUN% "build\audit_onefile.py" "%TARGET%" --report "%REPORT%"
set "AUDIT_RC=%ERRORLEVEL%"
if not "%AUDIT_RC%"=="0" echo [INFO] Use the same Python with PyInstaller 6.x installed as used for building. No packages installed automatically.
popd
exit /b %AUDIT_RC%
