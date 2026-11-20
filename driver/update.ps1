# Reload a freshly built mmsfilter.sys (admin): disable filtered devices -> replace file -> enable.
param([string]$Log)
if ($Log) { Start-Transcript -Path $Log -Force | Out-Null }
Import-Module (Join-Path $PSScriptRoot 'filters.psm1') -Force
$ids = @()
foreach ($e in 'USB', 'BTHENUM') {
  $ids += Set-MmsLowerFilter -Enumerator $e -IdPattern 'PID' -Filter 'mmsfilter' -Mode get |
          Where-Object { $_ -match 'mmsfilter' } | ForEach-Object { ($_ -split ' => ')[0] } |
          Where-Object { Get-PnpDevice -InstanceId $_ -PresentOnly -ErrorAction SilentlyContinue }
}
foreach ($id in $ids) { "disable $id"; pnputil /disable-device "$id" | Out-Null }
for ($i = 0; $i -lt 20 -and (Get-Service mmsfilter).Status -eq 'Running'; $i++) { Start-Sleep -Milliseconds 300 }
"service after disable: " + (Get-Service mmsfilter).Status
Copy-Item (Join-Path $PSScriptRoot 'out\mmsfilter.sys') "$env:SystemRoot\System32\drivers\mmsfilter.sys" -Force
foreach ($id in $ids) { "enable $id"; pnputil /enable-device "$id" | Out-Null }
Start-Sleep 2
"service: " + (Get-Service mmsfilter).Status
(Get-FileHash "$env:SystemRoot\System32\drivers\mmsfilter.sys").Hash -eq (Get-FileHash (Join-Path $PSScriptRoot 'out\mmsfilter.sys')).Hash
if ($Log) { Stop-Transcript | Out-Null }
