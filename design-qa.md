# Design QA — Waraqa inline editor

- Source visual truth: `docs/design-reference-inline-editor.png`
- Implementation screenshot: `docs/screenshots/inline-editor.png`
- Viewport: 1440 × 1024, Qt offscreen capture, device scale 1
- Source pixels: 1440 × 1024
- Implementation pixels: 1440 × 1024
- State: Arabic PDF page, direct text selection active, right properties inspector visible
- Comparison evidence: `tmp/inline-editor-comparison.png` contains the source and implementation at equal scale in one image.

## Findings

No actionable P0, P1, or P2 mismatch remains for the selected interaction direction. The implementation preserves the reference hierarchy: document-first canvas, active direct selection, eight resize handles, contextual right inspector, persistent editing actions, and an explicit finish action.

### Required fidelity surfaces

- Fonts and typography: both use an Arabic-capable sans-serif UI and clear RTL hierarchy. The implementation uses the operating-system/Office font catalog and permits persistent TTF/OTF/TTC imports. PDF text uses the selected document font rather than forcing the mock's Tajawal sample.
- Spacing and layout rhythm: the page is fit to available width and intentionally scrolls vertically, matching the reference's document-first scale. The inspector remains fixed at the right and controls are grouped vertically.
- Colors and tokens: white surfaces, pale blue-gray canvas, deep teal text and emerald selection accents match the source direction and existing Waraqa tokens.
- Image quality and assets: the selected implementation state contains text-only synthetic PDF content, so the reference's wind-turbine document photo is not a required application asset. Page rendering remains PDFium raster output at display scale.
- Copy and content: all core editing actions and inspector labels are Arabic and task-specific. Product branding stays «ورقة» rather than copying the source mock's earlier placeholder brand.

## Comparison history

1. Initial capture: page was fit entirely within the editor, making the document and selection materially smaller than the reference (P1). The editor canvas was changed to fit page width and allow vertical scrolling.
2. Initial selection used only a dashed outline (P1 for direct manipulation). Eight visible handles and functional corner resizing plus drag-to-move were added.
3. Revised capture: the document dominates the canvas, the selected paragraph is readable, the right inspector remains visible, and direct manipulation affordances are clear. The earlier P1 findings are resolved.

## Focused regions

The selected text box and right inspector were readable in the equal-size full comparison; a separate crop was unnecessary. Handles, font controls, size, weight, color, alignment, geometry, and imported-font action are all visible in the implementation evidence.

## Follow-up polish

- P3: replace a few text-only toolbar buttons with a consistent licensed icon library in a future visual-polish pass.
- P3: add collapsible inspector sections when advanced paragraph controls expand.

## Primary interactions tested

- Enter and leave inline edit mode.
- Click/region-select an element.
- Drag the selected rectangle and resize from corner handles.
- Change font properties and import a persistent font.
- Save and load a `.waraqt` template; generate three built-in business templates.

Console errors: not applicable to the native Qt application; the automated run produced no uncaught Qt/Python error.

final result: passed
