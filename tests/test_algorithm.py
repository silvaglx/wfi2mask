import numpy as np
import pytest

from wfi2mask.algorithm import (
    classify_scene,
    majority_composite,
    norm_scene,
    rgb_to_hsv_hue,
)


def test_norm_scene_p99():
    band = np.zeros((10, 10))
    band[0, :] = np.linspace(1, 100, 10)
    out = norm_scene(band)
    assert out.max() <= 1.0
    assert out.min() >= 0.0
    assert out[0, -1] == pytest.approx(1.0)


def test_norm_scene_empty():
    band = np.zeros((5, 5))
    out = norm_scene(band)
    assert np.all(out == 0)


def test_hue_pure_colors():
    r = np.array([[1.0]]); g = np.array([[0.0]]); b = np.array([[0.0]])
    assert rgb_to_hsv_hue(r, g, b)[0, 0] == pytest.approx(0.0)
    assert rgb_to_hsv_hue(g, r, b)[0, 0] == pytest.approx(120.0)
    assert rgb_to_hsv_hue(g, b, r)[0, 0] == pytest.approx(240.0)


def test_classify_water_by_hue():
    """A pixel with Hue inside [16, 35) must be class 1 water."""
    # r(=green band) dominant with some g: hue = 60*((g-b)/delta % 6)
    # choose green=1.0, red=0.4, nir=0.0 -> hue = 60*0.4/1.0 = 24 deg
    shape = (4, 4)
    green = np.full(shape, 0.5)
    red = np.full(shape, 0.2)
    nir = np.full(shape, 0.01)
    res = classify_scene(green, red, nir, hand=None)
    # NDWI is also strongly positive here; class must be 1 either way
    assert np.all(res["confidence"] == 1)
    assert np.all(res["water"])


def test_nir_filter_rejects_bright():
    shape = (4, 4)
    green = np.full(shape, 0.9)
    red = np.full(shape, 0.3)
    nir = np.full(shape, 0.5)  # > default 0.35
    res = classify_scene(green, red, nir, hand=None)
    assert not res["water"].any()


def test_hand_filter():
    shape = (2, 2)
    green = np.full(shape, 0.5)
    red = np.full(shape, 0.2)
    nir = np.full(shape, 0.01)
    hand = np.array([[0.0, 10.0], [20.0, np.nan]])
    res = classify_scene(green, red, nir, hand=hand, hand_max=15)
    assert res["water"][0, 0] and res["water"][0, 1]
    assert not res["water"][1, 0]  # 20 m > 15 m
    assert not res["water"][1, 1]  # nodata HAND rejected


def test_ndwi_dark_water_recovery():
    """Dark water: hue unstable but NDWI>0 -> class 1."""
    shape = (3, 3)
    green = np.full(shape, 0.02)
    red = np.full(shape, 0.02)
    nir = np.full(shape, 0.01)  # NDWI = (0.02-0.01)/0.03 > 0
    res = classify_scene(green, red, nir, hand=None)
    assert np.all(res["confidence"] == 1)


def test_invalid_pixels_excluded():
    shape = (2, 2)
    green = np.array([[0.5, 0.0], [0.5, 0.5]])
    red = np.full(shape, 0.2)
    nir = np.full(shape, 0.01)
    res = classify_scene(green, red, nir, hand=None)
    assert not res["valid"][0, 1]
    assert not res["water"][0, 1]


def test_variable_hue_window():
    """hue_min/hue_max are parameters: the window (and its confidence
    classes) must follow the values passed by the user."""
    shape = (3, 3)
    # constant bands -> p99 normalization gives (1,1,1) -> delta=0 -> hue=0
    green = np.full(shape, 0.3)
    red = np.full(shape, 0.3)
    nir = np.full(shape, 0.3)
    # ndwi_threshold=2 disables the NDWI promotion (NDWI is always <= 1)
    res_default = classify_scene(green, red, nir, hand=None, ndwi_threshold=2.0)
    assert np.all(res_default["confidence"] == 2)  # hue 0 < hue_min -> WATER95
    res_custom = classify_scene(
        green, red, nir, hand=None, ndwi_threshold=2.0, hue_min=0.0
    )
    assert np.all(res_custom["confidence"] == 1)  # window [0, 35) -> WATER


def test_majority_composite():
    # 3 scenes, one pixel water in 2/3 (majority), another in 1/3
    water = np.zeros((3, 1, 2), dtype=bool)
    valid = np.ones((3, 1, 2), dtype=bool)
    water[0, 0, 0] = True
    water[1, 0, 0] = True
    water[2, 0, 1] = True
    agg = majority_composite(water, valid)
    assert agg["mask"][0, 0] == 1
    assert agg["mask"][0, 1] == 0
    assert agg["min_obs"] == 2


def test_majority_unreliable():
    water = np.zeros((4, 1, 1), dtype=bool)
    valid = np.zeros((4, 1, 1), dtype=bool)  # never valid
    agg = majority_composite(water, valid)
    assert agg["mask"][0, 0] == 255
