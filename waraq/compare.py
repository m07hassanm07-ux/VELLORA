"""Local text and visual comparison of two PDF revisions."""
from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from io import BytesIO

from PIL import Image, ImageChops, ImageStat
from pypdf import PdfReader
import pypdfium2 as pdfium


@dataclass(frozen=True)
class PageComparison:
    page: int
    status: str
    text_similarity: float
    visual_difference: float
    first_size: tuple[float, float] | None
    second_size: tuple[float, float] | None


def _render(document, index, dpi):
    page=document[index]
    try:
        bitmap=page.render(scale=dpi/72,rev_byteorder=True)
        image=bitmap.to_pil().convert('RGB');bitmap.close();return image
    finally:page.close()


def _size(document,index):
    page=document[index]
    try:return page.get_size()
    finally:page.close()


def _visual_ratio(first: Image.Image, second: Image.Image) -> float:
    width=max(first.width,second.width);height=max(first.height,second.height)
    a=Image.new('RGB',(width,height),'white');b=Image.new('RGB',(width,height),'white')
    a.paste(first,(0,0));b.paste(second,(0,0));diff=ImageChops.difference(a,b).convert('L')
    # Ignore tiny antialiasing noise while retaining layout/content changes.
    histogram=diff.histogram();changed=sum(histogram[12:]);return changed/max(1,width*height)


def compare_pdfs(first: bytes, second: bytes, *, dpi: int = 96, progress=None) -> list[PageComparison]:
    if not 72<=dpi<=150:raise ValueError('دقة المقارنة يجب أن تكون بين 72 و150 DPI.')
    first_reader=PdfReader(BytesIO(first),strict=False);second_reader=PdfReader(BytesIO(second),strict=False)
    if first_reader.is_encrypted or second_reader.is_encrypted:raise ValueError('افتح المستند المحمي داخل ورقة أولًا قبل المقارنة.')
    results=[];total=max(len(first_reader.pages),len(second_reader.pages))
    with pdfium.PdfDocument(first) as first_pdf,pdfium.PdfDocument(second) as second_pdf:
        for index in range(total):
            if progress:progress(index,total,f'مقارنة الصفحة {index+1} من {total}…')
            if index>=len(first_reader.pages):
                results.append(PageComparison(index+1,'added',0,1,None,_size(second_pdf,index)));continue
            if index>=len(second_reader.pages):
                results.append(PageComparison(index+1,'removed',0,1,_size(first_pdf,index),None));continue
            left=first_reader.pages[index];right=second_reader.pages[index]
            left_text=' '.join((left.extract_text() or '').split());right_text=' '.join((right.extract_text() or '').split())
            similarity=SequenceMatcher(None,left_text.casefold(),right_text.casefold(),autojunk=False).ratio() if left_text or right_text else 1.0
            left_image=_render(first_pdf,index,dpi);right_image=_render(second_pdf,index,dpi)
            visual=_visual_ratio(left_image,right_image);left_image.close();right_image.close()
            first_size=_size(first_pdf,index);second_size=_size(second_pdf,index)
            changed=similarity<.999 or visual>.001 or any(abs(a-b)>.1 for a,b in zip(first_size,second_size))
            results.append(PageComparison(index+1,'changed' if changed else 'same',similarity,visual,first_size,second_size))
    if progress:progress(total,total,'اكتملت المقارنة')
    return results
