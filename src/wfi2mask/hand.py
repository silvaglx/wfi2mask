"""On-demand HAND (Height Above Nearest Drainage) tile management.

Source data: MERIT Hydro (Yamazaki et al., 2019), ~90 m resolution,
5x5-degree tiles named by their lower-left corner (e.g. ``s25w050_hnd.tif``).

The tiles required by a bounding box are downloaded on demand from the
project's GitHub Release (constants.HAND_RELEASE_BASE_URL, overridable via
the ``WFI2MASK_HAND_URL`` environment variable) and cached locally in
``~/.wfi2mask/hand`` (overridable via ``WFI2MASK_CACHE``).
"""

from __future__ import annotations

import math
import os

import numpy as np
import rasterio
from rasterio.merge import merge as rio_merge
from rasterio.warp import Resampling, reproject

from .constants import HAND_RELEASE_BASE_URL
from .utils import log, warn


def cache_dir() -> str:
    base = os.environ.get(
        "WFI2MASK_CACHE", os.path.join(os.path.expanduser("~"), ".wfi2mask")
    )
    d = os.path.join(base, "hand")
    os.makedirs(d, exist_ok=True)
    return d


def tile_name(lat_ll: int, lon_ll: int) -> str:
    """MERIT-Hydro tile filename from lower-left corner (multiples of 5)."""
    ns = "s" if lat_ll < 0 else "n"
    ew = "w" if lon_ll < 0 else "e"
    return f"{ns}{abs(lat_ll):02d}{ew}{abs(lon_ll):03d}_hnd.tif"


def tiles_for_bbox(bbox) -> list[str]:
    """List of 5x5-degree HAND tile filenames covering a bbox."""
    lon_min, lat_min, lon_max, lat_max = bbox
    tiles = []
    lat0 = int(math.floor(lat_min / 5.0) * 5)
    lat1 = int(math.floor((lat_max - 1e-9) / 5.0) * 5)
    lon0 = int(math.floor(lon_min / 5.0) * 5)
    lon1 = int(math.floor((lon_max - 1e-9) / 5.0) * 5)
    for lat in range(lat0, lat1 + 1, 5):
        for lon in range(lon0, lon1 + 1, 5):
            tiles.append(tile_name(lat, lon))
    return tiles


def _download_tile(name: str, dest: str) -> bool:
    import requests
    from tqdm import tqdm

    base_url = os.environ.get("WFI2MASK_HAND_URL", HAND_RELEASE_BASE_URL).rstrip("/")
    url = f"{base_url}/{name}"
    log(f"Baixando HAND tile {name} ...")
    try:
        with requests.get(url, stream=True, timeout=60) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0))
            tmp = dest + ".part"
            with open(tmp, "wb") as f, tqdm(
                total=total, unit="B", unit_scale=True, desc=name, leave=False
            ) as bar:
                for chunk in r.iter_content(chunk_size=1 << 20):
                    f.write(chunk)
                    bar.update(len(chunk))
            os.replace(tmp, dest)
        return True
    except Exception as exc:  # noqa: BLE001
        warn(f"Falha ao baixar {url}: {exc}")
        return False


def get_hand_tiles(bbox, hand_dir: str | None = None) -> list[str]:
    """Return local paths of the HAND tiles covering ``bbox``.

    Looks in ``hand_dir`` (if given), then in the local cache; missing tiles
    are downloaded on demand. Tiles that cannot be obtained are reported and
    skipped.
    """
    needed = tiles_for_bbox(bbox)
    if len(needed) > 1:
        log(f"O bbox cruza {len(needed)} tiles HAND: {', '.join(needed)}")

    cache = cache_dir()
    paths = []
    for name in needed:
        candidates = []
        if hand_dir:
            candidates.append(os.path.join(hand_dir, name))
        candidates.append(os.path.join(cache, name))
        found = next((c for c in candidates if os.path.exists(c)), None)
        if found is None:
            dest = os.path.join(cache, name)
            if _download_tile(name, dest):
                found = dest
        if found:
            paths.append(found)
        else:
            warn(
                f"Tile HAND '{name}' indisponível. Coloque o arquivo manualmente em "
                f"{cache} ou defina WFI2MASK_HAND_URL. O filtro HAND será ignorado "
                f"na área desse tile."
            )
    return paths


def load_hand_on_grid(bbox, target_shape, target_transform, target_crs,
                      hand_dir: str | None = None) -> np.ndarray | None:
    """Mosaic + reproject the HAND tiles for a bbox onto the analysis grid.

    Returns a float32 array (metres above nearest drainage) or ``None`` when
    no tile could be obtained (caller should then skip the HAND filter).
    """
    paths = get_hand_tiles(bbox, hand_dir=hand_dir)
    if not paths:
        return None

    hand = np.full(target_shape, np.nan, dtype=np.float32)
    if len(paths) == 1:
        with rasterio.open(paths[0]) as src:
            reproject(
                source=rasterio.band(src, 1), destination=hand,
                src_transform=src.transform, src_crs=src.crs,
                dst_transform=target_transform, dst_crs=target_crs,
                resampling=Resampling.bilinear,
                src_nodata=src.nodata, dst_nodata=np.nan,
            )
    else:
        srcs = [rasterio.open(p) for p in paths]
        try:
            mosaic, mosaic_transform = rio_merge(srcs)
            reproject(
                source=mosaic[0], destination=hand,
                src_transform=mosaic_transform, src_crs=srcs[0].crs,
                dst_transform=target_transform, dst_crs=target_crs,
                resampling=Resampling.bilinear,
                src_nodata=srcs[0].nodata, dst_nodata=np.nan,
            )
        finally:
            for s in srcs:
                s.close()
    return hand
