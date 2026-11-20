# One-step install / update of mmsfilter (admin). Used by Setup.exe and usable by hand.
#   1. checks Test Mode (the driver is test-signed)
#   2. creates/updates the kernel service + driver file
#   3. LowerFilters of the Magic Mouse 2 Bluetooth HID node = { mmsfilter, applewirelessmouse, ... }
#      (mmsfilter is removed from the USB interface: USB carries no touch data on this mouse)
# Exit codes: 0 ok | 10 Test Mode off (nothing changed) | 11 driver installed, but no paired Magic Mouse 2
#             | 12 filter attached, but the Apple Boot Camp mouse driver is missing (no touch data) | 1 error
# Revert: uninstall.ps1
param([string]$Log, [string]$Sys)
if ([Environment]::Is64BitOperatingSystem -and -not [Environment]::Is64BitProcess) {
  # started from a 32-bit host (Setup.exe is 32-bit): System32 would be redirected to SysWOW64, where bcdedit and
  # pnputil do not exist and drivers\ is the wrong folder -> run again in the 64-bit PowerShell
  $a = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $PSCommandPath)
  if ($Log) { $a += '-Log', $Log }
  if ($Sys) { $a += '-Sys', $Sys }
  & "$env:SystemRoot\Sysnative\WindowsPowerShell\v1.0\powershell.exe" @a
  exit $LASTEXITCODE
}
if ($Log) { Start-Transcript -Path $Log -Force | Out-Null }
"powershell: " + $(if ([Environment]::Is64BitProcess) { '64-bit' } else { '32-bit' })
$ErrorActionPreference = 'Continue'
$code = 0
try {
  Import-Module (Join-Path $PSScriptRoot 'filters.psm1') -Force
  if (-not $Sys) {
    $Sys = Join-Path $PSScriptRoot 'mmsfilter.sys'
    if (-not (Test-Path $Sys)) { $Sys = Join-Path $PSScriptRoot 'out\mmsfilter.sys' }
  }
  $dst = "$env:SystemRoot\System32\drivers\mmsfilter.sys"
  $svcKey = 'HKLM:\SYSTEM\CurrentControlSet\Services\mmsfilter'
  $btPattern = '{00001124-0000-1000-8000-00805F9B34FB}_VID&0001004C_PID&0269'

  # 1. Test Mode
  $bcd = (& "$env:SystemRoot\System32\bcdedit.exe" /enum '{current}') -join "`n"
  "testsigning: " + [bool]($bcd -match 'testsigning\s+(Yes|Da|On)')
  if ($bcd -notmatch 'testsigning\s+(Yes|Da|On)') {
    # bcdedit output is localized; fall back to the registry copy of the boot options
    $opts = (Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control' -Name SystemStartOptions).SystemStartOptions
    "SystemStartOptions: $opts"
    if ($opts -notmatch 'TESTSIGNING') { "Test Mode is OFF -> driver not installed"; $code = 10; throw 'TESTMODE_OFF' }
  }
  if (-not (Test-Path $Sys)) { throw "driver file not found: $Sys" }
  "source: $Sys  signature: " + (Get-AuthenticodeSignature $Sys).SignerCertificate.Subject

  # 2. service + file
  if (-not (Get-Service mmsfilter -ErrorAction SilentlyContinue)) {
    sc.exe create mmsfilter type= kernel start= demand error= normal binPath= System32\drivers\mmsfilter.sys DisplayName= "MagicMouse Studio filter" | Out-Host
  }
  New-Item -Force "$svcKey\Parameters\Wdf" | Out-Null
  Set-ItemProperty "$svcKey\Parameters\Wdf" KmdfLibraryVersion '1.15'

  $same = (Test-Path $dst) -and ((Get-FileHash $dst).Hash -eq (Get-FileHash $Sys).Hash)
  if ($same) { "driver file: up to date" }
  else {
    # stop every device that has mmsfilter loaded, replace the file, start them again
    $ids = @()
    foreach ($e in 'USB', 'BTHENUM') {
      $ids += Set-MmsLowerFilter -Enumerator $e -IdPattern 'PID' -Filter 'mmsfilter' -Mode get |
              Where-Object { $_ -match 'mmsfilter' } | ForEach-Object { ($_ -split ' => ')[0] } |
              Where-Object { Get-PnpDevice -InstanceId $_ -PresentOnly -ErrorAction SilentlyContinue }
    }
    foreach ($id in $ids) { "disable $id"; pnputil /disable-device "$id" | Out-Null }
    for ($i = 0; $i -lt 20 -and (Get-Service mmsfilter).Status -eq 'Running'; $i++) { Start-Sleep -Milliseconds 300 }
    Copy-Item $Sys $dst -Force
    foreach ($id in $ids) { "enable $id"; pnputil /enable-device "$id" | Out-Null }
    "driver file updated: " + ((Get-FileHash $dst).Hash -eq (Get-FileHash $Sys).Hash)
  }

  # 3. filters
  "--- USB: remove"
  Set-MmsLowerFilter -Enumerator 'USB' -IdPattern 'VID_05AC&PID_0269' -Filter 'mmsfilter' -Mode remove | ForEach-Object {
    $_; $id = ($_ -split ' => ')[0]
    if ($_ -match 'changed' -and (Get-PnpDevice -InstanceId $id -PresentOnly -ErrorAction SilentlyContinue)) { pnputil /restart-device "$id" | Out-Null }
  }
  "--- Bluetooth HID (Magic Mouse 2): prepend"
  $r = @(Set-MmsLowerFilter -Enumerator 'BTHENUM' -IdPattern $btPattern -Filter 'mmsfilter' -Mode prepend)
  $r
  if ($r.Count -eq 0) { "no paired Magic Mouse 2 found -> pair it, then run Setup again"; $code = 11 }
  foreach ($t in $r) {
    $id = ($t -split ' => ')[0]
    if ($t -match 'changed' -and (Get-PnpDevice -InstanceId $id -PresentOnly -ErrorAction SilentlyContinue)) {
      "restart $id"; pnputil /restart-device "$id" | Out-Host
    }
  }
  if ($code -eq 0 -and -not (Get-Service applewirelessmouse -ErrorAction SilentlyContinue)) {
    "Apple Boot Camp mouse driver (applewirelessmouse) is missing -> no touch data"; $code = 12
  }
  Start-Sleep 2
  "service: " + (Get-Service mmsfilter).Status
} catch {
  if ($code -ne 10) { "ERROR: $_"; $code = 1 }
} finally {
  "exit code: $code"
  if ($Log) { Stop-Transcript | Out-Null }
}
exit $code
