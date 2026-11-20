@echo off
rem Copies the REAL (non-virtualized) MagicMouse Studio state into app\captures\real-state\
rem so it can be inspected from tools that run inside a packaged (MSIX) app container.
set OUT=%~dp0..\captures\real-state
if not exist "%OUT%" mkdir "%OUT%"
del /q "%OUT%\*" >nul 2>&1
copy /y "%LOCALAPPDATA%\MagicMouseStudio\*.*" "%OUT%\" >nul 2>&1
dir "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup" > "%OUT%\startup-folder.txt" 2>&1
reg query "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" > "%OUT%\run-key.txt" 2>&1
tasklist /fi "imagename eq pythonw.exe" /v > "%OUT%\tasks.txt" 2>&1
echo done %date% %time% > "%OUT%\done.txt"
