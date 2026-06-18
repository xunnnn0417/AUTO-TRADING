@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Run install.bat first.
  pause
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ws=New-Object -ComObject WScript.Shell; $s=$ws.CreateShortcut('%TEMP%\\TradingWorkflowHelper.lnk'); $s.TargetPath='%CD%\\.venv\\Scripts\\pythonw.exe'; $s.Arguments='main.py'; $s.WorkingDirectory='%CD%'; $s.IconLocation='%CD%\\assets\\app.ico'; $s.Save(); Start-Process $s.FullName"
