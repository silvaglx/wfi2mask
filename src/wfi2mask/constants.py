"""Constants: sensor calibration, collections, band mappings and HAND hosting.

All calibration values come from the CIPC water-mask project validation
(RadCalNet-validated ESUN and ACC where available). See PROJECT docs.
"""

# ---------------------------------------------------------------------------
# Satellites / INPE catalog collections
# ---------------------------------------------------------------------------

# Friendly name -> INPE collection id (cbers4asat)
COLLECTIONS = {
    "cbers4": "CBERS4_AWFI_L4_DN",
    "cbers4a": "CBERS4A_WFI_L4_DN",
    "amazonia1": "AMAZONIA1_WFI_L4_DN",
}

# Reverse lookup and scene-id prefixes
SCENE_PREFIXES = {
    "CBERS4_AWFI": "cbers4",
    "CBERS_4_AWFI": "cbers4",
    "CBERS4A_WFI": "cbers4a",
    "CBERS_4A_WFI": "cbers4a",
    "AMAZONIA1_WFI": "amazonia1",
    "AMAZONIA_1_WFI": "amazonia1",
}


def satellite_from_scene_id(scene_id: str):
    """Infer satellite key ('cbers4' | 'cbers4a' | 'amazonia1') from a scene id."""
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
# ---------------------------------------------------------------------------

ESUN = {
    # from supervisor notebook, unvalidated
    "cbers4": {"blue": 1952.0, "green": 1852.0, "red": 1545.0, "nir": 1098.0},
    # validated via RadCalNet
    "cbers4a": {"blue": 1827.58, "green": 1647.70, "red": 1400.0, "nir": 971.53},
    # validated via RadCalNet
    "amazonia1": {"blue": 1930.0, "green": 1870.0, "red": 1550.0, "nir": 1050.0},
}

# Validated ACC overrides. Satellites absent here (cbers4) fall back to the
# per-scene XML metadata.
ACC_OVERRIDE = {
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
# WFI TOA is raw reflectance in [0, ~1]; the Sentinel-2 equivalent was
# NIR < 1000 on the x10000 L2A scale, i.e. 0.10. For WFI TOA the validated
# working threshold is 0.35 (TOA is brighter than surface reflectance).
DEFAULT_NIR_MAX = 0.35
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
# Upload the individual tiles as assets of a GitHub Release and set the
# base URL below (see docs/hand.md). It can also be overridden with the
# environment variable WFI2MASK_HAND_URL.
HAND_RELEASE_BASE_URL = (
    "https://github.com/SEU_USUARIO/wfi2mask/releases/download/hand-v1"
)

# Sentinel-2 STAC endpoint used for the cloud-cover matchup
S2_STAC_URL = "https://earth-search.aws.element84.com/v1"
S2_COLLECTION = "sentinel-2-l2a"
S2_MATCHUP_TOLERANCE_DAYS = 1
