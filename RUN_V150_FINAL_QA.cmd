@echo off
setlocal EnableExtensions DisableDelayedExpansion
pushd "%~dp0" || exit /b 1
where py >nul 2>nul
if not errorlevel 1 (
  py -3 "build\final_qa_v150.py" --all
) else (
  python "build\final_qa_v150.py" --all
)
set "RESULT=%ERRORLEVEL%"
popd
exit /b %RESULT%
