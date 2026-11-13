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
    echo [ERROR] Python x64 3.11+ is required.
    goto :failed
)
%PY_RUN% "build\preflight.py" runtime
if errorlevel 1 goto :failed

echo [1/4] Isolated CAD worker: PNG parity, cancel, reuse, close
%PY_RUN% -m unittest discover -s tests -p "test_cad_worker_process.py" -v
if errorlevel 1 goto :failed

echo [2/4] Catalog registration and batch MuPDF gate
%PY_RUN% -m unittest discover -s tests -p "test_p0_catalog_batch_gate.py" -v
if errorlevel 1 goto :failed

echo [3/4] HiDPI and light-dark theme asset contracts
%PY_RUN% -m unittest discover -s tests -p "test_hidpi_theme_icons_regression.py" -v
if errorlevel 1 goto :failed

echo [4/4] Real DXF / OnMap QA, only when both input paths are given
if "%~1"=="" (
    echo [NOT RUN] No real DXF/PDF paths were supplied.
    goto :optional_full
)
if "%~2"=="" (
    echo [ERROR] Please pass both DXF and OnMap PDF paths.
    goto :failed
)
if not exist "quality\P0_runtime" mkdir "quality\P0_runtime"
%PY_RUN% "quality\qa_dxf_onmap_handoff.py" "%~1" "%~2" --repeats 10 --report "quality\P0_runtime\DXF_ONMAP_HANDOFF.json"
if errorlevel 1 goto :failed

:optional_full
if /I "%RUN_ALL_TESTS%"=="1" (
    echo [OPTIONAL] Full regression suite
    %PY_RUN% -m unittest discover -s tests -v
    if errorlevel 1 goto :failed
)
echo.
echo [PASS] Completed requested QA commands only.
echo [INFO] Windows Qt GUI, signed EXE and DPI 100-175%% still require manual checks.
popd
exit /b 0

:failed
echo.
echo [FAILED] Runtime QA did not finish successfully.
echo [INFO] Do not promote the work branch or copy the EXE to dist.
popd
exit /b 1
