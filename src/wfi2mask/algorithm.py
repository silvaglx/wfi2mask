"""Core water-detection algorithm.

Namikawa et al. (2016) R2G3B5 Hue classification enhanced with NDWI,
HAND and NIR-brightness filters.

Per-pixel rule (binary):
    Water = (Hue_in_range OR NDWI > thr) AND (HAND <= max) AND (NIR < max) AND valid

Confidence classes (Namikawa et al., 2016), assigned by Hue:
    1 = WATER   : [hue_min, hue_max)                       (highest confidence)
    2 = WATER95 : [hue_max, hue_max+1) U [324, 360) U [0, hue_min)
    3 = WATER90 : [hue_max+1, hue_max+2) U [308, 324)
    4 = WATER80 : [hue_max+2, 160)                         (lowest confidence)

Pixels recovered only by NDWI (dark water whose Hue is unstable) receive
class 1 — NDWI > 0 is a physically strong water signal.
"""

from __future__ import annotations

import numpy as np

from .constants import (
    DEFAULT_HAND_MAX,
    DEFAULT_HUE_MAX,
    DEFAULT_HUE_MIN,
    DEFAULT_NDWI_THRESHOLD,
    DEFAULT_NIR_MAX,
)


def norm_scene(band_2d: np.ndarray) -> np.ndarray:
    """Per-scene, per-band normalization by the 99th percentile -> [0, 1]."""
    valid = band_2d[band_2d > 0]
    if valid.size == 0:
        return np.zeros_like(band_2d, dtype=np.float64)
    p99 = np.percentile(valid, 99)
    return np.clip(band_2d.astype(np.float64) / max(p99, 1e-6), 0, 1)


def rgb_to_hsv_hue(r: np.ndarray, g: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Vectorized HSV Hue (Foley et al., 1996), degrees in [0, 360).

    R2G3B5 composition: r=Green_norm, g=Red_norm, b=NIR_norm.
    ("B5" refers to the B channel of HSV fed with the NIR band, not to
    spectral band 5.)
    """
    cmax = np.maximum(np.maximum(r, g), b)
    cmin = np.minimum(np.minimum(r, g), b)
    delta = cmax - cmin
    h = np.zeros_like(r, dtype=np.float64)
    m_r = (cmax == r) & (delta > 0)
    h[m_r] = 60.0 * (((g[m_r] - b[m_r]) / delta[m_r]) % 6.0)
    m_g = (cmax == g) & (delta > 0) & ~m_r
    h[m_g] = 60.0 * (((b[m_g] - r[m_g]) / delta[m_g]) + 2.0)
    m_b = (cmax == b) & (delta > 0) & ~m_r & ~m_g
    h[m_b] = 60.0 * (((r[m_b] - g[m_b]) / delta[m_b]) + 4.0)
    return h % 360.0


def classify_scene(
    green: np.ndarray,
    red: np.ndarray,
    nir: np.ndarray,
    hand: np.ndarray | None = None,
    hue_min: float = DEFAULT_HUE_MIN,
    hue_max: float = DEFAULT_HUE_MAX,
    ndwi_threshold: float = DEFAULT_NDWI_THRESHOLD,
    hand_max: float = DEFAULT_HAND_MAX,
    nir_max: float = DEFAULT_NIR_MAX,
) -> dict:
    """Classify one scene. Bands are raw TOA reflectance arrays (same grid).

    Returns dict with:
      * ``confidence`` : uint8 array, 0 = non-water, 1..4 = Namikawa classes
      * ``water``      : bool array (confidence == 1..4 after filters)
      * ``valid``      : bool array of valid observations
      * ``hue``, ``ndwi`` : diagnostic arrays
    """
    green = np.asarray(green, dtype=np.float64)
    red = np.asarray(red, dtype=np.float64)
    nir = np.asarray(nir, dtype=np.float64)

    valid = (green > 0) & (red > 0) & (nir > 0)

    # --- Namikawa Hue (R2G3B5) ------------------------------------------
    g_n, r_n, n_n = norm_scene(green), norm_scene(red), norm_scene(nir)
    hue = rgb_to_hsv_hue(g_n, r_n, n_n)

    confidence = np.zeros(green.shape, dtype=np.uint8)
    # Assign lowest confidence first so higher classes overwrite.
    c4 = (hue >= hue_max + 2.0) & (hue < 160.0)
    c3 = ((hue >= hue_max + 1.0) & (hue < hue_max + 2.0)) | ((hue >= 308.0) & (hue < 324.0))
    c2 = ((hue >= hue_max) & (hue < hue_max + 1.0)) | (hue >= 324.0) | (hue < hue_min)
    c1 = (hue >= hue_min) & (hue < hue_max)
    confidence[c4] = 4
    confidence[c3] = 3
    confidence[c2] = 2
    confidence[c1] = 1

    # --- NDWI dark-water recovery (raw bands — self-normalizing) --------
    denom = green + nir
    ndwi = np.where(denom > 0, (green - nir) / np.where(denom > 0, denom, 1), -1.0)
    ndwi_water = ndwi > ndwi_threshold
    # NDWI-only pixels are promoted to the highest-confidence class
    confidence[ndwi_water & (confidence == 0)] = 1
    confidence[ndwi_water & (confidence > 1)] = 1

    # --- Filters ---------------------------------------------------------
    keep = valid & (nir < nir_max)
    if hand is not None:
        hand_ok = np.isfinite(hand) & (hand >= 0) & (hand <= hand_max)
        keep &= hand_ok
    confidence[~keep] = 0

    water = confidence > 0
    return {"confidence": confidence, "water": water, "valid": valid,
            "hue": hue, "ndwi": ndwi}


def majority_composite(water_stack: np.ndarray, valid_stack: np.ndarray) -> dict:
    """Temporal aggregation by the >50 % majority rule.

    water_stack / valid_stack: bool arrays (n_scenes, H, W).

    Returns dict with ``mask`` (uint8: 1=water, 0=non-water, 255=unreliable),
    ``freq`` (water frequency), ``n_valid`` and ``min_obs``.
    """
    n_scenes = int(water_stack.shape[0])
    n_valid = valid_stack.sum(axis=0)
    n_water = water_stack.sum(axis=0)
    min_obs = max(2, n_scenes // 3)
    reliable = n_valid >= min_obs

    with np.errstate(divide="ignore", invalid="ignore"):
        freq = np.where(n_valid > 0, n_water / n_valid, 0.0)

    mask = ((freq >= 0.5) & reliable).astype(np.uint8)
    mask[~reliable] = 255
    return {"mask": mask, "freq": freq, "n_valid": n_valid, "min_obs": min_obs}
