# Work toward 0.4

User order: 1 text grouping/style, 2 Arabic/English OCR, 3 search/select/copy,
4 autosave/recovery/projects, 5 background work/progress/cancel, 6 review tools.

- Text: geometric word/paragraph selection, original style inference, preserve
  unselected original glyphs when changing part of a text object.
- OCR: local Tesseract adapter, Arabic+English and invisible searchable layer;
  bilingual recognition and pixel-preservation integration check completed.
- Reading: Unicode search with highlights, region selection and copy.
- Projects: versioned archive, embedded sources, atomic writes, recovery and
  explicit handling of protected input; never serialize passwords silently.
- Performance: own worker processes for PDFium/long jobs, UI progress/cancel,
  transactional result application. No cross-thread shared PDFium handles.
- Review: actual PDF annotations with metadata and appearances, not flattened
  pictures pretending to be annotations; selection-driven highlight, notes,
  arrows and stamps, including deletion and undo.

All six stages are implemented in source. Release acceptance requires the full
automated suite, packaged diagnostics, and isolated setup/uninstall checks.
