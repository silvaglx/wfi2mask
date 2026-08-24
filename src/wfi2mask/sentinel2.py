"""Sentinel-2 L2A cloud-streaming helpers for ``get_water_mask(include_s2=True)``.

Sentinel-2 is not a WFI sensor, but it was the basis on which the wfi2mask
algorithm was developed and validated (16 Brazilian ROIs, F1 ~ 0.95 outside
shallow wetlands). It is supported as an additional input of
:func:`wfi2mask.get_water_mask` — alone or MIXED with WFI scenes in a
single composite water-mask product.

NOTHING IS DOWNLOADED TO DISK: the scenes are cloud-optimized GeoTIFFs on
AWS Open Data (Earth Search STAC, no credentials needed), and the bands are
read windowed straight from the cloud onto the analysis grid — only the
pixels of the bbox, already at the analysis resolution, cross the network.

Streamed per date: blue/green/red/nir (surface reflectance divided by
10000, i.e. [0, ~1] — the same convention as the WFI TOA) and SCL (the ESA
Scene Classification Layer), which get_water_mask applies as a PER-PIXEL
cloud mask — something WFI does not offer.
"""

from __future__ import annotations

import os
from collections import defaultdict

import numpy as np
import rasterio
from rasterio.vrt import WarpedVRT
from rasterio.warp import Resampling

from .constants import S2_COLLECTION, S2_SCALE, S2_STAC_URL
from .utils import log, warn

# GDAL settings for efficient windowed reads of the S2 COGs on AWS
_GDAL_ENV = {
    "AWS_NO_SIGN_REQUEST": "YES",
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif,.TIF",
    "GDAL_HTTP_MERGE_CONSECUTIVE_RANGES": "YES",
}

_S2_ASSETS = [
    # (band key, STAC asset, resampling onto the coarse analysis grid)
    ("blue", "blue", Resampling.average),
    ("green", "green", Resampling.average),
    ("red", "red", Resampling.average),
    ("nir", "nir", Resampling.average),
    ("scl", "scl", Resampling.mode),  # categorical: majority when coarsening
]


def search_s2_dates(bbox, d0, d1, max_cloud=20, max_images=None) -> dict:
    """Search Sentinel-2 L2A items and group them by acquisition date.

    Returns ``{date: [items]}`` (a bbox can straddle two tiles, hence the
    list), newest date first, capped at ``max_images`` dates. Returns an
    empty dict when nothing matches; raises ImportError without
    pystac-client.
    """
    from pystac_client import Client

    for k, v in _GDAL_ENV.items():
        os.environ.setdefault(k, v)

    query = {}
    if max_cloud is not None and float(max_cloud) >= 0:
        query["eo:cloud_cover"] = {"lte": float(max_cloud)}
    client = Client.open(S2_STAC_URL)
    search = client.search(
        collections=[S2_COLLECTION],
        bbox=bbox,
        datetime=f"{d0.isoformat()}/{d1.isoformat()}",
        query=query or None,
        max_items=500,
    )
    items_by_date: dict = defaultdict(list)
    for item in search.items():
        if item.datetime is not None:
            items_by_date[item.datetime.date()].append(item)

    dates = sorted(items_by_date.keys(), reverse=True)  # newest first
    if max_images is not None and len(dates) > int(max_images):
        log(f"  s2_max_images={max_images}: limitando de {len(dates)} para "
            f"{max_images} data(s) (mais recentes primeiro).")
        dates = dates[: int(max_images)]
    return {d: items_by_date[d] for d in dates}


def stream_s2_scene(items, crs, transform, shape) -> dict | None:
    """Stream one Sentinel-2 date (mosaic of ``items``) onto the grid.

    Reads each band windowed from the cloud directly at the analysis grid
    (crs/transform/shape) — no file is written. Returns
    ``{"blue","green","red","nir","scl"}`` with reflectance already in
    [0, ~1], or ``None`` on failure.
    """
    for k, v in _GDAL_ENV.items():
        os.environ.setdefault(k, v)

    bands: dict = {}
    try:
        for key, asset, resampling in _S2_ASSETS:
            merged = np.zeros(shape, dtype=np.float32)
            filled = np.zeros(shape, dtype=bool)
            for item in items:
                if asset not in item.assets:
                    warn(f"  {item.id}: asset '{asset}' ausente — ignorando item.")
                    continue
                with rasterio.open(item.assets[asset].href) as src:
                    with WarpedVRT(
                        src, crs=crs, transform=transform,
                        width=shape[1], height=shape[0], resampling=resampling,
                    ) as vrt:
                        arr = vrt.read(1).astype(np.float32)
                valid = arr > 0
                take = valid & ~filled
                merged[take] = arr[take]
                filled |= valid
            bands[key] = merged
    except Exception as exc:  # noqa: BLE001
        warn(f"  Falha ao ler Sentinel-2 da nuvem: {exc}")
        return None

    for key in ("blue", "green", "red", "nir"):
        bands[key] /= S2_SCALE  # [0, ~1], same convention as the WFI TOA
    return bands
