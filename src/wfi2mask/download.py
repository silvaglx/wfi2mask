"""Scene search and TOA conversion — the ``get_toa`` pipeline.

Data source: the **INPE STAC** at https://data.inpe.br/bdc/stac/v1, which
needs no account and no token. Level-4 DN rasters and their XML calibration
metadata are read **windowed straight from the cloud**: only the bbox is
transferred, and the whole scene is never downloaded.

``get_toa`` remains the entry point for people who want top-of-atmosphere
reflectance — notably for calibration work on ACC/ESUN. For surface
reflectance (which needs no calibration at all) use
``get_water_mask(level="sr", ...)``, which streams the L4-SR product
directly and writes nothing to disk.
"""

from __future__ import annotations

import os
from datetime import date, timedelta

import numpy as np
import rasterio

from .constants import (
    CATALOG_CLASSIC,
    ESUN,
    PRODUCTS,
    S2_COLLECTION,
    S2_MATCHUP_TOLERANCE_DAYS,
    S2_STAC_URL,
    SR_COVERAGE_START,
    SR_NODATA,
    SR_SCALE,
)
from .stac import (
    BAND_ORDER,
    band_assets,
    read_window,
    resolve_catalog,
    resolve_product,
    search_scenes,
)
from .toa import resolve_acc, resolve_calibration, sun_zenith_from_xml_text, toa_from_dn
from .utils import log, parse_dates, validate_bbox, warn


def _resolve_products(product, default_level="sr", catalog=None) -> list:
    """Resolve ``product=`` into a list of INPE product registry entries.

    Accepts full product names (``'CB4A-WFI-L4-SR-1'``,
    ``'CBERS4A_WFI_L4_DN'``), the satellite shorthands, ``'all'`` (every
    product of ``catalog``) or a list. ``default_level`` decides what a bare
    shorthand means in the STAC catalogue.
    """
    cat = resolve_catalog(catalog)
    if product is None or (isinstance(product, str) and product.lower() == "all"):
        return [{"id": cid, **meta} for cid, meta in PRODUCTS.items()
                if meta["catalog"] == cat and meta["source"] == "inpe"]

    items = product if isinstance(product, (list, tuple, set)) else [product]
    resolved, vistos = [], set()
    for item in items:
        entrada = resolve_product(item, default_level=default_level,
                                  catalog=cat)
        if entrada["source"] != "inpe":
            raise ValueError(
                f"{entrada['id']} não é baixável por get_reflectance "
                f"(origem {entrada['source']}). Use "
                f"get_water_mask(product='{entrada['id']}', ...), que o "
                f"processa direto da nuvem."
            )
        if entrada["id"] not in vistos:
            vistos.add(entrada["id"])
            resolved.append(entrada)
    return resolved


def _analyze_bbox_coverage(items, bbox) -> None:
    """Warn when no single scene covers the bbox (orbit-boundary case)."""
    try:
        from shapely.geometry import box as shp_box, shape as shp_shape
        from shapely.ops import unary_union
    except ImportError:
        return

    roi = shp_box(*bbox)
    full, partial, geoms = [], [], []
    for item in items:
        geom = item.geometry
        if not geom:
            continue
        g = shp_shape(geom)
        geoms.append(g)
        (full if g.contains(roi) else partial).append(item)
    if not geoms:
        return

    if full:
        log(f"  Cobertura do bbox: {len(full)} de {len(items)} cena(s) cobrem "
            f"o bbox por completo.")
    else:
        union = unary_union(geoms)
        if union.contains(roi):
            warn("  Nenhuma cena individual cobre o bbox por completo: o bbox cai "
                 "na divisa entre órbitas. Várias cenas serão usadas para cobrir "
                 "toda a área.")
        else:
            warn("  As cenas encontradas NÃO cobrem todo o bbox nem em conjunto. "
                 "Considere ampliar o intervalo de datas ou revisar o bbox.")


def _s2_clean_dates(bbox, d0: date, d1: date, max_cloud: float) -> set | None:
    """EXPERIMENTAL date-level cloud proxy via Sentinel-2 matchup (on hold)."""
    try:
        from pystac_client import Client
    except ImportError:
        warn("pystac-client não instalado — matchup Sentinel-2 indisponível.")
        return None
    try:
        search = Client.open(S2_STAC_URL).search(
            collections=[S2_COLLECTION], bbox=list(bbox),
            datetime=f"{d0.isoformat()}/{d1.isoformat()}",
            query={"eo:cloud_cover": {"lte": float(max_cloud)}}, max_items=500,
        )
        return {i.datetime.date() for i in search.items() if i.datetime}
    except Exception as exc:  # noqa: BLE001
        warn(f"Matchup Sentinel-2 falhou ({exc}) — prosseguindo sem esse filtro.")
        return None


