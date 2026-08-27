"""DN -> TOA reflectance conversion for WFI scenes.

Equation:  rho_TOA = (pi * ACC * DN) / (ESUN * cos(theta_sun))

* ACC   : Absolute Calibration Coefficient — validated override per satellite
          when available (constants.ACC_OVERRIDE), otherwise parsed from the
          scene XML metadata.
* ESUN  : exoatmospheric solar irradiance per band (constants.ESUN).
* theta : solar zenith = 90 deg - sun elevation (from the scene XML).

Known limitation: the Earth–Sun distance correction (d^2) is not applied,
introducing a seasonal error of +/- 3.3 %.
"""

from __future__ import annotations

import glob
import os
import xml.etree.ElementTree as ET
from math import cos, pi, radians

import numpy as np
import rasterio
from rasterio.windows import Window
from rasterio.windows import from_bounds as window_from_bounds

from .constants import ACC_OVERRIDE, BAND_NUMBERS, ESUN, satellite_from_scene_id
from .utils import log, warn

BAND_ORDER = ["blue", "green", "red", "nir"]


def resolve_calibration(param, satellite: str) -> dict | None:
    """Normalize a user-supplied ESUN/ACC override into ``{band: value}``.

    Accepts ``{"blue": v, "green": v, "red": v, "nir": v}`` (applied as-is)
    or ``{satellite: {band: value}}`` (per-satellite dict). Returns ``None``
    when the override does not apply to ``satellite``.
    """
    if param is None:
        return None
    if satellite in param and isinstance(param[satellite], dict):
        return {b: float(param[satellite][b]) for b in BAND_ORDER}
    if all(b in param for b in BAND_ORDER):
        return {b: float(param[b]) for b in BAND_ORDER}
    if any(k in BAND_NUMBERS for k in param):
        # per-satellite dict that simply doesn't cover this satellite
        return None
    raise ValueError(
        "Override de calibração inválido: use {'blue':v,'green':v,'red':v,'nir':v} "
        "ou {'<satelite>': {...}} — recebido: " + repr(param)
    )


# ---------------------------------------------------------------------------
# XML metadata parsing (robust: searches by tag-name keyword, structure
# varies between CBERS-4 / CBERS-4A / Amazonia-1)
# ---------------------------------------------------------------------------

def _find_in_xml(root, keyword):
    for elem in root.iter():
        if keyword.lower() in elem.tag.lower():
            return elem
    return None


def get_acc_from_xml(xml_path: str) -> dict:
    """Extract Absolute Calibration Coefficients from a scene XML file."""
    if not xml_path or not os.path.exists(xml_path):
        warn("XML não encontrado — usando ACC=1.0 (reflectância NÃO calibrada).")
        return {b: 1.0 for b in BAND_ORDER}
    return acc_from_root(ET.parse(xml_path).getroot())


def get_sun_zenith_from_xml(xml_path: str) -> float:
    """Solar zenith angle in degrees (90 - sun elevation) from a scene XML file."""
    if not xml_path or not os.path.exists(xml_path):
        warn("XML não encontrado — usando zênite solar = 45°.")
        return 45.0
    return sun_zenith_from_root(ET.parse(xml_path).getroot())


def acc_from_xml_text(text: str) -> dict:
    """ACC coefficients from XML content held in memory (STAC assets)."""
    try:
        return acc_from_root(ET.fromstring(text))
    except ET.ParseError as exc:
        warn(f"XML de calibração ilegível ({exc}) — usando ACC=1.0.")
        return {b: 1.0 for b in BAND_ORDER}


def sun_zenith_from_xml_text(text: str) -> float:
    """Solar zenith from XML content held in memory (STAC assets)."""
    try:
        return sun_zenith_from_root(ET.fromstring(text))
    except ET.ParseError as exc:
        warn(f"XML de geometria ilegível ({exc}) — usando zênite = 45°.")
        return 45.0


def acc_from_root(root) -> dict:
    """Extract Absolute Calibration Coefficients from a parsed XML tree."""
    fallback = {b: 1.0 for b in BAND_ORDER}
    acc_node = _find_in_xml(root, "absoluteCalibration") or _find_in_xml(
        root, "calibrationCoefficient"
    )
    if acc_node is None:
        warn("Tag de calibração ausente no XML — usando ACC=1.0.")
        return fallback

    children = list(acc_node)
    if len(children) >= 4:
        return {
            "blue": float(children[0].text),
            "green": float(children[1].text),
            "red": float(children[2].text),
            "nir": float(children[3].text),
        }
    if children:
        val = float(children[0].text)
        return {b: val for b in BAND_ORDER}
    try:
        val = float(acc_node.text)
        return {b: val for b in BAND_ORDER}
    except (TypeError, ValueError):
        warn("Não foi possível interpretar o ACC do XML — usando 1.0.")
        return fallback


