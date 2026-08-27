"""Constants: sensor calibration, collections, band mappings and HAND hosting.

All calibration values come from the CIPC water-mask project validation
(RadCalNet-validated ESUN and ACC where available). See PROJECT docs.
"""

# ---------------------------------------------------------------------------
# Satellites / INPE catalog collections
# ---------------------------------------------------------------------------

# Friendly name -> legacy INPE catalog collection id (cbers4asat)
COLLECTIONS = {
    "cbers4": "CBERS4_AWFI_L4_DN",
    "cbers4a": "CBERS4A_WFI_L4_DN",
    "amazonia1": "AMAZONIA1_WFI_L4_DN",
}

# ---------------------------------------------------------------------------
# INPE STAC (data.inpe.br) — no authentication required
#
# Two processing levels per WFI sensor:
#   'sr' : Level-4 Surface Reflectance, Cloud Optimized GeoTIFF, with a
#          per-pixel cloud mask (CMASK). Scaled by SR_SCALE, nodata SR_NODATA.
#   'dn' : Level-4 Digital Number + per-band XML metadata (calibration
#          coefficients and sun elevation) — the input of the TOA conversion.
# ---------------------------------------------------------------------------

STAC_URL = "https://data.inpe.br/bdc/stac/v1"

# ---------------------------------------------------------------------------
# Catalogues
#
# INPE publishes its WFI archive through two independent catalogues, and the
# institute has not designated either as the official one. They do NOT return
# the same scene set (measured over one bbox, Nov-Dec 2025: the classic
# catalogue returned 15/20/40 scenes for CBERS-4A/Amazonia-1/CBERS-4 against
# 9/12/29 in the STAC), so the choice is a scientific one, not cosmetic.
# ---------------------------------------------------------------------------

CATALOG_STAC = "INPE_STAC"
CATALOG_CLASSIC = "INPE_CLASSIC"
DEFAULT_CATALOG = CATALOG_STAC

CATALOGS = {
    CATALOG_STAC: {
        "label": "INPE STAC (data.inpe.br)",
        "auth": False,
        "levels": ("sr", "dn"),
        "windowed": True,
        "cloud": "eo:cloud_cover (float; ausente no DN, cruzado do SR)",
        "notes": "Mais recente, ainda não oficial. Leitura por janela (COG no "
                 "SR), máscara de nuvem por pixel (CMASK), sem cadastro.",
    },
    CATALOG_CLASSIC: {
        "label": "Catálogo clássico do INPE (via cbers4asat)",
        "auth": True,
        "levels": ("dn",),
        "windowed": False,
        "cloud": "cloud_cover (quantizado em múltiplos de 10 %)",
        "notes": "Mais antigo e mais completo em número de cenas. Exige "
                 "cadastro (user=), baixa a CENA INTEIRA (sem leitura por "
                 "janela), só oferece DN e não tem máscara de nuvem por pixel.",
    },
}

# ---------------------------------------------------------------------------
# Product registry — the catalogue the package can process.
#
# Users address products by their FULL collection name (the id published in
# the STAC), which already encodes sensor and processing level, so there is
# no separate 'satellite' + 'level' pair to keep in sync. Listed by
# wfi2mask.get_products().
#
# Fields: satellite, level ('sr' | 'dn'), source, resolution (m), platform
# label and a one-line description.
# ---------------------------------------------------------------------------

_SR_DESC = "Reflectância de superfície (L4-SR), COG + máscara de nuvem CMASK."
_DN_DESC = "Números digitais (L4-DN) + XML de calibração; convertido para TOA."
_CLASSIC_DESC = ("Números digitais do catálogo clássico; cena inteira baixada "
                 "e convertida para TOA. Exige cadastro no INPE.")

