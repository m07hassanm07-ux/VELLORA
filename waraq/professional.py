"""Professional PDF helpers kept independent from the desktop interface.

The functions in this module never overwrite their inputs.  They operate on
bytes so they can also be used by the background worker and automated tests.
"""
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import ctypes
import re

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_raw
from PIL import Image, ImageDraw
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (ArrayObject, BooleanObject, DictionaryObject,
                           NameObject, NumberObject, RectangleObject,
                           TextStringObject)


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


FIELD_KINDS = {"text": "/Tx", "checkbox": "/Btn", "choice": "/Ch"}


@dataclass(frozen=True)
class AttachmentInfo:
    name: str
    size: int
    description: str = ""


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


def add_form_field(data: bytes, page_index: int, kind: str, name: str,
                   rect: tuple[float, float, float, float], *, value: str = "",
                   options: list[str] | None = None) -> bytes:
    """Create one interoperable AcroForm widget at viewer coordinates."""
    kind = kind.lower().strip(); name = name.strip()
    if kind not in FIELD_KINDS:
        raise ValueError("نوع حقل النموذج غير مدعوم.")
    if not name or len(name) > 200 or any(ch in name for ch in "\r\n\0"):
        raise ValueError("اكتب اسمًا صالحًا ومختصرًا للحقل.")
    reader = _reader(data)
    if name in (reader.get_fields() or {}):
        raise ValueError("يوجد حقل آخر بهذا الاسم.")
    if not 0 <= page_index < len(reader.pages):
        raise ValueError("رقم صفحة الحقل غير صالح.")
    x, y, width, height = map(float, rect)
    if width < 8 or height < 8:
        raise ValueError("اسحب مساحة أكبر للحقل.")
    with pdfium.PdfDocument(data) as document:
        page = document[page_index]
        display_width, display_height = page.get_size()
        if x < 0 or y < 0 or x + width > display_width + .5 or y + height > display_height + .5:
            page.close(); raise ValueError("يجب أن يقع الحقل داخل الصفحة.")
        points = []
        for dx, dy in ((x, y), (x + width, y + height)):
            px, py = ctypes.c_double(), ctypes.c_double()
            ok = pdfium_raw.FPDF_DeviceToPage(page, 0, 0, round(display_width*20),
                round(display_height*20), 0, round(dx*20), round(dy*20), ctypes.byref(px), ctypes.byref(py))
            if not ok:
                page.close(); raise ValueError("تعذر تحويل موضع الحقل.")
            points.append((px.value, py.value))
        page.close()
    box = (min(p[0] for p in points), min(p[1] for p in points),
           max(p[0] for p in points), max(p[1] for p in points))
    writer = PdfWriter(); writer.append(reader, import_outline=True)
    page = writer.pages[page_index]
    field = DictionaryObject({
        NameObject("/Type"): NameObject("/Annot"), NameObject("/Subtype"): NameObject("/Widget"),
        NameObject("/FT"): NameObject(FIELD_KINDS[kind]), NameObject("/T"): TextStringObject(name),
        NameObject("/Rect"): RectangleObject(box), NameObject("/F"): NumberObject(4),
        NameObject("/P"): page.indirect_reference,
    })
    if kind == "checkbox":
        field[NameObject("/V")] = NameObject("/Yes" if value.casefold() in {"yes", "true", "1", "on"} else "/Off")
        field[NameObject("/AS")] = field[NameObject("/V")]
    else:
        field[NameObject("/V")] = TextStringObject(value[:4000])
        field[NameObject("/DA")] = TextStringObject("/Helv 10 Tf 0 g")
        if kind == "choice":
            choices = [str(item).strip() for item in (options or []) if str(item).strip()]
            if not choices: raise ValueError("أضف خيارًا واحدًا على الأقل للقائمة.")
            field[NameObject("/Opt")] = ArrayObject([TextStringObject(item[:500]) for item in choices])
    reference = writer._add_object(field)
    annotations = page.get("/Annots")
    if annotations is None:
        annotations = ArrayObject(); page[NameObject("/Annots")] = annotations
    annotations.append(reference)
    root = writer._root_object
    acroform = root.get("/AcroForm")
    acroform = acroform.get_object() if acroform else DictionaryObject()
    fields = acroform.get("/Fields")
    if fields is None: fields = ArrayObject(); acroform[NameObject("/Fields")] = fields
    fields.append(reference)
    acroform[NameObject("/NeedAppearances")] = BooleanObject(True)
    if kind != "checkbox":
        font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
        resources = acroform.get("/DR") or DictionaryObject()
        fonts = resources.get("/Font") or DictionaryObject(); fonts[NameObject("/Helv")] = writer._add_object(font)
        resources[NameObject("/Font")] = fonts; acroform[NameObject("/DR")] = resources
        acroform[NameObject("/DA")] = TextStringObject("/Helv 10 Tf 0 g")
    root[NameObject("/AcroForm")] = writer._add_object(acroform)
    output = BytesIO(); writer.write(output); writer.close(); return output.getvalue()


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


