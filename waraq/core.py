"""Document transformations independent of the desktop interface.

Inputs are read into memory, never changed in place. Output is assembled from
page references and committed atomically only after a full PDF is generated.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from io import BytesIO
from pathlib import Path
from typing import Callable
import os
import tempfile
import uuid

from pypdf import PdfReader, PdfWriter


class PasswordRequired(ValueError):
    """The input requires a nonempty password, or its password was incorrect."""


@dataclass(frozen=True)
class Overlay:
    text: str
    position: str = "bottom"
    size: int = 16
    color: str = "#123b48"
    opacity: float = 1.0
    numbering: bool = False


@dataclass(frozen=True)
class PageRef:
    source: str
    index: int
    rotation: int = 0
    overlays: tuple[Overlay, ...] = ()
    uid: str = field(default_factory=lambda: uuid.uuid4().hex)


@dataclass
class Source:
    name: str
    data: bytes
    reader: PdfReader
    password: str = field(default="", repr=False)
    path: Path | None = None

    @property
    def signed(self) -> bool:
        return any(v.get("/FT") == "/Sig" for v in (self.reader.get_fields() or {}).values())


OverlayRenderer = Callable[[float, float, Overlay], bytes]


def parse_pages(expression: str, total: int) -> list[int]:
    """Convert 1-based ranges to unique 0-based indexes, preserving input order."""
    expression = expression.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩،؛", "0123456789,;"))
    if not expression.strip():
        raise ValueError("اكتب أرقام الصفحات، مثل 1-3, 5")
    result: list[int] = []
    for token in expression.replace(";", ",").split(","):
        token = token.strip()
        if not token:
            raise ValueError("يوجد جزء فارغ في نطاق الصفحات.")
        parts = token.split("-")
        if len(parts) > 2 or any(not s.strip().isdigit() for s in parts):
            raise ValueError("استخدم أرقامًا أو نطاقًا مثل 1-3, 5")
        start = int(parts[0])
        end = int(parts[-1])
        if start < 1 or end > total or start > end:
            raise ValueError(f"اختر صفحات بين 1 و{total}، بنطاق تصاعدي.")
        for number in range(start - 1, end):
            if number not in result:
                result.append(number)
    return result


def atomic_write(path: Path | str, data: bytes) -> None:
    """Avoid truncating an existing file on a failed write."""
    path = Path(path)
    fd, temporary = tempfile.mkstemp(prefix=".waraq-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class Document:
    def __init__(self) -> None:
        self.sources: dict[str, Source] = {}
        self.pages: list[PageRef] = []
        self.metadata: dict[str, str] = {"/Title": "", "/Author": ""}
        self._undo: list[tuple[list[PageRef], dict[str, str]]] = []
        self._redo: list[tuple[list[PageRef], dict[str, str]]] = []
        self._saved = self.fingerprint()

    def fingerprint(self) -> tuple:
        return tuple(self.pages), tuple(sorted(self.metadata.items()))

    @property
    def dirty(self) -> bool:
        return self.fingerprint() != self._saved

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def mark_saved(self) -> None:
        self._saved = self.fingerprint()

    def checkpoint(self) -> None:
        self._undo.append((self.pages.copy(), self.metadata.copy()))
        self._undo = self._undo[-30:]
        self._redo.clear()

    def undo(self) -> None:
        if self._undo:
            self._redo.append((self.pages.copy(), self.metadata.copy()))
            self.pages, self.metadata = self._undo.pop()

    def redo(self) -> None:
        if self._redo:
            self._undo.append((self.pages.copy(), self.metadata.copy()))
            self.pages, self.metadata = self._redo.pop()

    def import_pdf(self, path: Path | str, password: str = "") -> str:
        path = Path(path)
        return self.import_bytes(path.name, path.read_bytes(), password, path)

    def import_bytes(self, name: str, data: bytes, password: str = "", path: Path | None = None) -> str:
        reader = PdfReader(BytesIO(data), strict=False)
        if reader.is_encrypted and not reader.decrypt(password):
            raise PasswordRequired("كلمة المرور مطلوبة أو غير صحيحة.")
        if not len(reader.pages):
            raise ValueError("الملف لا يحتوي على صفحات.")
        # Parse every page before changing the workspace (failed imports are atomic).
        count = len(reader.pages)
        for page in reader.pages:
            float(page.mediabox.width)
        source_id = uuid.uuid4().hex
        self.checkpoint()
        self.sources[source_id] = Source(name, data, reader, password, path)
        self.pages.extend(PageRef(source_id, index) for index in range(count))
        if len(self.pages) == count:
            for key in ("/Title", "/Author", "/Subject", "/Keywords"):
                value = (reader.metadata or {}).get(key)
                if value is not None:
                    self.metadata[key] = str(value)
        return source_id

    def rotate(self, indexes: list[int], degrees: int) -> None:
        if degrees % 90:
            raise ValueError("Rotation must be a multiple of 90.")
        self.checkpoint()
        chosen = set(indexes)
        self.pages = [replace(p, rotation=(p.rotation + degrees) % 360) if i in chosen else p for i, p in enumerate(self.pages)]

    def remove(self, indexes: list[int]) -> None:
        if len(set(indexes)) >= len(self.pages):
            raise ValueError("احتفظ بصفحة واحدة على الأقل، أو افتح مستندًا جديدًا.")
        self.checkpoint()
        chosen = set(indexes)
        self.pages = [p for i, p in enumerate(self.pages) if i not in chosen]

    def duplicate(self, indexes: list[int]) -> None:
        self.checkpoint()
        chosen = set(indexes)
        pages: list[PageRef] = []
        for i, page in enumerate(self.pages):
            pages.append(page)
            if i in chosen:
                pages.append(replace(page, uid=uuid.uuid4().hex))
        self.pages = pages

    def reorder(self, ids: list[str]) -> None:
        current = {p.uid: p for p in self.pages}
        if len(ids) != len(current) or set(ids) != set(current):
            raise ValueError("Invalid page order.")
        if ids == [p.uid for p in self.pages]:
            return
        self.checkpoint()
        self.pages = [current[uid] for uid in ids]

    def add_overlay(self, indexes: list[int], overlay: Overlay) -> None:
        self.checkpoint()
        chosen = set(indexes)
        self.pages = [replace(p, overlays=tuple(o for o in p.overlays if not (o.numbering and overlay.numbering)) + (overlay,)) if i in chosen else p for i, p in enumerate(self.pages)]

    def clear_overlays(self, indexes: list[int]) -> None:
        self.checkpoint()
        chosen = set(indexes)
        self.pages = [replace(p, overlays=()) if i in chosen else p for i, p in enumerate(self.pages)]

    def set_metadata(self, title: str, author: str) -> None:
        self.checkpoint()
        self.metadata.update({"/Title": title, "/Author": author})

    def build_bytes(self, indexes: list[int] | None = None, password: str = "", overlay_renderer: OverlayRenderer | None = None, preview_context: tuple[int, int] | None = None) -> bytes:
        indexes = list(range(len(self.pages))) if indexes is None else indexes
        if not indexes:
            raise ValueError("لا توجد صفحات للحفظ.")
        writer = PdfWriter()
        export_readers: dict[str, PdfReader] = {}
        selected_source_ids = {self.pages[i].source for i in indexes}
        for source_id in selected_source_ids:
            source = self.sources[source_id]
            reader = PdfReader(BytesIO(source.data))
            if reader.is_encrypted:
                reader.decrypt(source.password)
            # Distinct namespaces avoid field collisions when merging documents.
            if len(selected_source_ids) > 1 and reader.get_fields():
                reader.add_form_topname("document_" + source_id[:8])
            export_readers[source_id] = reader
        for output_index, index in enumerate(indexes):
            reference = self.pages[index]
            reader = export_readers[reference.source]
            writer.append(reader, pages=[reference.index], import_outline=False)
            page = writer.pages[-1]
            if reference.rotation:
                page.rotate(reference.rotation)
            if reference.overlays:
                if overlay_renderer is None:
                    raise ValueError("An overlay renderer is required.")
                page.transfer_rotation_to_content()
                for overlay in reference.overlays:
                    number, total = preview_context or (output_index + 1, len(indexes))
                    effective = replace(overlay, text=f"{number} / {total}") if overlay.numbering else overlay
                    layer = PdfReader(BytesIO(overlay_renderer(float(page.cropbox.width), float(page.cropbox.height), effective)))
                    page.merge_translated_page(layer.pages[0], float(page.cropbox.left), float(page.cropbox.bottom), expand=False)
        writer.add_metadata({k: v for k, v in self.metadata.items() if v} | {"/Producer": "Waraq PDF 0.1.0"})
        if password:
            writer.encrypt(password, algorithm="AES-256")
        output = BytesIO()
        writer.write(output)
        writer.close()
        return output.getvalue()

    def save(self, path: Path | str, **kwargs) -> None:
        atomic_write(path, self.build_bytes(**kwargs))
