Unicode true
!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "FileFunc.nsh"
!include "x64.nsh"
!include "WinVer.nsh"
!include "${GENERATED_FILES}"

Name "VELLORA ${APP_VERSION}"
OutFile "${SETUP_OUTPUT}"
InstallDir "$LOCALAPPDATA\Programs\VelloraPDF"
InstallDirRegKey HKCU "Software\VelloraPDF" "InstallDir"
RequestExecutionLevel user
SetCompressor /SOLID lzma
BrandingText "VELLORA — Professional PDF Studio"
ShowInstDetails show
ShowUninstDetails show
VIProductVersion "2.6.0.0"
VIAddVersionKey "ProductName" "VELLORA"
VIAddVersionKey "FileDescription" "VELLORA PDF Studio Installer"
VIAddVersionKey "FileVersion" "${APP_VERSION}"
VIAddVersionKey "LegalCopyright" "VELLORA contributors — MIT application license"

!define MUI_ICON "${PROJECT_ROOT}\assets\vellora.ico"
!define MUI_UNICON "${PROJECT_ROOT}\assets\vellora.ico"
!define MUI_ABORTWARNING
!define MUI_FINISHPAGE_RUN "$INSTDIR\Vellora.exe"
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
    MessageBox MB_OK|MB_ICONSTOP "VELLORA requires 64-bit Windows 10 or Windows 11."
    Abort
  ${EndIf}
  ${IfNot} ${AtLeastWin10}
    MessageBox MB_OK|MB_ICONSTOP "VELLORA requires Windows 10 or newer."
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
  IfFileExists "$INSTDIR\Vellora.exe" 0 Finished
  System::Call 'kernel32::CreateFileW(w "$INSTDIR\Vellora.exe", i 0x40000000, i 7, p 0, i 3, i 0, p 0) p.r0'
  ${If} $0 == -1
    MessageBox MB_RETRYCANCEL|MB_ICONEXCLAMATION "أغلق VELLORA قبل التثبيت أو التحديث، ثم اختر إعادة المحاولة.$\r$\nClose VELLORA before installing or updating." IDRETRY Retry
    Abort
  ${Else}
    System::Call 'kernel32::CloseHandle(p r0)'
  ${EndIf}
  Finished:
FunctionEnd

Section "VELLORA — البرنامج الأساسي" SEC_MAIN
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
  WriteRegStr HKCU "Software\VelloraPDF" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\VelloraPDF" "DisplayName" "VELLORA"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\VelloraPDF" "DisplayVersion" "${APP_VERSION}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\VelloraPDF" "Publisher" "VELLORA contributors"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\VelloraPDF" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\VelloraPDF" "UninstallString" '$\"$INSTDIR\Uninstall.exe$\"'
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\VelloraPDF" "QuietUninstallString" '$\"$INSTDIR\Uninstall.exe$\" /S'
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\VelloraPDF" "DisplayIcon" "$INSTDIR\Vellora.exe,0"
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\VelloraPDF" "NoModify" 1
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\VelloraPDF" "NoRepair" 1
  WriteRegStr HKCU "Software\Classes\VelloraPDF.Document" "" "VELLORA PDF Document"
  WriteRegStr HKCU "Software\Classes\VelloraPDF.Document\DefaultIcon" "" "$INSTDIR\Vellora.exe,0"
  WriteRegStr HKCU "Software\Classes\VelloraPDF.Document\shell\open\command" "" '$\"$INSTDIR\Vellora.exe$\" $\"%1$\"'
  WriteRegStr HKCU "Software\Classes\VelloraPDF.Document\shell\print\command" "" '$\"$INSTDIR\Vellora.exe$\" --print $\"%1$\"'
  WriteRegStr HKCU "Software\Classes\.pdf\OpenWithProgids" "VelloraPDF.Document" ""
  WriteRegStr HKCU "Software\Classes\Applications\Vellora.exe" "FriendlyAppName" "VELLORA"
  WriteRegStr HKCU "Software\Classes\Applications\Vellora.exe\SupportedTypes" ".pdf" ""
  WriteRegStr HKCU "Software\Classes\Applications\Vellora.exe\shell\open\command" "" '$\"$INSTDIR\Vellora.exe$\" $\"%1$\"'
  WriteRegStr HKCU "Software\VelloraPDF\Capabilities" "ApplicationName" "VELLORA"
  WriteRegStr HKCU "Software\VelloraPDF\Capabilities" "ApplicationDescription" "Professional local PDF creation and editing"
  WriteRegStr HKCU "Software\VelloraPDF\Capabilities\FileAssociations" ".pdf" "VelloraPDF.Document"
  WriteRegStr HKCU "Software\RegisteredApplications" "VELLORA" "Software\VelloraPDF\Capabilities"
  CreateDirectory "$SMPROGRAMS\VELLORA"
  CreateShortcut "$SMPROGRAMS\VELLORA\VELLORA.lnk" "$INSTDIR\Vellora.exe"
  CreateShortcut "$SMPROGRAMS\VELLORA\Uninstall VELLORA.lnk" "$INSTDIR\Uninstall.exe"
  System::Call 'shell32::SHChangeNotify(i 0x08000000, i 0, p 0, p 0)'
  DoneRegistration:
SectionEnd

Section /o "اختصار على سطح المكتب — Desktop shortcut" SEC_DESKTOP
  ${If} $TestMode != "1"
    CreateShortcut "$DESKTOP\VELLORA.lnk" "$INSTDIR\Vellora.exe"
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
  MessageBox MB_OK|MB_ICONSTOP "This directory is not a VELLORA installation."
  Abort
FunctionEnd

Function un.EnsureAppClosed
  Retry:
  IfFileExists "$INSTDIR\Vellora.exe" 0 Finished
  System::Call 'kernel32::CreateFileW(w "$INSTDIR\Vellora.exe", i 0x40000000, i 7, p 0, i 3, i 0, p 0) p.r0'
  ${If} $0 == -1
    MessageBox MB_RETRYCANCEL|MB_ICONEXCLAMATION "أغلق VELLORA قبل إلغاء التثبيت، ثم اختر إعادة المحاولة.$\r$\nClose VELLORA before uninstalling." IDRETRY Retry
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
    Delete "$DESKTOP\VELLORA.lnk"
    Delete "$SMPROGRAMS\VELLORA\VELLORA.lnk"
    Delete "$SMPROGRAMS\VELLORA\Uninstall VELLORA.lnk"
    RMDir "$SMPROGRAMS\VELLORA"
    DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\VelloraPDF"
    DeleteRegValue HKCU "Software\Classes\.pdf\OpenWithProgids" "VelloraPDF.Document"
    DeleteRegKey HKCU "Software\Classes\VelloraPDF.Document"
    DeleteRegKey HKCU "Software\Classes\Applications\Vellora.exe"
    DeleteRegValue HKCU "Software\RegisteredApplications" "VELLORA"
    DeleteRegKey HKCU "Software\VelloraPDF"
    System::Call 'shell32::SHChangeNotify(i 0x08000000, i 0, p 0, p 0)'
  ${EndIf}
  ; Only known installed files are deleted. User-created documents are retained.
  RMDir "$INSTDIR"
SectionEnd
