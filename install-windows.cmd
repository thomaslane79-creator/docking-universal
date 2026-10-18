@echo off
echo Docking Universal native Windows DEVELOPMENT PREVIEW
echo Setup downloads private dependencies and does not require Python or Conda.
echo Scientific desktop integration is not yet a supported Windows release.
choice /C YN /N /M "Continue with preview installation? [Y/N] "
if errorlevel 2 exit /b 1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-windows.ps1" -AcceptDevelopmentPreview %*
set "du_install_result=%errorlevel%"
if not "%du_install_result%"=="0" echo Setup did not complete. Read the message above; partial files were retained.
pause
exit /b %du_install_result%
