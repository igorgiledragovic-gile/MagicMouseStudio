# Put mmsfilter UNDER the existing Bluetooth driver of the Magic Mouse 2 (admin; testsigning ON):
#   BTHENUM HID node LowerFilters = { mmsfilter, applewirelessmouse }
# mmsfilter only copies incoming L2CAP data; Apple's driver keeps doing multi-touch enable + scrolling.
# Also removes mmsfilter from the USB interface (USB carries no input on this mouse).
# Revert: uninstall.ps1
param([string]$Log)
if ($Log) { Start-Transcript -Path $Log -Force | Out-Null }
Import-Module (Join-Path $PSScriptRoot 'filters.psm1') -Force
$dst = "$env:SystemRoot\System32\drivers\mmsfilter.sys"

"--- USB: remove"
Set-MmsLowerFilter -Enumerator 'USB' -IdPattern 'VID_05AC&PID_0269&MI_01' -Filter 'mmsfilter' -Mode remove | ForEach-Object {
  $_; $id = ($_ -split ' => ')[0]
  if ($_ -match 'changed' -and (Get-PnpDevice -InstanceId $id -PresentOnly -ErrorAction SilentlyContinue)) { pnputil /restart-device "$id" | Out-Null }
}
for ($i = 0; $i -lt 20 -and (Get-Service mmsfilter).Status -eq 'Running'; $i++) { Start-Sleep -Milliseconds 300 }
"service after USB detach: " + (Get-Service mmsfilter).Status
Copy-Item (Join-Path $PSScriptRoot 'out\mmsfilter.sys') $dst -Force
"driver file updated: " + ((Get-FileHash $dst).Hash -eq (Get-FileHash (Join-Path $PSScriptRoot 'out\mmsfilter.sys')).Hash)

"--- BTHENUM HID (Magic Mouse 2): prepend"
$r = Set-MmsLowerFilter -Enumerator 'BTHENUM' -IdPattern '{00001124-0000-1000-8000-00805F9B34FB}_VID&0001004C_PID&0269' -Filter 'mmsfilter' -Mode prepend
$r
foreach ($t in $r) {
  $id = ($t -split ' => ')[0]
  if (Get-PnpDevice -InstanceId $id -PresentOnly -ErrorAction SilentlyContinue) { "restart $id"; pnputil /restart-device "$id" | Out-Host }
}
Start-Sleep 3
"service: " + (Get-Service mmsfilter).Status
if ($Log) { Stop-Transcript | Out-Null }
