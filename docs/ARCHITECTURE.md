# Architecture

Waraq PDF is a new application, independent of Acrobat. There is no activation check in its application code.

`Document` reads source bytes once, then stores immutable `PageRef` values describing source page indexes, extra rotation and overlays. Undo/redo stores page-reference and metadata snapshots, not whole rendered documents. Original source readers are not mutated by export; each export creates fresh readers.

`pypdf` assembles output page objects, annotations and basic form fields. Multiple source documents with forms receive separate field namespaces. Reordered output does not import bookmarks. `atomic_write` prepares output in the destination directory and replaces the destination only after writing, flushing and syncing it. Password-protected output uses PDF AES-256 through pypdf and cryptography.

`pypdfium2` renders thumbnails, the current page and print jobs, with deterministic closing of bitmap/page resources. Print jobs fit rasterized pages to the printer's printable area at up to 300 DPI within a memory limit. Ordinary save operations retain original vector/text content, and text overlays themselves are vector PDF. Qt PrintSupport handles the printer dialog and preview.

Qt handles Arabic UI layout and shapes Arabic/Latin text into PDF overlays using installed system fonts. No Microsoft font binaries are shipped. The headless rendering fallback registers installed Segoe UI/Tahoma fonts only when the offscreen Qt platform cannot enumerate fonts.

The UI is single-threaded in 0.3.0; large files may block the UI during parsing/export. External conversion processes are polled with progress and cancellation. A future worker architecture must serialize PDFium access or use separate processes before accepting very large jobs.

`conversion.py` converts images locally and delegates Office conversion to an installed Microsoft Office application in an isolated worker process, or LibreOffice with a temporary profile. Web/HTML conversion uses an installed Chrome/Edge with a new temporary browser profile. No existing browser session or Office document is reused. `merge_dialog.py` collects and orders source PDFs before import.

The NSIS installer registers per-user Open With capabilities without changing Windows UserChoice. Its generated uninstall manifest removes only known installed files. `/TESTMODE` skips registry/shortcut writes for isolated setup tests. The explicit `--self-test <folder>` helper checks the built runtime with synthetic saving, encryption, rendering and printing to PDF.

`editing.py` normalizes an isolated page's geometry and enumerates top-level PDFium text/image objects. Selected objects are removed with no live text-page handles, then content is regenerated before saving. Qt shapes replacement plain text into an embedded-font vector layer; image additions retain aspect ratio. Text overflow is rejected before mutation. This does not provide secure redaction or interpret nested Form XObjects as paragraphs.

`editor_dialog.py` holds local page bytes and 30-step local undo/redo, with a draft preview separate from applied bytes. Mouse rectangles select text object centers; point selection prefers text over a background image. Committing the dialog calls `Document.replace_page` once, retaining the page UID and creating a new source for independent duplicates and document-level undo. Protected input stays marked by encrypting the replacement source with the original input password. Thumbnail cache keys include source/index so edits cannot reuse stale thumbnails.

Future areas: asynchronous processing, text search/copy, saveable project sessions, richer annotation placement, OCR using a separately licensed engine, paragraph/table reflow and digital-signature workflows. None are represented as already available.
