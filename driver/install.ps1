# Install mmsfilter as LowerFilter on the Magic Mouse 2 USB interface 1 (admin; testsigning must be ON).
# Reversible with uninstall.ps1. Does not touch Bluetooth or any other device.
param([string]$Log)
if ($Log) { Start-Transcript -Path $Log -Force | Out-Null }
$ErrorActionPreference = 'Continue'
Import-Module (Join-Path $PSScriptRoot 'filters.psm1') -Force
$sys = Join-Path $PSScriptRoot 'out\mmsfilter.sys'
$dst = "$env:SystemRoot\System32\drivers\mmsfilter.sys"
$svc = 'HKLM:\SYSTEM\CurrentControlSet\Services\mmsfilter'

"testsigning: " + ((bcdedit /enum '{current}' | Select-String testsigning) -join '')

if (-not (Get-Service mmsfilter -ErrorAction SilentlyContinue)) {
  sc.exe create mmsfilter type= kernel start= demand error= normal binPath= System32\drivers\mmsfilter.sys DisplayName= "MagicMouse Studio filter" | Out-Host
}
Copy-Item $sys $dst -Force
New-Item -Force "$svc\Parameters\Wdf" | Out-Null
Set-ItemProperty "$svc\Parameters\Wdf" KmdfLibraryVersion '1.15'

"--- LowerFilters (USB MI_01 of Magic Mouse 2):"
$targets = Set-MmsLowerFilter -Enumerator 'USB' -IdPattern 'VID_05AC&PID_0269&MI_01' -Filter 'mmsfilter' -Mode add
$targets
foreach ($t in $targets) {
  $id = ($t -split ' => ')[0]
  if (Get-PnpDevice -InstanceId $id -PresentOnly -ErrorAction SilentlyContinue) { "restart $id"; pnputil /restart-device "$id" | Out-Host }
}
Start-Sleep 3
"--- service:"; sc.exe query mmsfilter | Out-Host
if ($Log) { Stop-Transcript | Out-Null }
