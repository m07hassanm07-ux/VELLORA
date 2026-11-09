"""Character geometry shared by editing, selection, search and review.

Words/paragraphs are geometric heuristics, not a document-layout engine.
PDFium access belongs to the calling process, never a shared worker thread.
"""
from dataclasses import dataclass, replace
import ctypes
import re
import unicodedata

import pypdfium2 as pdfium
import pypdfium2.raw as raw

from .editing import EditableObject


def address(handle):
    return ctypes.cast(handle, ctypes.c_void_p).value


def display_rect(page,bounds):
    width,height=page.get_size();coordinates=[]
    for x,y in ((bounds[0],bounds[1]),(bounds[2],bounds[3])):
        dx,dy=ctypes.c_int(),ctypes.c_int()
        if not raw.FPDF_PageToDevice(page,0,0,round(width*20),round(height*20),0,x,y,ctypes.byref(dx),ctypes.byref(dy)):
            raise ValueError('تعذر تحديد موضع العنصر.')
        coordinates.append((dx.value/20,dy.value/20))
    l=min(p[0] for p in coordinates);t=min(p[1] for p in coordinates)
    return l,t,max(p[0] for p in coordinates)-l,max(p[1] for p in coordinates)-t


def normal_text(text):
    return unicodedata.normalize('NFKC', text).replace('\u200e', '').replace('\u200f', '')


@dataclass(frozen=True)
class Glyph:
    index: int
    text: str
    rect: tuple
    object_index: int | None


def character_map(data, page_index=0):
    with pdfium.PdfDocument(data) as document:
        page = document[page_index]
        try:
            width, height = page.get_size()
            roots = {address(obj.raw): i for i, obj in enumerate(page.get_objects(max_depth=1))}
            textpage = page.get_textpage()
            try:
                result = []
                for index in range(textpage.count_chars()):
                    code = raw.FPDFText_GetUnicode(textpage, index)
                    text = chr(code) if 0 < code <= 0x10ffff else ''
                    l, b, r, t = textpage.get_charbox(index)
                    obj = textpage.get_textobj(index)
                    coordinates = []
                    for x, y in ((l,b), (r,t)):
                        dx, dy = ctypes.c_int(), ctypes.c_int()
                        if not raw.FPDF_PageToDevice(page, 0, 0, round(width*20), round(height*20), 0, x, y, ctypes.byref(dx), ctypes.byref(dy)):
                            raise ValueError('تعذر تحديد إحداثيات النص.')
                        coordinates.append((dx.value/20, dy.value/20))
                    left = min(p[0] for p in coordinates); top = min(p[1] for p in coordinates)
                    right = max(p[0] for p in coordinates); bottom = max(p[1] for p in coordinates)
                    result.append(Glyph(index, text, (left, top, max(.1, right-left), max(.1, bottom-top)),
                        roots.get(address(obj.raw)) if obj is not None else None))
                return width, height, result
            finally:
                textpage.close()
        finally:
            page.close()


def union_rect(rects):
    l = min(r[0] for r in rects); t = min(r[1] for r in rects)
    r = max(r[0]+r[2] for r in rects); b = max(r[1]+r[3] for r in rects)
    return l, t, r-l, b-t


