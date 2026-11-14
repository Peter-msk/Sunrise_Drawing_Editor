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

echo [SOURCE GATE] Verify Git branch OR standalone GitHub source ZIP
if not exist "quality\P0_runtime" mkdir "quality\P0_runtime"
call :verify_source
if errorlevel 1 goto :failed

echo [1/9] Exact Git source identity: self-test
%PY_RUN% -m unittest discover -s tests -p "test_exact_branch_qa.py" -v
if errorlevel 1 goto :failed

echo [2/9] Isolated CAD worker: PNG parity, cancel, reuse, close
%PY_RUN% -m unittest discover -s tests -p "test_cad_worker_process.py" -v
if errorlevel 1 goto :failed

echo [3/9] DXF IPC response teardown race during OnMap switch
%PY_RUN% -m unittest discover -s tests -p "test_cad_ipc_close_race_stage6.py" -v
if errorlevel 1 goto :failed

echo [4/9] Catalog registration and batch MuPDF gate
%PY_RUN% -m unittest discover -s tests -p "test_p0_catalog_batch_gate.py" -v
if errorlevel 1 goto :failed

echo [5/9] Catalog registration ownership and remove/re-add race
%PY_RUN% -m unittest discover -s tests -p "test_catalog_generation_semantics.py" -v
if errorlevel 1 goto :failed

echo [6/9] DXF worker source revision and crash recovery
%PY_RUN% -m unittest discover -s tests -p "test_worker_source_identity.py" -v
if errorlevel 1 goto :failed

echo [7/9] HiDPI and light-dark theme asset contracts
%PY_RUN% -m unittest discover -s tests -p "test_hidpi_theme_icons_regression.py" -v
if errorlevel 1 goto :failed

echo [8/9] Stage8 SVG optical center and theme precedence
%PY_RUN% -m unittest discover -s tests -p "test_ui_optical_alignment_stage8.py" -v
if errorlevel 1 goto :failed

echo [9/9] Real DXF / OnMap QA, only when both input paths are given
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
echo [SOURCE GATE] Recheck source bytes after regression
call :verify_source
if errorlevel 1 goto :failed

echo [PASS] Completed requested QA commands only.
echo [INFO] SHA evidence: quality\P0_runtime\SOURCE_IDENTITY.json
echo [INFO] Windows Qt GUI, signed EXE and DPI 100-175%% still require manual checks.
popd
exit /b 0

:failed
echo.
echo [FAILED] Runtime QA did not finish successfully.
echo [INFO] Do not promote the work branch or copy the EXE to dist.
popd
exit /b 1

:verify_source
if exist ".git" (
    echo [INFO] Git checkout: strict branch/commit/source-identity validation
    if defined EXPECTED_SOURCE_SHA (
        %PY_RUN% "quality\qa_exact_branch.py" --expected-commit "%EXPECTED_SOURCE_SHA%" --report "quality\P0_runtime\SOURCE_IDENTITY.json"
    ) else (
        %PY_RUN% "quality\qa_exact_branch.py" --report "quality\P0_runtime\SOURCE_IDENTITY.json"
    )
) else (
    echo [INFO] GitHub ZIP: verify each tracked file against recorded Git blobs
    %PY_RUN% "quality\qa_source_archive.py" --report "quality\P0_runtime\SOURCE_IDENTITY.json"
)
exit /b %ERRORLEVEL%
