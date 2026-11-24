"""Suggest fillable text fields at printed blanks in text-based PDFs."""
import re

import pypdfium2 as pdfium

from .textlayout import character_map, display_rect, union_rect


BLANK = re.compile(r'(?<![\d.])(?:_{4,}|\.{6,}|…{2,})(?![\d.])')


def suggest_text_fields(data, page_index, widgets=()):
    width, height, glyphs = character_map(data, page_index)
    with pdfium.PdfDocument(data) as pdf:
        page = pdf[page_index]
        try:
            occupied = [display_rect(page, rect) for rect in widgets]
        finally:
            page.close()
    text = ''.join(glyph.text or '\0' for glyph in glyphs)
    proposals = []
    for match in BLANK.finditer(text):
        run = glyphs[match.start():match.end()]
        x, y, w, h = union_rect([glyph.rect for glyph in run])
        if w < 22 or h > 20 or h > w / 2:
            continue
        top = max(0, y - 7)
        h = min(height - top, max(12, h + 8))
        if x < 0 or x + w > width or h < 8:
            continue
        if any(x < ox + ow and x + w > ox and top < oy + oh and top + h > oy
               for ox, oy, ow, oh in occupied):
            continue
        label = text[text.rfind('\n', 0, match.start()) + 1:match.start()].strip(' :\r\t')
        if not label:
            end = text.find('\n', match.end())
            label = text[match.end():len(text) if end == -1 else end].strip(' :\r\t')
        proposals.append((label[-65:], (x, top, w, h)))
        occupied.append((x, top, w, h))
        if len(proposals) == 20:
            break
    return proposals
