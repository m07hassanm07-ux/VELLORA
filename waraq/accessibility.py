"""Inspect and repair existing tagged PDF structure without rebuilding pages."""
from dataclasses import dataclass
from io import BytesIO
import re

from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, BooleanObject, DictionaryObject, NameObject, TextStringObject

TEXT_ROLES = ('P', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6')


@dataclass(frozen=True)
class Tag:
    path: tuple[int, ...]
    role: str
    page: int | None
    alt: str


def is_marked(root):
    info = root.get('/MarkInfo')
    info = info.get_object() if info is not None else None
    marker = info.get('/Marked') if isinstance(info, DictionaryObject) else None
    tree = root.get('/StructTreeRoot')
    return bool(isinstance(marker, BooleanObject) and marker.value and tree is not None
                and isinstance(tree.get_object(), DictionaryObject))


def children(node):
    value = node.get('/K')
    if value is None:
        return ()
    resolved = value.get_object()
    return resolved if isinstance(resolved, ArrayObject) else (value,)


class AccessibilityDocument:
    def __init__(self, data):
        self.original = data
        self.reader = PdfReader(BytesIO(data), strict=False)
        if self.reader.is_encrypted:
            raise ValueError('اختر نسخة PDF غير مشفرة لفتح محرر الوصول.')
        self.signed = any(field.get('/FT') == '/Sig' and field.get('/V')
                          for field in (self.reader.get_fields() or {}).values())
        self.writer = PdfWriter(clone_from=self.reader)
        self.root = self.writer.root_object
        tree = self.root.get('/StructTreeRoot')
        tree = tree.get_object() if tree is not None else None
        self.tree = tree if isinstance(tree, DictionaryObject) else None
        self.pages = {page.indirect_reference.idnum: i for i, page in enumerate(self.writer.pages, 1)
                      if page.indirect_reference is not None}
        self.changed = False

    @property
    def title(self):
        return (self.writer.metadata.title or '') if self.writer.metadata else ''

    @property
    def language(self):
        return str(self.root.get('/Lang', ''))

    def role(self, node):
        role = node.get('/S')
        mapping = self.tree.get('/RoleMap') if self.tree is not None else None
        mapping = mapping.get_object() if mapping is not None else None
        visited = set()
        while isinstance(mapping, DictionaryObject) and role in mapping and role not in visited:
            visited.add(role)
            role = mapping[role]
        return str(role).lstrip('/')

    def tags(self):
        if self.tree is None:
            return []
        stack = [(ref, (index,), None) for index, ref in reversed(list(enumerate(children(self.tree))))]
        result = []
        visited = set()
        while stack:
            ref, path, page = stack.pop()
            node = ref.get_object()
            if not isinstance(node, DictionaryObject) or not isinstance(node.get('/S'), NameObject):
                continue
            if id(node) in visited or len(path) > 128 or len(result) >= 20000:
                raise ValueError('شجرة الوسوم متكررة أو تتجاوز حدود التحرير الآمن.')
            visited.add(id(node))
            page = self.pages.get(getattr(node.get('/Pg'), 'idnum', None), page)
            result.append(Tag(path, self.role(node), page, str(node.get('/Alt', ''))))
            stack.extend((child, path + (index,), page)
                         for index, child in reversed(list(enumerate(children(node)))))
        return result

    def issues(self, tags):
        issues = []
        if not tags or not is_marked(self.root):
            issues.append('لا توجد شجرة وسوم صالحة ومفعّلة. راجع وسم المستند من مصدره.')
        if tags and '/ParentTree' not in self.tree:
            issues.append('شجرة الربط بين المحتوى والوسوم (/ParentTree) مفقودة.')
        if not self.title.strip():
            issues.append('عنوان المستند مفقود.')
        if not self.language.strip():
            issues.append('لغة المستند مفقودة.')
        missing_alt = sum(tag.role in ('Figure', 'Formula') and not tag.alt.strip() for tag in tags)
        if missing_alt:
            issues.append(f'عدد وسوم الصور أو المعادلات بلا وصف بديل: {missing_alt}.')
        return issues

    def node(self, path):
        node = self.tree
        for index in path:
            node = children(node)[index].get_object()
        return node

    def require_editable(self):
        if self.signed:
            raise ValueError('هذا الملف موقّع رقميًا. اختر نسخة غير موقّعة لإصلاح إمكانية الوصول.')

    def auto_tag(self):
        from .autotag import create_initial_tags
        self.require_editable()
        # Publish a staged writer only after every page and tree are ready.
        staged = PdfWriter(clone_from=PdfReader(BytesIO(self.output())))
        tree = create_initial_tags(staged)
        self.writer = staged
        self.root = staged.root_object
        self.tree = tree
        self.pages = {page.indirect_reference.idnum: i for i, page in enumerate(staged.pages, 1)}
        self.changed = True

    def set_metadata(self, title, language):
        self.require_editable()
        if not title.strip() or not re.fullmatch(r'[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*', language):
            raise ValueError('أدخل عنوانًا ورمز لغة مثل ar أو en أو ar-EG.')
        self.writer.add_metadata({'/Title': title.strip()})
        self.root[NameObject('/Lang')] = TextStringObject(language)
        prefs = self.root.get('/ViewerPreferences')
        if prefs is None:
            prefs = DictionaryObject()
            self.root[NameObject('/ViewerPreferences')] = prefs
        prefs.get_object()[NameObject('/DisplayDocTitle')] = BooleanObject(True)
        self.changed = True

    def set_text_role(self, path, role):
        self.require_editable()
        node = self.node(path)
        if str(node.get('/S')).lstrip('/') not in TEXT_ROLES or role not in TEXT_ROLES:
            raise ValueError('اختر وسم فقرة أو عنوانًا قياسيًا.')
        node[NameObject('/S')] = NameObject('/' + role)
        self.changed = True

    def set_alt(self, path, text):
        self.require_editable()
        node = self.node(path)
        if self.role(node) not in ('Figure', 'Formula'):
            raise ValueError('اختر وسم صورة أو معادلة.')
        if not text.strip():
            raise ValueError('أدخل وصفًا بديلًا يوضح معنى الصورة أو المعادلة.')
        node[NameObject('/Alt')] = TextStringObject(text.strip())
        self.changed = True

    def move(self, path, step):
        self.require_editable()
        parent = self.node(path[:-1])
        siblings = children(parent)
        index = path[-1]
        target = index + step
        if (abs(step) != 1 or not isinstance(siblings, ArrayObject) or not 0 <= target < len(siblings)
                or not isinstance(siblings[target].get_object(), DictionaryObject)
                or not isinstance(siblings[target].get_object().get('/S'), NameObject)):
            raise ValueError('يمكن نقل الوسم بجوار وسم شقيق في المستوى نفسه.')
        siblings[index], siblings[target] = siblings[target], siblings[index]
        self.changed = True
        return path[:-1] + (target,)

    def output(self):
        self.require_editable()
        stream = BytesIO()
        self.writer.write(stream)
        return stream.getvalue()

    def validation_bytes(self):
        return self.output() if self.changed else self.original
