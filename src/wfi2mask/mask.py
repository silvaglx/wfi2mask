"""The ``get_water_mask`` pipeline: TOA folder -> classified shapefiles.

Steps
-----
1. Locate valid TOA GeoTIFFs (``toa_*.tif``) under ``path`` (recursively,
   so ``outdir/toa`` with per-satellite subfolders works directly).
2. Build a common analysis grid: UTM zone of the bbox centre, at the
   ``coarse`` resolution (default 100 m — matches the ~90 m HAND data).
   The bbox defaults to the extent of the TOA images themselves (which
   get_toa already crops to the requested area).
3. Download (on demand) and warp the HAND tiles for the bbox.
4. Classify each scene (Namikawa Hue + NDWI + HAND + NIR filters) into the
   4 Namikawa et al. (2016) confidence classes and export one shapefile
   per scene.
5. With ``include_s2=True``, stream Sentinel-2 L2A scenes DIRECTLY FROM
   THE CLOUD (no download) onto the same grid and classify them too —
   with a PER-PIXEL cloud mask from the SCL band and their own NIR
   threshold default.
6. With 2+ scenes (WFI and Sentinel-2 mixed), aggregate with the >50 %
   majority rule and export a composite shapefile.
7. Save a demonstration plot (true color + mask overlay).
"""

from __future__ import annotations

import glob
import os

import numpy as np
import rasterio
from rasterio import features as rio_features
from rasterio.crs import CRS
from rasterio.transform import from_bounds as rio_from_bounds
from rasterio.warp import Resampling, reproject, transform_bounds

from .algorithm import classify_scene, majority_composite
from .constants import (
    COLLECTIONS,
    CONFIDENCE_LABELS,
    DEFAULT_COARSE,
    DEFAULT_HAND_MAX,
    DEFAULT_HUE_MAX,
    DEFAULT_HUE_MIN,
    DEFAULT_NDWI_THRESHOLD,
    DEFAULT_NIR_MAX,
    DEFAULT_NIR_MAX_S2,
    S2_SCALE,
    S2_SCL_INVALID,
    satellite_from_scene_id,
)
from .hand import load_hand_on_grid
from .plotting import plot_overlay, stretch
from .utils import log, parse_dates, validate_bbox, warn


#: satellite keys accepted by ``product=`` in get_water_mask
SUPPORTED_SATELLITES = tuple(COLLECTIONS) + ("sentinel2",)

_SATELLITE_ALIASES = {
    "s2": "sentinel2", "sentinel-2": "sentinel2", "sentinel_2": "sentinel2",
    "cbers-4": "cbers4", "cbers_4": "cbers4",
    "cbers-4a": "cbers4a", "cbers_4a": "cbers4a",
    "amazonia-1": "amazonia1", "amazonia_1": "amazonia1",
}


def _resolve_products(product):
    """Normalize ``product=`` into a set of satellite keys, or None (= all)."""
    if product is None or (isinstance(product, str) and product.lower() == "all"):
        return None
    items = product if isinstance(product, (list, tuple, set)) else [product]
    resolved = set()
    for item in items:
        key = str(item).strip().lower()
        key = _SATELLITE_ALIASES.get(key, key)
        if key not in SUPPORTED_SATELLITES:
            raise ValueError(
                f"Produto desconhecido: {item!r}. Use "
                f"{', '.join(repr(s) for s in SUPPORTED_SATELLITES)}, 'all' "
                f"ou uma lista desses valores."
            )
        resolved.add(key)
    return resolved


def _resolve_satellite(tag, scene_name) -> str:
    """Satellite key from the GeoTIFF SATELLITE tag, falling back to the id."""
    return (tag or satellite_from_scene_id(scene_name) or "desconhecido").lower()


def _satellite_of_file(toa_path) -> str:
    """Satellite key of a TOA file on disk (tag first, then the file name)."""
    scene_name = os.path.basename(toa_path).replace("toa_", "").replace(".tif", "")
    try:
        with rasterio.open(toa_path) as src:
            tag = src.tags().get("SATELLITE")
    except Exception:  # noqa: BLE001
        tag = None
    return _resolve_satellite(tag, scene_name)


