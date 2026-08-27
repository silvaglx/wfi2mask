"""INPE STAC client — scene search and windowed cloud reads.

Data source: https://data.inpe.br/bdc/stac/v1 (Brazil Data Cube / INPE).
**No account and no token are required** — a change from the previous
``cbers4asat`` path, which needed an e-mail registered at the INPE catalog.

Two processing levels are exposed per WFI sensor (see
:data:`wfi2mask.constants.STAC_COLLECTIONS`):

``sr``
    Level-4 Surface Reflectance, delivered as **Cloud Optimized GeoTIFF**
    (512x512 tiles + overviews) with a per-pixel cloud mask (CMASK) and the
    same 1/10000 scaling as Sentinel-2 L2A. Read windowed straight from the
    cloud: only the pixels of the bbox cross the network.

``dn``
    Level-4 Digital Number plus per-band XML metadata (absolute calibration
    coefficients and sun elevation) — the input of the TOA conversion in
    :mod:`wfi2mask.toa`. These rasters are striped rather than tiled, so a
    windowed read still works but transfers whole-width strips (roughly 3x
    more bytes than the SR equivalent for a small bbox).

Nothing is written to disk by this module: every read lands directly on the
caller's analysis grid.
"""

from __future__ import annotations

import os

import numpy as np
import rasterio
from rasterio.warp import Resampling, reproject, transform_bounds

from .constants import (
    CATALOG_CLASSIC,
    CATALOG_STAC,
    CATALOGS,
    CLASSIC_COLLECTIONS,
    CMASK_CLEAR,
    DEFAULT_CATALOG,
    PRODUCTS,
    SR_COVERAGE_START,
    SR_NODATA,
    SR_SCALE,
    STAC_COLLECTIONS,
    STAC_PRODUCTS,
    STAC_URL,
)
from .utils import log, warn

BAND_ORDER = ("blue", "green", "red", "nir")

#: WFI sensors served by the INPE STAC
WFI_SATELLITES = ("amazonia1", "cbers4a", "cbers4")

# GDAL settings for efficient windowed reads of remote COGs
_GDAL_ENV = {
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif,.TIF",
    "GDAL_HTTP_MERGE_CONSECUTIVE_RANGES": "YES",
    "GDAL_HTTP_MULTIRANGE": "YES",
}

# Fallback band mapping, used when the collection metadata cannot be read.
# The authoritative mapping comes from each collection's eo:bands
# (common_name -> asset key), which is why band numbering never needs to be
# hardcoded per satellite any more.
_FALLBACK_ASSETS = {
    "amazonia1": {"blue": "BAND1", "green": "BAND2", "red": "BAND3", "nir": "BAND4"},
    "cbers4a": {"blue": "BAND13", "green": "BAND14", "red": "BAND15", "nir": "BAND16"},
    "cbers4": {"blue": "BAND13", "green": "BAND14", "red": "BAND15", "nir": "BAND16"},
}

_band_cache: dict = {}


def _apply_gdal_env() -> None:
    for key, value in _GDAL_ENV.items():
        os.environ.setdefault(key, value)


#: satellite shorthands accepted wherever a product name is expected
_LEGACY_NAMES = {
    "amazonia1": "amazonia1", "amazonia-1": "amazonia1",
    "cbers4a": "cbers4a", "cbers-4a": "cbers4a",
    "cbers4": "cbers4", "cbers-4": "cbers4",
    "sentinel2": "sentinel2", "sentinel-2": "sentinel2", "s2": "sentinel2",
}


def resolve_catalog(catalog) -> str:
    """Validate and normalize a catalogue name."""
    if catalog is None:
        return DEFAULT_CATALOG
    key = str(catalog).strip().upper().replace("-", "_").replace(" ", "_")
    aliases = {"STAC": CATALOG_STAC, "INPE": CATALOG_STAC,
               "CLASSIC": CATALOG_CLASSIC, "CLASSICO": CATALOG_CLASSIC,
               "CBERS4ASAT": CATALOG_CLASSIC}
    key = aliases.get(key, key)
    if key not in CATALOGS:
        raise ValueError(
            f"Catálogo desconhecido: {catalog!r}. Use "
            f"{' ou '.join(repr(c) for c in CATALOGS)}."
        )
    return key


