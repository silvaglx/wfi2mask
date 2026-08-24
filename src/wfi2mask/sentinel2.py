"""Sentinel-2 L2A download — the ``get_s2`` pipeline.

Sentinel-2 is not a WFI sensor, but it was the basis on which the wfi2mask
algorithm was developed and validated (16 Brazilian ROIs, F1 ~ 0.95 outside
shallow wetlands). ``get_s2`` brings it into the package as a supported
input for :func:`wfi2mask.get_water_mask` — either alone or MIXED with WFI
scenes to build a composite water-mask product.

Data source: Earth Search STAC (AWS Open Data, no credentials needed),
collection ``sentinel-2-l2a``. Scenes are searched by bbox/date/cloud
cover, cropped to the bbox, mosaicked per date and saved in the same
layout used by :func:`wfi2mask.get_toa`::

    outdir/toa/sentinel2/toa_S2_<date>.tif

Each product has 5 float32 bands: 1=Blue, 2=Green, 3=Red, 4=NIR (surface
reflectance already divided by 10000, i.e. in [0, ~1]) and 5=SCL (the ESA
Scene Classification Layer). get_water_mask uses the SCL band as a
PER-PIXEL cloud mask for Sentinel-2 scenes — something WFI does not offer.
"""

from __future__ import annotations

import os
from collections import defaultdict
from datetime import timedelta

import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.transform import from_bounds as rio_from_bounds
from rasterio.vrt import WarpedVRT
from rasterio.warp import Resampling, transform_bounds

from .constants import (
    DEFAULT_S2_RESOLUTION,
    S2_COLLECTION,
    S2_SCALE,
    S2_STAC_URL,
)
from .utils import log, parse_dates, validate_bbox, warn

# GDAL settings for efficient windowed reads of the S2 COGs on AWS
_GDAL_ENV = {
    "AWS_NO_SIGN_REQUEST": "YES",
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif,.TIF",
    "GDAL_HTTP_MERGE_CONSECUTIVE_RANGES": "YES",
}

_S2_ASSETS = [
    # (band key, STAC asset, resampling)
    ("blue", "blue", Resampling.bilinear),
    ("green", "green", Resampling.bilinear),
    ("red", "red", Resampling.bilinear),
    ("nir", "nir", Resampling.bilinear),
    ("scl", "scl", Resampling.nearest),
]