def _fetch_xml(item) -> str | None:
    """Text of any per-band XML asset of a DN item (all carry the 4 ACC values)."""
    import requests

    for key, asset in item.assets.items():
        if key.lower().endswith("_xml") and not key.upper().startswith(("LEFT", "RIGHT")):
            try:
                resp = requests.get(asset.href, timeout=90)
                resp.raise_for_status()
                return resp.text
            except Exception as exc:  # noqa: BLE001
                warn(f"  {item.id}: XML de calibração inacessível ({exc}).")
                return None
    return None


def get_reflectance(
    date=None,
    bbox=None,
    product="all",
    catalog=None,
    max_cloud=-1,
    max_images=None,
    outdir="./wfi2mask_data",
    esun=None,
    acc=None,
    s2_matchup=False,
    save_dn=False,
    user=None,
    _default_level="sr",
):
    """Download reflectance imagery for a bbox, from either INPE catalogue.

    One function for both processing levels — the product name decides:

    * ``*-L4-SR-*`` — surface reflectance, taken as published (no
      calibration involved), with the CMASK cloud band alongside;
    * ``*-L4-DN-*`` — digital numbers converted to TOA reflectance with
      ``rho = pi*ACC*DN / (ESUN*cos(theta_sun))``, ACC read from the scene
      XML.

    Rasters are read windowed from the cloud, so only the bbox travels and
    whole scenes are never downloaded. One GeoTIFF per scene is written to
    ``outdir/reflectance/<product>/refl_<scene>.tif`` (float32 reflectance,
    bands 1=B 2=G 3=R 4=NIR, plus band 5 = CMASK for SR products).

    Run :func:`wfi2mask.get_products` to see the product names.

    Parameters
    ----------
    date : str | tuple
        Single date ``"2024-08-01"`` (searched in a +/-15-day window, nearest
        date kept) or range ``"2024-08-01, 2024-09-30"``.
    bbox : list
        ``[lon_min, lat_min, lon_max, lat_max]`` in EPSG:4326. Outputs are
        cropped to it.
    product : str | list
        Product name(s), e.g. ``"CB4A-WFI-L4-SR-1"`` or
        ``["CB4A-WFI-L4-SR-1", "AMZ1-WFI-L4-DN-1"]``. ``'all'`` (default)
        takes every product of ``catalog``. Satellite shorthands
        (``'cbers4a'``) also work. See :func:`wfi2mask.get_products`.
    catalog : str, optional
        ``'INPE_STAC'`` (default) or ``'INPE_CLASSIC'``. The classic
        catalogue **requires** ``user=`` (a registered INPE e-mail), offers
        DN only, and has no windowed access — whole scenes are downloaded
        and then cropped, which is far slower. It does, however, list
        noticeably more scenes than the STAC.
    max_cloud : float
        ``-1`` (default) disables cloud screening. ``>= 0`` keeps scenes whose
        cloud cover is at most this percentage. DN collections carry no cloud
        metadata, so the values are cross-referenced from the matching L4-SR
        collection. NOTE: the percentage refers to the WHOLE scene (684-866 km
        swath), not to the bbox.
    max_images : int, optional
        Cap on scenes per product, most recent first.
    outdir : str
        Base output directory.
    esun, acc : dict, optional
        Calibration overrides for the DN->TOA conversion only — ``{band:
        value}`` or ``{satellite: {band: value}}``. By default ACC comes from
        each scene's XML and ESUN from ``constants.ESUN``.
    s2_matchup : bool
        EXPERIMENTAL (default False): additionally keep only dates within
        +/-1 day of a clear Sentinel-2 acquisition. Requires ``max_cloud>=0``.
    save_dn : bool
        For DN products, also write the cropped raw DN next to the TOA
        product (useful for calibration work). Default False.
    user : str, optional
        E-mail registered at the INPE catalogue. **Required** for
        ``catalog='INPE_CLASSIC'``; ignored (with a notice) for the STAC,
        which needs no account.

    Returns
    -------
    list of dict
        One entry per scene: ``{"scene", "product", "satellite", "level",
        "path", "cloud_cover"}`` plus ``"zenith"`` and ``"acc"`` for DN.
    """
    bbox = validate_bbox(bbox)
    d0, d1 = parse_dates(date)
    single_date = d0 == d1
    target = d0
    if single_date:
        d0, d1 = target - timedelta(days=15), target + timedelta(days=15)
        log(f"Data única solicitada ({target}): buscando na janela {d0} a {d1} "
            f"e mantendo a(s) cena(s) mais próxima(s).")

    cat = resolve_catalog(catalog)
    if cat == CATALOG_CLASSIC:
        if not user:
            raise ValueError(
                "catalog='INPE_CLASSIC' exige user= (e-mail cadastrado em "
                "https://www.dgi.inpe.br/catalogo/explore). O catálogo "
                "INPE_STAC não precisa de cadastro."
            )
    elif user is not None:
        warn("O parâmetro user= não é necessário no catálogo INPE_STAC "
             "(é aberto) e será ignorado.")

    produtos = _resolve_products(product, default_level=_default_level,
                                 catalog=cat)
    base = os.path.join(outdir, "reflectance")

    log(f"  catálogo:   {cat}")
    log(f"  bbox:       {bbox}")
    log(f"  período:    {d0} a {d1}")
    log(f"  produtos:   {', '.join(p['id'] for p in produtos)}")
    log(f"  saídas em:  {os.path.abspath(base)}/<produto>/")

    if cat == CATALOG_CLASSIC:
        return _get_reflectance_classic(
            produtos, bbox, d0, d1, target, single_date, max_cloud, max_images,
            base, outdir, esun, acc, save_dn, user,
        )

    cloud_screening = max_cloud is not None and float(max_cloud) >= 0
    clean_dates = None
    if s2_matchup:
        if not cloud_screening:
            warn("s2_matchup=True requer max_cloud >= 0 — matchup ignorado.")
        else:
            clean_dates = _s2_clean_dates(bbox, d0, d1, float(max_cloud))

    results = []
    for prod in produtos:
        satellite, level, cid = prod["satellite"], prod["level"], prod["id"]
        if level == "sr":
            inicio = SR_COVERAGE_START.get(satellite)
            if inicio and d0.isoformat() < inicio:
                warn(f"{cid}: cobertura SR começa em {inicio}; para datas "
                     f"anteriores use o produto DN correspondente.")
        log(f"Consultando STAC do INPE ({cid})...")
        try:
            items = search_scenes(
                satellite, level, bbox, d0, d1,
                max_cloud=(float(max_cloud) if cloud_screening else None),
                max_images=None,
            )
        except Exception as exc:  # noqa: BLE001
            warn(f"Busca falhou para {cid}: {exc}")
            continue
        log(f"  {len(items)} cena(s) encontradas.")
        if not items:
            continue

        if clean_dates is not None:
            tol = timedelta(days=S2_MATCHUP_TOLERANCE_DAYS)
            kept = [i for i in items
                    if any(abs(i.datetime.date() - cd) <= tol for cd in clean_dates)]
            log(f"  Matchup Sentinel-2: {len(kept)} de {len(items)} cenas mantidas.")
            items = kept
            if not items:
                continue

        if single_date:
            best = min(abs(i.datetime.date() - target) for i in items)
            items = [i for i in items if abs(i.datetime.date() - target) == best]
            log(f"  Data mais próxima de {target}: {items[0].datetime.date()} "
                f"({len(items)} cena(s)).")

        if max_images is not None and len(items) > int(max_images):
            log(f"  max_images={max_images}: limitando de {len(items)} para "
                f"{max_images} cena(s) (mais recentes primeiro).")
            items = items[: int(max_images)]

        _analyze_bbox_coverage(items, bbox)

        dest = os.path.join(base, cid)
        os.makedirs(dest, exist_ok=True)
        try:
            from tqdm import tqdm
            iterator = tqdm(items, desc=cid, unit="cena")
        except ImportError:
            iterator = items

        assets = band_assets(cid, satellite)
        esun_scene = resolve_calibration(esun, satellite) or ESUN[satellite]

        for item in iterator:
            if level == "sr":
                meta = _write_sr_item(item, prod, bbox, assets, dest)
            else:
                meta = _write_toa_item(item, prod, bbox, assets, esun_scene,
                                       acc, dest, save_dn)
            if meta:
                results.append(meta)

    return results