def list_attachments(data: bytes, password: str = "") -> list[AttachmentInfo]:
    reader=_reader(data,password);result=[]
    for embedded in reader.attachment_list:
        result.append(AttachmentInfo(str(embedded.name),len(embedded.content),str(embedded.description or '')))
    return sorted(result,key=lambda item:item.name.casefold())


def attachment_bytes(data: bytes, name: str, password: str = "") -> bytes:
    reader=_reader(data,password);matches=[item for item in reader.attachment_list if str(item.name)==name]
    if len(matches)!=1:raise ValueError('لم يتم العثور على المرفق المطلوب بصورة فريدة.')
    return bytes(matches[0].content)


def add_attachment(data: bytes, name: str, content: bytes, description: str = "") -> bytes:
    name=Path(name).name.strip()
    if not name or len(name)>240:raise ValueError('اسم المرفق غير صالح.')
    if len(content)>100*1024*1024:raise ValueError('حجم المرفق يتجاوز 100 ميجابايت.')
    reader=_reader(data)
    if any(str(item.name).casefold()==name.casefold() for item in reader.attachment_list):
        raise ValueError('يوجد مرفق آخر بهذا الاسم.')
    writer=PdfWriter();writer.append(reader,import_outline=True)
    for current in reader.attachment_list:
        copied=writer.add_attachment(str(current.name),bytes(current.content))
        copied.description=TextStringObject(str(current.description or ''))
    embedded=writer.add_attachment(name,content);embedded.description=TextStringObject(description[:500])
    output=BytesIO();writer.write(output);writer.close();return output.getvalue()


def remove_attachment(data: bytes, name: str) -> bytes:
    reader=_reader(data);writer=PdfWriter();writer.append(reader,import_outline=True);removed=0
    for current in reader.attachment_list:
        if str(current.name)==name:removed+=1;continue
        copied=writer.add_attachment(str(current.name),bytes(current.content))
        copied.description=TextStringObject(str(current.description or ''))
    if removed!=1:raise ValueError('لم يتم العثور على المرفق المطلوب بصورة فريدة.')
    output=BytesIO();writer.write(output);writer.close();return output.getvalue()


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


def secure_redact_page(data: bytes, page_index: int, rects: list[tuple[float, float, float, float]],
                       *, dpi: int = 200, color: str = "black") -> bytes:
    """Permanently redact regions by flattening the selected page to pixels.

    Rasterising the complete page deliberately removes the original text,
    images and hidden objects from that page. Other pages remain unchanged.
    Coordinates use the same top-left PDF-point space as Waraqa's viewer.
    """
    if not rects:
        raise ValueError("حدد مساحة واحدة على الأقل للتنقيح.")
    reader = _reader(data)
    if not 0 <= page_index < len(reader.pages):
        raise ValueError("رقم صفحة التنقيح غير صالح.")
    with pdfium.PdfDocument(data) as document:
        page = document[page_index]
        width, height = page.get_size()
        scale = dpi / 72
        bitmap = page.render(scale=scale, rev_byteorder=True)
        image = bitmap.to_pil().convert("RGB")
        draw = ImageDraw.Draw(image)
        for raw in rects:
            x, y, w, h = map(float, raw)
            if w <= 0 or h <= 0 or x < 0 or y < 0 or x + w > width + .5 or y + h > height + .5:
                raise ValueError("مساحة التنقيح يجب أن تقع داخل الصفحة.")
            draw.rectangle((round(x*scale), round(y*scale), round((x+w)*scale), round((y+h)*scale)), fill=color)
        flattened = BytesIO()
        image.save(flattened, format="PDF", resolution=dpi)
        bitmap.close(); page.close()
    replacement = PdfReader(BytesIO(flattened.getvalue())).pages[0]
    # Match the original page boxes exactly; Pillow's PDF dimensions can vary
    # by a fraction of a point because pixels are integral.
    original = reader.pages[page_index]
    replacement.mediabox = original.mediabox
    replacement.cropbox = original.cropbox
    writer = PdfWriter()
    for index, current in enumerate(reader.pages):
        writer.add_page(replacement if index == page_index else current)
    if reader.metadata:
        writer.add_metadata({str(k): str(v) for k, v in reader.metadata.items() if v is not None})
    output = BytesIO(); writer.write(output); writer.close()
    return output.getvalue()


def secure_redact_text(data: bytes, query: str, *, dpi: int = 200, progress=None) -> tuple[bytes, int]:
    query=query.strip()
    if not query:raise ValueError('اكتب النص المطلوب تنقيحه.')
    from .textlayout import find_matches
    matches=find_matches(data,query,progress=progress)
    if not matches:raise ValueError('لم يُعثر على النص المطلوب في المستند.')
    by_page={}
    for match in matches:by_page.setdefault(match['page'],[]).extend(match['rects'])
    result=data
    for offset,(page,rects) in enumerate(sorted(by_page.items())):
        if progress:progress(offset,len(by_page),f'تنقيح الصفحة {page+1}…')
        result=secure_redact_page(result,page,rects,dpi=dpi)
    if progress:progress(len(by_page),len(by_page),'اكتمل التنقيح الآمن')
    return result,len(matches)