def _bbox_from_files(toa_files) -> list:
    """Union of the TOA image extents in EPSG:4326 (fallback when bbox=None)."""
    lon0 = lat0 = float("inf")
    lon1 = lat1 = float("-inf")
    for f in toa_files:
        try:
            with rasterio.open(f) as src:
                b = transform_bounds(src.crs, "EPSG:4326", *src.bounds)
        except Exception:  # noqa: BLE001
            continue
        lon0, lat0 = min(lon0, b[0]), min(lat0, b[1])
        lon1, lat1 = max(lon1, b[2]), max(lat1, b[3])
    if not (lon0 < lon1 and lat0 < lat1):
        raise ValueError(
            "Não foi possível derivar o bbox das imagens TOA — informe bbox=."
        )
    return [lon0, lat0, lon1, lat1]


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
    return crs, transform, (height, width), (left, bottom, right, top)


def _warp_band(src, band_idx, shape, transform, crs,
               resampling=Resampling.average) -> np.ndarray:
    dst = np.zeros(shape, dtype=np.float32)
    reproject(
        source=rasterio.band(src, band_idx), destination=dst,
        src_transform=src.transform, src_crs=src.crs,
        dst_transform=transform, dst_crs=crs,
        resampling=resampling,  # average = proper aggregation when coarsening
    )
    return dst


def _vectorize(class_array: np.ndarray, transform, crs, out_shp: str) -> int:
    """Polygonize a class raster (values 1..4) into a shapefile."""
    import geopandas as gpd
    from shapely.geometry import shape as shp_shape

    records = []
    mask_any = class_array > 0
    if mask_any.any():
        for geom, value in rio_features.shapes(
            class_array.astype(np.uint8), mask=mask_any, transform=transform
        ):
            code = int(value)
            records.append(
                {
                    "geometry": shp_shape(geom),
                    "classe": code,
                    "rotulo": CONFIDENCE_LABELS.get(code, str(code)),
                }
            )
    if records:
        gdf = gpd.GeoDataFrame(records, geometry="geometry", crs=crs)
    else:
        # empty but valid shapefile schema (e.g. fully cloudy scene)
        gdf = gpd.GeoDataFrame(
            {"classe": [], "rotulo": []}, geometry=[], crs=crs
        )
    gdf.to_file(out_shp)
    return len(gdf)


def _infer_dates_from_scenes(scene_names):
    """Date range (min, max) parsed from scene ids (YYYYMMDD), or None.

    INPE scene ids (e.g. ``AMAZONIA1_WFI03401920250217...``) embed the
    acquisition date; this is used as the default Sentinel-2 search window.
    """
    import re
    from datetime import datetime

    found = []
    for name in scene_names:
        for m in re.findall(r"20\d{6}", name):
            try:
                d = datetime.strptime(m, "%Y%m%d").date()
            except ValueError:
                continue
            if 2000 <= d.year <= 2100:
                found.append(d)
                break
    if not found:
        return None
    return min(found), max(found)


