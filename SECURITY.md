# Security

VELLORA 2.23.0 parses documents using pypdf and PDFium. It has not undergone an independent security audit and does not isolate PDF parsing in a sandbox. Keep dependencies updated and avoid opening untrusted PDFs in privileged sessions.

The application contains no account system, activation mechanism, telemetry client, or file-upload feature. Passwords remain in process memory for the life of the loaded document/history and are not deliberately persisted. Output encryption is optional AES-256 PDF encryption.

Explicit web conversion contacts the requested page and its resources through an installed Chrome/Edge process with a temporary profile. It does not reuse personal login sessions or disable browser sandbox or certificate checks. Local HTML can load resources referenced by that document. External browser and Office applications may contact their own services according to their settings.

Microsoft Office conversion uses a separate application instance, disables macros, opens inputs read-only and does not save them. LibreOffice uses a separate temporary profile. Conversion is not a malware analysis sandbox; documents are processed by those external applications. Temporary conversion files are removed after use where the operating system permits it.

Installation is per-user. Windows default PDF associations are left to the user's settings. Uninstallation removes a known-file manifest and preserves unrecognized user-created documents in the installation directory.

Page editing removes selected top-level page objects and adds replacement text/images. It is not secure redaction: unused resources, alternative copies or other document structures may retain sensitive data. The editor does not guarantee forensic erasure. Replacement text is passed to Qt as plain text, not interpreted as HTML. The original source bytes stay in memory for undo/history and are not overwritten by editing alone.

Please report suspected vulnerabilities through GitHub's private security-advisory feature for this repository. Do not open a public issue containing confidential documents, passwords, certificates, personal information, or full memory dumps. Include the VELLORA version, Windows version, concise reproduction steps, and a minimal non-confidential sample when possible.
