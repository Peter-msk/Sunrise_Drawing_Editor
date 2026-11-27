@echo off
setlocal EnableExtensions DisableDelayedExpansion
pushd "%~dp0" || exit /b 1
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
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
if not defined PY_RUN (
  echo [ERROR] Python x64 3.11 or newer not found.
  popd
  exit /b 1
)
%PY_RUN% "build\final_qa_v150.py" --all
set "RESULT=%ERRORLEVEL%"
popd
exit /b %RESULT%
