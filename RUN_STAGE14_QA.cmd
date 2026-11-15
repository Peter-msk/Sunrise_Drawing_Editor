@echo off
setlocal EnableExtensions DisableDelayedExpansion
pushd "%~dp0" || (echo [FAIL] Cannot open Stage14 source folder.& exit /b 1)
set "PYTHONUTF8=1"
set "QT_API=pyside6"
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
if not defined PY_RUN (echo [FAIL] Windows x64 Python 3.11+ required.& goto :fail)
%PY_RUN% "build\preflight.py" runtime
if errorlevel 1 goto :fail
echo [1/6] Source identity gate: Git branch or verified GitHub ZIP
if exist ".git" (
    %PY_RUN% "quality\qa_exact_branch.py" --required-branch "STAGE14_SOURCE"
) else (
    %PY_RUN% "quality\qa_source_archive.py"
)
if errorlevel 1 goto :fail
echo [2/6] Compile modified native render, GUI and QA code
%PY_RUN% -m compileall -q "drawing_editor" "quality" "tests" "main.py"
if errorlevel 1 goto :fail
echo [3/6] Stage14 real subprocess OCG + icon/checkbox contracts
%PY_RUN% -m unittest discover -s tests -p "test_stage14_render_icons.py" -v
if errorlevel 1 goto :fail
echo [4/6] Light-dark vector icon syntax and optical geometry
%PY_RUN% -m unittest discover -s tests -p "test_hidpi_theme_icons_regression.py" -v
if errorlevel 1 goto :fail
%PY_RUN% -m unittest discover -s tests -p "test_ui_optical_alignment_stage8.py" -v
if errorlevel 1 goto :fail
echo [5/6] Capture both themes, four Qt scales, four window sizes
if not exist "quality\P0_runtime\UI_STAGE14" mkdir "quality\P0_runtime\UI_STAGE14"
for %%S in (1.0 1.25 1.5 1.75) do (
    %PY_RUN% "quality\qa_stage13_ui_final.py" --scale %%S --output "quality\P0_runtime\UI_STAGE14"
    if errorlevel 1 goto :fail
)
if defined STAGE14_PDF_DIR (
    echo [FIELD] Real OnMap OCG raster timing and pixel parity
    %PY_RUN% -m quality.benchmark_stage14_onmap --pdf-dir "%STAGE14_PDF_DIR%"
    if errorlevel 1 goto :fail
)
echo [6/6] Verify unchanged audited source tree
if exist ".git" (
    %PY_RUN% "quality\qa_exact_branch.py" --required-branch "STAGE14_SOURCE"
) else (
    %PY_RUN% "quality\qa_source_archive.py"
)
if errorlevel 1 goto :fail
echo [PASS] Stage14 targeted QA and synthetic native OCG pixel parity.
echo [NOT RUN] Real user 15-OnMap field performance unless STAGE14_PDF_DIR is configured.
echo [INFO] Review light/dark PNG files under quality\P0_runtime\UI_STAGE14.
popd
exit /b 0
:fail
echo [FAILED] Stage14 candidate cannot be promoted to the official release.
popd
exit /b 1
