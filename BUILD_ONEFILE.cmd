@echo off
setlocal EnableExtensions DisableDelayedExpansion
pushd "%~dp0" || (echo [ERROR] Cannot open source folder.& exit /b 1)
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
rem PySide6 is the only supported UI binding, including on machines with other Qt packages.
set "QT_API=pyside6"
set "PY_RUN="

rem Do not pin Python 3.11. Use an installed x64 Python 3.11+ (3.12 is supported).
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
    echo [ERROR] Python x64 3.11 or newer not found. Please install Python and reopen CMD.
    echo [INFO] No virtual environment was created.
    goto :failed
)

rem R24: selected LEAN only; no repeated candidate builds.
if not "%~1"=="" (
    echo [ERROR] Run BUILD_ONEFILE.cmd without arguments.
    goto :failed
)

echo.
echo [1/9] Python runtime - existing system interpreter, no venv
%PY_RUN% "build\preflight.py" python
if errorlevel 1 goto :failed

echo.
echo [2/9] Dependencies - install only if missing
%PY_RUN% "build\preflight.py" dependencies
if errorlevel 1 (
    if /I "%BUILD_NO_INSTALL%"=="1" (
        echo [ERROR] Missing dependencies; BUILD_NO_INSTALL=1 forbids installation.
        goto :failed
    )
    echo [INFO] Installing into the CURRENT Python, not creating a venv.
    %PY_RUN% -m pip install -r "requirements.txt" -r "build\requirements-build.txt"
    if errorlevel 1 goto :failed
    %PY_RUN% "build\preflight.py" dependencies
    if errorlevel 1 goto :failed
)

echo.
echo [3/9] Build/signing preflight and compile validation
%PY_RUN% "build\sign_release.py" --check-tools
if errorlevel 1 goto :failed
%PY_RUN% -m compileall -q "main.py" "drawing_editor" "build"
if errorlevel 1 goto :failed
if /I "%BUILD_RUN_TESTS%"=="1" (
    echo [INFO] BUILD_RUN_TESTS=1: running focused v1.1.0 regression tests.
    %PY_RUN% -m unittest discover -s build -p "test_v110.py" -v
    if errorlevel 1 goto :failed
    %PY_RUN% "build\test_release_gate.py"
    if errorlevel 1 goto :failed
    %PY_RUN% "build\test_pe_version.py"
    if errorlevel 1 goto :failed
) else (
    echo [INFO] Targeted packaged drawing QA is mandatory; full source suite is optional.
)

echo.
echo [4/9] Prepare clean STAGING output, retain previous successful release until publishing
echo [INFO] PySide6-only build: PyQt5, PyQt6, PySide2 and optional Matplotlib are excluded.
if not exist "build\staging" mkdir "build\staging"
if errorlevel 1 goto :failed
if exist "build\staging\Sunrise Drawing Editor.exe" del /q "build\staging\Sunrise Drawing Editor.exe"
if exist "build\staging\SIGNATURE_STATUS.json" del /q "build\staging\SIGNATURE_STATUS.json"
if exist "build\staging\SMOKE_STATUS.json" del /q "build\staging\SMOKE_STATUS.json"
if exist "build\staging\Sunrise Drawing Editor.exe" goto :failed

if exist "build\staging\PLAN.json" del /q "build\staging\PLAN.json"
if exist "build\staging\FUNCTIONAL_QA.json" del /q "build\staging\FUNCTIONAL_QA.json"
%PY_RUN% -m PyInstaller --noconfirm --clean ^
    --distpath "%CD%\build\staging" ^
    --workpath "%CD%\build\pyinstaller_work" ^
    "%CD%\build\onefile_lightweight.spec" -- --profile lean --plan "%CD%\build\staging\PLAN.json"
if errorlevel 1 goto :failed
if not exist "build\staging\Sunrise Drawing Editor.exe" (
    echo [ERROR] PyInstaller returned success but the EXE does not exist.
    goto :failed
)

echo.
echo [5/9] Windows version resource and EXE smoke test BEFORE signing
%PY_RUN% "build\smoke_test.py" "build\staging\Sunrise Drawing Editor.exe" --timeout 120
if errorlevel 1 goto :failed

echo.
echo [6/9] Sunrise Group Authenticode signing - CMD + native SignTool
%PY_RUN% "build\sign_release.py" "build\staging\Sunrise Drawing Editor.exe"
if errorlevel 1 goto :failed

echo.
echo [7/9] Windows version resource and EXE smoke test AFTER signing
%PY_RUN% "build\smoke_test.py" "build\staging\Sunrise Drawing Editor.exe" --timeout 120
if errorlevel 1 goto :failed

echo.
echo [8/9] Functional QA on actual signed LEAN EXE
%PY_RUN% "build\verify_lean.py" "build\staging\Sunrise Drawing Editor.exe" "build\staging\FUNCTIONAL_QA.json"
if errorlevel 1 goto :failed

echo.
echo [9/9] Publish local LEAN EXE and product release metadata after QA
%PY_RUN% "build\publish_release.py" "build\staging\Sunrise Drawing Editor.exe" "dist"
if errorlevel 1 goto :failed

echo.
echo [PASS] Local LEAN output: dist\Sunrise Drawing Editor.exe
echo [PASS] Release metadata: dist\release-metadata\latest.json
echo [PASS] Notice: dist\release-metadata\notice.txt
echo [INFO] Upload only after release approval; live repository feeds stay unchanged.
echo [INFO] Functional QA: build\staging\FUNCTIONAL_QA.json
echo [INFO] Full Windows GUI / DWG / RDP / trusted release QA remains required.
if exist "dist\SIGNATURE_STATUS.json" echo [INFO] Trust state: dist\SIGNATURE_STATUS.json
popd
exit /b 0

:failed
echo.
echo [FAILED] The previous dist EXE was not replaced.
echo [INFO] Review the step shown above. No PowerShell or virtual environment is used.
popd
exit /b 1
