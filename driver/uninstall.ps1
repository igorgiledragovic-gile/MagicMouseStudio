# Remove mmsfilter completely (admin): LowerFilters entries (USB + BTHENUM), service, driver file.
param([string]$Log)
if ([Environment]::Is64BitOperatingSystem -and -not [Environment]::Is64BitProcess) {
  # 32-bit host: System32 would be redirected to SysWOW64 -> run again in the 64-bit PowerShell
  $a = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $PSCommandPath)
  if ($Log) { $a += '-Log', $Log }
  & "$env:SystemRoot\Sysnative\WindowsPowerShell\v1.0\powershell.exe" @a
  exit $LASTEXITCODE
}
if ($Log) { Start-Transcript -Path $Log -Force | Out-Null }
Import-Module (Join-Path $PSScriptRoot 'filters.psm1') -Force
foreach ($e in 'USB', 'BTHENUM') {
  $r = Set-MmsLowerFilter -Enumerator $e -IdPattern 'PID' -Filter 'mmsfilter' -Mode remove | Where-Object { $_ -match 'changed' }
  $r
  foreach ($t in $r) { $id = ($t -split ' => ')[0]; if (Get-PnpDevice -InstanceId $id -PresentOnly -ErrorAction SilentlyContinue) { pnputil /restart-device "$id" | Out-Host } }
}
sc.exe stop mmsfilter | Out-Host
sc.exe delete mmsfilter | Out-Host
Remove-Item "$env:SystemRoot\System32\drivers\mmsfilter.sys" -Force -ErrorAction SilentlyContinue
if (Test-Path "$env:SystemRoot\System32\drivers\mmsfilter.sys") { "driver file in use - removed after reboot" }
if ($Log) { Stop-Transcript | Out-Null }