def get_toa(*args, **kwargs):
    """DEPRECATED alias of :func:`get_reflectance`, kept on the TOA path.

    Existing scripts keep working: bare satellite names resolve to that
    sensor's **DN** product, so the output is still TOA reflectance, as the
    name promises. New code should call ``get_reflectance`` and name the
    product explicitly (see :func:`wfi2mask.get_products`).
    """
    warn("get_toa() foi renomeada para get_reflectance(). O alias continua "
         "funcionando (resolvendo para os produtos DN->TOA), mas será "
         "removido numa versão futura.")
    kwargs.setdefault("_default_level", "dn")
    return get_reflectance(*args, **kwargs)


def _get_reflectance_classic(produtos, bbox, d0, d1, target, single_date,
                             max_cloud, max_images, base, outdir,
                             esun, acc, save_dn, user):
    """Classic-catalogue pipeline: query -> whole-scene download -> TOA.

    This catalogue has no windowed access, so each scene is transferred in
    full before being cropped to the bbox — expect minutes per scene.
    """
    from . import classic
    from .toa import convert_scene_to_toa

    warn("Catálogo clássico: sem leitura por janela — cada cena é baixada "
         "POR INTEIRO antes do recorte (minutos por cena). O catálogo "
         "INPE_STAC transfere apenas o bbox.")

    raw_base = os.path.join(outdir, "raw")
    resultados = []
    for prod in produtos:
        satellite, cid = prod["satellite"], prod["id"]
        log(f"Consultando catálogo clássico ({cid})...")
        try:
            features = classic.search_scenes(
                satellite, bbox, d0, d1,
                max_cloud=(max_cloud if max_cloud is not None
                           and float(max_cloud) >= 0 else None),
                max_images=None, user=user,
            )
        except Exception as exc:  # noqa: BLE001
            warn(f"Busca falhou para {cid}: {exc}")
            continue
        log(f"  {len(features)} cena(s) encontradas.")
        if not features:
            continue

        if single_date:
            melhor = min(abs((classic.feature_date(f) or d0) - target)
                         for f in features)
            features = [f for f in features
                        if abs((classic.feature_date(f) or d0) - target) == melhor]
            log(f"  Data mais próxima de {target}: "
                f"{classic.feature_date(features[0])} ({len(features)} cena(s)).")

        if max_images is not None and len(features) > int(max_images):
            log(f"  max_images={max_images}: limitando de {len(features)} para "
                f"{max_images} cena(s) (mais recentes primeiro).")
            features = features[: int(max_images)]

        classic.analyze_bbox_coverage(features, bbox)

        raw_dir = os.path.join(raw_base, satellite)
        dest = os.path.join(base, cid)
        os.makedirs(dest, exist_ok=True)
        try:
            from tqdm import tqdm
            iterator = tqdm(features, desc=cid, unit="cena")
        except ImportError:
            iterator = features

        for feat in iterator:
            scene_dir = classic.download_scene(feat, raw_dir, user)
            if scene_dir is None:
                continue
            sid = feat.get("id", os.path.basename(scene_dir))
            out_path = os.path.join(dest, f"refl_{sid}.tif")
            meta = convert_scene_to_toa(scene_dir, out_path,
                                        satellite=satellite, bbox=bbox,
                                        esun=esun, acc=acc)
            if not meta:
                continue
            with rasterio.open(out_path, "r+") as dst:
                dst.update_tags(PRODUCT=cid, PRODUCT_LEVEL="TOA",
                                CATALOG=CATALOG_CLASSIC, SCENE_ID=sid,
                                SOURCE=f"INPE clássico {cid}")
            resultados.append({
                "scene": sid, "product": cid, "satellite": satellite,
                "level": "toa", "path": out_path,
                "zenith": meta.get("zenith"), "acc": meta.get("acc"),
                "cloud_cover": feat.get("properties", {}).get("cloud_cover"),
                "raw_dir": scene_dir,
            })
    return resultados


