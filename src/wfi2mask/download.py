"""Catalog search, download and TOA conversion — the ``get_toa`` pipeline.

Data source: INPE catalog (https://www.dgi.inpe.br/catalogo/explore) accessed
through the ``cbers4asat`` library. An account (e-mail) registered at the
INPE catalog is required for downloading.
"""

from __future__ import annotations

import os
from datetime import date, timedelta

from .constants import (
    COLLECTIONS,
    S2_COLLECTION,
    S2_MATCHUP_TOLERANCE_DAYS,
    S2_STAC_URL,
    satellite_from_scene_id,
)
from .toa import convert_scene_to_toa
from .utils import log, parse_dates, validate_bbox, warn


def _resolve_collections(product) -> dict:
    """Accepts 'amazonia1', 'cbers4a', 'cbers4', 'all', an INPE collection id,
    or a list of any of these. Returns {collection_id: satellite_key}."""
    if product is None or (isinstance(product, str) and product.lower() == "all"):
        return {cid: sat for sat, cid in COLLECTIONS.items()}

    items = product if isinstance(product, (list, tuple)) else [product]
    resolved = {}
    for it in items:
        key = str(it).strip()
        low = key.lower()
        if low in COLLECTIONS:
            resolved[COLLECTIONS[low]] = low
        elif key.upper() in {c.upper() for c in COLLECTIONS.values()}:
            for sat, cid in COLLECTIONS.items():
                if cid.upper() == key.upper():
                    resolved[cid] = sat
        else:
            raise ValueError(
                f"Produto desconhecido: {it!r}. Use 'amazonia1', 'cbers4a', "
                f"'cbers4', 'all' ou um id de coleção INPE "
                f"({', '.join(COLLECTIONS.values())})."
            )
    return resolved


def _feature_date(feat) -> date | None:
    dt = feat.get("properties", {}).get("datetime", "")
    try:
        return date.fromisoformat(str(dt)[:10])
    except ValueError:
        return None


def _analyze_bbox_coverage(features: list, bbox: list) -> None:
    """Warn the user when the bbox is not covered by a single scene.

    A WFI swath is huge (684–866 km), so most bboxes fit inside one scene —
    but a bbox that falls on the boundary between two orbit paths/rows needs
    two (or more) scenes on different dates to be fully covered.
    """
    try:
        from shapely.geometry import box as shp_box, shape as shp_shape
        from shapely.ops import unary_union
    except ImportError:
        warn("shapely indisponível — análise de cobertura do bbox ignorada.")
        return

    roi = shp_box(*bbox)
    full, partial = [], []
    geoms = []
    for feat in features:
        geom = feat.get("geometry")
        if not geom:
            continue
        g = shp_shape(geom)
        geoms.append(g)
        (full if g.contains(roi) else partial).append(feat)

    if not geoms:
        return

    if full:
        log(f"Cobertura do bbox: {len(full)} de {len(features)} cenas cobrem o bbox por completo.")
        if partial:
            log(
                f"  As outras {len(partial)} cenas cobrem o bbox apenas parcialmente "
                f"(bbox na borda da órbita) — pixels fora da cena ficam sem dado nessas datas."
            )
    else:
        union = unary_union(geoms)
        if union.contains(roi):
            warn(
                "Nenhuma cena individual cobre o bbox por completo: o bbox cai na "
                "divisa entre órbitas/cenas. Múltiplas cenas (datas/órbitas "
                "diferentes) serão baixadas para cobrir toda a área solicitada."
            )
            by_date: dict = {}
            for feat in partial:
                d = _feature_date(feat)
                by_date.setdefault(d, []).append(feat.get("id", "?"))
            for d, ids in sorted(by_date.items(), key=lambda kv: (kv[0] is None, kv[0])):
                log(f"  {d}: {len(ids)} cena(s) parciais -> {', '.join(ids)}")
        else:
            warn(
                "As cenas encontradas NÃO cobrem todo o bbox nem em conjunto. "
                "Considere ampliar o intervalo de datas ou revisar o bbox."
            )