def group_text(data, entries, mode='paragraph'):
    width, height, glyphs = character_map(data)
    texts = {e.index: e for e in entries if e.kind == 'text'}
    valid = [g for g in glyphs if g.object_index in texts and g.text and not g.text.isspace()]
    if mode == 'object':
        return [replace(e, chars=tuple(g.index for g in glyphs if g.object_index == e.index)) if e.kind == 'text' else e for e in entries]
    # Cluster baselines conservatively, then split large horizontal gaps so
    # independent columns/labels do not become one paragraph.
    lines = []
    for glyph in sorted(valid, key=lambda g: (g.rect[1]+g.rect[3]/2, g.rect[0])):
        center = glyph.rect[1]+glyph.rect[3]/2
        candidates = [line for line in lines if abs(line['center']-center) <= max(2, glyph.rect[3]*.45)]
        if candidates:
            line = min(candidates, key=lambda l: abs(l['center']-center))
            line['glyphs'].append(glyph)
        else:
            lines.append({'center': center, 'glyphs': [glyph]})
    runs = []
    for line in lines:
        run = []
        for glyph in sorted(line['glyphs'], key=lambda g: g.rect[0]):
            if run and glyph.rect[0]-(run[-1].rect[0]+run[-1].rect[2]) > max(12, texts[glyph.object_index].size*2):
                runs.append(run); run = []
            run.append(glyph)
        if run: runs.append(run)
    words = []
    for run in runs:
        logical = sorted(run, key=lambda g: g.index)
        word = []
        for glyph in logical:
            between = glyphs[word[-1].index+1:glyph.index] if word else []
            if word and (any(g.text.isspace() for g in between) or abs(glyph.rect[0]-word[-1].rect[0]) > max(glyph.rect[3], word[-1].rect[3])*3):
                words.append(word); word = []
            word.append(glyph)
        if word: words.append(word)
    if mode == 'word':
        groups = words
    else:
        groups = []
        for run in sorted(runs, key=lambda r: (union_rect([g.rect for g in r])[1], union_rect([g.rect for g in r])[0])):
            box = union_rect([g.rect for g in run]); sample = texts[run[0].object_index]
            best = None
            for group in reversed(groups):
                old = union_rect([g.rect for g in group]); old_style = texts[group[-1].object_index]
                gap = box[1]-(old[1]+old[3]); overlap = min(box[0]+box[2], old[0]+old[2])-max(box[0], old[0])
                if -.5 <= gap <= sample.size*1.25 and overlap > min(box[2], old[2])*.4 and abs(old_style.size-sample.size) <= max(1, sample.size*.15) and old_style.family == sample.family:
                    best = group; break
            if best is None: groups.append(list(run))
            else: best.extend(run)
    output = []
    for group in groups:
        ids = {g.index for g in group}
        selected = sorted(group, key=lambda g: g.index)
        indexes = tuple(dict.fromkeys(g.object_index for g in selected))
        sample = texts[indexes[0]]
        # Include generated whitespace only between selected characters, never
        # text from a neighboring column or object outside this group.
        pieces = []
        for pos, glyph in enumerate(selected):
            if pos:
                previous=selected[pos-1]
                between = glyphs[previous.index+1:glyph.index]
                whites = ''.join(g.text for g in between if g.text.isspace())
                # Separate PDF text objects often omit an explicit newline.
                # Preserve visual line structure from glyph baselines so a
                # multi-line paragraph reflows as a paragraph, not one line.
                vertical=abs((glyph.rect[1]+glyph.rect[3]/2)-(previous.rect[1]+previous.rect[3]/2))
                if vertical>max(glyph.rect[3],previous.rect[3])*.55:pieces.append('\n')
                elif whites:pieces.append('\n' if '\n' in whites or '\r' in whites else ' ')
            pieces.append(glyph.text)
        text = normal_text(''.join(pieces))
        box = union_rect([g.rect for g in selected])
        rtl = sum(unicodedata.bidirectional(c) in ('AL', 'R') for c in text) > sum(c.isascii() and c.isalpha() for c in text)
        alignment = 'right' if rtl else 'left'
        if mode == 'paragraph' and abs(box[0]+box[2]/2-width/2) < width*.025 and box[2] < width*.7:
            alignment = 'center'
        output.append(replace(sample, text=text, rect=box, indices=indexes, chars=tuple(sorted(ids)), alignment=alignment))
    output.extend(e for e in entries if e.kind == 'image')
    return sorted(output, key=lambda e: (e.rect[1], e.rect[0]))


def extract_text(data, page_index=0):
    with pdfium.PdfDocument(data) as pdf:
        page = pdf[page_index]
        try:
            textpage = page.get_textpage()
            try: return normal_text(textpage.get_text_range())
            finally: textpage.close()
        finally: page.close()


def find_matches(data, query, progress=None):
    """Return geometry for normalized, case-insensitive Unicode matches."""
    query = normal_text(query).casefold()
    if not query.strip(): return []
    results = []
    with pdfium.PdfDocument(data) as pdf:
        count = len(pdf)
    for page_index in range(count):
        if progress:progress(page_index,count,f'البحث في الصفحة {page_index+1} من {count}…')
        _, _, glyphs = character_map(data, page_index)
        chars, owners = [], []
        for glyph in glyphs:
            for char in normal_text(glyph.text).casefold():
                chars.append(char); owners.append(glyph)
        text = ''.join(chars); start = 0
        while True:
            index = text.find(query, start)
            if index < 0: break
            found = owners[index:index+len(query)]
            results.append({'page': page_index, 'text': normal_text(''.join(g.text for g in found)),
                'rects': [g.rect for g in dict.fromkeys(found)], 'char_ids': list(dict.fromkeys(g.index for g in found))})
            start = index+max(1, len(query))
            if len(results)>=10000:return results
    return results


def select_region(glyphs, rect):
    x,y,w,h = rect
    selected = [g for g in glyphs if g.text.strip() and x <= g.rect[0]+g.rect[2]/2 <= x+w and y <= g.rect[1]+g.rect[3]/2 <= y+h]
    selected.sort(key=lambda g: g.index)
    pieces=[]
    for pos, glyph in enumerate(selected):
        if pos:
            between=[g for g in glyphs if selected[pos-1].index < g.index < glyph.index]
            whitespace=''.join(g.text for g in between if g.text.isspace())
            if whitespace: pieces.append('\n' if '\r' in whitespace or '\n' in whitespace else ' ')
        pieces.append(glyph.text)
    return normal_text(''.join(pieces)), [g.rect for g in selected], [g.index for g in selected]