def sun_zenith_from_root(root) -> float:
    """Solar zenith angle in degrees (90 - sun elevation) from a parsed tree."""
    for keyword in (
        "sunPosition", "sun_position", "sunElevation", "sun_elevation",
        "solarElevation", "solar_elevation", "elevacao", "elevation",
    ):
        node = _find_in_xml(root, keyword)
        if node is None:
            continue
        candidates = list(node) or [node]
        for cand in candidates:
            try:
                elevation = float(cand.text)
                if 0.0 < elevation < 90.0:
                    return 90.0 - elevation
            except (TypeError, ValueError):
                continue

    for elem in root.iter():
        if "elev" in elem.tag.lower() and elem.text:
            try:
                val = float(elem.text)
                if 0.0 < val < 90.0:
                    return 90.0 - val
            except ValueError:
                continue

    warn("Elevação solar ausente no XML — usando zênite = 45°.")
    return 45.0


# ---------------------------------------------------------------------------
# DN -> TOA on arrays (shared by the local-file and STAC paths)
# ---------------------------------------------------------------------------

def toa_from_dn(dn_by_band: dict, acc: dict, esun: dict, zenith: float) -> dict:
    """Convert DN arrays to TOA reflectance.

    ``rho = (pi * ACC * DN) / (ESUN * cos(theta_sun))``. DN <= 0 (nodata
    border) is preserved as 0. Returns a dict with the same band keys.
    """
    cos_zenith = cos(radians(zenith))
    out = {}
    for band, dn in dn_by_band.items():
        dn = np.asarray(dn, dtype=np.float32)
        rho = (pi * dn * acc[band]) / (esun[band] * cos_zenith)
        rho[dn <= 0] = 0.0
        out[band] = rho.astype(np.float32)
    return out


def resolve_acc(satellite: str, acc_override, xml_text: str | None,
                xml_path: str | None = None) -> dict:
    """ACC for a scene: user override > ACC_OVERRIDE table > scene XML.

    ``ACC_OVERRIDE`` ships EMPTY, so by default the coefficients always come
    from the scene's own ``<absoluteCalibrationCoefficient>`` metadata — the
    authoritative source published with the product.
    """
    resolved = resolve_calibration(acc_override, satellite)
    if resolved is not None:
        return resolved
    if satellite in ACC_OVERRIDE:
        return dict(ACC_OVERRIDE[satellite])
    if xml_text is not None:
        return acc_from_xml_text(xml_text)
    return get_acc_from_xml(xml_path or "")


# ---------------------------------------------------------------------------
# Band file identification
# ---------------------------------------------------------------------------

def identify_band_files(scene_dir: str, satellite: str | None) -> dict:
    """Map blue/green/red/nir -> tif path inside a downloaded scene folder.

    Matches by spectral band number (per satellite) and by band-name suffix
    (files downloaded by cbers4asat may carry either convention).
    """
    tifs = sorted(glob.glob(os.path.join(scene_dir, "*.tif")))
    band_files: dict = {}

    numbers = BAND_NUMBERS.get(satellite) if satellite else None

    for tif in tifs:
        fname = os.path.basename(tif).upper()
        matched = None
        # 1) by explicit color name
        for color in BAND_ORDER:
            if f"_{color.upper()}" in fname or f"{color.upper()}." in fname:
                matched = color
                break
        # 2) by satellite-specific band number (e.g. BAND13. for CBERS-4 blue)
        if matched is None and numbers:
            for color, num in numbers.items():
                if f"BAND{num}." in fname or fname.endswith(f"BAND{num}.TIF"):
                    matched = color
                    break
        # 3) by any known band number across satellites (fallback)
        if matched is None:
            for sat_numbers in BAND_NUMBERS.values():
                for color, num in sat_numbers.items():
                    if f"BAND{num}." in fname:
                        matched = color
                        break
                if matched:
                    break
        if matched and matched not in band_files:
            band_files[matched] = tif

    return band_files


# ---------------------------------------------------------------------------
# Scene conversion
# ---------------------------------------------------------------------------

