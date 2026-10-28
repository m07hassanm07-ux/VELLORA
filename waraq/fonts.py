"""System and user font integration for document editing."""
from pathlib import Path
import hashlib
from PySide6.QtGui import QFontDatabase
from .projects import data_directory
from .core import atomic_write


def font_directory() -> Path:
    path=data_directory()/'fonts';path.mkdir(parents=True,exist_ok=True);return path


def install_font(path: str | Path) -> list[str]:
    source=Path(path)
    if source.suffix.lower() not in ('.ttf','.otf','.ttc') or not source.is_file():
        raise ValueError('اختر ملف خط TTF أو OTF أو TTC صالحًا.')
    payload=source.read_bytes()
    if len(payload)>100*1024*1024:raise ValueError('ملف الخط أكبر من الحد المسموح.')
    target=font_directory()/(hashlib.sha256(payload).hexdigest()[:12]+'-'+source.name)
    if not target.exists():atomic_write(target,payload)
    font_id=QFontDatabase.addApplicationFont(str(target))
    families=QFontDatabase.applicationFontFamilies(font_id) if font_id>=0 else []
    if not families:
        raise ValueError('تعذر تحميل الخط. قد يكون الملف تالفًا أو محميًا.')
    return families


def load_user_fonts() -> list[str]:
    families=[]
    for path in font_directory().iterdir():
        if path.is_file() and path.suffix.lower() in ('.ttf','.otf','.ttc'):
            font_id=QFontDatabase.addApplicationFont(str(path))
            if font_id>=0:families.extend(QFontDatabase.applicationFontFamilies(font_id))
    return list(dict.fromkeys(families))
