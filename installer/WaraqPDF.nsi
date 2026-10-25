Unicode true
!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "FileFunc.nsh"
!include "x64.nsh"
!include "WinVer.nsh"
!include "${GENERATED_FILES}"

Name "Waraq PDF ${APP_VERSION}"
OutFile "${SETUP_OUTPUT}"
InstallDir "$LOCALAPPDATA\Programs\WaraqPDF"
InstallDirRegKey HKCU "Software\WaraqPDF" "InstallDir"
RequestExecutionLevel user
SetCompressor /SOLID lzma
BrandingText "Waraq PDF — independent open-source PDF tools"
ShowInstDetails show
ShowUninstDetails show
VIProductVersion "0.4.0.0"
VIAddVersionKey "ProductName" "Waraq PDF"
VIAddVersionKey "FileDescription" "Waraq PDF Setup"
VIAddVersionKey "FileVersion" "${APP_VERSION}"
VIAddVersionKey "LegalCopyright" "Waraq PDF contributors — MIT application license"

!define MUI_ICON "${PROJECT_ROOT}\assets\waraq.ico"
!define MUI_UNICON "${PROJECT_ROOT}\assets\waraq.ico"
!define MUI_ABORTWARNING
!define MUI_FINISHPAGE_RUN "$INSTDIR\WaraqPDF.exe"
!define MUI_FINISHPAGE_RUN_NOTCHECKED

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "${PROJECT_ROOT}\LICENSE"
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_UNPAGE_FINISH
!insertmacro MUI_LANGUAGE "Arabic"
!insertmacro MUI_LANGUAGE "English"

Var TestMode
Var Parameters

Function .onInit
  SetShellVarContext current
  SetRegView 64
  ${IfNot} ${RunningX64}
    MessageBox MB_OK|MB_ICONSTOP "Waraq PDF requires 64-bit Windows 10 or Windows 11."
    Abort
  ${EndIf}
  ${IfNot} ${AtLeastWin10}
    MessageBox MB_OK|MB_ICONSTOP "Waraq PDF requires Windows 10 or newer."
    Abort
  ${EndIf}
  StrCpy $TestMode "0"
  ${GetParameters} $Parameters
  ClearErrors
  ${GetOptions} $Parameters "/TESTMODE" $0
  ${IfNot} ${Errors}
    StrCpy $TestMode "1"
  ${EndIf}
  ${If} $TestMode != "1"
    !insertmacro MUI_LANGDLL_DISPLAY
  ${EndIf}
FunctionEnd

Function EnsureAppClosed
  Retry:
  IfFileExists "$INSTDIR\WaraqPDF.exe" 0 Finished
  System::Call 'kernel32::CreateFileW(w "$INSTDIR\WaraqPDF.exe", i 0x40000000, i 7, p 0, i 3, i 0, p 0) p.r0'
  ${If} $0 == -1
    MessageBox MB_RETRYCANCEL|MB_ICONEXCLAMATION "أغلق ورّاق PDF قبل التثبيت أو التحديث، ثم اختر إعادة المحاولة.$\r$\nClose Waraq PDF before installing or updating." IDRETRY Retry
    Abort
  ${Else}
    System::Call 'kernel32::CloseHandle(p r0)'
  ${EndIf}
  Finished:
FunctionEnd

