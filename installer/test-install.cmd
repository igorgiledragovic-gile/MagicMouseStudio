@echo off
rem Install test on this PC (run through Explorer, not from inside a packaged app):
rem stops the development copy, installs Setup.exe silently (UAC prompt), starts the installed app, self-tests it.
setlocal
set "HERE=%~dp0"
set "RES=%HERE%build\install-test"
if not exist "%RES%" mkdir "%RES%"
del /q "%RES%\*" 2>nul
powershell -NoProfile -Command "Get-CimInstance Win32_Process | ? { $_.CommandLine -match 'MagicMouseStudio\\app\\run.py' } | %% { Stop-Process -Id $_.ProcessId -Force -EA SilentlyContinue }"
for %%f in ("%HERE%Output\MagicMouseStudio-Setup-*.exe") do set "SETUP=%%f"
"%SETUP%" /SILENT /SUPPRESSMSGBOXES /NORESTART /LOG="%RES%\setup.log"
echo setup exit code %ERRORLEVEL% > "%RES%\setup-rc.txt"
set "APP=%ProgramFiles%\MagicMouse Studio\MagicMouseStudio.exe"
start "" /wait "%APP%" --selftest "%RES%\selftest.txt"
start "" "%APP%"
powershell -NoProfile -Command "Start-Sleep 8; $l='%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\MagicMouse Studio.lnk'; if (Test-Path $l) { $s=(New-Object -ComObject WScript.Shell).CreateShortcut($l); 'startup lnk: ' + $s.TargetPath + ' ' + $s.Arguments } else { 'startup lnk: MISSING' }; Get-Process MagicMouseStudio -EA SilentlyContinue | select Id,StartTime | ft -auto | Out-String; Get-Content '%LOCALAPPDATA%\MagicMouseStudio\settings.json' | Select-String 'language','rotate'; 'driver service: ' + (Get-Service mmsfilter -EA SilentlyContinue).Status; 'driver file: ' + (Test-Path \"$env:SystemRoot\System32\drivers\mmsfilter.sys\"); Import-Module '%HERE%..\driver\filters.psm1'; Set-MmsLowerFilter -Enumerator BTHENUM -IdPattern 'PID&0269' -Filter mmsfilter -Mode get" > "%RES%\after.txt" 2>&1
copy /y "%ProgramFiles%\MagicMouse Studio\driver\setup-driver.log" "%RES%\" >nul 2>&1
echo done > "%RES%\done.txt"
