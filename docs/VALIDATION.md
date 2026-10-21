# Validation of 0.1.0

Local validation date: 21 October 2026. Host: Windows 11 x64, Python 3.12.14.

## Automated checks

Ten tests passed:

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

The intentionally corrupt test fixture emits pypdf parsing warnings before the test confirms rejection.

## Visual checks

Synthetic three-page sample `examples/welcome.pdf`, application's own Qt widget screenshots, and a separately reopened/exported page rendered using PDFium. Arabic text was visually inspected for shaping, legibility and placement.

Screenshots are in `docs/screenshots/`. The sample contains no user documents or Adobe content.

## Limits

No exhaustive PDF conformance suite, performance/security audit, cross-platform test, or OCR/direct-text-editing test was performed. Complex XFA forms, signed-document validity, attachments, bookmarks and PDF/A archival conformance are outside the supported preservation scope.

The native Windows packaged executable was launched successfully and its Arabic interface and PDF preview were observed. An initial bundle incorrectly collected Poppler's ICU from the developer PATH; the spec now excludes this incompatible ICU and uses the Windows OS ICU required by Qt. This is recorded in `release/native-check.txt`.

No automated full native-file-dialog save flow was completed: the user was working in the live application, so their workspace was left available. Save/export and encryption were verified by the automated document/rendering tests. No unrelated user PDF was copied into the sample, screenshots or release.
