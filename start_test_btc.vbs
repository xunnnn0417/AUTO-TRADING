Option Explicit

Dim shell, pythonw, entryPoint, command
Set shell = CreateObject("WScript.Shell")

pythonw = "C:\Users\User\Desktop\codex\trading-workflow-helper\.venv\Scripts\pythonw.exe"
entryPoint = "C:\Users\User\Desktop\codex\AUTO-TRADING-lab-unified\main.py"
shell.CurrentDirectory = "C:\Users\User\Desktop\codex\AUTO-TRADING-lab-unified"
command = """" & pythonw & """ """ & entryPoint & """"
shell.Run command, 0, False
