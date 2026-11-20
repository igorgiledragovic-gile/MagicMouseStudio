# Build mmshook.dll (x64) with VS 2022 Build Tools -> app\mmstudio\mmshook.dll
$ErrorActionPreference = 'Stop'
$vc  = 'C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat'
$src = Join-Path $PSScriptRoot 'mmshook.c'
$obj = Join-Path $PSScriptRoot 'out'; New-Item -ItemType Directory -Force $obj | Out-Null
$dll = Join-Path $PSScriptRoot '..\mmstudio\mmshook.dll'
$log = Join-Path $obj 'build.log'
# a loaded DLL cannot be overwritten but can be renamed: move the old one aside
if (Test-Path $dll) {
  Get-ChildItem (Join-Path $PSScriptRoot '..\mmstudio\mmshook.old-*.dll') -ErrorAction SilentlyContinue | Remove-Item -ErrorAction SilentlyContinue
  try { Remove-Item $dll -ErrorAction Stop } catch { Rename-Item $dll ("mmshook.old-{0}.dll" -f (Get-Date -Format 'HHmmss')) }
}
cmd /c "(call `"$vc`" >nul 2>&1 && cl /nologo /W4 /WX /O2 /LD /MT `"$src`" /Fo`"$obj\\`" /Fe`"$dll`" /link user32.lib kernel32.lib) > `"$log`" 2>&1"
$rc = $LASTEXITCODE
Get-Content $log | Where-Object { $_ -match 'error|warning' }
if ($rc -ne 0) { throw "build failed ($rc), see $log" }
Get-Item $dll | Select-Object Name, Length, LastWriteTime
