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
$sysFile = "$env:SystemRoot\System32\drivers\mmsfilter.sys"
Remove-Item $sysFile -Force -ErrorAction SilentlyContinue
if (Test-Path $sysFile) {
  # still loaded (e.g. an open handle to \\.\MagicMouseStudio): let Windows delete it at the next boot
  if (-not ('MmsUninstall.Native' -as [type])) {
    Add-Type -Namespace MmsUninstall -Name Native -MemberDefinition '[DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)] public static extern bool MoveFileEx(string existing, string target, int flags);'
  }
  # [NullString]::Value: a plain $null would be marshalled as "" and MoveFileEx fails with error 3
  if ([MmsUninstall.Native]::MoveFileEx($sysFile, [NullString]::Value, 4)) {  # 4 = MOVEFILE_DELAY_UNTIL_REBOOT
    "driver file in use - scheduled for deletion at next reboot"
  } else {
    "driver file in use - could not schedule deletion (error $([Runtime.InteropServices.Marshal]::GetLastWin32Error())); delete $sysFile after a reboot"
  }
}
if ($Log) { Stop-Transcript | Out-Null }
