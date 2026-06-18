@echo off
setlocal
cd /d "%~dp0"
if exist "dist\TradingWorkflowHelper\TradingWorkflowHelper.exe" (
  start "" "%CD%\dist\TradingWorkflowHelper\TradingWorkflowHelper.exe"
  exit /b 0
)
if exist ".venv\Scripts\pythonw.exe" (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "$ws=New-Object -ComObject WScript.Shell; $shortcut='%CD%\\TradingWorkflowHelper.lnk'; $s=$ws.CreateShortcut($shortcut); $s.TargetPath='%CD%\\.venv\\Scripts\\pythonw.exe'; $s.Arguments='main.py'; $s.WorkingDirectory='%CD%'; $s.IconLocation='%CD%\\assets\\app.ico'; $s.Save(); Start-Process $shortcut"
  exit /b 0
)
echo Run install.bat first.
pause
exit /b 1