PRODUCTS = {
    # ---------------- INPE STAC ----------------
    "AMZ1-WFI-L4-SR-1": {
        "satellite": "amazonia1", "level": "sr", "gsd": 64,
        "platform": "Amazonia-1 / WFI", "desc": _SR_DESC,
        "catalog": CATALOG_STAC, "source": "inpe",
    },
    "AMZ1-WFI-L4-DN-1": {
        "satellite": "amazonia1", "level": "dn", "gsd": 64,
        "platform": "Amazonia-1 / WFI", "desc": _DN_DESC,
        "catalog": CATALOG_STAC, "source": "inpe",
    },
    "CB4A-WFI-L4-SR-1": {
        "satellite": "cbers4a", "level": "sr", "gsd": 55,
        "platform": "CBERS-4A / WFI", "desc": _SR_DESC,
        "catalog": CATALOG_STAC, "source": "inpe",
    },
    "CB4A-WFI-L4-DN-1": {
        "satellite": "cbers4a", "level": "dn", "gsd": 55,
        "platform": "CBERS-4A / WFI", "desc": _DN_DESC,
        "catalog": CATALOG_STAC, "source": "inpe",
    },
    "CB4-WFI-L4-SR-1": {
        "satellite": "cbers4", "level": "sr", "gsd": 64,
        "platform": "CBERS-4 / AWFI", "desc": _SR_DESC,
        "catalog": CATALOG_STAC, "source": "inpe",
    },
    "CB4-WFI-L4-DN-1": {
        "satellite": "cbers4", "level": "dn", "gsd": 64,
        "platform": "CBERS-4 / AWFI", "desc": _DN_DESC,
        "catalog": CATALOG_STAC, "source": "inpe",
    },
    # -------------- INPE clássico --------------
    "AMAZONIA1_WFI_L4_DN": {
        "satellite": "amazonia1", "level": "dn", "gsd": 64,
        "platform": "Amazonia-1 / WFI", "desc": _CLASSIC_DESC,
        "catalog": CATALOG_CLASSIC, "source": "inpe",
    },
    "CBERS4A_WFI_L4_DN": {
        "satellite": "cbers4a", "level": "dn", "gsd": 55,
        "platform": "CBERS-4A / WFI", "desc": _CLASSIC_DESC,
        "catalog": CATALOG_CLASSIC, "source": "inpe",
    },
    "CBERS4_AWFI_L4_DN": {
        "satellite": "cbers4", "level": "dn", "gsd": 64,
        "platform": "CBERS-4 / AWFI", "desc": _CLASSIC_DESC,
        "catalog": CATALOG_CLASSIC, "source": "inpe",
    },
    # ---- Sentinel-2 (AWS, disponível nos dois modos) ----
    "sentinel-2-l2a": {
        "satellite": "sentinel2", "level": "sr", "gsd": 10,
        "platform": "Sentinel-2 / MSI",
        "desc": "Reflectância de superfície L2A + máscara SCL (AWS Open Data). "
                "Somente por streaming em get_water_mask.",
        "catalog": None, "source": "aws",   # catalog=None => vale para ambos
    },
}

#: STAC-only view of the registry (kept for internal use)
STAC_PRODUCTS = {cid: meta for cid, meta in PRODUCTS.items()
                 if meta["catalog"] in (CATALOG_STAC, None)}

# (satellite, level) -> STAC collection id
STAC_COLLECTIONS = {
    (meta["satellite"], meta["level"]): cid
    for cid, meta in PRODUCTS.items()
    if meta["catalog"] == CATALOG_STAC
}

# satellite -> classic catalogue collection id
CLASSIC_COLLECTIONS = {
    meta["satellite"]: cid
    for cid, meta in PRODUCTS.items()
    if meta["catalog"] == CATALOG_CLASSIC
}

# Surface-reflectance scaling declared in the STAC band metadata
# (scale 0.0001 => integers 0..10000 map to reflectance [0, 1]) — the same
# convention as Sentinel-2 L2A, so SR products of every sensor share one scale.
SR_SCALE = 10000.0
SR_NODATA = -9999.0

# CMASK (WFI cloud mask). The collection metadata declares 0..4 with nodata
# 255, but the delivered rasters use 127 for clear observations and 255 for
# cloud/no-data. Treated as: clear == CMASK_CLEAR, everything else rejected.
# NOTE: undocumented upstream — validate before relying on it.
CMASK_CLEAR = 127

