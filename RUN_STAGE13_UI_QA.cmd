@echo off
setlocal EnableExtensions DisableDelayedExpansion
pushd "%~dp0" || (echo [FAIL] Cannot open source folder.& exit /b 1)
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
if not defined PY_RUN (echo [FAIL] Windows x64 Python 3.11+ required.& goto :failed)
%PY_RUN% "build\preflight.py" runtime
if errorlevel 1 goto :failed

echo [1/4] Verify source against exact Git branch or ZIP blob manifest
if exist ".git" (
  %PY_RUN% "quality\qa_exact_branch.py" --required-branch "STAGE13_SOURCE"
) else (
  %PY_RUN% "quality\qa_source_archive.py"
)
if errorlevel 1 goto :failed

echo [2/4] Run ONLY Stage13 changed-area UI contracts
%PY_RUN% -m unittest discover -s tests -p "test_stage13_ui_final.py" -v
if errorlevel 1 goto :failed

echo [3/4] Capture 100 / 125 / 150 / 175 percent logical Qt DPI, both themes
if not exist "quality\P0_runtime\UI_STAGE13" mkdir "quality\P0_runtime\UI_STAGE13"
for %%S in (1.0 1.25 1.5 1.75) do (
  %PY_RUN% "quality\qa_stage13_ui_final.py" --scale %%S --output "quality\P0_runtime\UI_STAGE13"
  if errorlevel 1 goto :failed
)

echo [4/4] Revalidate exact source after Qt screenshot evidence
if exist ".git" (
  %PY_RUN% "quality\qa_exact_branch.py" --required-branch "STAGE13_SOURCE"
) else (
  %PY_RUN% "quality\qa_source_archive.py"
)
if errorlevel 1 goto :failed

echo [PASS] Stage13 Qt geometry smoke / screenshot evidence collected.
echo [NOT RUN] Physical monitor DPI visual sign-off and actual 15-OnMap export.
echo [INFO] Review quality\P0_runtime\UI_STAGE13 images and JSON reports.
popd
exit /b 0

:failed
echo [FAIL] Stage13 QA; inspect the saved reports, no official release.
popd
exit /b 1
