@echo off
setlocal
cd /d "%~dp0"
if exist "dist\對沖小幫手\對沖小幫手.exe" (
  start "" "%CD%\dist\對沖小幫手\對沖小幫手.exe"
  exit /b 0
)
if exist ".venv\Scripts\pythonw.exe" (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "$ws=New-Object -ComObject WScript.Shell; $shortcut='%CD%\\對沖小幫手.lnk'; $s=$ws.CreateShortcut($shortcut); $s.TargetPath='%CD%\\.venv\\Scripts\\pythonw.exe'; $s.Arguments='main.py'; $s.WorkingDirectory='%CD%'; $s.IconLocation='%CD%\\assets\\app.ico'; $s.Save(); Start-Process $shortcut"
  exit /b 0
)
echo Run install.bat first.
pause
exit /b 1
