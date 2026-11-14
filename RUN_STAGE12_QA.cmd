@echo off
setlocal EnableExtensions DisableDelayedExpansion
pushd "%~dp0" || (echo [FAIL] Source folder unavailable.& exit /b 1)
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
if not defined PY_RUN (echo [FAIL] Requires Windows Python x64 3.11+.& goto :failed)

echo [1/5] Confirm source identity without enabling GitHub Actions
if exist ".git" (
    %PY_RUN% "quality\qa_exact_branch.py" --required-branch "STAGE13_SOURCE"
) else (
    %PY_RUN% "quality\qa_source_archive.py"
)
if errorlevel 1 goto :failed

echo [2/5] Manifest tampering and unexpected executable regression
%PY_RUN% -m unittest discover -s tests -p "test_stage12_source_archive.py" -v
if errorlevel 1 goto :failed

echo [3/5] Batch export, OCG, PNG and user wheel/static UI contract
%PY_RUN% -m unittest discover -s tests -p "test_batch_responsiveness_stage11.py" -v
if errorlevel 1 goto :failed

echo [4/5] Native Qt light/dark smoke (not real monitor visual approval)
%PY_RUN% -m unittest discover -s tests -p "test_stage11_qt_light_dark.py" -v
if errorlevel 1 goto :failed

echo [5/5] Recheck unchanged source bytes after targeted tests
if exist ".git" (
    %PY_RUN% "quality\qa_exact_branch.py" --required-branch "STAGE13_SOURCE"
) else (
    %PY_RUN% "quality\qa_source_archive.py"
)
if errorlevel 1 goto :failed

echo [PASS] Targeted audit complete.
echo [NOT RUN] Actual 15 OnMap field PDFs, real Windows DPI capture and signed onefile.
popd
exit /b 0

:failed
echo [FAILED] Stage12 targeted audit. Do not publish this candidate.
popd
exit /b 1