def resolve_product(name: str, default_level: str = "sr", catalog=None) -> dict:
    """Resolve a product name into its registry entry.

    Accepts the full product name (``'CB4A-WFI-L4-SR-1'``,
    ``'CBERS4A_WFI_L4_DN'``, case-insensitive) and the satellite shorthands
    (``'cbers4a'``), which resolve within ``catalog`` at ``default_level``.
    Product names are unique across catalogues, so an explicit name also
    determines the catalogue — and conflicts with ``catalog=`` are rejected
    rather than silently reinterpreted.
    """
    if not isinstance(name, str):
        raise ValueError(f"Nome de produto inválido: {name!r}")
    key = name.strip()
    cat = resolve_catalog(catalog) if catalog is not None else None

    for cid, meta in PRODUCTS.items():
        if key.lower() == cid.lower():
            if (cat and meta["catalog"] is not None and meta["catalog"] != cat):
                raise ValueError(
                    f"O produto {cid!r} pertence ao catálogo "
                    f"{meta['catalog']!r}, mas catalog={cat!r} foi informado. "
                    f"Use get_products(catalog={cat!r}) para ver os nomes "
                    f"válidos nesse catálogo."
                )
            return {"id": cid, **meta}

    low = key.lower().replace("_", "-")
    if low in _LEGACY_NAMES:
        satellite = _LEGACY_NAMES[low]
        alvo = cat or DEFAULT_CATALOG
        if satellite == "sentinel2":
            return {"id": "sentinel-2-l2a", **PRODUCTS["sentinel-2-l2a"]}
        if alvo == CATALOG_CLASSIC:
            cid = CLASSIC_COLLECTIONS.get(satellite)
        else:
            cid = (STAC_COLLECTIONS.get((satellite, default_level))
                   or STAC_COLLECTIONS.get((satellite, "sr")))
        if cid:
            return {"id": cid, **PRODUCTS[cid]}

    raise ValueError(
        f"Produto desconhecido: {name!r}. Use wfi2mask.get_products() para "
        f"ver a lista completa de nomes aceitos."
    )


def get_products(catalog=None, level=None, source=None, verbose=True) -> list:
    """List the products this package can process, printing a summary.

    Parameters
    ----------
    catalog : str, optional
        ``'INPE_STAC'`` (default) or ``'INPE_CLASSIC'``. Pass ``'all'`` to
        list both. Sentinel-2 comes from AWS and appears in either mode.
    level : str, optional
        ``'sr'`` (surface reflectance) or ``'dn'`` (digital numbers,
        converted to TOA).
    source : str, optional
        ``'inpe'`` or ``'aws'``.
    verbose : bool
        Print the table (default True). The list is always returned.

    Returns
    -------
    list of dict
        One entry per product: ``id``, ``catalog``, ``platform``, ``level``,
        ``gsd``, ``source``, ``desc`` and ``coverage_start`` when known.

    Examples
    --------
    >>> import wfi2mask as w2m
    >>> w2m.get_products(catalog="INPE_CLASSIC")     # doctest: +SKIP
    """
    todos = isinstance(catalog, str) and catalog.strip().lower() == "all"
    alvo = None if todos else resolve_catalog(catalog)

    itens = []
    for cid, meta in PRODUCTS.items():
        # catalog=None entries (Sentinel-2/AWS) belong to every catalogue
        if alvo and meta["catalog"] is not None and meta["catalog"] != alvo:
            continue
        if level and meta["level"] != str(level).lower():
            continue
        if source and meta["source"] != str(source).lower():
            continue
        entrada = {"id": cid, **meta}
        if meta["level"] == "sr" and meta["source"] == "inpe":
            entrada["coverage_start"] = SR_COVERAGE_START.get(meta["satellite"])
        itens.append(entrada)

    if verbose:
        _print_products(itens, alvo)
    return itens