def _build_grid(bbox, resolution: float):
    """UTM grid covering the bbox at ``resolution`` metres."""
    center_lon = (bbox[0] + bbox[2]) / 2.0
    center_lat = (bbox[1] + bbox[3]) / 2.0
    utm_zone = int((center_lon + 180) // 6) + 1
    epsg = (32600 if center_lat >= 0 else 32700) + utm_zone
    crs = CRS.from_epsg(epsg)
    left, bottom, right, top = transform_bounds("EPSG:4326", crs, *bbox)
    width = max(1, int(round((right - left) / resolution)))
    height = max(1, int(round((top - bottom) / resolution)))
    transform = rio_from_bounds(left, bottom, right, top, width, height)
    return crs, transform, (height, width)


def _load_mosaic(items, asset_key, resampling, crs, transform, shape):
    """Mosaic one asset of several same-date items onto the target grid."""
    merged = np.zeros(shape, dtype=np.float32)
    filled = np.zeros(shape, dtype=bool)
    for item in items:
        if asset_key not in item.assets:
            warn(f"  {item.id}: asset '{asset_key}' ausente — ignorando item.")
            continue
        with rasterio.open(item.assets[asset_key].href) as src:
            with WarpedVRT(
                src, crs=crs, transform=transform,
                width=shape[1], height=shape[0], resampling=resampling,
            ) as vrt:
                arr = vrt.read(1).astype(np.float32)
        valid = arr > 0
        take = valid & ~filled
        merged[take] = arr[take]
        filled |= valid
    return merged


def get_s2(
    date=None,
    bbox=None,
    max_cloud=20,
    max_images=None,
    outdir="./wfi2mask_data",
    resolution=DEFAULT_S2_RESOLUTION,
):
    """Search, download and crop Sentinel-2 L2A scenes for the water mask.

    Sentinel-2 counterpart of :func:`wfi2mask.get_toa` (which remains
    WFI/INPE only). The products land in ``outdir/toa/sentinel2/`` so that
    :func:`wfi2mask.get_water_mask` picks them up automatically — alone or
    together with WFI scenes for a composite product. No account is needed
    (AWS Open Data).

    Parameters
    ----------
    date : str | tuple
        Single date ``"2025-08-01"`` (searched in a +/-15-day window,
        nearest date kept) or range ``"2025-07-01, 2025-09-30"``.
    bbox : list
        ``[lon_min, lat_min, lon_max, lat_max]`` in EPSG:4326. The output is
        cropped to this bbox.
    max_cloud : float
        Maximum ``eo:cloud_cover`` (%) of the scenes (default 20). Note this
        is scene-level: a Sentinel-2 tile is 110x110 km, so the percentage
        may not represent the bbox. Unlike WFI, however, Sentinel-2 also
        carries the per-pixel SCL cloud mask, which get_water_mask applies
        automatically. ``-1`` disables the scene-level filter.
    max_images : int, optional
        Cap on the number of DATES downloaded, most recent first.
    outdir : str
        Base output directory (same as get_toa). Products are saved in
        ``outdir/toa/sentinel2/toa_S2_<date>.tif``.
    resolution : float
        Output resolution in metres (default 10, the native resolution of
        the 10 m bands). Use e.g. 20 to halve download size.

    Returns
    -------
    list of dict
        One entry per date: ``{"scene", "satellite", "path", "date",
        "n_items"}``.
    """
    try:
        from pystac_client import Client
    except ImportError as exc:
        raise ImportError(
            "pystac-client é necessário para get_s2: pip install pystac-client"
        ) from exc

    bbox = validate_bbox(bbox)
    d0, d1 = parse_dates(date)
    single_date = d0 == d1
    if single_date:
        target = d0
        d0 = target - timedelta(days=15)
        d1 = target + timedelta(days=15)
        log(f"Data única solicitada ({target}): buscando na janela {d0} a {d1} "
            f"e mantendo a data mais próxima.")

    for k, v in _GDAL_ENV.items():
        os.environ.setdefault(k, v)

    out_dir = os.path.join(outdir, "toa", "sentinel2")
    os.makedirs(out_dir, exist_ok=True)

    log("=" * 62)
    log("wfi2mask.get_s2 (Sentinel-2 L2A via Earth Search / AWS)")
    log(f"  bbox:      {bbox}")
    log(f"  período:   {d0} a {d1}")
    log(f"  max_cloud: {max_cloud}% (nível de cena; máscara SCL por pixel "
        f"aplicada depois em get_water_mask)")
    log(f"  saídas em: {os.path.abspath(out_dir)}")
    log("=" * 62)

    client = Client.open(S2_STAC_URL)
    query = {}
    if max_cloud is not None and float(max_cloud) >= 0:
        query["eo:cloud_cover"] = {"lte": float(max_cloud)}
    search = client.search(
        collections=[S2_COLLECTION],
        bbox=bbox,
        datetime=f"{d0.isoformat()}/{d1.isoformat()}",
        query=query or None,
        max_items=500,
    )
    items = [it for it in search.items() if it.datetime is not None]
    log(f"{len(items)} item(ns) Sentinel-2 encontrados no período.")
    if not items:
        warn("Nenhuma cena Sentinel-2 atende aos critérios.")
        return []

    # Group by date (a bbox can straddle two tiles -> mosaic per date)
    items_by_date = defaultdict(list)
    for it in items:
        items_by_date[it.datetime.date()].append(it)
    dates = sorted(items_by_date.keys(), reverse=True)  # newest first

    if single_date:
        best = min(dates, key=lambda d: abs(d - target))
        log(f"Data mais próxima de {target}: {best}.")
        dates = [best]
    if max_images is not None and len(dates) > int(max_images):
        log(f"max_images={max_images}: limitando de {len(dates)} para "
            f"{max_images} data(s) (mais recentes primeiro).")
        dates = dates[: int(max_images)]

    crs, transform, shape = _build_grid(bbox, float(resolution))
    log(f"Grade de saída: {shape[0]} x {shape[1]} px @ {resolution:.0f} m ({crs})")

    try:
        from tqdm import tqdm
        iterator = tqdm(dates, desc="download sentinel-2", unit="data")
    except ImportError:
        iterator = dates

    results = []
    for d in iterator:
        date_items = items_by_date[d]
        scene_name = f"S2_{d.strftime('%Y%m%d')}"
        out_path = os.path.join(out_dir, f"toa_{scene_name}.tif")
        try:
            bands = {}
            for key, asset, resamp in _S2_ASSETS:
                bands[key] = _load_mosaic(
                    date_items, asset, resamp, crs, transform, shape
                )
        except Exception as exc:  # noqa: BLE001
            warn(f"  Falha ao baixar {scene_name}: {exc}")
            continue

        profile = {
            "driver": "GTiff", "dtype": "float32", "count": 5,
            "width": shape[1], "height": shape[0],
            "crs": crs, "transform": transform,
            "compress": "lzw", "nodata": 0.0,
        }
        with rasterio.open(out_path, "w", **profile) as dst:
            for i, key in enumerate(("blue", "green", "red", "nir"), start=1):
                # reflectance in [0, ~1], same convention as the WFI TOA
                dst.write(bands[key] / S2_SCALE, i)
            dst.write(bands["scl"], 5)
            dst.update_tags(
                SATELLITE="sentinel2",
                SCENE_ID=scene_name,
                DATE=d.isoformat(),
                BAND_ORDER="blue,green,red,nir,scl",
                BBOX=",".join(f"{v:.6f}" for v in bbox),
                PROCESSING=f"wfi2mask get_s2 (L2A/{S2_SCALE:.0f}, SCL na banda 5)",
            )
        log(f"  Salvo: {out_path} ({len(date_items)} item(ns) na data {d})")
        results.append({
            "scene": scene_name, "satellite": "sentinel2", "path": out_path,
            "date": d.isoformat(), "n_items": len(date_items),
        })

    log("=" * 62)
    log(f"Concluído: {len(results)} produto(s) Sentinel-2 prontos.")
    log("Use w2m.get_water_mask(path=...) para gerar a máscara d'água "
        "(sozinho ou junto com cenas WFI).")
    return results