def _read_bands(item, bbox, assets):
    """Windowed read of the 4 spectral bands. Returns (dict, profile) or None."""
    arrays, profile = {}, None
    for band in BAND_ORDER:
        key = assets.get(band)
        if key not in item.assets:
            warn(f"  {item.id}: banda '{band}' ({key}) ausente — pulando.")
            return None, None
        arr, prof = read_window(item.assets[key].href, bbox)
        if arr is None:
            warn(f"  {item.id}: sem sobreposição com o bbox — pulando.")
            return None, None
        arrays[band] = arr
        profile = profile or prof
    return arrays, profile


def _base_tags(item, prod, bbox):
    return dict(
        SATELLITE=prod["satellite"],
        SCENE_ID=item.id,
        PRODUCT=prod["id"],
        CATALOG=prod.get("catalog") or "",
        BAND_ORDER=",".join(BAND_ORDER),
        BBOX=",".join(f"{v:.6f}" for v in bbox),
        SOURCE=f"INPE STAC {prod['id']}",
    )


def _write_sr_item(item, prod, bbox, assets, dest):
    """Write one L4-SR scene as float32 reflectance + the CMASK band."""
    raw, profile = _read_bands(item, bbox, assets)
    if raw is None:
        return None

    bands = {}
    for band, arr in raw.items():
        refl = arr.astype(np.float32)
        refl[refl == SR_NODATA] = 0.0
        bands[band] = refl / SR_SCALE

    cmask = None
    if "CMASK" in item.assets:
        cmask, _ = read_window(item.assets["CMASK"].href, bbox)

    count = 4 if cmask is None else 5
    out_profile = profile.copy()
    out_profile.update(dtype="float32", count=count, compress="lzw", nodata=0.0)
    out_path = os.path.join(dest, f"refl_{item.id}.tif")
    with rasterio.open(out_path, "w", **out_profile) as dst:
        for i, band in enumerate(BAND_ORDER, start=1):
            dst.write(bands[band], i)
        tags = _base_tags(item, prod, bbox)
        tags["PRODUCT_LEVEL"] = "SR"
        tags["PROCESSING"] = f"wfi2mask SR (L4-SR / {SR_SCALE:.0f})"
        if cmask is not None:
            dst.write(cmask.astype(np.float32), 5)
            tags["MASK_BAND"] = "CMASK"
            tags["BAND_ORDER"] += ",cmask"
        dst.update_tags(**tags)

    return {"scene": item.id, "product": prod["id"], "satellite": prod["satellite"],
            "level": "sr", "path": out_path,
            "cloud_cover": item.properties.get("eo:cloud_cover")}