def _s2_clean_dates(bbox, d0: date, d1: date, max_cloud: float) -> set | None:
    """Dates with a clean Sentinel-2 acquisition over the bbox (cloud proxy).

    EXPERIMENTAL (on hold): alternative date-level cloud screening by matchup
    — keep WFI dates within +/-1 day of a Sentinel-2 scene whose
    eo:cloud_cover <= max_cloud. The primary cloud filter is the INPE
    catalog's own scene-level cloud percentage (``max_cloud``); this matchup
    is kept for testing as a possible future refinement.
    """
    try:
        from pystac_client import Client
    except ImportError:
        warn("pystac-client não instalado — matchup Sentinel-2 indisponível.")
        return None
    try:
        client = Client.open(S2_STAC_URL)
        search = client.search(
            collections=[S2_COLLECTION],
            bbox=bbox,
            datetime=f"{d0.isoformat()}/{d1.isoformat()}",
            query={"eo:cloud_cover": {"lte": float(max_cloud)}},
            max_items=500,
        )
        dates = set()
        for item in search.items():
            if item.datetime is not None:
                dates.add(item.datetime.date())
        return dates
    except Exception as exc:  # noqa: BLE001
        warn(f"Matchup Sentinel-2 falhou ({exc}) — prosseguindo sem filtro de nuvem.")
        return None


