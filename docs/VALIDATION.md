# Validation of Waraqa 1.4.0

Editing, runtime and setup validation: 22 October 2026. Host: Windows 11 x64, Python 3.12.14. Earlier conversion/browser observations from 0.2.0 on 21 October are explicitly retained below.

## Automated checks

Twenty-six tests passed. The original ten scenarios remain covered:

1. Page-range parsing, Arabic numerals, invalid input and range boundaries.
2. Merge/reorder/rotate, undo/redo state and original-input immutability.
3. Independent rotation of duplicated pages.
4. Selected-page extraction and deletion boundaries.
5. Encrypted input, rejected wrong password and AES-256 encrypted output.
6. Failed import and failed export leave the workspace/existing destination intact; atomic writes leave no temporary file.
7. Two forms with identical field names retain distinct field values after merge.
8. Arabic overlay produces a vector PDF with embedded fonts and visible rendered glyphs.
9. Desktop widget/preview/history initialization and encrypted-input protection defaults.
10. Number overlays on rotated pages preserve dimensions; full exports and single-page previews use correct number contexts.

Additional checks cover PDF header preservation including PDF 2.0; merging three sources; image and multi-page TIFF conversion; URL validation; print page selection, ranges and reverse order; print cancellation; printing to PDF; and initialization of the merge/create/print controls. `test-results.json` records the count and outcome.

Eight editing tests check actual removal of old text, retention of unselected content and a colored background, image insertion/deletion with aspect ratio, Arabic shaping and plain-text handling, rejection of invalid geometry/overflow before removal, visual equivalence of cropped pages at all four right-angle rotations, independent duplicates/encryption/document undo, editor draft/apply/local undo/redo/cancel, and mouse-region replacement with draft invalidation. Qt emits whitespace differences on extraction; visible content and PDFium Arabic extraction were also checked.

The intentionally corrupt test fixture emits pypdf parsing warnings before the test confirms rejection.

## Visual checks

Synthetic three-page sample `examples/welcome.pdf`, application's own Qt widget screenshots, and a separately reopened/exported page rendered using PDFium. Arabic text was visually inspected for shaping, legibility and placement.

Screenshots are in `docs/screenshots/`. The sample contains no user documents or Adobe content.

## Packaged runtime and installer

The final frozen 0.6.0 executable's `--self-test` uses synthetic input: saving two pages, AES-256 encryption/decryption, rendering, printing two pages to PDF, replacing text, searching, project encryption/restore, a review annotation, the inline editor, and a child worker process. See `packaged-results.json` and the installed-runtime check in `installer-results.json`. No physical print job was sent.

Setup tests use a fresh directory under `tmp/` and `/TESTMODE`, which suppresses registry and shortcut changes. The test verifies installation, runs the installed executable's diagnostics, uninstalls, and checks that user-created documents survive and known runtime files are removed. See `installer-results.json`. Registration/shortcut source was reviewed; regular installation was not applied to the user's Windows profile during testing.

The test waits for both the executable and runtime directory to disappear because NSIS uninstallation continues in a child process. The uninstaller uses a known-file manifest rather than recursive deletion of the installation directory.

One initial installed-runtime diagnostic exceeded its 90-second test budget. The identical installed executable's SHA-256 matched the tested distribution, and an explicit repeat passed all diagnostics. The cause of that single delay was not established. A subsequent fresh setup/uninstall cycle is recorded separately in `installer-results.json`; no runtime retry or silent error suppression was added to the application.

## Interoperability

Three synthetic source documents were merged to nine pages and reopened through pypdf, PDFium and Poppler. The merged PDF was opened in Chrome and its nine-page viewer and Arabic content were observed. A synthetic HTML page was converted through Chrome, and synthetic DOCX and XLSX files through installed Microsoft Office; output text and rendering were checked. See `compatibility-results.json` and `COMPATIBILITY.md`.

Those Office/browser integration observations are from 0.2.0 on 21 October. The editor and final edited-page screenshots were inspected on 22 October; the synthetic example is `examples/editing-demo.pdf`. Existing content, Arabic replacement, an added image and a new note remain visible after reopening the edited PDF. No private documents were used.

Edge/Firefox display, PowerPoint conversion and LibreOffice conversion were not integration-tested in this round. All-printer or all-program compatibility is not claimed.

## Limits

No exhaustive PDF conformance suite, performance/security audit or cross-platform test was performed. A real synthetic bilingual OCR check verified Arabic/English extraction and pixel-identical visible rendering, but this is not a broad corpus benchmark. Editing is limited to top-level text/image objects and adds no table reflow or secure-redaction guarantee. Complex XFA forms, signed-document validity, attachments, bookmarks and PDF/A archival conformance are outside the supported preservation scope.

The native Windows packaged executable was launched successfully and its Arabic interface and PDF preview were observed. An initial bundle incorrectly collected Poppler's ICU from the developer PATH; the spec now excludes this incompatible ICU and uses the Windows OS ICU required by Qt. This is recorded in `release/native-check.txt`.

No automated full native-file-dialog save flow was completed: the user was working in the live application, so their workspace was left available. Save/export and encryption were verified by the automated document/rendering tests. No unrelated user PDF was copied into the sample, screenshots or release.