# Earliest surface-reflectance coverage per sensor (STAC temporal extent).
# Before these dates only the DN product (and therefore TOA) is available.
SR_COVERAGE_START = {
    "amazonia1": "2024-01-01",
    "cbers4a": "2020-01-01",
    "cbers4": "2016-01-01",
}

# Reverse lookup and scene-id prefixes
SCENE_PREFIXES = {
    "CBERS4_AWFI": "cbers4",
    "CBERS_4_AWFI": "cbers4",
    "CBERS4A_WFI": "cbers4a",
    "CBERS_4A_WFI": "cbers4a",
    "AMAZONIA1_WFI": "amazonia1",
    "AMAZONIA_1_WFI": "amazonia1",
    # Sentinel-2 (cenas locais nomeadas pelo padrao ESA ou "S2_<data>")
    "S2A": "sentinel2",
    "S2B": "sentinel2",
    "S2C": "sentinel2",
    "S2_": "sentinel2",
    "SENTINEL2": "sentinel2",
    "SENTINEL_2": "sentinel2",
    "SENTINEL-2": "sentinel2",
}


def satellite_from_scene_id(scene_id: str):
    """Infer satellite key ('cbers4' | 'cbers4a' | 'amazonia1' | 'sentinel2')
    from a scene id."""
    sid = scene_id.upper()
    for prefix, sat in SCENE_PREFIXES.items():
        if sid.startswith(prefix):
            return sat
    return None


# ---------------------------------------------------------------------------
# Sensor spectral band numbering (used to identify band files on disk)
#   CBERS-4  AWFI: B13(Blue) B14(Green) B15(Red) B16(NIR)  @ 64 m
#   CBERS-4A WFI : B5(Blue)  B6(Green)  B7(Red)  B8(NIR)   @ 55 m
#   Amazonia-1 WFI: B1(Blue) B2(Green)  B3(Red)  B4(NIR)   @ 64 m
# ---------------------------------------------------------------------------

BAND_NUMBERS = {
    "cbers4": {"blue": 13, "green": 14, "red": 15, "nir": 16},
    "cbers4a": {"blue": 5, "green": 6, "red": 7, "nir": 8},
    "amazonia1": {"blue": 1, "green": 2, "red": 3, "nir": 4},
}

NATIVE_RESOLUTION = {"cbers4": 64.0, "cbers4a": 55.0, "amazonia1": 64.0}

# ---------------------------------------------------------------------------
# TOA calibration (rho = pi * ACC * DN / (ESUN * cos(theta_sun)))
#
# ESUN and ACC_OVERRIDE below are the package DEFAULTS. They can be
# customized without editing this file:
#   * per call:   w2m.get_toa(..., esun={...}, acc={...})
#   * globally:   w2m.constants.ESUN["cbers4a"]["nir"] = 975.0  (before get_toa)
# ---------------------------------------------------------------------------

# Exoatmospheric solar irradiance per band. NOTE: unlike the ACC, ESUN is NOT
# published in the scene XML (which carries only absoluteCalibrationCoefficient,
# sunPosition/elevation, sunAzimuth and sunIncidenceAngle), so it has to come
# from a table. These are provisional reference values — treat them as
# unvalidated and override with esun={...} in get_toa when better figures
# become available.
ESUN = {
    "cbers4": {"blue": 1952.0, "green": 1852.0, "red": 1545.0, "nir": 1098.0},
    "cbers4a": {"blue": 1827.58, "green": 1647.70, "red": 1400.0, "nir": 971.53},
    "amazonia1": {"blue": 1930.0, "green": 1870.0, "red": 1550.0, "nir": 1050.0},
}

# ACC overrides. EMPTY BY DESIGN: the absolute calibration coefficients are
# read from each scene's own XML metadata (<absoluteCalibrationCoefficient>),
# which is the authoritative source published with the product.
#
# The externally derived coefficients previously applied here are parked in
# ACC_REFERENCE below — they are NOT used. The CBERS-4A set in particular is
# ~3.5x larger than the values the scene XML publishes (0.245/0.287/0.264/
# 0.211 for a 2025 scene) and produced TOA reflectance above 1.0.
#
# To apply a revised calibration when better values become available, either
# pass acc={...} to get_toa or populate this table at runtime:
#     wfi2mask.constants.ACC_OVERRIDE["cbers4a"] = {...}
ACC_OVERRIDE: dict = {}

