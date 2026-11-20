# Build + test-sign mmsfilter.sys (x64, KMDF 1.15) with VS 2022 Build Tools + WDK 10.0.26100.
# No admin needed. Output: driver\out\mmsfilter.sys
param([string]$CertSubject = 'CN=MagicMouse Studio Test')
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$out  = Join-Path $root 'out'; New-Item -ItemType Directory -Force $out | Out-Null
$wk   = 'C:\Program Files (x86)\Windows Kits\10'
$ver  = '10.0.26100.0'
$vc   = 'C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat'

$inc = @("$wk\Include\$ver\km", "$wk\Include\$ver\shared", "$wk\Include\wdf\kmdf\1.15", "$wk\Include\$ver\km\crt") | ForEach-Object { "/I`"$_`"" }
$defs = '/D_AMD64_ /DAMD64 /D_WIN64 /DNTDDI_VERSION=0x0A000000 /D_WIN32_WINNT=0x0A00 /DWINVER=0x0A00 /DKMDF_VERSION_MAJOR=1 /DKMDF_VERSION_MINOR=15 /DPOOL_NX_OPTIN=1 /DNDEBUG'
$cl   = "cl /nologo /c /W4 /WX /wd4324 /O2 /Zi /kernel /GS /Gy /Zp8 /Gz /Zc:wchar_t- $defs $($inc -join ' ') /Fo`"$out\\`" /Fd`"$out\mmsfilter_c.pdb`" `"$root\src\mmsfilter.c`""
$libs = @("$wk\Lib\$ver\km\x64\ntoskrnl.lib", "$wk\Lib\$ver\km\x64\hal.lib", "$wk\Lib\$ver\km\x64\BufferOverflowFastFailK.lib",
          "$wk\Lib\wdf\kmdf\x64\1.15\WdfLdr.lib", "$wk\Lib\wdf\kmdf\x64\1.15\WdfDriverEntry.lib") | ForEach-Object { "`"$_`"" }
$link = "link /nologo /DRIVER /SUBSYSTEM:NATIVE,10.00 /ENTRY:FxDriverEntry /NODEFAULTLIB /MACHINE:X64 /RELEASE /DEBUG /OPT:REF /OPT:ICF /MERGE:_TEXT=.text;_PAGE=PAGE /PDB:`"$out\mmsfilter.pdb`" /OUT:`"$out\mmsfilter.sys`" `"$out\mmsfilter.obj`" $($libs -join ' ')"

$log = Join-Path $out 'build.log'
$cmd = "call `"$vc`" >nul 2>&1 && $cl && $link"
cmd /c "($cmd) > `"$log`" 2>&1"
$rc = $LASTEXITCODE
Get-Content $log | Where-Object { $_ -match 'error|warning|mmsfilter' }
if ($rc -ne 0) { throw "build failed ($rc), see $log" }

# test certificate in the CURRENT USER store only (not trusted anywhere; testsigning mode accepts it)
$cert = Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert | Where-Object Subject -eq $CertSubject | Select-Object -First 1
if (-not $cert) {
  $cert = New-SelfSignedCertificate -Type CodeSigningCert -Subject $CertSubject -CertStoreLocation Cert:\CurrentUser\My -NotAfter (Get-Date).AddYears(3) -KeyExportPolicy NonExportable
}
& "$wk\bin\$ver\x64\signtool.exe" sign /fd SHA256 /s My /sha1 $cert.Thumbprint "$out\mmsfilter.sys"
if ($LASTEXITCODE -ne 0) { throw "sign failed" }
Get-Item "$out\mmsfilter.sys" | Select-Object Name, Length, LastWriteTime
