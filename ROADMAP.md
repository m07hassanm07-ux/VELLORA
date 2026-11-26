# Enterprise roadmap

VELLORA is a local-first PDF editor for Windows. Enterprise readiness is tracked by verifiable deliverables.

| Area | Acceptance criteria |
| --- | --- |
| Releases | Version checks from the Help menu, a signed installer, verified update packages and a tested recovery path |
| Deployment | Silent install and uninstall validated on managed Windows devices, with documented configuration and recovery |
| Editing and OCR | Regression fixtures for Arabic and mixed-language documents, complex layouts and direct table editing |
| Accessibility | Reading order, tags and alternative text verified with external PDF/UA tooling and manual checks |
| Office and devices | Compatibility matrix covering Windows, Office, printers and scanners |
| Shared review and signing | Explicitly configured service with access controls, audit records and retention settings |

The update-check command opens the official GitHub release page on request. Managed installation requires a trusted signing identity and an environment for testing deployment and recovery.

See the [Windows deployment guide in Arabic](docs/DEPLOYMENT_AR.md) for silent deployment and package verification.
