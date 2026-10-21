# Architecture

Waraq PDF is a new application, independent of Acrobat. There is no activation check in its application code.

`Document` reads source bytes once, then stores immutable `PageRef` values describing source page indexes, extra rotation and overlays. Undo/redo stores page-reference and metadata snapshots, not whole rendered documents. Original source readers are not mutated by export; each export creates fresh readers.

`pypdf` assembles output page objects, annotations and basic form fields. Multiple source documents with forms receive separate field namespaces. Reordered output does not import bookmarks. `atomic_write` prepares output in the destination directory and replaces the destination only after writing, flushing and syncing it. Password-protected output uses PDF AES-256 through pypdf and cryptography.

`pypdfium2` renders thumbnails and the current page, with deterministic closing of bitmap/page resources. Rasterization is only used for the preview. Save operations retain original vector/text page content unless an overlay is explicitly added; overlay generation itself is vector PDF.

Qt handles Arabic UI layout and shapes Arabic/Latin text into PDF overlays using installed system fonts. No Microsoft font binaries are shipped. The headless rendering fallback registers installed Segoe UI/Tahoma fonts only when the offscreen Qt platform cannot enumerate fonts.

The UI is deliberately single-threaded in 0.1.0; large files may block the UI during parsing/export. A future worker architecture must serialize PDFium access or use separate processes, and report cancellation/progress before accepting very large jobs.

Future areas: asynchronous processing, text search/selection, saveable project sessions, richer annotation placement, OCR using a separately licensed engine, direct text editing with layout-aware constraints, and digital-signature workflows. None are represented as already available.
