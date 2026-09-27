import base64
import io

import numpy as np
import pytest
from PIL import Image

from vegetacao.indices import (
    BREAKS,
    CLASSES,
    class_areas_ha,
    colorize,
    normalized_difference,
    stats,
)


def test_normalized_difference_known_values():
    nir = np.array([[50, 30]], dtype=np.uint16)
    red = np.array([[10, 30]], dtype=np.uint16)
    nd = normalized_difference(nir, red)
    assert nd[0, 0] == pytest.approx(40 / 60)
    assert nd[0, 1] == 0


def test_normalized_difference_does_not_overflow_integer_bands():
    # somar dois uint16 grandes no tipo inteiro estouraria antes da conversão para float
    nir = np.array([[60000]], dtype=np.uint16)
    red = np.array([[20000]], dtype=np.uint16)
    assert normalized_difference(nir, red)[0, 0] == pytest.approx(0.5)


def test_normalized_difference_masks_zero_division_and_input_mask():
    nir = np.ma.array([[0, 50, 50]], mask=[[False, False, True]])
    red = np.ma.array([[0, 10, 10]], mask=[[False, False, True]])
    nd = normalized_difference(nir, red)
    assert nd.mask.tolist() == [[True, False, True]]


def test_stats_ignore_masked_pixels():
    values = np.ma.array([0.2, 0.4, 0.6, 0.8, 99.0], mask=[0, 0, 0, 0, 1])
    s = stats(values)
    assert s["min"] == pytest.approx(0.2)
    assert s["max"] == pytest.approx(0.8)
    assert s["mean"] == pytest.approx(0.5)
    assert s["median"] == pytest.approx(0.5)
    assert s["q1"] == pytest.approx(0.35)
    assert s["q3"] == pytest.approx(0.65)
    assert s["pixels"] == 4


def test_class_areas_ha_uses_pixel_area_and_break_edges():
    # 0.25 fica na classe "baixo" (limite inferior inclusivo), 0.70 fica em "muito_alto"
    values = np.ma.array([0.1, 0.25, 0.5, 0.6, 0.70, 0.9, 0.9, 0.0], mask=[0] * 7 + [1])
    areas = class_areas_ha(values, BREAKS["ndvi"], pixel_area_m2=100)
    assert list(areas) == CLASSES
    assert areas == {"muito_baixo": 0.01, "baixo": 0.01, "medio": 0.01, "alto": 0.01, "muito_alto": 0.03}


def test_colorize_returns_png_with_transparent_masked_pixels():
    values = np.ma.array([[0.1, 0.9], [0.5, 0.0]], mask=[[0, 0], [0, 1]])
    png = Image.open(io.BytesIO(base64.b64decode(colorize(values, BREAKS["ndvi"]))))
    assert png.format == "PNG"
    assert png.size == (2, 2)
    assert png.getpixel((0, 0))[3] == 255
    assert png.getpixel((1, 1))[3] == 0
    # classe mais baixa mais vermelha, mais alta mais verde
    low, high = png.getpixel((0, 0)), png.getpixel((1, 0))
    assert low[0] > low[1] and high[1] > high[0]
