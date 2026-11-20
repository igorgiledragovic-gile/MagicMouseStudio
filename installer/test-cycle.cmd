@echo off
rem Full test cycle on this PC (run through Explorer): reset view rotation -> silent UNINSTALL (UAC) and check
rem that app + driver are gone -> silent INSTALL (UAC) via test-install.cmd.
setlocal
set "HERE=%~dp0"
set "RES=%HERE%build\install-test"
if not exist "%RES%" mkdir "%RES%"
del /q "%RES%\*" 2>nul
"%HERE%..\app\.venv\Scripts\python.exe" "%HERE%..\app\tools\apply_settings.py" rotate=0
set "DIR=%ProgramFiles%\MagicMouse Studio"
if exist "%DIR%\unins000.exe" (
  "%DIR%\unins000.exe" /SILENT /SUPPRESSMSGBOXES /NORESTART /LOG="%RES%\uninstall.log"
  powershell -NoProfile -Command "for($i=0;$i -lt 90 -and ((Get-Process | ? { $_.ProcessName -like '_iu*' -or $_.ProcessName -eq 'unins000' }) -or (Test-Path '%DIR%\MagicMouseStudio.exe'));$i++){ Start-Sleep 2 }"
)
powershell -NoProfile -Command "'app exe present: ' + (Test-Path '%DIR%\MagicMouseStudio.exe'); 'service: ' + [bool](Get-Service mmsfilter -EA SilentlyContinue); 'sys file: ' + (Test-Path \"$env:SystemRoot\System32\drivers\mmsfilter.sys\"); Import-Module '%HERE%..\driver\filters.psm1'; Set-MmsLowerFilter -Enumerator BTHENUM -IdPattern 'PID&0269' -Filter mmsfilter -Mode get; 'startup lnk: ' + (Test-Path \"$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\MagicMouse Studio.lnk\"); 'running: ' + [bool](Get-Process MagicMouseStudio -EA SilentlyContinue)" > "%RES%\after-uninstall.txt" 2>&1
copy /y "%RES%\after-uninstall.txt" "%TEMP%\mms-after-uninstall.txt" >nul
call "%HERE%test-install.cmd"
copy /y "%TEMP%\mms-after-uninstall.txt" "%RES%\after-uninstall.txt" >nul
