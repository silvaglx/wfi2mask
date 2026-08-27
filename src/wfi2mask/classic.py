"""Classic INPE catalogue (``cbers4asat``) — search and whole-scene download.

This is the legacy access path, kept alongside the STAC one because INPE has
not designated either catalogue as official and they do **not** return the
same scenes: measured over one bbox (Nov-Dec 2025), the classic catalogue
returned 15/20/40 scenes for CBERS-4A/Amazonia-1/CBERS-4 against 9/12/29 in
the STAC — roughly 50 % more.

Known limitations of this catalogue, compared with the STAC path:

* **Requires an INPE account** — the registered e-mail must be passed as
  ``user=``; downloads fail without it.
* **No windowed reads.** The catalogue serves plain band files, so a scene
  is downloaded in full (~5 min per scene measured) and only then cropped
  to the bbox. The STAC path transfers only the bbox.
* **DN only.** There is no surface-reflectance product, so every scene goes
  through the DN -> TOA conversion and depends on ACC/ESUN.
* **No per-pixel cloud mask** (no CMASK equivalent).
* **Coarse cloud metadata** — ``cloud_cover`` is quantised to multiples of
  10 %, against the float ``eo:cloud_cover`` of the STAC.
* **Different scene ids** for the same acquisition
  (``CBERS4A_WFI20414020251229ETC2`` here vs
  ``CBERS_4A_WFI_20251229_204_140_L4`` in the STAC), so ids are not
  interchangeable between catalogues.
"""

from __future__ import annotations

import os
from datetime import date

from .constants import CLASSIC_COLLECTIONS
from .utils import log, warn


def _api(user):
    """Build the cbers4asat client, with a clear error when unavailable."""
    try:
        from cbers4asat import Cbers4aAPI
    except ImportError as exc:
        raise ImportError(
            "O catálogo INPE_CLASSIC precisa da biblioteca cbers4asat: "
            "pip install cbers4asat"
        ) from exc
    return Cbers4aAPI(user)


def feature_date(feat) -> date | None:
    dt = feat.get("properties", {}).get("datetime", "")
    try:
        return date.fromisoformat(str(dt)[:10])
    except ValueError:
        return None


def search_scenes(satellite, bbox, d0, d1, max_cloud=None, max_images=None,
                  user=None) -> list:
    """Search the classic catalogue. Returns GeoJSON features, newest first.

    ``max_cloud`` is applied server-side by the catalogue itself (values are
    quantised to multiples of 10 %).
    """
    collection = CLASSIC_COLLECTIONS.get(satellite)
    if collection is None:
        raise ValueError(
            f"O catálogo clássico não possui produto para {satellite!r}."
        )
    api = _api(user)
    cloud = int(max_cloud) if max_cloud is not None and float(max_cloud) >= 0 else 100
    fc = api.query(location=list(bbox), initial_date=d0, end_date=d1,
                   cloud=cloud, limit=200, collections=[collection])
    features = fc.get("features", [])
    features.sort(key=lambda f: feature_date(f) or d0, reverse=True)
    if max_images is not None and len(features) > int(max_images):
        log(f"  max_images={max_images}: limitando de {len(features)} para "
            f"{max_images} cena(s) (mais recentes primeiro).")
        features = features[: int(max_images)]
    return features


def download_scene(feature, raw_dir, user) -> str | None:
    """Download one whole scene (4 bands + XML). Returns its folder or None.

    The classic catalogue has no windowed access, so the entire scene is
    transferred before any cropping can happen.
    """
    api = _api(user)
    sid = feature.get("id", "?")
    os.makedirs(raw_dir, exist_ok=True)
    products = {"type": "FeatureCollection", "features": [feature]}
    try:
        api.download(products=products, bands=["blue", "green", "red", "nir"],
                     threads=3, outdir=raw_dir, with_folder=True,
                     with_metadata=True)
    except TypeError:
        # older cbers4asat signatures without threads=
        try:
            api.download(products=products,
                         bands=["blue", "green", "red", "nir"],
                         outdir=raw_dir, with_folder=True, with_metadata=True)
        except Exception as exc:  # noqa: BLE001
            warn(f"  Falha ao baixar {sid}: {exc}")
            return None
    except Exception as exc:  # noqa: BLE001
        warn(f"  Falha ao baixar {sid}: {exc}")
        return None

    scene_dir = os.path.join(raw_dir, sid)
    if os.path.isdir(scene_dir):
        return scene_dir
    # some versions do not name the folder exactly after the scene id
    candidatos = [os.path.join(raw_dir, d) for d in os.listdir(raw_dir)
                  if sid in d and os.path.isdir(os.path.join(raw_dir, d))]
    if candidatos:
        return candidatos[0]
    warn(f"  Pasta da cena {sid} não encontrada após o download.")
    return None


def analyze_bbox_coverage(features, bbox) -> None:
    """Warn when no single scene covers the bbox (orbit-boundary case)."""
    try:
        from shapely.geometry import box as shp_box, shape as shp_shape
        from shapely.ops import unary_union
    except ImportError:
        return
    roi = shp_box(*bbox)
    geoms, full = [], []
    for feat in features:
        geom = feat.get("geometry")
        if not geom:
            continue
        g = shp_shape(geom)
        geoms.append(g)
        if g.contains(roi):
            full.append(feat)
    if not geoms:
        return
    if full:
        log(f"  Cobertura do bbox: {len(full)} de {len(features)} cena(s) "
            f"cobrem o bbox por completo.")
    elif unary_union(geoms).contains(roi):
        warn("  Nenhuma cena individual cobre o bbox por completo: o bbox cai "
             "na divisa entre órbitas. Várias cenas serão usadas.")
    else:
        warn("  As cenas encontradas NÃO cobrem todo o bbox nem em conjunto.")
