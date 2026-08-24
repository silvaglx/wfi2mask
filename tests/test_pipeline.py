"""End-to-end synthetic test of get_water_mask (no network)."""

import os

import numpy as np
import pytest
import rasterio
from pyproj import Transformer
from rasterio.transform import from_origin

from wfi2mask.mask import get_water_mask
from wfi2mask.utils import parse_dates, validate_bbox

BBOX = [-46.65, -23.85, -46.45, -23.65]  # billings


def _make_toa(path, lake=True, seed=42):
    """Synthetic 4-band TOA scene covering the bbox in UTM 23S."""
    tr = Transformer.from_crs("EPSG:4326", "EPSG:32723", always_xy=True)
    x0, y1 = tr.transform(BBOX[0] - 0.05, BBOX[3] + 0.05)
    x1, y0 = tr.transform(BBOX[2] + 0.05, BBOX[1] - 0.05)
    res = 64.0
    w = int((x1 - x0) / res)
    h = int((y1 - y0) / res)
    transform = from_origin(x0, y1, res, res)

    rng = np.random.default_rng(seed)
    # land: bright NIR, moderate green/red
    blue = rng.uniform(0.05, 0.10, (h, w)).astype(np.float32)
    green = rng.uniform(0.08, 0.14, (h, w)).astype(np.float32)
    red = rng.uniform(0.07, 0.13, (h, w)).astype(np.float32)
    nir = rng.uniform(0.30, 0.45, (h, w)).astype(np.float32)

    if lake:
        # central lake: dark NIR, green > nir -> NDWI > 0
        cy, cx = h // 2, w // 2
        sl = (slice(cy - h // 6, cy + h // 6), slice(cx - w // 6, cx + w // 6))
        blue[sl] = 0.04
        green[sl] = 0.06
        red[sl] = 0.04
        nir[sl] = 0.02

    profile = {
        "driver": "GTiff", "height": h, "width": w, "count": 4,
        "dtype": "float32", "crs": "EPSG:32723", "transform": transform,
        "nodata": 0.0,
    }
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with rasterio.open(path, "w", **profile) as dst:
        for i, band in enumerate([blue, green, red, nir], 1):
            dst.write(band, i)


def _make_s2_toa(path, cloudy=False, seed=7):
    """Synthetic 5-band Sentinel-2 product (get_s2 layout): B,G,R,NIR + SCL.

    Reflectance already in [0, ~1]; SCL 6 = water, 4 = vegetation,
    9 = cloud high probability (invalid).
    """
    tr = Transformer.from_crs("EPSG:4326", "EPSG:32723", always_xy=True)
    x0, y1 = tr.transform(BBOX[0] - 0.05, BBOX[3] + 0.05)
    x1, y0 = tr.transform(BBOX[2] + 0.05, BBOX[1] - 0.05)
    res = 64.0
    w = int((x1 - x0) / res)
    h = int((y1 - y0) / res)
    transform = from_origin(x0, y1, res, res)

    rng = np.random.default_rng(seed)
    blue = rng.uniform(0.02, 0.05, (h, w)).astype(np.float32)
    green = rng.uniform(0.04, 0.08, (h, w)).astype(np.float32)
    red = rng.uniform(0.03, 0.07, (h, w)).astype(np.float32)
    nir = rng.uniform(0.20, 0.35, (h, w)).astype(np.float32)
    scl = np.full((h, w), 4.0, dtype=np.float32)  # vegetation

    # central lake (same place as the WFI synthetic scenes)
    cy, cx = h // 2, w // 2
    sl = (slice(cy - h // 6, cy + h // 6), slice(cx - w // 6, cx + w // 6))
    blue[sl] = 0.02
    green[sl] = 0.05
    red[sl] = 0.03
    nir[sl] = 0.02
    scl[sl] = 6.0  # water

    if cloudy:
        scl[:] = 9.0  # whole scene under high-probability cloud

    profile = {
        "driver": "GTiff", "height": h, "width": w, "count": 5,
        "dtype": "float32", "crs": "EPSG:32723", "transform": transform,
        "nodata": 0.0,
    }
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with rasterio.open(path, "w", **profile) as dst:
        for i, band in enumerate([blue, green, red, nir, scl], 1):
            dst.write(band, i)
        dst.update_tags(SATELLITE="sentinel2",
                        BAND_ORDER="blue,green,red,nir,scl")


def _make_hand_tile(hand_dir):
    """Fake s25w050 HAND tile: everything at 2 m (eligible)."""
    os.makedirs(hand_dir, exist_ok=True)
    h = w = 600  # 5 deg / 600 px = 30 arcsec, coarse but fine for the test
    transform = from_origin(-50.0, -20.0, 5.0 / w, 5.0 / h)
    profile = {
        "driver": "GTiff", "height": h, "width": w, "count": 1,
        "dtype": "float32", "crs": "EPSG:4326", "transform": transform,
        "nodata": -9999.0,
    }
    with rasterio.open(os.path.join(hand_dir, "s25w050_hnd.tif"), "w", **profile) as dst:
        dst.write(np.full((h, w), 2.0, dtype=np.float32), 1)


def test_parse_dates_variants():
    from datetime import date
    assert parse_dates("2024-08-01") == (date(2024, 8, 1), date(2024, 8, 1))
    assert parse_dates("2024-08-01, 2024-09-30") == (date(2024, 8, 1), date(2024, 9, 30))
    assert parse_dates(("2024-09-30", "2024-08-01")) == (date(2024, 8, 1), date(2024, 9, 30))
    with pytest.raises(ValueError):
        parse_dates(None)


def test_validate_bbox_errors():
    with pytest.raises(ValueError):
        validate_bbox(None)
    with pytest.raises(ValueError):
        validate_bbox([-46.45, -23.85, -46.65, -23.65])  # lon inverted


def test_get_water_mask_invalid_path():
    with pytest.raises(FileNotFoundError, match="path"):
        get_water_mask(path=None, bbox=BBOX)


def test_get_water_mask_synthetic(tmp_path):
    toa_dir = tmp_path / "toa" / "amazonia1"
    for i, name in enumerate(
        ["AMAZONIA1_WFI_TEST1", "AMAZONIA1_WFI_TEST2", "AMAZONIA1_WFI_TEST3"]
    ):
        _make_toa(str(toa_dir / f"toa_{name}.tif"), lake=True)
    hand_dir = tmp_path / "hand"
    _make_hand_tile(str(hand_dir))

    out = get_water_mask(
        path=str(tmp_path / "toa"),
        bbox=BBOX,
        coarse=100,
        hand_dir=str(hand_dir),
        outdir=str(tmp_path / "out"),
    )

    assert len(out["scenes"]) == 3
    for s in out["scenes"]:
        assert os.path.exists(s["shapefile"])
        assert s["n_water_px"] > 0
    assert out["composite"] is not None and os.path.exists(out["composite"])
    assert out["plot"] is not None and os.path.exists(out["plot"])

    import geopandas as gpd
    gdf = gpd.read_file(out["scenes"][0]["shapefile"])
    assert "classe" in gdf.columns
    assert (gdf["classe"] == 1).any()

    comp = gpd.read_file(out["composite"])
    assert len(comp) > 0


def test_get_water_mask_mixed_wfi_s2(tmp_path):
    """WFI + Sentinel-2 in the same run: automatic NIR default per scene,
    SCL per-pixel cloud mask, bbox derived from the images (bbox=None)."""
    toa_dir = tmp_path / "toa"
    for name in ["AMAZONIA1_WFI_TEST1", "AMAZONIA1_WFI_TEST2"]:
        _make_toa(str(toa_dir / "amazonia1" / f"toa_{name}.tif"), lake=True)
    _make_s2_toa(str(toa_dir / "sentinel2" / "toa_S2_20250101.tif"))
    _make_s2_toa(str(toa_dir / "sentinel2" / "toa_S2_20250111.tif"), cloudy=True)
    hand_dir = tmp_path / "hand"
    _make_hand_tile(str(hand_dir))

    out = get_water_mask(
        path=str(toa_dir),
        bbox=None,  # derived from the TOA images
        coarse=100,
        hand_dir=str(hand_dir),
        outdir=str(tmp_path / "out"),
    )

    assert len(out["scenes"]) == 4
    by_scene = {s["scene"]: s for s in out["scenes"]}

    wfi = by_scene["AMAZONIA1_WFI_TEST1"]
    assert wfi["satellite"] == "amazonia1"
    assert wfi["nir_max"] == pytest.approx(0.35)
    assert wfi["n_water_px"] > 0

    s2 = by_scene["S2_20250101"]
    assert s2["satellite"] == "sentinel2"
    assert s2["nir_max"] == pytest.approx(0.10)
    assert s2["n_water_px"] > 0

    # fully cloudy S2 scene: the SCL mask must reject every pixel
    assert by_scene["S2_20250111"]["n_water_px"] == 0

    # mixed composite still produced
    assert out["composite"] is not None and os.path.exists(out["composite"])
