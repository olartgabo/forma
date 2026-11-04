"""The printable FORMA reference card and its planar layout."""

import cv2
import numpy as np

from forma_domain.photo_measurement_contracts import (
    CARD_DICTIONARY,
    CARD_HEIGHT_MM,
    CARD_MARKER_IDS,
    CARD_MARKER_MM,
    CARD_WIDTH_MM,
)

DICTIONARY = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, CARD_DICTIONARY))
# Top-left corner of each marker's outer black square, in card millimetres.
MARKER_ORIGINS = {
    CARD_MARKER_IDS[0]: (0.0, 0.0),
    CARD_MARKER_IDS[1]: (CARD_WIDTH_MM - CARD_MARKER_MM, 0.0),
    CARD_MARKER_IDS[2]: (
        CARD_WIDTH_MM - CARD_MARKER_MM,
        CARD_HEIGHT_MM - CARD_MARKER_MM,
    ),
    CARD_MARKER_IDS[3]: (0.0, CARD_HEIGHT_MM - CARD_MARKER_MM),
}


def marker_corners_mm(marker_id: int, scale_x: float = 1.0, scale_y: float = 1.0):
    """Outer corners in ArUco order (TL, TR, BR, BL), scaled by the printed check."""

    x, y = MARKER_ORIGINS[marker_id]
    s = CARD_MARKER_MM
    corners = ((x, y), (x + s, y), (x + s, y + s), (x, y + s))
    return np.array([(cx * scale_x, cy * scale_y) for cx, cy in corners], np.float64)


def marker_modules(marker_id: int) -> np.ndarray:
    """6 x 6 module grid including the black border; 1 is black."""

    image = cv2.aruco.generateImageMarker(DICTIONARY, marker_id, 6)
    return (image < 128).astype(np.uint8)


def card_svg() -> str:
    """Deterministic SVG at true size. Only the printed check lines set scale."""

    margin = 15.0
    page_w = CARD_WIDTH_MM + 2 * margin + 20
    page_h = CARD_HEIGHT_MM + 2 * margin + 45
    module = CARD_MARKER_MM / 6
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{page_w:g}mm" height="{page_h:g}mm" '
        f'viewBox="0 0 {page_w:g} {page_h:g}">',
        "<title>FORMA reference card v1</title>",
        f'<rect width="{page_w:g}" height="{page_h:g}" fill="#fff"/>',
    ]
    for marker_id, (mx, my) in MARKER_ORIGINS.items():
        modules = marker_modules(marker_id)
        for row in range(6):
            for col in range(6):
                if modules[row, col]:
                    parts.append(
                        f'<rect x="{margin + mx + col * module:g}" y="{margin + my + row * module:g}" '
                        f'width="{module:g}" height="{module:g}" fill="#000"/>'
                    )
    # Check lines with end ticks: horizontal 150 mm and vertical 100 mm.
    y_line = margin + CARD_HEIGHT_MM + 10
    x_line = margin + CARD_WIDTH_MM + 10
    stroke = 'stroke="#000" stroke-width="0.3"'
    parts += [
        f'<line x1="{margin:g}" y1="{y_line:g}" x2="{margin + CARD_WIDTH_MM:g}" y2="{y_line:g}" {stroke}/>',
        f'<line x1="{margin:g}" y1="{y_line - 3:g}" x2="{margin:g}" y2="{y_line + 3:g}" {stroke}/>',
        f'<line x1="{margin + CARD_WIDTH_MM:g}" y1="{y_line - 3:g}" x2="{margin + CARD_WIDTH_MM:g}" y2="{y_line + 3:g}" {stroke}/>',
        f'<line x1="{x_line:g}" y1="{margin:g}" x2="{x_line:g}" y2="{margin + CARD_HEIGHT_MM:g}" {stroke}/>',
        f'<line x1="{x_line - 3:g}" y1="{margin:g}" x2="{x_line + 3:g}" y2="{margin:g}" {stroke}/>',
        f'<line x1="{x_line - 3:g}" y1="{margin + CARD_HEIGHT_MM:g}" x2="{x_line + 3:g}" y2="{margin + CARD_HEIGHT_MM:g}" {stroke}/>',
    ]
    text = 'font-family="sans-serif" font-size="3.6" fill="#000"'
    lines = (
        "Line A should be 150 mm and line B 100 mm. Print at 100% (Actual size),",
        "then measure both lines with a ruler and enter what you measure.",
        "Lay the card flat beside your materials. Do not fold or crop the markers.",
    )
    parts.append(
        f'<text x="{margin:g}" y="{y_line + 2:g}" dy="-2" {text}>A</text>'
        f'<text x="{x_line + 2:g}" y="{margin + CARD_HEIGHT_MM / 2:g}" {text}>B</text>'
    )
    for index, line in enumerate(lines):
        parts.append(
            f'<text x="{margin:g}" y="{y_line + 9 + index * 5.5:g}" {text}>{line}</text>'
        )
    parts.append("</svg>")
    return "\n".join(parts) + "\n"
