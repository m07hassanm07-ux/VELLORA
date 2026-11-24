"""Initial tagged PDF structure for simple, untagged page content."""
from pypdf.generic import (ArrayObject, BooleanObject, ContentStream, DictionaryObject,
                           NameObject, NumberObject)


STATE_OPERATORS = frozenset(b'q Q cm w J j M d ri i gs CS cs SC SCN sc scn G g RG rg K k'.split())
TEXT_OPERATORS = frozenset(b'Tc Tw Tz TL Tf Tr Ts Td TD Tm T* Tj TJ'.split()) | {b"'", b'"'}
SHOW_TEXT = {b'Tj', b'TJ', b"'", b'"'}


def plan_page(page, index):
    if page.get('/Annots') or '/StructParents' in page:
        raise ValueError(f'الصفحة {index} تحتوي تعليقات أو روابط أو بنية وسم سابقة.')
    stream = page.get_contents()
    if stream is None:
        return None, []
    resources = page.get('/Resources', DictionaryObject()).get_object()
    objects = resources.get('/XObject', DictionaryObject()).get_object()
    start = None
    has_text = False
    spans = []
    for i, (operands, operator) in enumerate(stream.operations):
        if start is not None:
            if operator == b'ET':
                if has_text:
                    spans.append((start, i, '/P'))
                start = None
                continue
            if operator in TEXT_OPERATORS and (operator != b'Tr' or operands == [0]):
                has_text |= operator in SHOW_TEXT
                continue
        elif operator == b'BT':
            start = i
            has_text = False
            continue
        elif operator in STATE_OPERATORS:
            continue
        elif operator == b'Do' and len(operands) == 1:
            image = objects.get(operands[0])
            if image is not None and image.get_object().get('/Subtype') == '/Image':
                spans.append((i, i, '/Figure'))
                continue
        raise ValueError(f'الصفحة {index} تحتوي محتوى معقدًا يحتاج وسمًا يدويًا.')
    if start is not None:
        raise ValueError(f'تعذر تحليل نص الصفحة {index}.')
    return stream, spans


def create_initial_tags(writer):
    root = writer.root_object
    if '/StructTreeRoot' in root:
        raise ValueError('المستند يحتوي شجرة وسوم موجودة.')
    plans = []
    count = 0
    for index, page in enumerate(writer.pages, 1):
        stream, spans = plan_page(page, index)
        if spans:
            plans.append((page, stream, spans))
            count += len(spans)
        if count >= 19999:
            raise ValueError('عدد الوسوم المقترحة يتجاوز الحد المتاح في المحرر.')
    if not plans:
        raise ValueError('لا يوجد نص مباشر أو صور يمكن وسمها.')

    tree = DictionaryObject({NameObject('/Type'): NameObject('/StructTreeRoot')})
    tree_ref = writer._add_object(tree)
    document = DictionaryObject({NameObject('/Type'): NameObject('/StructElem'),
                                 NameObject('/S'): NameObject('/Document'),
                                 NameObject('/P'): tree_ref, NameObject('/K'): ArrayObject()})
    tree[NameObject('/K')] = writer._add_object(document)
    numbers = ArrayObject()
    for key, (page, stream, spans) in enumerate(plans):
        parent_entries = ArrayObject()
        operations = []
        offset = 0
        for mcid, (start, end, role) in enumerate(spans):
            tag = DictionaryObject({
                NameObject('/Type'): NameObject('/StructElem'),
                NameObject('/S'): NameObject(role),
                NameObject('/P'): document.indirect_reference,
                NameObject('/Pg'): page.indirect_reference,
                NameObject('/K'): NumberObject(mcid),
            })
            tag_ref = writer._add_object(tag)
            document['/K'].append(tag_ref)
            parent_entries.append(tag_ref)
            operations.extend(stream.operations[offset:start])
            operations.append(([NameObject(role), DictionaryObject({NameObject('/MCID'): NumberObject(mcid)})], b'BDC'))
            operations.extend(stream.operations[start:end + 1])
            operations.append(([], b'EMC'))
            offset = end + 1
        operations.extend(stream.operations[offset:])
        replacement = ContentStream(None, writer)
        replacement.operations = operations
        page.replace_contents(replacement)
        page[NameObject('/StructParents')] = NumberObject(key)
        numbers.extend((NumberObject(key), writer._add_object(parent_entries)))
    tree[NameObject('/ParentTree')] = writer._add_object(DictionaryObject({NameObject('/Nums'): numbers}))
    tree[NameObject('/ParentTreeNextKey')] = NumberObject(len(plans))
    root[NameObject('/StructTreeRoot')] = tree_ref
    info = root.get('/MarkInfo', DictionaryObject()).get_object()
    info[NameObject('/Marked')] = BooleanObject(True)
    if '/MarkInfo' not in root:
        root[NameObject('/MarkInfo')] = info
    if tuple(map(int, writer.pdf_header.removeprefix('%PDF-').split('.'))) < (1, 4):
        writer.pdf_header = '%PDF-1.4'
    return tree
