"""API REST que calcula índices de vegetação (NDVI/NDRE) a partir de um GeoTIFF multibanda."""

import json

import rasterio
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from rasterio.errors import RasterioIOError
from rasterio.mask import mask
from rasterio.warp import transform_geom

from . import indices

MAX_UPLOAD_BYTES = 50 * 1024 * 1024

app = FastAPI(title="Índices de Vegetação API", version="1.0.0")


def _fail(detail: str, status_code: int = 422):
    raise HTTPException(status_code=status_code, detail=detail)


def _geometries(geojson: dict) -> list[dict]:
    """Aceita Geometry, Feature ou FeatureCollection (formato exportado pelo geojson.io/QGIS)."""
    if geojson.get("type") == "FeatureCollection":
        return [f["geometry"] for f in geojson["features"]]
    if geojson.get("type") == "Feature":
        return [geojson["geometry"]]
    return [geojson]


def _index(values, name: str, pixel_area_m2: float) -> dict:
    if values.count() == 0:
        _fail("nenhum pixel válido na área analisada")
    breaks = indices.BREAKS[name]
    return {
        **indices.stats(values),
        "classes_ha": indices.class_areas_ha(values, breaks, pixel_area_m2),
        "png": indices.colorize(values, breaks),
    }


def _process(src, red: int, nir: int, rededge: int | None, geometry: str | None) -> dict:
    bands = [b for b in (red, nir, rededge) if b is not None]
    if max(bands) > src.count:
        _fail(f"banda inexistente: o raster tem {src.count} bandas")
    if src.crs is None or src.crs.is_geographic:
        _fail("o raster precisa estar em um CRS projetado (metros), ex.: UTM, para calcular áreas")

    if geometry:
        try:
            shapes = [transform_geom("EPSG:4326", src.crs, g) for g in _geometries(json.loads(geometry))]
        except (ValueError, KeyError, TypeError, AttributeError):
            _fail("geometry inválida: envie um GeoJSON (Polygon, Feature ou FeatureCollection) em EPSG:4326")
        try:
            data, _ = mask(src, shapes, crop=True, filled=False, indexes=bands)
        except ValueError:
            _fail("o polígono não cruza a área do raster")
    else:
        data = src.read(bands, masked=True)

    # área real do pixel a partir da geotransformação (10 m no Sentinel-2 = 100 m², 3 m no Planet = 9 m²)
    pixel_area_m2 = abs(src.transform.determinant)
    result = {
        "ndvi": _index(indices.normalized_difference(data[1], data[0]), "ndvi", pixel_area_m2),
        "ndre": None,
    }
    if rededge:
        result["ndre"] = _index(indices.normalized_difference(data[1], data[2]), "ndre", pixel_area_m2)
    return result


@app.post("/indices")
def calcular_indices(
    file: UploadFile = File(..., description="GeoTIFF multibanda em CRS projetado (metros)"),
    red: int = Form(..., ge=1, description="número da banda do vermelho (começa em 1)"),
    nir: int = Form(..., ge=1, description="número da banda do infravermelho próximo"),
    rededge: int | None = Form(None, ge=1, description="número da banda red edge (ativa o NDRE)"),
    geometry: str | None = Form(None, description="GeoJSON do talhão em EPSG:4326 (recorte opcional)"),
):
    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        _fail("arquivo maior que 50 MB", 413)
    with rasterio.MemoryFile(data) as memfile:
        try:
            src = memfile.open()
        except (RasterioIOError, ValueError):
            _fail("o arquivo enviado não é um raster válido (GeoTIFF)")
        with src:
            return _process(src, red, nir, rededge, geometry)
