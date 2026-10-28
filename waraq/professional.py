"""Professional PDF helpers kept independent from the desktop interface.

The functions in this module never overwrite their inputs.  They operate on
bytes so they can also be used by the background worker and automated tests.
"""
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import re

import pypdfium2 as pdfium
from PIL import Image
from pypdf import PdfReader, PdfWriter


@dataclass(frozen=True)
class FormField:
    name: str
    kind: str
    value: str
    page: int | None
    options: tuple[str, ...] = ()


@dataclass(frozen=True)
class SignatureInfo:
    name: str
    signer: str
    reason: str
    location: str
    signing_time: str
    has_cryptographic_value: bool


def _reader(data: bytes, password: str = "") -> PdfReader:
    reader = PdfReader(BytesIO(data), strict=False)
    if reader.is_encrypted and not reader.decrypt(password):
        raise ValueError("كلمة مرور المستند غير صحيحة.")
    return reader


def list_form_fields(data: bytes, password: str = "") -> list[FormField]:
    """Return standard AcroForm fields without executing PDF JavaScript."""
    reader = _reader(data, password)
    raw = reader.get_fields() or {}
    page_by_reference = {}
    for page_number, page in enumerate(reader.pages):
        for annotation in page.get("/Annots", []):
            page_by_reference[getattr(annotation, "idnum", -1)] = page_number
    result = []
    for name, field in raw.items():
        kind = str(field.get("/FT", ""))
        value = field.get("/V", "")
        options = field.get("/Opt", ()) or ()
        page = None
        reference = field.indirect_reference
        if reference is not None:
            page = page_by_reference.get(reference.idnum)
        result.append(FormField(str(name), kind, str(value), page, tuple(str(v) for v in options)))
    return sorted(result, key=lambda item: item.name.casefold())


def fill_form_fields(data: bytes, values: dict[str, str], *, flatten: bool = False,
                     password: str = "") -> bytes:
    """Fill existing AcroForm fields and optionally make their appearance final."""
    if not values:
        raise ValueError("لم تُدخل قيمًا للنموذج.")
    reader = _reader(data, password)
    known = set((reader.get_fields() or {}).keys())
    unknown = sorted(set(values) - known)
    if unknown:
        raise ValueError("حقول غير موجودة: " + "، ".join(unknown))
    writer = PdfWriter()
    writer.append(reader, import_outline=True)
    writer.set_need_appearances_writer(False)
    writer.update_page_form_field_values(None, values, auto_regenerate=False, flatten=flatten)
    output = BytesIO()
    writer.write(output)
    writer.close()
    return output.getvalue()


def inspect_signatures(data: bytes, password: str = "") -> list[SignatureInfo]:
    """Inspect embedded signature dictionaries without claiming trust validation."""
    reader = _reader(data, password)
    result = []
    for name, field in (reader.get_fields() or {}).items():
        if str(field.get("/FT", "")) != "/Sig":
            continue
        value = field.get("/V")
        value = value.get_object() if value else {}
        result.append(SignatureInfo(
            str(name), str(value.get("/Name", "")), str(value.get("/Reason", "")),
            str(value.get("/Location", "")), str(value.get("/M", "")), bool(value.get("/Contents")),
        ))
    return result


def extract_text(data: bytes, password: str = "", page_break: str = "\n\f\n") -> str:
    reader = _reader(data, password)
    return page_break.join((page.extract_text() or "") for page in reader.pages)


def export_page_images(data: bytes, folder: Path | str, *, dpi: int = 150,
                       image_format: str = "png", prefix: str = "page") -> list[Path]:
    """Render all pages using PDFium, atomically replacing only output images."""
    if not 72 <= dpi <= 600:
        raise ValueError("الدقة يجب أن تكون بين 72 و600 DPI.")
    image_format = image_format.lower()
    if image_format not in {"png", "jpeg", "jpg", "tiff"}:
        raise ValueError("صيغة الصور المدعومة: PNG أو JPEG أو TIFF.")
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    safe_prefix = re.sub(r"[^\w.-]+", "-", prefix, flags=re.UNICODE).strip(".-") or "page"
    suffix = "jpg" if image_format in {"jpeg", "jpg"} else image_format
    written = []
    with pdfium.PdfDocument(data) as document:
        for number, page in enumerate(document, 1):
            bitmap = page.render(scale=dpi / 72, rev_byteorder=True)
            image = bitmap.to_pil()
            if suffix == "jpg":
                image = image.convert("RGB")
            destination = folder / f"{safe_prefix}-{number:04d}.{suffix}"
            temporary = destination.with_suffix(destination.suffix + ".tmp")
            image.save(temporary, format="JPEG" if suffix == "jpg" else suffix.upper(), quality=92)
            temporary.replace(destination)
            written.append(destination)
            bitmap.close()
            page.close()
    return written