def _classify_s2_from_cloud(bbox, s2_date, s2_max_cloud, s2_max_images,
                            toa_files, crs, transform, shape, hand_grid,
                            hue_min, hue_max, ndwi, hand, nir, register):
    """Search, stream and classify Sentinel-2 L2A scenes — no download.

    Failures are non-fatal: the run continues with the local scenes only.
    ``register`` is the per-scene callback of get_water_mask.
    """
    from datetime import timedelta

    try:
        from .sentinel2 import search_s2_dates, stream_s2_scene

        if s2_date is not None:
            d0, d1 = parse_dates(s2_date)
        else:
            inferred = _infer_dates_from_scenes(
                [os.path.basename(f) for f in toa_files]
            )
            if inferred is None:
                warn("include_s2=True: não foi possível inferir o período a "
                     "partir das cenas locais — informe s2_date=. "
                     "Sentinel-2 ignorado.")
                return
            d0, d1 = inferred
            log(f"Sentinel-2: período inferido das cenas WFI: {d0} a {d1}.")
        if d0 == d1:
            d0, d1 = d0 - timedelta(days=15), d1 + timedelta(days=15)
            log(f"Sentinel-2: data única — janela expandida para {d0} a {d1}.")

        log(f"Sentinel-2: buscando cenas L2A na nuvem "
            f"(eo:cloud_cover <= {s2_max_cloud}%)...")
        dates_items = search_s2_dates(bbox, d0, d1, s2_max_cloud, s2_max_images)
    except ImportError:
        warn("pystac-client não instalado — Sentinel-2 ignorado "
             "(pip install pystac-client).")
        return
    except Exception as exc:  # noqa: BLE001
        warn(f"Busca Sentinel-2 falhou ({exc}) — prosseguindo sem Sentinel-2.")
        return

    if not dates_items:
        warn("Nenhuma cena Sentinel-2 atende aos critérios no período.")
        return
    log(f"  {len(dates_items)} data(s) Sentinel-2 serão processadas "
        f"direto da nuvem (sem download).")

    try:
        from tqdm import tqdm
        iterator = tqdm(dates_items.items(), desc="sentinel-2 (nuvem)",
                        unit="data", total=len(dates_items))
    except ImportError:
        iterator = dates_items.items()

    nir_max_scene = float(nir) if nir is not None else DEFAULT_NIR_MAX_S2
    for d, items in iterator:
        bands = stream_s2_scene(items, crs, transform, shape)
        if bands is None:
            warn(f"  S2 {d}: leitura na nuvem falhou — pulando.")
            continue
        res = classify_scene(
            bands["green"], bands["red"], bands["nir"], hand=hand_grid,
            hue_min=hue_min, hue_max=hue_max,
            ndwi_threshold=ndwi, hand_max=hand, nir_max=nir_max_scene,
        )
        register(f"S2_{d.strftime('%Y%m%d')}", "sentinel2", nir_max_scene,
                 res, bands["red"], bands["green"], bands["blue"],
                 scl_grid=bands["scl"])


