import json

import numpy as np
import pytest
import rasterio
from fastapi.testclient import TestClient
from rasterio.transform import from_origin
from rasterio.warp import transform_geom

from vegetacao.main import app

client = TestClient(app)

# raster 10x10 com pixel de 10 m (100 m²) em UTM 22S, bandas: 1=red, 2=rededge, 3=nir
ORIGIN_X, ORIGIN_Y, PIXEL = 600_000, 8_150_000, 10


def write_tiff(path, crs="EPSG:32722"):
    bands = np.zeros((3, 10, 10), dtype="uint16")
    bands[0] = 1000  # red
    bands[1] = 3000  # rededge
    bands[2] = 9000  # nir -> NDVI 0.8 na metade esquerda
    bands[2][:, 5:] = 1500  # -> NDVI 0.2 na metade direita
    with rasterio.open(
        path, "w", driver="GTiff", width=10, height=10, count=3, dtype="uint16",
        crs=crs, transform=from_origin(ORIGIN_X, ORIGIN_Y, PIXEL, PIXEL),
    ) as dst:
        dst.write(bands)
    return path


@pytest.fixture
def tiff(tmp_path):
    return write_tiff(tmp_path / "talhao.tif")


def post(path, **form):
    with open(path, "rb") as f:
        return client.post("/indices", files={"file": ("talhao.tif", f)}, data={"red": 1, "nir": 3, **form})


def left_half_geojson():
    """Polígono da metade esquerda do raster, convertido para EPSG:4326 como um usuário enviaria."""
    x0, y0, x1, y1 = ORIGIN_X, ORIGIN_Y - 10 * PIXEL, ORIGIN_X + 5 * PIXEL, ORIGIN_Y
    utm = {"type": "Polygon", "coordinates": [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]]}
    return transform_geom("EPSG:32722", "EPSG:4326", utm)


def test_ndvi_stats_and_class_areas(tiff):
    resp = post(tiff)
    assert resp.status_code == 200
    ndvi = resp.json()["ndvi"]
    assert ndvi["mean"] == pytest.approx(0.5)
    assert ndvi["min"] == pytest.approx(0.2)
    assert ndvi["max"] == pytest.approx(0.8)
    assert ndvi["pixels"] == 100
    # 50 pixels de 100 m² em cada extremo = 0.5 ha
    assert ndvi["classes_ha"] == {"muito_baixo": 0.5, "baixo": 0.0, "medio": 0.0, "alto": 0.0, "muito_alto": 0.5}
    assert ndvi["png"]
    assert resp.json()["ndre"] is None


def test_ndre_when_rededge_is_sent(tiff):
    ndre = post(tiff, rededge=2).json()["ndre"]
    assert ndre["max"] == pytest.approx(0.5)  # (9000 - 3000) / (9000 + 3000)


@pytest.mark.parametrize("wrap", [
    lambda g: g,
    lambda g: {"type": "Feature", "properties": {}, "geometry": g},
    lambda g: {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {}, "geometry": g}]},
])
def test_clip_by_polygon_in_wgs84(tiff, wrap):
    ndvi = post(tiff, geometry=json.dumps(wrap(left_half_geojson()))).json()["ndvi"]
    assert ndvi["pixels"] == 50
    assert ndvi["mean"] == pytest.approx(0.8)
    assert ndvi["classes_ha"]["muito_alto"] == 0.5
    assert ndvi["classes_ha"]["muito_baixo"] == 0.0


def test_polygon_outside_raster(tiff):
    far = {"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]]}
    resp = post(tiff, geometry=json.dumps(far))
    assert resp.status_code == 422
    assert "não cruza" in resp.json()["detail"]


@pytest.mark.parametrize("geometry", ["{x", "{}", "[1, 2]", '{"type": "Polygon", "coordinates": "x"}'])
def test_invalid_geometry(tiff, geometry):
    resp = post(tiff, geometry=geometry)
    assert resp.status_code == 422
    assert "geometry inválida" in resp.json()["detail"]


def test_band_out_of_range(tiff):
    resp = post(tiff, nir=4)
    assert resp.status_code == 422
    assert "3 bandas" in resp.json()["detail"]


def test_geographic_crs_is_rejected(tmp_path):
    resp = post(write_tiff(tmp_path / "geo.tif", crs="EPSG:4326"))
    assert resp.status_code == 422
    assert "CRS projetado" in resp.json()["detail"]


def test_file_is_not_a_raster(tmp_path):
    path = tmp_path / "nao.tif"
    path.write_text("isto não é um GeoTIFF")
    resp = post(path)
    assert resp.status_code == 422
    assert "raster válido" in resp.json()["detail"]


def test_missing_required_band(tiff):
    with open(tiff, "rb") as f:
        assert client.post("/indices", files={"file": f}, data={"red": 1}).status_code == 422