# Parked for future recalibration — never applied automatically.
ACC_REFERENCE = {
    "cbers4a": {"blue": 0.947982, "green": 0.965583, "red": 0.946315, "nir": 0.739644},
    "amazonia1": {"blue": 0.240, "green": 0.310, "red": 0.214, "nir": 0.185},
}

# ---------------------------------------------------------------------------
# Algorithm defaults (validated on Sentinel-2, transferred to WFI)
# ---------------------------------------------------------------------------

DEFAULT_HUE_MIN = 16.0
DEFAULT_HUE_MAX = 35.0
DEFAULT_NDWI_THRESHOLD = 0.0
DEFAULT_HAND_MAX = 15.0
# NIR brightness rejection is DISABLED by default (nir=None in
# get_water_mask): the thresholds below are reference values only, kept for
# anyone who wants to switch the filter on explicitly, e.g.
#     get_water_mask(..., nir={"cbers4": 0.35, "amazonia1": 0.35})
#   * 'toa' — top-of-atmosphere reflectance in [0, ~1], brighter than surface
#     reflectance, so a looser threshold (0.35).
#   * 'sr'  — surface reflectance (WFI L4-SR and Sentinel-2 L2A, same 1/10000
#     scale). Validated on Sentinel-2 as NIR < 1000 on the x10000 scale.
#     Does NOT transfer cleanly to WFI SR: the eligible-area NIR minimum
#     varies with orbit/view angle, so recalibration per sensor is needed.
DEFAULT_NIR_MAX_BY_LEVEL = {"toa": 0.35, "sr": 0.10}
DEFAULT_NIR_MAX = DEFAULT_NIR_MAX_BY_LEVEL["toa"]
DEFAULT_NIR_MAX_S2 = DEFAULT_NIR_MAX_BY_LEVEL["sr"]
DEFAULT_COARSE = 100.0  # metres; matches MERIT-Hydro HAND (~90 m)

# Namikawa et al. (2016) confidence classes (degrees of Hue)
#   code 1 = WATER   : [16, 35)          (highest confidence)
#   code 2 = WATER95 : [35, 36) U [324, 360) U [0, 16)
#   code 3 = WATER90 : [36, 37) U [308, 324)
#   code 4 = WATER80 : [37, 160)         (lowest confidence)
CONFIDENCE_LABELS = {1: "WATER", 2: "WATER95", 3: "WATER90", 4: "WATER80"}

# ---------------------------------------------------------------------------
# HAND (MERIT Hydro) on-demand hosting
# ---------------------------------------------------------------------------

# 5x5-degree tiles named by their lower-left corner, e.g. "s25w050_hnd.tif".
# The tiles are hosted as assets of the GitHub Release 'hand-v1' and are
# downloaded on demand (no manual setup needed). The base URL can be
# overridden with the environment variable WFI2MASK_HAND_URL.
HAND_RELEASE_BASE_URL = (
    "https://github.com/silvaglx/wfi2mask/releases/download/hand-v1"
)

# ---------------------------------------------------------------------------
# Sentinel-2 (Earth Search STAC on AWS)
# Used by get_water_mask(include_s2=True) — L2A scenes streamed directly
# from the cloud, no download — and by the EXPERIMENTAL date-level cloud
# matchup of get_toa (s2_matchup=True).
# ---------------------------------------------------------------------------
S2_STAC_URL = "https://earth-search.aws.element84.com/v1"
S2_COLLECTION = "sentinel-2-l2a"
S2_MATCHUP_TOLERANCE_DAYS = 1
# Sentinel-2 L2A reflectance comes multiplied by 10000; the streaming
# divides by this factor so everything is in the same [0, ~1] scale.
S2_SCALE = 10000.0
# SCL (Scene Classification Layer) codes treated as invalid observations:
# 0 = no data, 8 = cloud medium prob., 9 = cloud high prob., 10 = cirrus
S2_SCL_INVALID = (0, 8, 9, 10)