def get_water_mask(
    path=None,
    bbox=None,
    coarse=DEFAULT_COARSE,
    hand=DEFAULT_HAND_MAX,
    ndwi=DEFAULT_NDWI_THRESHOLD,
    nir=None,
    hue_min=DEFAULT_HUE_MIN,
    hue_max=DEFAULT_HUE_MAX,
    hand_dir=None,
    outdir=None,
    plot=True,
    product=None,
    include_s2=False,
    s2_date=None,
    s2_max_cloud=20,
    s2_max_images=None,
):
    """Generate water-mask shapefiles from WFI TOA images and/or Sentinel-2.

    WFI products come from a local folder (output of
    :func:`wfi2mask.get_toa`). Sentinel-2 L2A is processed DIRECTLY FROM THE
    CLOUD (``include_s2=True``): the scenes are searched on the Earth Search
    STAC (AWS Open Data, no credentials) and their bands are read windowed
    straight onto the analysis grid — nothing is downloaded to disk. Every
    scene lands on the same grid, so the majority composite can combine WFI
    and Sentinel-2 observations in one water-mask product.

    Parameters
    ----------
    path : str, optional
        Directory containing valid TOA images (``toa_*.tif``, output of
        :func:`wfi2mask.get_toa`). Searched recursively. Optional when
        ``include_s2=True`` (Sentinel-2-only run: pass ``bbox`` and
        ``s2_date`` instead).
    bbox : list, optional
        ``[lon_min, lat_min, lon_max, lat_max]``. Since get_toa already
        crops to the requested bbox, this is OPTIONAL when ``path`` has
        images — the extent of the images themselves is used. Required for
        a Sentinel-2-only run.
    coarse : float
        Analysis resolution in metres (default 100, matching the ~90 m HAND
        data). Bands are aggregated (average) onto this grid.
    hand : float
        Maximum HAND (m). Pixels above this height over the nearest drainage
        are rejected. Default 15.
    ndwi : float
        NDWI threshold for dark-water recovery. Default 0.0.
    nir : float, optional
        Maximum NIR reflectance (bright-surface rejection). Default ``None``
        = automatic per scene: 0.35 for WFI TOA and 0.10 for Sentinel-2 L2A
        surface reflectance (both in the [0, ~1] scale). Pass a number to
        force the same threshold for every scene.
    hue_min, hue_max : float
        Namikawa water Hue window (degrees). Defaults 16 and 35. The
        confidence-class boundaries adapt to these values, so the window
        can be tuned (e.g. for a future WFI recalibration).
    hand_dir : str, optional
        Local folder with HAND tiles. Normally unnecessary: the tiles are
        downloaded on demand from the project's GitHub Release and cached
        in ``~/.wfi2mask/hand``. Useful offline or with custom tiles.
    outdir : str, optional
        Output folder. Default: ``<path>/../water_mask`` (or
        ``./water_mask`` when ``path`` is not given).
    plot : bool
        Save the demonstration plot (true color + overlay). Default True.
    product : str | list, optional
        Which satellites go into the analysis (and therefore into the
        composite): ``'amazonia1'``, ``'cbers4a'``, ``'cbers4'``,
        ``'sentinel2'``, ``'all'`` (default) or a list of these. Local TOA
        images of other satellites are ignored. Listing ``'sentinel2'``
        turns on the cloud streaming (same as ``include_s2=True``); omitting
        it from an explicit list turns the streaming off.
    include_s2 : bool
        Default False. When True, Sentinel-2 L2A scenes over the bbox are
        streamed from the cloud and classified alongside the WFI scenes
        (per-pixel SCL cloud mask included) — no data is written to disk.
    s2_date : str | tuple, optional
        Sentinel-2 search period (same formats as ``get_toa``'s ``date``).
        Default: the date range of the WFI scenes found in ``path``
        (inferred from the scene ids); a single date is expanded to a
        +/-15-day window. Required when there are no WFI scenes to infer
        from.
    s2_max_cloud : float
        Scene-level ``eo:cloud_cover`` filter for the Sentinel-2 search
        (default 20 %; -1 disables). The per-pixel SCL mask is applied
        regardless.
    s2_max_images : int, optional
        Cap on the number of Sentinel-2 DATES used, most recent first.

    Returns
    -------
    dict with keys ``scenes`` (per-scene outputs), ``composite`` (shapefile
    path or None), ``plot`` (png path or None) and ``outdir``.
    """
    # ------------------------------------------------------------------ #
    # Input validation                                                    #
    # ------------------------------------------------------------------ #
    toa_files = []
    if path:
        if not os.path.isdir(str(path)):
            raise FileNotFoundError(
                f"path= não é um diretório válido: {path}"
            )
        toa_files = sorted(
            glob.glob(os.path.join(path, "**", "toa_*.tif"), recursive=True)
        )

    # ------------------------------------------------------------------ #
    # Satellite selection (product=)                                      #
    # ------------------------------------------------------------------ #
    products = _resolve_products(product)
    if products is not None:
        if "sentinel2" in products and not include_s2:
            include_s2 = True
        elif "sentinel2" not in products and include_s2:
            warn("product não inclui 'sentinel2' — as cenas Sentinel-2 da "
                 "nuvem não serão processadas.")
            include_s2 = False
        if toa_files:
            n_before = len(toa_files)
            kept, skipped = [], set()
            for f in toa_files:
                sat = _satellite_of_file(f)
                (kept.append(f) if sat in products else skipped.add(sat))
            toa_files = kept
            if skipped:
                log(f"product={sorted(products)}: {len(toa_files)} de {n_before} "
                    f"imagem(ns) TOA selecionada(s) "
                    f"(ignorado(s): {', '.join(sorted(skipped))}).")

    if not toa_files and not include_s2:
        if products is not None and path:
            raise FileNotFoundError(
                f"Nenhuma imagem TOA de {sorted(products)} encontrada em "
                f"{os.path.abspath(path)}. Revise product= ou o caminho."
            )
        raise FileNotFoundError(
            "Nenhuma imagem TOA encontrada: informe em path= um diretório com "
            "arquivos 'toa_*.tif' (saída de wfi2mask.get_toa) e/ou use "
            "include_s2=True para processar Sentinel-2 direto da nuvem."
        )

    if bbox is None:
        if not toa_files:
            raise ValueError(
                "bbox é obrigatório quando não há imagens TOA locais "
                "(execução somente Sentinel-2)."
            )
        bbox = _bbox_from_files(toa_files)
        log(f"bbox não informado — usando a extensão das imagens TOA: "
            f"[{', '.join(f'{v:.4f}' for v in bbox)}]")
    else:
        bbox = validate_bbox(bbox)

    if outdir is None:
        outdir = (os.path.join(os.path.dirname(os.path.abspath(path)), "water_mask")
                  if path else "./water_mask")
    os.makedirs(outdir, exist_ok=True)

    nir_desc = (f"{nir}" if nir is not None
                else f"auto ({DEFAULT_NIR_MAX} WFI / {DEFAULT_NIR_MAX_S2} S2)")
    if toa_files:
        log(f"  {len(toa_files)} imagem(ns) TOA em {os.path.abspath(path)}")
    if include_s2:
        log("  Sentinel-2: processamento direto da nuvem (sem download)")
    log(f"  bbox:      {bbox}")
    log(f"  grade:     {coarse:.0f} m")
    log(f"  filtros:   HAND<={hand} m | NDWI>{ndwi} | NIR<{nir_desc} | Hue [{hue_min},{hue_max})")
    log(f"  saídas em: {os.path.abspath(outdir)}")

    crs, transform, shape, _bounds = _build_grid(bbox, float(coarse))
    log(f"Grade comum: {shape[0]} x {shape[1]} px @ {coarse:.0f} m ({crs})")

    # ------------------------------------------------------------------ #
    # HAND                                                                #
    # ------------------------------------------------------------------ #
    log("Carregando dados HAND...")
    hand_grid = load_hand_on_grid(bbox, shape, transform, crs, hand_dir=hand_dir)
    if hand_grid is None:
        warn("HAND indisponível — classificação prosseguirá SEM o filtro topográfico.")

    # ------------------------------------------------------------------ #
    # Per-scene classification                                            #
    # ------------------------------------------------------------------ #
    try:
        from tqdm import tqdm
    except ImportError:
        tqdm = None
    iterator = (tqdm(toa_files, desc="classificando cenas", unit="cena")
                if tqdm and toa_files else toa_files)

    water_list = []
    valid_list = []
    tc_list = {b: [] for b in ("red", "green", "blue")}
    scene_results = []

    def _register_scene(scene_name, satellite, nir_max_scene, res,
                        red, green, blue, scl_grid=None):
        """Apply the optional SCL mask, vectorize and store one scene."""
        if scl_grid is not None:
            # Sentinel-2 per-pixel cloud mask: drop clouds/cirrus/nodata
            scl_ok = ~np.isin(scl_grid.astype(np.int16), S2_SCL_INVALID)
            res["confidence"][~scl_ok] = 0
            res["water"] &= scl_ok
            res["valid"] &= scl_ok
        water_list.append(res["water"])
        valid_list.append(res["valid"])
        tc_list["red"].append(red)
        tc_list["green"].append(green)
        tc_list["blue"].append(blue)
        shp_path = os.path.join(outdir, f"water_{scene_name}.shp")
        n_polys = _vectorize(res["confidence"], transform, crs, shp_path)
        scene_results.append(
            {
                "scene": scene_name,
                "satellite": satellite,
                "nir_max": nir_max_scene,
                "shapefile": shp_path,
                "n_polygons": n_polys,
                "n_water_px": int(res["water"].sum()),
                "confidence": res["confidence"],
            }
        )

    for toa_path in iterator:
        scene_name = os.path.basename(toa_path).replace("toa_", "").replace(".tif", "")
        scl = None
        with rasterio.open(toa_path) as src:
            # overlap check
            try:
                sb = transform_bounds(src.crs, crs, *src.bounds)
            except Exception:  # noqa: BLE001
                sb = None
            if sb and (sb[2] < _bounds[0] or sb[0] > _bounds[2]
                       or sb[3] < _bounds[1] or sb[1] > _bounds[3]):
                warn(f"{scene_name}: sem sobreposição com o bbox — pulando.")
                continue
            if src.count < 4:
                warn(f"{scene_name}: menos de 4 bandas — pulando.")
                continue

            # satellite: GeoTIFF tag (get_toa products) or scene name
            satellite = _resolve_satellite(src.tags().get("SATELLITE"), scene_name)
            is_s2 = satellite == "sentinel2"

            blue = _warp_band(src, 1, shape, transform, crs)
            green = _warp_band(src, 2, shape, transform, crs)
            red = _warp_band(src, 3, shape, transform, crs)
            nir_b = _warp_band(src, 4, shape, transform, crs)
            if is_s2 and src.count >= 5:
                # SCL is categorical: majority (mode) when coarsening
                scl = _warp_band(src, 5, shape, transform, crs,
                                 resampling=Resampling.mode)

        # Local Sentinel-2 file on the raw x10000 scale: bring it to the
        # common [0, ~1] reflectance scale.
        if is_s2 and float(np.nanmax(green)) > 10.0:
            log(f"  {scene_name}: reflectância na escala x{S2_SCALE:.0f} — normalizando.")
            blue, green, red, nir_b = (a / S2_SCALE for a in (blue, green, red, nir_b))

        # NIR threshold: per-scene automatic default unless the user fixed one
        nir_max_scene = float(nir) if nir is not None else (
            DEFAULT_NIR_MAX_S2 if is_s2 else DEFAULT_NIR_MAX
        )

        res = classify_scene(
            green, red, nir_b, hand=hand_grid,
            hue_min=hue_min, hue_max=hue_max,
            ndwi_threshold=ndwi, hand_max=hand, nir_max=nir_max_scene,
        )

        _register_scene(scene_name, satellite, nir_max_scene, res,
                        red, green, blue, scl_grid=scl)

    # ------------------------------------------------------------------ #
    # Sentinel-2 streamed from the cloud (include_s2=True)                #
    # ------------------------------------------------------------------ #
    if include_s2:
        _classify_s2_from_cloud(
            bbox, s2_date, s2_max_cloud, s2_max_images,
            toa_files, crs, transform, shape, hand_grid,
            hue_min, hue_max, ndwi, hand, nir, _register_scene,
        )

    if not scene_results:
        raise RuntimeError(
            "Nenhuma cena pôde ser classificada (sem sobreposição com o "
            "bbox, ou nenhuma cena Sentinel-2 no período?)."
        )

    # ------------------------------------------------------------------ #
    # Majority-rule composite                                             #
    # ------------------------------------------------------------------ #
    composite_shp = None
    composite_conf = None
    if len(scene_results) >= 2:
        agg = majority_composite(np.stack(water_list), np.stack(valid_list))
        composite_conf = np.zeros(shape, dtype=np.uint8)
        composite_conf[agg["mask"] == 1] = 1
        composite_shp = os.path.join(outdir, "water_composite_majority.shp")
        _vectorize(composite_conf, transform, crs, composite_shp)

    # ------------------------------------------------------------------ #
    # Demonstration plot                                                  #
    # ------------------------------------------------------------------ #
    png_path = None
    if plot:
        def med(stack):
            masked = np.where(stack > 0, stack, np.nan)
            with np.errstate(all="ignore"):
                return np.nan_to_num(np.nanmedian(masked, axis=0))

        true_color = np.stack(
            [stretch(med(np.stack(tc_list["red"]))),
             stretch(med(np.stack(tc_list["green"]))),
             stretch(med(np.stack(tc_list["blue"])))], axis=-1,
        )
        conf_for_plot = (
            composite_conf if composite_conf is not None
            else scene_results[0]["confidence"]
        )
        title = ("composição (maioria)" if composite_conf is not None
                 else scene_results[0]["scene"])
        png_path = os.path.join(outdir, "water_mask_overlay.png")
        plot_overlay(true_color, conf_for_plot, title, png_path)

    log("Concluído.")
    for r in scene_results:
        r.pop("confidence", None)
    return {
        "scenes": scene_results,
        "composite": composite_shp,
        "plot": png_path,
        "outdir": os.path.abspath(outdir),
    }
