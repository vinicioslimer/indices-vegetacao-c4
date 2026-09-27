"""Núcleo de cálculo dos índices de vegetação, sem I/O: só arrays numpy."""

import base64
import io

import numpy as np
from PIL import Image

# limites de classe de vigor: o valor no limite pertence à classe de cima
BREAKS = {
    "ndvi": [0.25, 0.40, 0.55, 0.70],
    "ndre": [0.10, 0.20, 0.30, 0.40],
}
CLASSES = ["muito_baixo", "baixo", "medio", "alto", "muito_alto"]
# vermelho -> verde (ColorBrewer RdYlGn, 5 classes)
COLORS = np.array(
    [[215, 25, 28], [253, 174, 97], [255, 255, 191], [166, 217, 106], [26, 150, 65]],
    dtype=np.uint8,
)


def normalized_difference(a, b) -> np.ma.MaskedArray:
    """(a - b) / (a + b). NDVI = nd(nir, red), NDRE = nd(nir, rededge).

    Converte para float antes de somar (bandas uint16 estourariam) e mascara pixels
    já mascarados, NaN e divisões por zero.
    """
    a = np.ma.asarray(a, dtype=float)
    b = np.ma.asarray(b, dtype=float)
    return np.ma.masked_invalid((a - b) / (a + b))


def stats(values: np.ma.MaskedArray) -> dict:
    """Estatísticas dos pixels válidos."""
    v = np.ma.asarray(values).compressed()
    q1, median, q3 = np.percentile(v, [25, 50, 75])
    return {
        "min": round(float(v.min()), 4),
        "max": round(float(v.max()), 4),
        "mean": round(float(v.mean()), 4),
        "std": round(float(v.std()), 4),
        "q1": round(float(q1), 4),
        "median": round(float(median), 4),
        "q3": round(float(q3), 4),
        "pixels": int(v.size),
    }


def class_areas_ha(values: np.ma.MaskedArray, breaks: list[float], pixel_area_m2: float) -> dict:
    """Área em hectares de cada classe de vigor."""
    counts = np.bincount(np.digitize(np.ma.asarray(values).compressed(), breaks), minlength=len(CLASSES))
    return {name: round(float(n * pixel_area_m2 / 10_000), 4) for name, n in zip(CLASSES, counts)}


def colorize(values: np.ma.MaskedArray, breaks: list[float]) -> str:
    """PNG RGBA (base64) com a cor da classe de cada pixel; pixels mascarados ficam transparentes."""
    values = np.ma.asarray(values)
    rgb = COLORS[np.digitize(values.filled(0), breaks)]
    alpha = np.where(np.ma.getmaskarray(values), 0, 255).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(np.dstack([rgb, alpha])).save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()
