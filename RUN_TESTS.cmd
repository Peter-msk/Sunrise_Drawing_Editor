@echo off
setlocal EnableExtensions DisableDelayedExpansion
pushd "%~dp0" || exit /b 1
set "PY_RUN=python"
where py >nul 2>nul
if not errorlevel 1 set "PY_RUN=py -3"
%PY_RUN% -m unittest discover -s tests -v
set "RESULT=%ERRORLEVEL%"
popd
exit /b %RESULT%
