"""PDFium previews and Qt's font-shaped, vector PDF text overlays."""
from __future__ import annotations

from pathlib import Path
import os
from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QMarginsF, QRectF, QSizeF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPageLayout, QPageSize, QPainter, QPdfWriter, QTextOption
import pypdfium2 as pdfium

from .core import Overlay


def ensure_font_support() -> None:
    """Qt's headless Windows plugin does not enumerate installed fonts.

    Reference system fonts if needed; no Microsoft font is copied or shipped.
    Normal desktop platforms enumerate their fonts without this fallback.
    """
    if not QFontDatabase.families() and os.name == "nt":
        folder = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        for filename in ("segoeui.ttf", "segoeuib.ttf", "tahoma.ttf"):
            path = folder / filename
            if path.is_file():
                QFontDatabase.addApplicationFont(str(path))


def text_overlay(width: float, height: float, overlay: Overlay) -> bytes:
    """Use Qt text shaping and embedded fonts, including right-to-left Arabic."""
    ensure_font_support()
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    pdf = QPdfWriter(buffer)
    pdf.setResolution(72)
    pdf.setPageSize(QPageSize(QSizeF(width, height), QPageSize.Unit.Point))
    pdf.setPageMargins(QMarginsF(0, 0, 0, 0), QPageLayout.Unit.Point)
    pdf.setCreator("VELLORA")
    painter = QPainter(pdf)
    try:
        if not painter.isActive():
            raise RuntimeError("تعذر إنشاء طبقة النص.")
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.setOpacity(overlay.opacity)
        painter.setPen(QColor(overlay.color))
        font = QFont("Segoe UI", overlay.size)
        font.setBold(overlay.position == "center")
        painter.setFont(font)
        area_height = max(overlay.size * 2.5, 50)
        margin = min(24, height / 12)
        top = {"top": margin, "center": (height - area_height) / 2, "bottom": height - margin - area_height}[overlay.position]
        option = QTextOption(Qt.AlignmentFlag.AlignCenter)
        option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        option.setTextDirection(Qt.LayoutDirection.LayoutDirectionAuto)
        painter.drawText(QRectF(margin, top, max(width - 2 * margin, 1), area_height), overlay.text, option)
    finally:
        painter.end()
    # Destroy the writer before reading the backing device so its trailer is flushed.
    del pdf
    buffer.close()
    return bytes(data)


def render_image(pdf: pdfium.PdfDocument, index: int, scale: float = 1.0, rotation: int = 0,
                 draw_annotations: bool = True) -> QImage:
    page = pdf[index]
    bitmap = None
    try:
        bitmap = page.render(scale=max(0.05, scale), rotation=rotation, draw_annots=draw_annotations)
        pil = bitmap.to_pil().convert("RGBA")
        raw = pil.tobytes()
        # Copy owns its pixels after bitmap/page release.
        return QImage(raw, pil.width, pil.height, pil.width * 4, QImage.Format.Format_RGBA8888).copy()
    finally:
        if bitmap is not None:
            bitmap.close()
        page.close()