def _bbox_window(src, bbox):
    """Reading window of ``src`` covering ``bbox`` (EPSG:4326), or None.

    Returns (window, transform) clipped to the raster extent; ``None`` when
    the bbox does not intersect the scene at all.
    """
    from rasterio.warp import transform_bounds

    wb = transform_bounds("EPSG:4326", src.crs, *bbox)
    window = window_from_bounds(*wb, transform=src.transform)
    try:
        window = window.intersection(Window(0, 0, src.width, src.height))
    except Exception:  # rasterio raises when the windows are disjoint
        return None
    window = window.round_offsets().round_lengths()
    if window.width <= 0 or window.height <= 0:
        return None
    return window, src.window_transform(window)


def convert_scene_to_toa(
    scene_dir: str,
    out_path: str,
    satellite: str | None = None,
    bbox=None,
    esun=None,
    acc=None,
) -> dict | None:
    """Convert one downloaded scene folder to a 4-band TOA GeoTIFF.

    Output band order: 1=Blue, 2=Green, 3=Red, 4=NIR (float32 reflectance).
    Returns a small metadata dict, or None if the scene was skipped.

    Parameters
    ----------
    bbox : list, optional
        ``[lon_min, lat_min, lon_max, lat_max]`` (EPSG:4326). When given, the
        TOA output is CROPPED to this bbox (scenes without overlap are
        skipped). Without it, the full scene is converted.
    esun, acc : dict, optional
        Calibration overrides: ``{band: value}`` or ``{satellite: {band:
        value}}``. Defaults come from :mod:`wfi2mask.constants` (``ESUN`` and
        ``ACC_OVERRIDE``; for CBERS-4, ACC is read from the scene XML).
    """
    scene_name = os.path.basename(os.path.normpath(scene_dir))
    if satellite is None:
        satellite = satellite_from_scene_id(scene_name)
    if satellite is None:
        warn(f"{scene_name}: satélite não identificado pelo nome da cena — pulando.")
        return None

    band_files = identify_band_files(scene_dir, satellite)
    if len(band_files) < 4:
        warn(
            f"{scene_name}: apenas {len(band_files)}/4 bandas identificadas — pulando. "
            f"Arquivos: {[os.path.basename(t) for t in glob.glob(os.path.join(scene_dir, '*.tif'))]}"
        )
        return None

    xmls = sorted(glob.glob(os.path.join(scene_dir, "*.xml")))
    xml_path = xmls[0] if xmls else ""

    # ACC: user override > validated override > XML fallback (e.g. CBERS-4)
    acc = resolve_calibration(acc, satellite)
    if acc is None:
        if satellite in ACC_OVERRIDE:
            acc = dict(ACC_OVERRIDE[satellite])
        else:
            acc = get_acc_from_xml(xml_path)

    zenith = get_sun_zenith_from_xml(xml_path)
    cos_zenith = cos(radians(zenith))
    # ESUN: user override > package default
    esun = resolve_calibration(esun, satellite) or ESUN[satellite]

    bands_toa = {}
    profile = None
    window = None
    win_transform = None
    for band_name in BAND_ORDER:
        with rasterio.open(band_files[band_name]) as src:
            if profile is None:
                profile = src.profile.copy()
                if bbox is not None:
                    clipped = _bbox_window(src, bbox)
                    if clipped is None:
                        warn(f"{scene_name}: sem sobreposição com o bbox — pulando.")
                        return None
                    window, win_transform = clipped
            dn = src.read(1, window=window).astype(np.float32)
        radiance = dn * acc[band_name]
        toa = (pi * radiance) / (esun[band_name] * cos_zenith)
        # keep DN==0 (nodata border) as 0
        toa[dn <= 0] = 0.0
        bands_toa[band_name] = toa

    out_profile = profile.copy()
    out_profile.update(dtype="float32", count=4, compress="lzw", nodata=0.0)
    if window is not None:
        out_profile.update(
            width=int(window.width), height=int(window.height),
            transform=win_transform,
        )
        log(f"  Recorte no bbox: {int(window.width)} x {int(window.height)} px.")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with rasterio.open(out_path, "w", **out_profile) as dst:
        for i, band_name in enumerate(BAND_ORDER, start=1):
            dst.write(bands_toa[band_name], i)
        tags = dict(
            SATELLITE=satellite,
            SCENE_ID=scene_name,
            SUN_ZENITH_DEG=f"{zenith:.4f}",
            BAND_ORDER="blue,green,red,nir",
            PROCESSING="wfi2mask TOA (pi*ACC*DN)/(ESUN*cos(zenith))",
        )
        if bbox is not None:
            tags["BBOX"] = ",".join(f"{v:.6f}" for v in bbox)
        dst.update_tags(**tags)

    log(f"  TOA salvo: {out_path} (zênite={zenith:.1f}°)")
    return {"scene": scene_name, "satellite": satellite, "path": out_path,
            "zenith": zenith, "acc": acc}
