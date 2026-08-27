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
4. Classify each scene (Namikawa Hue + NDWI + HAND [+ optional NIR]) into
   the 4 Namikawa et al. (2016) confidence classes.
5. With ``include_s2=True``, stream Sentinel-2 L2A scenes DIRECTLY FROM
   THE CLOUD (no download) onto the same grid and classify them too, with
   a PER-PIXEL cloud mask from the SCL band.
6. With 2+ scenes (WFI and Sentinel-2 mixed), aggregate with the >50 %
   majority rule.
7. Save the comparison plot (true colour vs water mask).

Vector export (per-scene and composite shapefiles) is currently disabled —
the function returns the comparison plot and per-scene statistics only.
"""

from __future__ import annotations

import glob
import os

import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.transform import from_bounds as rio_from_bounds
from rasterio.warp import Resampling, reproject, transform_bounds

from .algorithm import classify_scene, majority_composite
from .constants import (
    COLLECTIONS,
    DEFAULT_COARSE,
    DEFAULT_HAND_MAX,
    DEFAULT_HUE_MAX,
    DEFAULT_HUE_MIN,
    DEFAULT_NDWI_THRESHOLD,
    DEFAULT_NIR_MAX,
    DEFAULT_NIR_MAX_BY_LEVEL,
    DEFAULT_NIR_MAX_S2,
    S2_SCALE,
    S2_SCL_INVALID,
    SR_COVERAGE_START,
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


def _resolve_products(product, default_level="sr", catalog=None):
    """Normalize ``product=`` into ``(satellites, levels)`` or ``(None, {})``.

    Accepts full product names (``'CB4A-WFI-L4-SR-1'``,
    ``'CBERS4A_WFI_L4_DN'``, see :func:`wfi2mask.get_products`), the
    satellite shorthands, ``'all'`` or a list. ``levels`` maps each satellite
    to the level implied by its product name.
    """
    from .stac import resolve_product

    if product is None or (isinstance(product, str) and product.lower() == "all"):
        return None, {}
    items = product if isinstance(product, (list, tuple, set)) else [product]
    satellites, levels = set(), {}
    for item in items:
        entrada = resolve_product(item, default_level=default_level,
                                  catalog=catalog)
        satellites.add(entrada["satellite"])
        levels[entrada["satellite"]] = entrada["level"]
    return satellites, levels


def _resolve_satellite(tag, scene_name) -> str:
    """Satellite key from the GeoTIFF SATELLITE tag, falling back to the id."""
    return (tag or satellite_from_scene_id(scene_name) or "desconhecido").lower()


def _resolve_nir(nir, satellite):
    """NIR threshold for one satellite, or None when the filter is off.

    ``nir`` accepts:
      * ``None`` (default) — no NIR filter at all;
      * a number — the same threshold for every scene;
      * a dict ``{'cbers4': 0.35, 'amazonia1': 0.30}`` — per satellite;
        satellites absent from the dict get no NIR filter.
    """
    if nir is None:
        return None
    if isinstance(nir, dict):
        for chave, valor in nir.items():
            key = str(chave).strip().lower().rstrip(":")
            key = _SATELLITE_ALIASES.get(key, key)
            if key == satellite:
                return None if valor is None else float(valor)
        return None
    return float(nir)


def _resolve_level(tag, satellite) -> str:
    """Processing level of a scene: 'toa' or 'sr'.

    Read from the PRODUCT_LEVEL GeoTIFF tag written by get_toa / the SR
    streaming. Sentinel-2 L2A is surface reflectance by definition; files
    without the tag (produced by wfi2mask < 0.4) are assumed to be TOA.
    """
    if tag:
        low = str(tag).strip().lower()
        if low in DEFAULT_NIR_MAX_BY_LEVEL:
            return low
    return "sr" if satellite == "sentinel2" else "toa"


def _scene_name_of(path) -> str:
    """Scene id from a reflectance filename (``refl_<id>.tif``/``toa_<id>.tif``)."""
    nome = os.path.basename(path)
    for prefixo in ("refl_", "toa_"):
        if nome.startswith(prefixo):
            nome = nome[len(prefixo):]
            break
    return nome.replace(".tif", "")


def _satellite_of_file(toa_path) -> str:
    """Satellite key of a local file (tag first, then the file name)."""
    scene_name = _scene_name_of(toa_path)
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


def _classify_wfi_from_cloud(satellites, level, bbox, periodo, max_cloud,
                             max_images, crs, transform, shape, hand_grid,
                             hue_min, hue_max, ndwi, hand, nir, register):
    """Stream WFI L4-SR scenes from the INPE STAC and classify them.

    Nothing is downloaded: each band is read windowed onto the analysis grid.
    Failures are non-fatal — the run continues with whatever else is
    available. ``register`` is the per-scene callback of get_water_mask.
    """
    from . import stac

    if level != "sr":
        warn(f"O streaming direto da nuvem só existe para produtos SR "
             f"(pedido: {level.upper()}). Para TOA, gere os arquivos com "
             f"get_reflectance(product='*-L4-DN-*', ...) e informe path=.")
        return

    d0, d1 = periodo

    for satellite in satellites:
        nir_max_scene = _resolve_nir(nir, satellite)
        inicio = SR_COVERAGE_START.get(satellite)
        if level == "sr" and inicio and d0.isoformat() < inicio:
            warn(f"{satellite}: o produto SR começa em {inicio}; cenas anteriores "
                 f"a essa data não existem (use get_toa para o período antigo).")
        try:
            itens = stac.search_scenes(satellite, level, bbox, d0, d1,
                                       max_cloud=max_cloud, max_images=max_images)
        except Exception as exc:  # noqa: BLE001
            warn(f"{satellite}: busca no STAC falhou ({exc}) — pulando.")
            continue
        if not itens:
            log(f"{satellite}: nenhuma cena no período/critérios.")
            continue
        log(f"{satellite}: {len(itens)} cena(s) {level.upper()} da nuvem "
            f"(sem download).")

        try:
            from tqdm import tqdm
            iterator = tqdm(itens, desc=f"{satellite} ({level})", unit="cena")
        except ImportError:
            iterator = itens

        for item in iterator:
            bandas = stac.stream_sr_scene(item, satellite, crs, transform, shape)
            if bandas is None:
                continue
            res = classify_scene(
                bandas["green"], bandas["red"], bandas["nir"], hand=hand_grid,
                hue_min=hue_min, hue_max=hue_max,
                ndwi_threshold=ndwi, hand_max=hand, nir_max=nir_max_scene,
            )
            cmask = bandas.get("cmask")
            valido = stac.cmask_valid(cmask) if cmask is not None else None
            register(item.id, satellite, nir_max_scene, res,
                     bandas["red"], bandas["green"], bandas["blue"],
                     valid_grid=valido, level=level)


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

    nir_max_scene = _resolve_nir(nir, "sentinel2")
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
        valido = ~np.isin(bands["scl"].astype(np.int16), S2_SCL_INVALID)
        register(f"S2_{d.strftime('%Y%m%d')}", "sentinel2", nir_max_scene,
                 res, bands["red"], bands["green"], bands["blue"],
                 valid_grid=valido, level="sr")


def get_water_mask(
    path=None,
    bbox=None,
    date=None,
    catalog=None,
    level="sr",
    max_cloud=20,
    max_images=None,
    user=None,
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
    s2_max_cloud=None,
    s2_max_images=None,
):
    """Generate water-mask shapefiles from WFI and/or Sentinel-2 imagery.

    Three sources can be combined in a single run, all landing on the same
    analysis grid so the majority composite mixes them freely:

    * **WFI surface reflectance** streamed from the INPE STAC — pass
      ``date`` (and optionally ``product``). Nothing is downloaded: each
      band is read windowed straight from the cloud, and the per-pixel WFI
      cloud mask (CMASK) is applied.
    * **Local files** produced by :func:`wfi2mask.get_toa` — pass ``path``.
      Their processing level is read from the ``PRODUCT_LEVEL`` tag, so TOA
      and SR scenes can coexist, each with its own NIR threshold.
    * **Sentinel-2 L2A** streamed from AWS — ``include_s2=True`` or
      ``'sentinel2'`` in ``product``.

    Parameters
    ----------
    path : str, optional
        Directory containing TOA/SR images (``toa_*.tif``, output of
        :func:`wfi2mask.get_toa`). Searched recursively. Optional when a
        streaming source is used.
    date : str | tuple, optional
        Period for the STAC streaming, e.g. ``"2025-07-01, 2025-09-30"``
        (same formats as ``get_toa``). Giving it activates the WFI streaming
        for the satellites named in ``product``; a single date is expanded
        to a +/-15-day window.
    catalog : str, optional
        ``'INPE_STAC'`` (default) or ``'INPE_CLASSIC'``. With the STAC the
        WFI scenes are streamed from the cloud and nothing is written to
        disk. The classic catalogue has no windowed access, so it falls back
        to the original pipeline: whole scenes are downloaded, converted to
        TOA under ``outdir`` and then classified — which needs ``user=`` and
        takes minutes per scene. Sentinel-2 always comes from AWS,
        regardless of this setting.
    level : str
        Processing level of the streamed WFI scenes: ``'sr'`` (default,
        surface reflectance, no calibration needed, CMASK included) or
        ``'dn'``. Ignored for ``catalog='INPE_CLASSIC'``, which only has DN.
        Local files are unaffected — their level comes from their own
        metadata.
    user : str, optional
        E-mail registered at the INPE catalogue; required only when
        ``catalog='INPE_CLASSIC'`` downloads scenes.
    max_cloud : float
        Scene-level cloud filter (%) for the STAC searches. Default 20;
        ``-1`` disables it.
    max_images : int, optional
        Cap on streamed scenes per satellite, most recent first.
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
    nir : float | dict, optional
        NIR brightness rejection. **Default ``None`` = no NIR filter at
        all**, which is the recommended setting while the thresholds are
        being recalibrated. Pass a dict to enable it per satellite::

            nir={"cbers4": 0.35, "amazonia1": 0.30}

        Satellites absent from the dict keep the filter off. A plain number
        applies the same threshold to every scene. Reference values live in
        ``constants.DEFAULT_NIR_MAX_BY_LEVEL``.
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
        Sentinel-2 search period. Defaults to ``date`` and, failing that, to
        the date range inferred from the WFI scene ids in ``path``.
    s2_max_cloud : float, optional
        Cloud filter for the Sentinel-2 search; defaults to ``max_cloud``.
    s2_max_images : int, optional
        Cap on the number of Sentinel-2 DATES used, most recent first.

    Returns
    -------
    dict with keys ``scenes`` (one entry per classified scene: ``scene``,
    ``satellite``, ``level``, ``nir_max``, ``n_water_px``), ``plot`` (path
    of the comparison PNG, or None) and ``outdir``.
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
        # refl_* = get_reflectance (SR e TOA); toa_* = versões anteriores
        toa_files = sorted(
            glob.glob(os.path.join(path, "**", "refl_*.tif"), recursive=True)
            + glob.glob(os.path.join(path, "**", "toa_*.tif"), recursive=True)
        )

    # ------------------------------------------------------------------ #
    # Satellite selection (product=)                                      #
    # ------------------------------------------------------------------ #
    from .constants import CATALOG_CLASSIC
    from .stac import WFI_SATELLITES, resolve_catalog

    cat = resolve_catalog(catalog)
    level = {"toa": "dn"}.get(str(level).lower(), str(level).lower())
    if level not in ("sr", "dn"):
        raise ValueError(f"level deve ser 'sr' ou 'dn', recebido {level!r}.")
    if cat == CATALOG_CLASSIC and level != "dn":
        level = "dn"   # the classic catalogue only publishes DN
    if s2_max_cloud is None:
        s2_max_cloud = max_cloud
    if s2_date is None and date is not None:
        s2_date = date

    products, prod_levels = _resolve_products(product, default_level=level,
                                              catalog=cat)
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
                    f"imagem(ns) local(is) selecionada(s) "
                    f"(ignorado(s): {', '.join(sorted(skipped))}).")

    # WFI streaming from the INPE STAC is activated by date=
    stream_wfi = []
    if date is not None:
        alvo = sorted(products) if products is not None else list(WFI_SATELLITES)
        stream_wfi = [s for s in alvo if s in WFI_SATELLITES]
        if not stream_wfi and not include_s2:
            warn("date= foi informado mas product= não seleciona nenhum satélite "
                 "WFI — nada será buscado no catálogo.")
        if stream_wfi and cat == CATALOG_CLASSIC and not user:
            raise ValueError(
                "catalog='INPE_CLASSIC' exige user= (e-mail cadastrado em "
                "https://www.dgi.inpe.br/catalogo/explore) para baixar as "
                "cenas. Use catalog='INPE_STAC' para processar direto da "
                "nuvem, sem cadastro."
            )

    if not toa_files and not include_s2 and not stream_wfi:
        if products is not None and path:
            raise FileNotFoundError(
                f"Nenhuma imagem TOA de {sorted(products)} encontrada em "
                f"{os.path.abspath(path)}. Revise product= ou o caminho."
            )
        raise FileNotFoundError(
            "Nenhuma fonte de dados: informe path= com arquivos 'toa_*.tif', "
            "e/ou date= para buscar cenas WFI no STAC do INPE, e/ou "
            "include_s2=True para o Sentinel-2."
        )

    if bbox is None:
        if not toa_files:
            raise ValueError(
                "bbox é obrigatório quando não há imagens TOA locais "
                "(execução por streaming)."
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

    nir_desc = "desativado" if nir is None else f"{nir}"
    log(f"  catálogo:  {cat}")
    if toa_files:
        log(f"  {len(toa_files)} imagem(ns) local(is) em {os.path.abspath(path)}")
    if stream_wfi and cat != CATALOG_CLASSIC:
        log(f"  WFI {level.upper()} da nuvem (STAC do INPE, sem download): "
            f"{', '.join(stream_wfi)}")
    elif stream_wfi:
        log(f"  WFI do catálogo clássico (download completo): "
            f"{', '.join(stream_wfi)}")
    if include_s2:
        log("  Sentinel-2: processamento direto da nuvem (sem download)")
    log(f"  bbox:      {bbox}")
    log(f"  grade:     {coarse:.0f} m")
    log(f"  filtros:   HAND<={hand} m | NDWI>{ndwi} | NIR: {nir_desc} | "
        f"Hue [{hue_min},{hue_max})")
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
    # Classic catalogue: no streaming — materialise the scenes as files    #
    # ------------------------------------------------------------------ #
    if stream_wfi and cat == CATALOG_CLASSIC:
        from .download import get_reflectance

        log("Catálogo clássico: as cenas serão baixadas e convertidas para "
            "TOA antes da classificação (não há streaming).")
        alvo = [p for p in (product if isinstance(product, (list, tuple, set))
                            else [product]) if p] if product else "all"
        baixadas = get_reflectance(
            date=date, bbox=bbox, product=alvo, catalog=cat,
            max_cloud=max_cloud, max_images=max_images,
            outdir=os.path.join(outdir, "_classic"), user=user,
        )
        toa_files = toa_files + [m["path"] for m in baixadas]
        stream_wfi = []   # already on disk; classified with the local files
        if not toa_files:
            raise RuntimeError(
                "Nenhuma cena pôde ser baixada do catálogo clássico."
            )

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
                        red, green, blue, valid_grid=None, level="toa"):
        """Apply the optional per-pixel cloud mask, vectorize and store a scene.

        ``valid_grid`` is a boolean array of clear observations — from the
        Sentinel-2 SCL band or the WFI CMASK band.
        """
        if valid_grid is not None:
            res["confidence"][~valid_grid] = 0
            res["water"] &= valid_grid
            res["valid"] &= valid_grid
        water_list.append(res["water"])
        valid_list.append(res["valid"])
        tc_list["red"].append(red)
        tc_list["green"].append(green)
        tc_list["blue"].append(blue)
        scene_results.append(
            {
                "scene": scene_name,
                "satellite": satellite,
                "level": level,
                "nir_max": nir_max_scene,
                "n_water_px": int(res["water"].sum()),
                "confidence": res["confidence"],
            }
        )

    for toa_path in iterator:
        scene_name = _scene_name_of(toa_path)
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

            # satellite / processing level: GeoTIFF tags, falling back to the id
            tags = src.tags()
            satellite = _resolve_satellite(tags.get("SATELLITE"), scene_name)
            # NOTE: must not shadow the `level` argument, which drives the
            # STAC streaming further down.
            scene_level = _resolve_level(tags.get("PRODUCT_LEVEL"), satellite)
            is_s2 = satellite == "sentinel2"

            blue = _warp_band(src, 1, shape, transform, crs)
            green = _warp_band(src, 2, shape, transform, crs)
            red = _warp_band(src, 3, shape, transform, crs)
            nir_b = _warp_band(src, 4, shape, transform, crs)
            # band 5, when present, is the per-pixel cloud mask: SCL for
            # Sentinel-2, CMASK for WFI SR (get_reflectance writes it)
            mask_kind = tags.get("MASK_BAND") or ("SCL" if is_s2 else None)
            if mask_kind and src.count >= 5:
                # categorical: majority (mode) when coarsening
                scl = _warp_band(src, 5, shape, transform, crs,
                                 resampling=Resampling.mode)

        # Local Sentinel-2 file on the raw x10000 scale: bring it to the
        # common [0, ~1] reflectance scale.
        if is_s2 and float(np.nanmax(green)) > 10.0:
            log(f"  {scene_name}: reflectância na escala x{S2_SCALE:.0f} — normalizando.")
            blue, green, red, nir_b = (a / S2_SCALE for a in (blue, green, red, nir_b))

        nir_max_scene = _resolve_nir(nir, satellite)

        res = classify_scene(
            green, red, nir_b, hand=hand_grid,
            hue_min=hue_min, hue_max=hue_max,
            ndwi_threshold=ndwi, hand_max=hand, nir_max=nir_max_scene,
        )

        if scl is None:
            valido = None
        elif str(mask_kind).upper() == "CMASK":
            from .stac import cmask_valid
            valido = cmask_valid(scl)
        else:
            valido = ~np.isin(scl.astype(np.int16), S2_SCL_INVALID)
        _register_scene(scene_name, satellite, nir_max_scene, res,
                        red, green, blue, valid_grid=valido, level=scene_level)

    # ------------------------------------------------------------------ #
    # WFI streamed from the INPE STAC (date=)                             #
    # ------------------------------------------------------------------ #
    if stream_wfi:
        from datetime import timedelta

        d0, d1 = parse_dates(date)
        if d0 == d1:
            d0, d1 = d0 - timedelta(days=15), d1 + timedelta(days=15)
            log(f"Data única: janela expandida para {d0} a {d1}.")
        limite = (float(max_cloud)
                  if max_cloud is not None and float(max_cloud) >= 0 else None)
        # the level comes from each product name when one was given
        for satellite in stream_wfi:
            _classify_wfi_from_cloud(
                [satellite], prod_levels.get(satellite, level), bbox, (d0, d1),
                limite, max_images, crs, transform, shape, hand_grid,
                hue_min, hue_max, ndwi, hand, nir, _register_scene,
            )

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
    # Majority-rule composite (in memory — no vector export for now)      #
    # ------------------------------------------------------------------ #
    composite_conf = None
    if len(scene_results) >= 2:
        agg = majority_composite(np.stack(water_list), np.stack(valid_list))
        composite_conf = np.zeros(shape, dtype=np.uint8)
        composite_conf[agg["mask"] == 1] = 1

    # ------------------------------------------------------------------ #
    # Comparison plot: true colour vs water mask                          #
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
        "plot": png_path,
        "outdir": os.path.abspath(outdir),
    }
