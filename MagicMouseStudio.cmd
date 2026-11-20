@echo off
rem MagicMouse Studio launcher (no console window)
start "" "%~dp0app\.venv\Scripts\pythonw.exe" "%~dp0app\run.py" %*