Section "Waraq PDF — البرنامج الأساسي" SEC_MAIN
  SectionIn RO
  Call EnsureAppClosed
  !insertmacro WARAQ_INSTALL_FILES
  SetOutPath "$INSTDIR"
  FileOpen $0 "$INSTDIR\.waraq-install" w
  FileWrite $0 "$TestMode"
  FileClose $0
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  ${If} $TestMode == "1"
    Goto DoneRegistration
  ${EndIf}
  WriteRegStr HKCU "Software\WaraqPDF" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\WaraqPDF" "DisplayName" "Waraq PDF"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\WaraqPDF" "DisplayVersion" "${APP_VERSION}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\WaraqPDF" "Publisher" "Waraq PDF contributors"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\WaraqPDF" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\WaraqPDF" "UninstallString" '$\"$INSTDIR\Uninstall.exe$\"'
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\WaraqPDF" "QuietUninstallString" '$\"$INSTDIR\Uninstall.exe$\" /S'
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\WaraqPDF" "DisplayIcon" "$INSTDIR\WaraqPDF.exe,0"
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\WaraqPDF" "NoModify" 1
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\WaraqPDF" "NoRepair" 1
  WriteRegStr HKCU "Software\Classes\WaraqPDF.Document" "" "PDF document — Waraq PDF"
  WriteRegStr HKCU "Software\Classes\WaraqPDF.Document\DefaultIcon" "" "$INSTDIR\WaraqPDF.exe,0"
  WriteRegStr HKCU "Software\Classes\WaraqPDF.Document\shell\open\command" "" '$\"$INSTDIR\WaraqPDF.exe$\" $\"%1$\"'
  WriteRegStr HKCU "Software\Classes\WaraqPDF.Document\shell\print\command" "" '$\"$INSTDIR\WaraqPDF.exe$\" --print $\"%1$\"'
  WriteRegStr HKCU "Software\Classes\.pdf\OpenWithProgids" "WaraqPDF.Document" ""
  WriteRegStr HKCU "Software\Classes\Applications\WaraqPDF.exe" "FriendlyAppName" "Waraq PDF"
  WriteRegStr HKCU "Software\Classes\Applications\WaraqPDF.exe\SupportedTypes" ".pdf" ""
  WriteRegStr HKCU "Software\Classes\Applications\WaraqPDF.exe\shell\open\command" "" '$\"$INSTDIR\WaraqPDF.exe$\" $\"%1$\"'
  WriteRegStr HKCU "Software\WaraqPDF\Capabilities" "ApplicationName" "Waraq PDF"
  WriteRegStr HKCU "Software\WaraqPDF\Capabilities" "ApplicationDescription" "عرض ودمج وإنشاء وطباعة PDF محليًا"
  WriteRegStr HKCU "Software\WaraqPDF\Capabilities\FileAssociations" ".pdf" "WaraqPDF.Document"
  WriteRegStr HKCU "Software\RegisteredApplications" "Waraq PDF" "Software\WaraqPDF\Capabilities"
  CreateDirectory "$SMPROGRAMS\Waraq PDF"
  CreateShortcut "$SMPROGRAMS\Waraq PDF\Waraq PDF.lnk" "$INSTDIR\WaraqPDF.exe"
  CreateShortcut "$SMPROGRAMS\Waraq PDF\Uninstall.lnk" "$INSTDIR\Uninstall.exe"
  System::Call 'shell32::SHChangeNotify(i 0x08000000, i 0, p 0, p 0)'
  DoneRegistration:
SectionEnd

Section /o "اختصار على سطح المكتب — Desktop shortcut" SEC_DESKTOP
  ${If} $TestMode != "1"
    CreateShortcut "$DESKTOP\Waraq PDF.lnk" "$INSTDIR\WaraqPDF.exe"
  ${EndIf}
SectionEnd

Function un.onInit
  SetShellVarContext current
  SetRegView 64
  IfFileExists "$INSTDIR\.waraq-install" 0 InvalidDirectory
  FileOpen $0 "$INSTDIR\.waraq-install" r
  FileRead $0 $TestMode
  FileClose $0
  Return
  InvalidDirectory:
  MessageBox MB_OK|MB_ICONSTOP "This directory is not a Waraq PDF installation."
  Abort
FunctionEnd

Function un.EnsureAppClosed
  Retry:
  IfFileExists "$INSTDIR\WaraqPDF.exe" 0 Finished
  System::Call 'kernel32::CreateFileW(w "$INSTDIR\WaraqPDF.exe", i 0x40000000, i 7, p 0, i 3, i 0, p 0) p.r0'
  ${If} $0 == -1
    MessageBox MB_RETRYCANCEL|MB_ICONEXCLAMATION "أغلق ورّاق PDF قبل إلغاء التثبيت، ثم اختر إعادة المحاولة.$\r$\nClose Waraq PDF before uninstalling." IDRETRY Retry
    Abort
  ${Else}
    System::Call 'kernel32::CloseHandle(p r0)'
  ${EndIf}
  Finished:
FunctionEnd

Section "Uninstall"
  Call un.EnsureAppClosed
  !insertmacro WARAQ_UNINSTALL_FILES
  Delete "$INSTDIR\.waraq-install"
  Delete "$INSTDIR\Uninstall.exe"
  ${If} $TestMode != "1"
    Delete "$DESKTOP\Waraq PDF.lnk"
    Delete "$SMPROGRAMS\Waraq PDF\Waraq PDF.lnk"
    Delete "$SMPROGRAMS\Waraq PDF\Uninstall.lnk"
    RMDir "$SMPROGRAMS\Waraq PDF"
    DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\WaraqPDF"
    DeleteRegValue HKCU "Software\Classes\.pdf\OpenWithProgids" "WaraqPDF.Document"
    DeleteRegKey HKCU "Software\Classes\WaraqPDF.Document"
    DeleteRegKey HKCU "Software\Classes\Applications\WaraqPDF.exe"
    DeleteRegValue HKCU "Software\RegisteredApplications" "Waraq PDF"
    DeleteRegKey HKCU "Software\WaraqPDF"
    System::Call 'shell32::SHChangeNotify(i 0x08000000, i 0, p 0, p 0)'
  ${EndIf}
  ; Only known installed files are deleted. User-created documents are retained.
  RMDir "$INSTDIR"
SectionEnd
