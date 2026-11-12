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

echo.
echo [1/8] Python runtime - existing system interpreter, no venv
%PY_RUN% "build\preflight.py" python
if errorlevel 1 goto :failed

echo.
echo [2/8] Dependencies - install only if missing
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
echo [3/8] Build/signing preflight and compile validation
%PY_RUN% "build\sign_release.py" --check-tools
if errorlevel 1 goto :failed
%PY_RUN% -m compileall -q "main.py" "drawing_editor" "build"
if errorlevel 1 goto :failed
if /I "%BUILD_RUN_TESTS%"=="1" (
    echo [INFO] BUILD_RUN_TESTS=1: running the full regression suite.
    %PY_RUN% -m unittest discover -s tests -v
    if errorlevel 1 goto :failed
) else (
    echo [INFO] Unchanged engine regression results retained; set BUILD_RUN_TESTS=1 to rerun.
)

echo.
echo [4/8] Prepare clean STAGING output, retain previous successful release until publishing
echo [INFO] PySide6-only build: PyQt5, PyQt6, PySide2 and optional Matplotlib are excluded.
if not exist "build\staging" mkdir "build\staging"
if errorlevel 1 goto :failed
if exist "build\staging\Sunrise Drawing Editor.exe" del /q "build\staging\Sunrise Drawing Editor.exe"
if exist "build\staging\SIGNATURE_STATUS.json" del /q "build\staging\SIGNATURE_STATUS.json"
if exist "build\staging\SMOKE_STATUS.json" del /q "build\staging\SMOKE_STATUS.json"
if exist "build\staging\Sunrise Drawing Editor.exe" goto :failed

%PY_RUN% -m PyInstaller --noconfirm --clean --onefile --windowed --noupx ^
    --name "Sunrise Drawing Editor" ^
    --icon "%CD%\assets\app.ico" --add-data "%CD%\assets;assets" ^
    --hidden-import "ezdxf.addons.drawing.pymupdf" ^
    --hidden-import "ezdxf.addons.drawing.recorder" ^
    --exclude-module "PyQt5" ^
    --exclude-module "PyQt6" ^
    --exclude-module "PySide2" ^
    --exclude-module "matplotlib" ^
    --hidden-import "ezdxf.addons.odafc" ^
    --exclude-module "PySide6.QtWebEngineCore" ^
    --exclude-module "PySide6.QtWebEngineWidgets" ^
    --exclude-module "PySide6.QtWebEngineQuick" ^
    --exclude-module "PySide6.QtPdf" ^
    --exclude-module "PySide6.QtPdfWidgets" ^
    --paths "%CD%" ^
    --distpath "%CD%\build\staging" ^
    --workpath "%CD%\build\pyinstaller_work" ^
    --specpath "%CD%\build\pyinstaller_spec" "%CD%\main.py"
if errorlevel 1 goto :failed
if not exist "build\staging\Sunrise Drawing Editor.exe" (
    echo [ERROR] PyInstaller returned success but the EXE does not exist.
    goto :failed
)

echo.
echo [5/8] Real packaged EXE smoke test BEFORE signing
%PY_RUN% "build\smoke_test.py" "build\staging\Sunrise Drawing Editor.exe" --timeout 120
if errorlevel 1 goto :failed

echo.
echo [6/8] Sunrise Group Authenticode signing - CMD + native SignTool
%PY_RUN% "build\sign_release.py" "build\staging\Sunrise Drawing Editor.exe"
if errorlevel 1 goto :failed

echo.
echo [7/8] Real packaged EXE smoke test AFTER signing
%PY_RUN% "build\smoke_test.py" "build\staging\Sunrise Drawing Editor.exe" --timeout 120
if errorlevel 1 goto :failed

echo.
echo [8/8] Atomic publish, signature/hash report
%PY_RUN% "build\publish_release.py" "build\staging\Sunrise Drawing Editor.exe" "dist"
if errorlevel 1 goto :failed

echo.
echo [PASS] dist\Sunrise Drawing Editor.exe
if exist "dist\SIGNATURE_STATUS.json" echo [INFO] Trust state: dist\SIGNATURE_STATUS.json
popd
exit /b 0

:failed
echo.
echo [FAILED] The previous dist EXE was not replaced.
echo [INFO] Review the step shown above. No PowerShell or virtual environment is used.
popd
exit /b 1
