"""Icon loading for Qt: native SVG rendering for Bootstrap Icons (dropping
subgen.py's PyMuPDF SVG->raster->CTkImage round-trip, since Qt has first-
class SVG support), and a QIcon cache for country flags — resolved via
config.FLAGS_DIR (PROJECT_DIR-based), which is the actual fix for the
"flags don't show in the packaged build" bug: get_flag_photo/get_flag_ctk_image
in subgen.py used `Path(__file__).resolve().parent / "assets" / "flags"`,
which doesn't reliably point at the exe folder in a frozen PyInstaller
build. Every path here goes through PROJECT_DIR from day one.

Bootstrap Icons ship with `fill="currentColor"` on the root <svg> — Qt's
QSvgRenderer has no CSS context to resolve that against, so loading the
file as-is renders solid black. The original get_bs_icon() in subgen.py
worked around this the same way: string-replace currentColor with a real
hex color before rendering (there it fed PyMuPDF; here it feeds
QSvgRenderer directly, still simpler than the old PDF round-trip).
"""
from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from .config import BS_ICONS_DIR, FLAGS_DIR, TEXT_SUB

_BS_ICON_CACHE: dict[tuple[str, str, int], QIcon] = {}
_FLAG_ICON_CACHE: dict[str, QIcon] = {}
_FLAG_PIXMAP_CACHE: dict[tuple[str, int, int], QPixmap] = {}


def get_bs_icon(icon_name: str, color: str = TEXT_SUB, size: int = 18) -> QIcon | None:
    """Load a Bootstrap Icons SVG by name, recolored to `color`, as a QIcon."""
    key = (icon_name, color, size)
    if key in _BS_ICON_CACHE:
        return _BS_ICON_CACHE[key]
    svg_file = BS_ICONS_DIR / f"{icon_name}.svg"
    if not svg_file.exists():
        return None

    svg_str = svg_file.read_text(encoding="utf-8")
    if "currentColor" in svg_str:
        svg_str = svg_str.replace("currentColor", color)
    else:
        svg_str = svg_str.replace("<svg", f'<svg fill="{color}"', 1)

    renderer = QSvgRenderer(QByteArray(svg_str.encode("utf-8")))
    if not renderer.isValid():
        return None
    pixmap = QPixmap(QSize(size, size))
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    renderer.render(painter)
    painter.end()

    icon = QIcon(pixmap)
    _BS_ICON_CACHE[key] = icon
    return icon


def get_flag_icon(flag_filename: str | None) -> QIcon | None:
    """Load and cache a country flag PNG as a QIcon."""
    if not flag_filename:
        return None
    if flag_filename in _FLAG_ICON_CACHE:
        return _FLAG_ICON_CACHE[flag_filename]
    file_path = FLAGS_DIR / flag_filename
    if not file_path.exists():
        return None
    icon = QIcon(str(file_path))
    _FLAG_ICON_CACHE[flag_filename] = icon
    return icon


def get_flag_pixmap(flag_filename: str | None, size=(20, 14)) -> QPixmap | None:
    if not flag_filename:
        return None
    key = (flag_filename, size[0], size[1])
    if key in _FLAG_PIXMAP_CACHE:
        return _FLAG_PIXMAP_CACHE[key]
    file_path = FLAGS_DIR / flag_filename
    if not file_path.exists():
        return None
    pix = QPixmap(str(file_path))
    if pix.isNull():
        return None
    from PySide6.QtCore import Qt
    pix = pix.scaled(size[0], size[1], Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    _FLAG_PIXMAP_CACHE[key] = pix
    return pix
