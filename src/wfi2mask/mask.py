"""The ``get_water_mask`` pipeline: TOA folder -> classified shapefiles.

Steps
-----
1. Locate valid TOA GeoTIFFs (``toa_*.tif``) under ``path`` (recursively,
   so ``outdir/toa`` with per-satellite subfolders works directly).
2. Build a common analysis grid: UTM zone of the bbox centre, at the
   ``coarse`` resolution (default 100 m — matches the ~90 m HAND data).
   Warping each scene onto this grid simultaneously CROPS to the bbox and
   RESAMPLES to the coarse resolution.
3. Download (on demand) and warp the HAND tiles for the bbox.
4. Classify each scene (Namikawa Hue + NDWI + HAND + NIR filters) into the
   4 Namikawa et al. (2016) confidence classes and export one shapefile
   per scene.
5. With 2+ scenes, aggregate with the >50 % majority rule and export a
   composite shapefile.
6. Save a demonstration plot (true color + mask overlay).
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
    CONFIDENCE_LABELS,
    DEFAULT_COARSE,
    DEFAULT_HAND_MAX,
    DEFAULT_HUE_MAX,
    DEFAULT_HUE_MIN,
    DEFAULT_NDWI_THRESHOLD,
    DEFAULT_NIR_MAX,
)
from .hand import load_hand_on_grid
from .plotting import plot_overlay, stretch
from .utils import log, validate_bbox, warn


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


def _warp_band(src, band_idx, shape, transform, crs) -> np.ndarray:
    dst = np.zeros(shape, dtype=np.float32)
    reproject(
        source=rasterio.band(src, band_idx), destination=dst,
        src_transform=src.transform, src_crs=src.crs,
        dst_transform=transform, dst_crs=crs,
        resampling=Resampling.average,  # proper aggregation when coarsening
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
    gdf = gpd.GeoDataFrame(records, geometry="geometry", crs=crs)
    if gdf.empty:
        # write an empty but valid shapefile schema
        gdf = gpd.GeoDataFrame(
            {"classe": [], "rotulo": []}, geometry=[], crs=crs
        )
    gdf.to_file(out_shp)
    return len(gdf)


def get_water_mask(
    path=None,
    bbox=None,
    coarse=DEFAULT_COARSE,
    hand=DEFAULT_HAND_MAX,
    ndwi=DEFAULT_NDWI_THRESHOLD,
    nir=DEFAULT_NIR_MAX,
    hue_min=DEFAULT_HUE_MIN,
    hue_max=DEFAULT_HUE_MAX,
    hand_dir=None,
    outdir=None,
    plot=True,
):
    """Generate water-mask shapefiles from a folder of TOA images.

    Parameters
    ----------
    path : str
        Directory containing valid TOA images (``toa_*.tif``, output of
        :func:`wfi2mask.get_toa`). Searched recursively.
    bbox : list
        ``[lon_min, lat_min, lon_max, lat_max]``. The TOA images cover the
        full scene; this function crops them to the bbox.
    coarse : float
        Analysis resolution in metres (default 100, matching the ~90 m HAND
        data). Bands are aggregated (average) onto this grid.
    hand : float
        Maximum HAND (m). Pixels above this height over the nearest drainage
        are rejected. Default 15.
    ndwi : float
        NDWI threshold for dark-water recovery. Default 0.0.
    nir : float
        Maximum NIR TOA reflectance (bright-surface rejection). Default 0.35
        for WFI TOA in the [0, ~1] reflectance scale.
    hue_min, hue_max : float
        Namikawa water Hue window (degrees). Defaults 16 and 35.
    hand_dir : str, optional
        Local folder with HAND tiles (skips the on-demand download).
    outdir : str, optional
        Output folder. Default: ``<path>/../water_mask``.
    plot : bool
        Save the demonstration plot (true color + overlay). Default True.

    Returns
    -------
    dict with keys ``scenes`` (per-scene outputs), ``composite`` (shapefile
    path or None), ``plot`` (png path or None) and ``outdir``.
    """
    # ------------------------------------------------------------------ #
    # Input validation                                                    #
    # ------------------------------------------------------------------ #
    if not path or not os.path.isdir(str(path)):
        raise FileNotFoundError(
            "Imagens não encontradas: informe em path= um diretório válido com "
            "imagens TOA (saída de wfi2mask.get_toa, arquivos 'toa_*.tif')."
        )
    bbox = validate_bbox(bbox)

    toa_files = sorted(glob.glob(os.path.join(path, "**", "toa_*.tif"), recursive=True))
    if not toa_files:
        raise FileNotFoundError(
            f"Nenhum arquivo 'toa_*.tif' encontrado em {os.path.abspath(path)}. "
            "Execute wfi2mask.get_toa primeiro ou verifique o caminho."
        )

    if outdir is None:
        outdir = os.path.join(os.path.dirname(os.path.abspath(path)), "water_mask")
    os.makedirs(outdir, exist_ok=True)

    log("=" * 62)
    log("wfi2mask.get_water_mask")
    log(f"  {len(toa_files)} imagem(ns) TOA em {os.path.abspath(path)}")
    log(f"  bbox:      {bbox}")
    log(f"  grade:     {coarse:.0f} m (recorte no bbox + reamostragem)")
    log(f"  filtros:   HAND<={hand} m | NDWI>{ndwi} | NIR<{nir} | Hue [{hue_min},{hue_max})")
    log(f"  saídas em: {os.path.abspath(outdir)}")
    log("=" * 62)

    crs, transform, shape, _bounds = _build_grid(bbox, float(coarse))
    log(f"Grade comum: {shape[0]} x {shape[1]} px @ {coarse:.0f} m ({crs})")

    # ------------------------------------------------------------------ #
    # HAND                                                                #
    # ------------------------------------------------------------------ #
    log("Carregando dados HAND (download sob demanda se necessário)...")
    hand_grid = load_hand_on_grid(bbox, shape, transform, crs, hand_dir=hand_dir)
    if hand_grid is None:
        warn("HAND indisponível — classificação prosseguirá SEM o filtro topográfico.")

    # ------------------------------------------------------------------ #
    # Per-scene classification                                            #
    # ------------------------------------------------------------------ #
    try:
        from tqdm import tqdm
        iterator = tqdm(toa_files, desc="classificando cenas", unit="cena")
    except ImportError:
        iterator = toa_files

    n = len(toa_files)
    water_stack = np.zeros((n, *shape), dtype=bool)
    valid_stack = np.zeros((n, *shape), dtype=bool)
    tc_stack = {b: np.zeros((n, *shape), dtype=np.float32) for b in ("red", "green", "blue")}
    scene_results = []

    for idx, toa_path in enumerate(iterator):
        scene_name = os.path.basename(toa_path).replace("toa_", "").replace(".tif", "")
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
            blue = _warp_band(src, 1, shape, transform, crs)
            green = _warp_band(src, 2, shape, transform, crs)
            red = _warp_band(src, 3, shape, transform, crs)
            nir_b = _warp_band(src, 4, shape, transform, crs)

        res = classify_scene(
            green, red, nir_b, hand=hand_grid,
            hue_min=hue_min, hue_max=hue_max,
            ndwi_threshold=ndwi, hand_max=hand, nir_max=nir,
        )
        water_stack[idx] = res["water"]
        valid_stack[idx] = res["valid"]
        tc_stack["red"][idx] = red
        tc_stack["green"][idx] = green
        tc_stack["blue"][idx] = blue

        shp_path = os.path.join(outdir, f"water_{scene_name}.shp")
        n_polys = _vectorize(res["confidence"], transform, crs, shp_path)
        scene_results.append(
            {
                "scene": scene_name,
                "shapefile": shp_path,
                "n_polygons": n_polys,
                "n_water_px": int(res["water"].sum()),
                "confidence": res["confidence"],
            }
        )

    if not scene_results:
        raise RuntimeError(
            "Nenhuma cena pôde ser classificada (sem sobreposição com o bbox?)."
        )
    for r in scene_results:
        log(f"  {r['scene']}: {r['n_water_px']:,d} px de água -> {r['shapefile']}")

    # ------------------------------------------------------------------ #
    # Majority-rule composite                                             #
    # ------------------------------------------------------------------ #
    composite_shp = None
    composite_conf = None
    if len(scene_results) >= 2:
        agg = majority_composite(water_stack, valid_stack)
        log(f"Composição por regra da maioria (>50 %, min {agg['min_obs']} observações):")
        n_water_final = int((agg["mask"] == 1).sum())
        n_reliable = int((agg["mask"] != 255).sum())
        log(f"  pixels confiáveis: {n_reliable:,d} | água: {n_water_final:,d}")

        composite_conf = np.zeros(shape, dtype=np.uint8)
        composite_conf[agg["mask"] == 1] = 1
        composite_shp = os.path.join(outdir, "water_composite_majority.shp")
        _vectorize(composite_conf, transform, crs, composite_shp)
        log(f"  composto salvo: {composite_shp}")

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
            [stretch(med(tc_stack["red"])), stretch(med(tc_stack["green"])),
             stretch(med(tc_stack["blue"]))], axis=-1,
        )
        conf_for_plot = (
            composite_conf if composite_conf is not None
            else scene_results[0]["confidence"]
        )
        title = ("composição (maioria)" if composite_conf is not None
                 else scene_results[0]["scene"])
        png_path = os.path.join(outdir, "water_mask_overlay.png")
        plot_overlay(true_color, conf_for_plot, title, png_path)
        log(f"Plot de demonstração salvo: {png_path}")

    log("Concluído.")
    for r in scene_results:
        r.pop("confidence", None)
    return {
        "scenes": scene_results,
        "composite": composite_shp,
        "plot": png_path,
        "outdir": os.path.abspath(outdir),
    }
