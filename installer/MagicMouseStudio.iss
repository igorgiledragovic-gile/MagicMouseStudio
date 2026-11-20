; MagicMouse Studio - installer (Inno Setup 7). Build with installer\build-installer.ps1.
; Installs the app (PyInstaller folder) + the mmsfilter kernel filter (test-signed -> needs Windows Test Mode).
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#define AppName "MagicMouse Studio"
#define AppExe "MagicMouseStudio.exe"

[Setup]
AppId={{02955DD2-5E67-40E2-B545-8F210CE0D959}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppName}
VersionInfoVersion={#AppVersion}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=Output
OutputBaseFilename=MagicMouseStudio-Setup-{#AppVersion}
SetupIconFile=..\app\mmstudio\assets\app.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ShowLanguageDialog=yes
; English is the default; the language picked here is also the app's first-start language
LanguageDetectionMethod=none
CloseApplications=yes
RestartApplications=no
SetupLogging=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "serbian"; MessagesFile: "SerbianLatin.isl"
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"
Name: "french"; MessagesFile: "compiler:Languages\French.isl"
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "arabic"; MessagesFile: "compiler:Languages\Arabic.isl"

[CustomMessages]
english.DriverTask=Install the sensor driver (mmsfilter) for the Bluetooth Magic Mouse 2
english.DriverGroup=Driver:
english.DriverRunning=Installing the sensor driver...
english.TestModeOff=The app is installed, but the sensor driver was NOT installed: it is test-signed and Windows Test Mode is off.%n%nTo enable it (Secure Boot must be off), run in an administrator command prompt:%n    bcdedit /set testsigning on%nthen restart the computer and run this Setup again.
english.NoMouse=The driver is installed, but no paired Magic Mouse 2 was found.%n%nPair the mouse over Bluetooth, then run this Setup again to attach the driver.
english.NoApple=The driver is installed, but the Apple Boot Camp mouse driver (applewirelessmouse) is missing, so the mouse sends no touch data.%n%nInstall Apple's Boot Camp mouse driver, then restart the computer.
english.DriverError=The driver could not be installed (code %1). Details: %2
serbian.DriverTask=Instaliraj drajver senzora (mmsfilter) za Bluetooth Magic Mouse 2
serbian.DriverGroup=Drajver:
serbian.DriverRunning=Instaliranje drajvera senzora...
serbian.TestModeOff=Aplikacija je instalirana, ali drajver senzora NIJE: test-potpisan je, a Windows test režim je isključen.%n%nDa ga uključiš (Secure Boot mora biti isključen), u komandnoj liniji kao administrator pokreni:%n    bcdedit /set testsigning on%nzatim restartuj računar i ponovo pokreni ovu instalaciju.
serbian.NoMouse=Drajver je instaliran, ali nije pronađen uparen Magic Mouse 2.%n%nUpari miša preko Bluetooth-a, pa ponovo pokreni ovu instalaciju da se drajver poveže.
serbian.NoApple=Drajver je instaliran, ali nedostaje Apple Boot Camp drajver za miša (applewirelessmouse), pa miš ne šalje podatke o dodiru.%n%nInstaliraj Apple Boot Camp drajver za miša i restartuj računar.
serbian.DriverError=Drajver nije mogao da se instalira (kod %1). Detalji: %2
spanish.DriverTask=Instalar el controlador del sensor (mmsfilter) para el Magic Mouse 2 Bluetooth
spanish.DriverGroup=Controlador:
spanish.DriverRunning=Instalando el controlador del sensor...
spanish.TestModeOff=La aplicación está instalada, pero el controlador del sensor NO: tiene firma de prueba y el modo de prueba de Windows está desactivado.%n%nPara activarlo (Secure Boot debe estar desactivado), ejecute en un símbolo del sistema como administrador:%n    bcdedit /set testsigning on%nluego reinicie el equipo y vuelva a ejecutar este instalador.
spanish.NoMouse=El controlador está instalado, pero no se encontró ningún Magic Mouse 2 emparejado.%n%nEmpareje el ratón por Bluetooth y vuelva a ejecutar este instalador.
spanish.NoApple=El controlador está instalado, pero falta el controlador de ratón de Apple Boot Camp (applewirelessmouse), así que el ratón no envía datos táctiles.%n%nInstale el controlador de ratón de Boot Camp y reinicie el equipo.
spanish.DriverError=No se pudo instalar el controlador (código %1). Detalles: %2
brazilianportuguese.DriverTask=Instalar o driver do sensor (mmsfilter) para o Magic Mouse 2 Bluetooth
brazilianportuguese.DriverGroup=Driver:
brazilianportuguese.DriverRunning=Instalando o driver do sensor...
brazilianportuguese.TestModeOff=O aplicativo foi instalado, mas o driver do sensor NÃO: ele tem assinatura de teste e o modo de teste do Windows está desativado.%n%nPara ativá-lo (o Secure Boot deve estar desativado), execute em um prompt de comando como administrador:%n    bcdedit /set testsigning on%ndepois reinicie o computador e execute este instalador novamente.
brazilianportuguese.NoMouse=O driver foi instalado, mas nenhum Magic Mouse 2 pareado foi encontrado.%n%nPareie o mouse via Bluetooth e execute este instalador novamente.
brazilianportuguese.NoApple=O driver foi instalado, mas falta o driver de mouse do Apple Boot Camp (applewirelessmouse), então o mouse não envia dados de toque.%n%nInstale o driver de mouse do Boot Camp e reinicie o computador.
brazilianportuguese.DriverError=Não foi possível instalar o driver (código %1). Detalhes: %2
french.DriverTask=Installer le pilote du capteur (mmsfilter) pour la Magic Mouse 2 Bluetooth
french.DriverGroup=Pilote :
french.DriverRunning=Installation du pilote du capteur...
french.TestModeOff=L'application est installée, mais le pilote du capteur ne l'est PAS : il est signé pour les tests et le mode test de Windows est désactivé.%n%nPour l'activer (Secure Boot doit être désactivé), exécutez dans une invite de commandes administrateur :%n    bcdedit /set testsigning on%npuis redémarrez l'ordinateur et relancez ce programme d'installation.
french.NoMouse=Le pilote est installé, mais aucune Magic Mouse 2 appairée n'a été trouvée.%n%nAppairez la souris en Bluetooth, puis relancez ce programme d'installation.
french.NoApple=Le pilote est installé, mais le pilote de souris Apple Boot Camp (applewirelessmouse) est absent : la souris n'envoie aucune donnée tactile.%n%nInstallez le pilote de souris Boot Camp, puis redémarrez l'ordinateur.
french.DriverError=Le pilote n'a pas pu être installé (code %1). Détails : %2
chinesesimplified.DriverTask=为蓝牙 Magic Mouse 2 安装传感器驱动程序 (mmsfilter)
chinesesimplified.DriverGroup=驱动程序：
chinesesimplified.DriverRunning=正在安装传感器驱动程序...
chinesesimplified.TestModeOff=应用程序已安装，但传感器驱动程序未安装：它使用测试签名，而 Windows 测试模式已关闭。%n%n要启用测试模式（必须关闭安全启动），请在管理员命令提示符中运行：%n    bcdedit /set testsigning on%n然后重启计算机并再次运行本安装程序。
chinesesimplified.NoMouse=驱动程序已安装，但未找到已配对的 Magic Mouse 2。%n%n请通过蓝牙配对鼠标，然后再次运行本安装程序。
chinesesimplified.NoApple=驱动程序已安装，但缺少 Apple Boot Camp 鼠标驱动程序 (applewirelessmouse)，因此鼠标不会发送触控数据。%n%n请安装 Boot Camp 鼠标驱动程序并重启计算机。
chinesesimplified.DriverError=无法安装驱动程序（代码 %1）。详细信息：%2
arabic.DriverTask=تثبيت برنامج تشغيل المستشعر (mmsfilter) لماوس Magic Mouse 2 عبر البلوتوث
arabic.DriverGroup=برنامج التشغيل:
arabic.DriverRunning=جارٍ تثبيت برنامج تشغيل المستشعر...
arabic.TestModeOff=تم تثبيت التطبيق، لكن لم يتم تثبيت برنامج تشغيل المستشعر: فهو موقّع بتوقيع اختباري ووضع الاختبار في Windows متوقف.%n%nلتفعيله (يجب إيقاف Secure Boot)، شغّل في موجه أوامر المسؤول:%n    bcdedit /set testsigning on%nثم أعد تشغيل الكمبيوتر وشغّل هذا المثبّت مرة أخرى.
arabic.NoMouse=تم تثبيت برنامج التشغيل، لكن لم يتم العثور على Magic Mouse 2 مقترن.%n%nقم بإقران الماوس عبر البلوتوث، ثم شغّل هذا المثبّت مرة أخرى.
arabic.NoApple=تم تثبيت برنامج التشغيل، لكن برنامج تشغيل ماوس Apple Boot Camp (applewirelessmouse) غير موجود، لذلك لا يرسل الماوس بيانات اللمس.%n%nثبّت برنامج تشغيل ماوس Boot Camp ثم أعد تشغيل الكمبيوتر.
arabic.DriverError=تعذّر تثبيت برنامج التشغيل (الرمز %1). التفاصيل: %2

[Tasks]
Name: "driver"; Description: "{cm:DriverTask}"; GroupDescription: "{cm:DriverGroup}"
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "build\dist\MagicMouseStudio\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\driver\out\mmsfilter.sys"; DestDir: "{app}\driver"; Flags: ignoreversion
Source: "..\driver\filters.psm1"; DestDir: "{app}\driver"; Flags: ignoreversion
Source: "..\driver\setup-driver.ps1"; DestDir: "{app}\driver"; Flags: ignoreversion
Source: "..\driver\uninstall.ps1"; DestDir: "{app}\driver"; Flags: ignoreversion

[InstallDelete]
; an older shortcut may point to another copy; the app recreates it at its first start
Type: files; Name: "{userstartup}\MagicMouse Studio.lnk"
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: postinstall nowait skipifsilent runasoriginaluser

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM {#AppExe}"; Flags: runhidden; RunOnceId: "StopApp"
Filename: "{sysnative}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\driver\uninstall.ps1"" -Log ""{tmp}\mms-driver-uninstall.log"""; Flags: runhidden waituntilterminated; RunOnceId: "RemoveDriver"

[UninstallDelete]
Type: files; Name: "{userstartup}\MagicMouse Studio.lnk"
Type: files; Name: "{app}\language.txt"
Type: files; Name: "{app}\driver\*.log"

[Code]
function LangCode(): String;
begin
  case ActiveLanguage() of
    'serbian': Result := 'sr';
    'spanish': Result := 'es';
    'brazilianportuguese': Result := 'pt';
    'french': Result := 'fr';
    'chinesesimplified': Result := 'zh';
    'arabic': Result := 'ar';
  else
    Result := 'en';
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Rc: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM {#AppExe}', '', SW_HIDE, ewWaitUntilTerminated, Rc);
  Result := '';
end;

procedure InstallDriver();
var
  Rc: Integer;
  LogFile: String;
begin
  LogFile := ExpandConstant('{app}\driver\setup-driver.log');
  WizardForm.StatusLabel.Caption := CustomMessage('DriverRunning');
  if not Exec(ExpandConstant('{sysnative}\WindowsPowerShell\v1.0\powershell.exe'),
      '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{app}\driver\setup-driver.ps1') + '" -Log "' + LogFile + '"',
      ExpandConstant('{app}\driver'), SW_HIDE, ewWaitUntilTerminated, Rc) then
    Rc := 1;
  Log('mmsfilter setup-driver.ps1 exit code ' + IntToStr(Rc));
  case Rc of
    0: ;
    10: SuppressibleMsgBox(CustomMessage('TestModeOff'), mbInformation, MB_OK, IDOK);
    11: SuppressibleMsgBox(CustomMessage('NoMouse'), mbInformation, MB_OK, IDOK);
    12: SuppressibleMsgBox(CustomMessage('NoApple'), mbInformation, MB_OK, IDOK);
  else
    SuppressibleMsgBox(FmtMessage(CustomMessage('DriverError'), [IntToStr(Rc), LogFile]), mbError, MB_OK, IDOK);
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    SaveStringToFile(ExpandConstant('{app}\language.txt'), LangCode(), False);
    if WizardIsTaskSelected('driver') then
      InstallDriver();
  end;
end;