def get_toa(
    date=None,
    bbox=None,
    product="all",
    max_cloud=-1,
    max_images=None,
    user=None,
    outdir="./wfi2mask_data",
    s2_matchup=False,
    esun=None,
    acc=None,
):
    """Search the INPE catalog, download WFI scenes and convert them to TOA.

    Parameters
    ----------
    date : str | tuple
        Single date ``"2024-08-01"`` or range ``"2024-08-01, 2024-09-30"``.
        With a single date, the search covers a +/-15-day window and the
        scene(s) nearest to the requested date are kept.
    bbox : list
        ``[lon_min, lat_min, lon_max, lat_max]`` in EPSG:4326. The TOA
        products are CROPPED to this bbox (the raw DN download still covers
        the full scene, as served by the INPE catalog).
    product : str | list
        ``'amazonia1'``, ``'cbers4a'``, ``'cbers4'``, ``'all'`` (default) or
        INPE collection ids.
    max_cloud : float
        ``-1`` (default) disables cloud screening. Any value >= 0 filters the
        INPE catalog query by its scene-level cloud percentage
        (``cloud <= max_cloud``). NOTE: the percentage refers to the WHOLE
        WFI scene (684-866 km swath) — a partially cloudy scene may still be
        perfectly clear over your bbox, so a strict value can discard usable
        dates.
    max_images : int, optional
        Cap on the number of scenes downloaded (per satellite), most recent
        first. Works with or without ``max_cloud``.
    user : str
        E-mail registered at the INPE catalog (required for download).
    outdir : str
        Base output directory. Raw DN data goes to ``outdir/raw/<satellite>/``
        and TOA products to ``outdir/toa/<satellite>/``.
    s2_matchup : bool
        EXPERIMENTAL (default False): additionally screen dates by matchup
        with Sentinel-2 (keep WFI dates within +/-1 day of a Sentinel-2
        acquisition with eo:cloud_cover <= ``max_cloud``). Kept on hold for
        testing; requires ``max_cloud >= 0``.
    esun, acc : dict, optional
        Calibration overrides — ``{band: value}`` or ``{satellite: {band:
        value}}``. Defaults: ``wfi2mask.constants.ESUN`` and
        ``ACC_OVERRIDE`` (for CBERS-4 the ACC comes from each scene's XML).

    Returns
    -------
    list of dict
        One entry per converted scene: ``{"scene", "satellite", "path", ...}``.
    """
    from cbers4asat import Cbers4aAPI

    bbox = validate_bbox(bbox)
    d0, d1 = parse_dates(date)
    single_date = d0 == d1
    if single_date:
        target = d0
        d0 = target - timedelta(days=15)
        d1 = target + timedelta(days=15)
        log(f"Data única solicitada ({target}): buscando na janela {d0} a {d1} "
            f"e mantendo a(s) cena(s) mais próxima(s).")

    if user is None:
        raise ValueError(
            "user= é obrigatório: e-mail cadastrado no catálogo do INPE "
            "(https://www.dgi.inpe.br/catalogo/explore)."
        )
    if max_cloud is False:
        max_cloud = -1

    collections = _resolve_collections(product)
    raw_base = os.path.join(outdir, "raw")
    toa_base = os.path.join(outdir, "toa")

    log("=" * 62)
    log("wfi2mask.get_toa")
    log(f"  bbox:       {bbox}")
    log(f"  período:    {d0} a {d1}")
    log(f"  produtos:   {', '.join(collections.values())}")
    log(f"  dados brutos (DN) serão armazenados em:  {os.path.abspath(raw_base)}/<satelite>/")
    log(f"  produtos TOA serão armazenados em:       {os.path.abspath(toa_base)}/<satelite>/")
    log("=" * 62)

    api = Cbers4aAPI(user)

    # ------------------------------------------------------------------ #
    # Cloud screening                                                     #
    # ------------------------------------------------------------------ #
    cloud_screening = max_cloud is not None and float(max_cloud) >= 0
    inpe_cloud = float(max_cloud) if cloud_screening else 100.0
    if cloud_screening:
        log(f"Filtro de nuvem ativo (max_cloud={max_cloud}%): usando o percentual "
            f"de nuvem do catálogo INPE (nível de cena).")
        warn("O percentual refere-se à CENA inteira (faixa de 684–866 km) — "
             "uma cena parcialmente nublada pode estar limpa sobre o seu bbox.")

    # EXPERIMENTAL: date-level Sentinel-2 matchup (on hold / em teste)
    clean_dates = None
    if s2_matchup:
        if not cloud_screening:
            warn("s2_matchup=True requer max_cloud >= 0 — matchup ignorado.")
        else:
            log(f"[experimental] Matchup Sentinel-2 ativo (tolerância "
                f"+/-{S2_MATCHUP_TOLERANCE_DAYS} dia)...")
            clean_dates = _s2_clean_dates(bbox, d0, d1, float(max_cloud))
            if clean_dates is not None:
                log(f"  {len(clean_dates)} datas Sentinel-2 limpas encontradas no período.")

    results = []
    for collection_id, satellite in collections.items():
        log(f"--- {satellite.upper()} ({collection_id}) ---")
        log("Consultando catálogo INPE...")
        try:
            products_fc = api.query(
                location=bbox,
                initial_date=d0,
                end_date=d1,
                cloud=inpe_cloud,
                limit=200,
                collections=[collection_id],
            )
        except Exception as exc:  # noqa: BLE001
            warn(f"Consulta ao catálogo falhou para {collection_id}: {exc}")
            continue

        features = products_fc.get("features", [])
        log(f"  {len(features)} cena(s) encontradas no catálogo.")
        if not features:
            continue

        # EXPERIMENTAL Sentinel-2 matchup filter (s2_matchup=True)
        if clean_dates is not None:
            tol = timedelta(days=S2_MATCHUP_TOLERANCE_DAYS)
            kept = []
            for feat in features:
                fd = _feature_date(feat)
                if fd and any(abs(fd - cd) <= tol for cd in clean_dates):
                    kept.append(feat)
            log(f"  [experimental] Matchup Sentinel-2: {len(kept)} de "
                f"{len(features)} cenas mantidas.")
            features = kept
            if not features:
                warn("  Nenhuma cena WFI coincide com datas Sentinel-2 limpas.")
                continue

        # Single date: keep only the nearest date(s)
        if single_date and features:
            dated = [(abs((_feature_date(f) or d0) - target), f) for f in features]
            best = min(d for d, _ in dated)
            features = [f for d, f in dated if d == best]
            fdate = _feature_date(features[0])
            log(f"  Data mais próxima de {target}: {fdate} "
                f"({len(features)} cena(s) nessa data).")

        # Sort newest first and cap
        features.sort(key=lambda f: _feature_date(f) or d0, reverse=True)
        if max_images is not None and len(features) > int(max_images):
            log(f"  max_images={max_images}: limitando de {len(features)} para "
                f"{max_images} cena(s) (mais recentes primeiro).")
            features = features[: int(max_images)]

        # bbox coverage analysis (multi-scene warning)
        _analyze_bbox_coverage(features, bbox)

        # ------------------------------------------------------------------
        # Download
        # ------------------------------------------------------------------
        raw_dir = os.path.join(raw_base, satellite)
        os.makedirs(raw_dir, exist_ok=True)
        log(f"  Baixando {len(features)} cena(s) para {raw_dir} "
            f"(bandas: blue, green, red, nir + metadados XML)...")
        try:
            from tqdm import tqdm
            iterator = tqdm(features, desc=f"download {satellite}", unit="cena")
        except ImportError:
            iterator = features

        downloaded_ids = []
        for feat in iterator:
            sid = feat.get("id", "?")
            try:
                api.download(
                    products={"type": "FeatureCollection", "features": [feat]},
                    bands=["blue", "green", "red", "nir"],
                    threads=3,
                    outdir=raw_dir,
                    with_folder=True,
                    with_metadata=True,  # XML needed for TOA conversion
                )
                downloaded_ids.append(sid)
            except TypeError:
                # older cbers4asat signatures
                try:
                    api.download(
                        products={"type": "FeatureCollection", "features": [feat]},
                        bands=["blue", "green", "red", "nir"],
                        outdir=raw_dir,
                        with_folder=True,
                        with_metadata=True,
                    )
                    downloaded_ids.append(sid)
                except Exception as exc:  # noqa: BLE001
                    warn(f"  Falha ao baixar {sid}: {exc}")
            except Exception as exc:  # noqa: BLE001
                warn(f"  Falha ao baixar {sid}: {exc}")

        # ------------------------------------------------------------------
        # TOA conversion
        # ------------------------------------------------------------------
        toa_dir = os.path.join(toa_base, satellite)
        os.makedirs(toa_dir, exist_ok=True)
        log(f"  Convertendo DN -> reflectância TOA em {toa_dir} ...")
        for sid in downloaded_ids:
            scene_dir = os.path.join(raw_dir, sid)
            if not os.path.isdir(scene_dir):
                # some versions save without the id as folder name; try to find
                candidates = [
                    os.path.join(raw_dir, d)
                    for d in os.listdir(raw_dir)
                    if sid in d and os.path.isdir(os.path.join(raw_dir, d))
                ]
                if not candidates:
                    warn(f"  Pasta da cena {sid} não encontrada após download.")
                    continue
                scene_dir = candidates[0]
            out_path = os.path.join(toa_dir, f"toa_{os.path.basename(scene_dir)}.tif")
            meta = convert_scene_to_toa(
                scene_dir, out_path,
                satellite=satellite_from_scene_id(sid) or satellite,
                bbox=bbox, esun=esun, acc=acc,
            )
            if meta:
                results.append(meta)

    log("=" * 62)
    log(f"Concluído: {len(results)} cena(s) TOA prontas (recortadas no bbox).")
    log(f"  DN bruto: {os.path.abspath(raw_base)}/<satelite>/<cena>/")
    log(f"  TOA:      {os.path.abspath(toa_base)}/<satelite>/toa_<cena>.tif")
    log("Use w2m.get_water_mask(path=...) para gerar a máscara d'água.")
    return results