def _write_toa_item(item, prod, bbox, assets, esun_scene, acc_override,
                    dest, save_dn):
    """Read one DN scene windowed, convert to TOA and write the GeoTIFF."""
    satellite = prod["satellite"]
    dn_by_band, profile = _read_bands(item, bbox, assets)
    if dn_by_band is None:
        return None

    xml_text = _fetch_xml(item)
    acc = resolve_acc(satellite, acc_override, xml_text)
    zenith = (sun_zenith_from_xml_text(xml_text) if xml_text else 45.0)
    bands_toa = toa_from_dn(dn_by_band, acc, esun_scene, zenith)

    out_profile = profile.copy()
    out_profile.update(dtype="float32", count=4, compress="lzw", nodata=0.0)
    out_path = os.path.join(dest, f"refl_{item.id}.tif")
    with rasterio.open(out_path, "w", **out_profile) as dst:
        for i, band in enumerate(BAND_ORDER, start=1):
            dst.write(bands_toa[band], i)
        tags = _base_tags(item, prod, bbox)
        tags["PRODUCT_LEVEL"] = "TOA"
        tags["SUN_ZENITH_DEG"] = f"{zenith:.4f}"
        tags["PROCESSING"] = "wfi2mask TOA (pi*ACC*DN)/(ESUN*cos(zenith))"
        dst.update_tags(**tags)

    if save_dn:
        dn_profile = profile.copy()
        dn_profile.update(count=4, compress="lzw")
        dn_path = os.path.join(dest, f"dn_{item.id}.tif")
        with rasterio.open(dn_path, "w", **dn_profile) as dst:
            for i, band in enumerate(BAND_ORDER, start=1):
                dst.write(dn_by_band[band].astype(dn_profile["dtype"]), i)

    return {"scene": item.id, "product": prod["id"], "satellite": satellite,
            "level": "toa", "path": out_path, "zenith": zenith, "acc": acc,
            "cloud_cover": item.properties.get("eo:cloud_cover")}