def _print_products(itens: list, alvo=None) -> None:
    """Render the product table (plain print, not the [wfi2mask] log)."""
    if not itens:
        print("Nenhum produto corresponde aos filtros informados.")
        return

    largura = max(len(i["id"]) for i in itens)
    titulo = (f"Produtos disponíveis — catálogo {alvo}" if alvo
              else "Produtos disponíveis — todos os catálogos")
    print()
    print(titulo)
    print("=" * (largura + 60))
    print(f"{'PRODUTO'.ljust(largura)}  {'PLATAFORMA':<20} {'NÍVEL':<7} "
          f"{'RES.':>5}  CATÁLOGO")
    print("-" * (largura + 60))
    for i in sorted(itens, key=lambda x: (x["catalog"] or "", x["satellite"],
                                          x["level"])):
        nivel = "SR" if i["level"] == "sr" else "DN→TOA"
        cat = i["catalog"] or "ambos (AWS)"
        print(f"{i['id'].ljust(largura)}  {i['platform']:<20} {nivel:<7} "
              f"{i['gsd']:>4}m  {cat}")
        print(f"{' ' * largura}  {i['desc']}")
        inicio = i.get("coverage_start")
        if inicio:
            print(f"{' ' * largura}  cobertura a partir de {inicio}")
        print()

    catalogos = {i["catalog"] for i in itens if i["catalog"]}
    if catalogos:
        print("Catálogos")
        print("-" * (largura + 60))
        for nome in sorted(catalogos):
            meta = CATALOGS[nome]
            cadastro = ("exige cadastro (user=)" if meta["auth"]
                        else "sem cadastro")
            leitura = ("leitura por janela (só o bbox trafega)"
                       if meta["windowed"] else "baixa a CENA INTEIRA")
            print(f"  {nome}: {meta['label']}")
            print(f"     {cadastro} | {leitura}")
            print(f"     nuvem: {meta['cloud']}")
            print(f"     {meta['notes']}")
            print()
    print("Use o nome do PRODUTO em get_reflectance(product=...) e "
          "get_water_mask(product=...),")
    print("ou selecione o catálogo inteiro com catalog='INPE_STAC' / "
          "'INPE_CLASSIC'.")
    print()


def collection_id(satellite: str, level: str) -> str:
    """INPE STAC collection id for a satellite/level pair."""
    key = (satellite.lower(), level.lower())
    if key not in STAC_COLLECTIONS:
        raise ValueError(
            f"Sem coleção STAC para satélite={satellite!r} nível={level!r}. "
            f"Combinações disponíveis: {sorted(STAC_COLLECTIONS)}"
        )
    return STAC_COLLECTIONS[key]


def _client():
    try:
        from pystac_client import Client
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise ImportError(
            "pystac-client é necessário para acessar o STAC do INPE: "
            "pip install pystac-client"
        ) from exc
    return Client.open(STAC_URL)


def band_assets(cid: str, satellite: str) -> dict:
    """Map ``{'blue','green','red','nir'} -> asset key`` for a collection.

    Resolved from the collection's ``eo:bands`` metadata (``common_name``),
    so the per-satellite band numbering (BAND1-4, BAND13-16, ...) never has
    to be hardcoded. Falls back to a static table if the metadata is
    unavailable.
    """
    if cid in _band_cache:
        return _band_cache[cid]

    mapping: dict = {}
    try:
        import requests

        meta = requests.get(f"{STAC_URL}/collections/{cid}", timeout=60).json()
        bands = (meta.get("properties", {}).get("eo:bands")
                 or meta.get("summaries", {}).get("eo:bands") or [])
        for band in bands:
            if not isinstance(band, dict):
                continue
            common = (band.get("common_name") or "").lower()
            name = band.get("name")
            if common in BAND_ORDER and name:
                mapping[common] = name
    except Exception as exc:  # noqa: BLE001
        warn(f"Metadados de banda de {cid} indisponíveis ({exc}) — usando tabela padrão.")

    if len(mapping) < 4:
        mapping = dict(_FALLBACK_ASSETS.get(satellite.lower(), {}))
    _band_cache[cid] = mapping
    return mapping


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def search_scenes(satellite, level, bbox, d0, d1, max_cloud=None, max_images=None):
    """Search WFI scenes, newest first.

    ``max_cloud`` (percent) filters on ``eo:cloud_cover``. The DN collections
    do not carry that property, so for ``level='dn'`` the cloud values are
    cross-referenced from the matching SR collection (both share the same
    item ids). Returns a list of STAC items.
    """
    _apply_gdal_env()
    cid = collection_id(satellite, level)
    client = _client()

    query = {}
    if max_cloud is not None and float(max_cloud) >= 0:
        query["eo:cloud_cover"] = {"lte": float(max_cloud)}

    search = client.search(
        collections=[cid], bbox=list(bbox),
        datetime=f"{d0.isoformat()}/{d1.isoformat()}",
        query=query or None, max_items=500,
    )
    items = list(search.items())

    # The DN collections carry no eo:cloud_cover, and the server silently
    # ignores a query on a property the items do not have — so filtering DN
    # requires borrowing the cloud values from the SR twin (identical ids).
    if query and items and all(
        i.properties.get("eo:cloud_cover") is None for i in items
    ):
        nuvens = _cloud_from_sr(satellite, bbox, d0, d1)
        if nuvens is None:
            warn("Cobertura de nuvem indisponível para o produto DN — "
                 "filtro de nuvem IGNORADO nesta busca.")
        else:
            antes = len(items)
            mantidos = []
            for item in items:
                valor = nuvens.get(item.id)
                if valor is None:
                    continue
                # propagate the value so callers can report it
                item.properties["eo:cloud_cover"] = valor
                if valor <= float(max_cloud):
                    mantidos.append(item)
            items = mantidos
            log(f"  filtro de nuvem via produto SR: {len(items)} de {antes} cena(s).")

    items.sort(key=lambda i: i.datetime, reverse=True)
    if max_images is not None and len(items) > int(max_images):
        log(f"  max_images={max_images}: limitando de {len(items)} para "
            f"{max_images} cena(s) (mais recentes primeiro).")
        items = items[: int(max_images)]
    return items


