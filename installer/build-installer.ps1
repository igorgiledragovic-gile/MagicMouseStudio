# Build MagicMouse Studio for distribution (no admin needed):
#   1. app icon  2. app -> MagicMouseStudio.exe (PyInstaller, one folder)  3. Setup.exe (Inno Setup 7)
# Output: installer\Output\MagicMouseStudio-Setup-<version>.exe
# Driver: uses the already built + test-signed driver\out\mmsfilter.sys (driver\build.ps1).
# Needs: app\.venv with app\requirements-build.txt, Inno Setup 6.4+/7 (ISCC.exe; pass -Iscc or install it normally).
param([string]$Iscc)
$ErrorActionPreference = 'Continue'   # native tools write progress to stderr; failures are checked via exit codes
if (-not $Iscc) {
  $Iscc = @((Join-Path $PSScriptRoot '..\..\tools\InnoSetup7\ISCC.exe'),
            "${env:ProgramFiles(x86)}\Inno Setup 7\ISCC.exe", "$env:ProgramFiles\Inno Setup 7\ISCC.exe",
            "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
            "$env:LOCALAPPDATA\Programs\Inno Setup 7\ISCC.exe", "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe") |
          Where-Object { Test-Path $_ } | Select-Object -First 1
  if (-not $Iscc) { $Iscc = (Get-Command ISCC.exe -ErrorAction SilentlyContinue).Source }
  if (-not $Iscc) { throw 'Inno Setup (ISCC.exe) not found - install it or pass -Iscc <path>' }
}
$root  = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$app   = Join-Path $root 'app'
$py    = Join-Path $app '.venv\Scripts\python.exe'
$work  = Join-Path $PSScriptRoot 'build'
$ver   = (& $py -c "import sys; sys.path.insert(0, r'$app'); import mmstudio; print(mmstudio.__version__)").Trim()
"version $ver"

# 1. icon
$env:QT_QPA_PLATFORM = 'offscreen'
& $py (Join-Path $app 'tools\make_icon.py'); if ($LASTEXITCODE) { throw 'icon failed' }
Remove-Item Env:QT_QPA_PLATFORM

# 2. tests must pass before packaging
foreach ($t in 'test_protocol.py', 'test_inputengine.py', 'test_i18n.py', 'test_widgets.py') {
  & $py -I (Join-Path $app "tests\$t") | Out-Null; if ($LASTEXITCODE) { throw "test $t failed" }
}
"tests ok"

# 3. PyInstaller (one folder: fast start, the installer compresses it)
$pkg = Join-Path $app 'mmstudio'
& $py -m PyInstaller --noconfirm --clean --log-level WARN --windowed --name MagicMouseStudio `
  --icon (Join-Path $pkg 'assets\app.ico') `
  --add-data "$pkg\locales;mmstudio\locales" --add-data "$pkg\assets;mmstudio\assets" `
  --add-binary "$pkg\mmshook.dll;mmstudio" `
  --exclude-module tkinter --exclude-module unittest --exclude-module pydoc `
  --version-file (Join-Path $PSScriptRoot 'version.txt') `
  --distpath (Join-Path $work 'dist') --workpath (Join-Path $work 'work') --specpath $work `
  (Join-Path $app 'run.py')
if ($LASTEXITCODE) { throw 'PyInstaller failed' }
$dist = Join-Path $work 'dist\MagicMouseStudio'
# Qt parts the app never uses (translations of Qt itself, PDF/QML/opengl software renderer)
Get-ChildItem $dist -Recurse -Include 'Qt6Pdf.dll','Qt6Qml*.dll','Qt6Quick*.dll','Qt6VirtualKeyboard.dll','opengl32sw.dll','Qt6OpenGL.dll' -ErrorAction SilentlyContinue | Remove-Item -Force
Remove-Item (Join-Path $dist '_internal\PySide6\translations') -Recurse -Force -ErrorAction SilentlyContinue
"app folder: {0:N1} MB" -f ((Get-ChildItem $dist -Recurse -File | Measure-Object Length -Sum).Sum / 1MB)

# 4. driver payload
$sys = Join-Path $root 'driver\out\mmsfilter.sys'
if ((Get-AuthenticodeSignature $sys).SignerCertificate -eq $null) { throw 'driver\out\mmsfilter.sys is not signed (run driver\build.ps1)' }

# 5. Setup.exe
& $Iscc /Q "/DAppVersion=$ver" (Join-Path $PSScriptRoot 'MagicMouseStudio.iss')
if ($LASTEXITCODE) { throw 'ISCC failed' }
Get-ChildItem (Join-Path $PSScriptRoot 'Output') | Select-Object Name, @{n='MB';e={[math]::Round($_.Length/1MB,1)}}, LastWriteTime
