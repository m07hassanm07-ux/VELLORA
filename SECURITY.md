# Security

Waraq PDF 0.1.0 is an initial desktop release, not a security-audited PDF sandbox. It parses documents using pypdf and PDFium. Keep dependencies updated and avoid opening untrusted PDFs in privileged sessions.

The application contains no account system, activation mechanism, telemetry client, or file-upload feature. Passwords remain in process memory for the life of the loaded document/history and are not deliberately persisted. Output encryption is optional AES-256 PDF encryption.

There is no public repository or security-report address configured. Before publishing, set a private reporting channel for your fork. Do not post confidential documents, password values, or full memory dumps in public issue reports.