def _cloud_from_sr(satellite, bbox, d0, d1):
    """``{item_id: eo:cloud_cover}`` from the SR twin collection, or None.

    DN and SR items share the same ids, so the SR product supplies the cloud
    metadata the DN product lacks.
    """
    try:
        cid = collection_id(satellite, "sr")
        search = _client().search(
            collections=[cid], bbox=list(bbox),
            datetime=f"{d0.isoformat()}/{d1.isoformat()}", max_items=500,
        )
        return {item.id: item.properties.get("eo:cloud_cover")
                for item in search.items()}
    except Exception as exc:  # noqa: BLE001
        warn(f"Cruzamento de nuvem com o produto SR falhou ({exc}).")
        return None


# ---------------------------------------------------------------------------
# Windowed reads
# ---------------------------------------------------------------------------

def read_on_grid(href, crs, transform, shape,
                 resampling=Resampling.average) -> np.ndarray:
    """Read one remote raster straight onto the analysis grid (no download)."""
    _apply_gdal_env()
    dst = np.zeros(shape, dtype=np.float32)
    with rasterio.open(href) as src:
        reproject(
            source=rasterio.band(src, 1), destination=dst,
            src_transform=src.transform, src_crs=src.crs,
            dst_transform=transform, dst_crs=crs,
            src_nodata=src.nodata, dst_nodata=0.0,
            resampling=resampling,
        )
    return dst


def read_window(href, bbox):
    """Read the bbox window of a remote raster at its NATIVE resolution.

    Returns ``(array, profile)`` where the profile is already updated with
    the cropped width/height/transform — ready to be written as a GeoTIFF.
    Returns ``(None, None)`` when the bbox does not intersect the raster.
    """
    from rasterio.windows import Window
    from rasterio.windows import from_bounds as window_from_bounds

    _apply_gdal_env()
    with rasterio.open(href) as src:
        wb = transform_bounds("EPSG:4326", src.crs, *bbox)
        window = window_from_bounds(*wb, transform=src.transform)
        try:
            window = window.intersection(Window(0, 0, src.width, src.height))
        except Exception:  # noqa: BLE001 - disjoint windows raise
            return None, None
        window = window.round_offsets().round_lengths()
        if window.width <= 0 or window.height <= 0:
            return None, None
        arr = src.read(1, window=window)
        profile = src.profile.copy()
        profile.update(width=int(window.width), height=int(window.height),
                       transform=src.window_transform(window))
    return arr, profile


def stream_sr_scene(item, satellite, crs, transform, shape) -> dict | None:
    """Stream one L4-SR scene onto the analysis grid.

    Returns ``{'blue','green','red','nir'}`` as surface reflectance in
    ``[0, ~1]`` plus ``'cmask'`` (or ``None`` when the scene has no usable
    cloud mask), or ``None`` if the scene could not be read.
    """
    cid = collection_id(satellite, "sr")
    assets = band_assets(cid, satellite)
    out: dict = {}
    try:
        for band in BAND_ORDER:
            key = assets.get(band)
            if key not in item.assets:
                warn(f"  {item.id}: banda '{band}' ({key}) ausente — pulando cena.")
                return None
            arr = read_on_grid(item.assets[key].href, crs, transform, shape)
            arr[arr == SR_NODATA] = 0.0
            out[band] = arr / SR_SCALE
        if "CMASK" in item.assets:
            out["cmask"] = read_on_grid(
                item.assets["CMASK"].href, crs, transform, shape,
                resampling=Resampling.nearest,
            )
        else:
            out["cmask"] = None
    except Exception as exc:  # noqa: BLE001
        warn(f"  {item.id}: falha na leitura do SR ({exc}).")
        return None
    return out


def cmask_valid(cmask: np.ndarray) -> np.ndarray:
    """Boolean array of clear observations from a CMASK raster."""
    return np.isclose(cmask, CMASK_CLEAR)
