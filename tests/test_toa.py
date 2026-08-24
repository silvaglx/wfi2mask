import os
from math import cos, pi, radians

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from wfi2mask.constants import ACC_OVERRIDE, ESUN, satellite_from_scene_id
from wfi2mask.toa import (
    convert_scene_to_toa,
    get_acc_from_xml,
    get_sun_zenith_from_xml,
    identify_band_files,
)

XML = """<?xml version="1.0"?>
<prdf>
  <image>
    <sunPosition>
      <elevation>62.5</elevation>
      <sunAzimuth>45.0</sunAzimuth>
    </sunPosition>
  </image>
  <absoluteCalibrationCoefficient>
    <blue>0.24</blue><green>0.31</green><red>0.214</red><nir>0.185</nir>
  </absoluteCalibrationCoefficient>
</prdf>
"""


@pytest.fixture
def xml_file(tmp_path):
    p = tmp_path / "scene.xml"
    p.write_text(XML)
    return str(p)


def test_satellite_from_scene_id():
    assert satellite_from_scene_id("AMAZONIA1_WFI03401920250217ETC2") == "amazonia1"
    assert satellite_from_scene_id("CBERS4_AWFI15012320251121CB11") == "cbers4"
    assert satellite_from_scene_id("CBERS4A_WFI12345") == "cbers4a"
    assert satellite_from_scene_id("LANDSAT_FOO") is None


def test_get_acc(xml_file):
    acc = get_acc_from_xml(xml_file)
    assert acc == {"blue": 0.24, "green": 0.31, "red": 0.214, "nir": 0.185}


def test_get_zenith(xml_file):
    assert get_sun_zenith_from_xml(xml_file) == pytest.approx(90.0 - 62.5)


def test_missing_xml_fallbacks(tmp_path):
    acc = get_acc_from_xml(str(tmp_path / "nope.xml"))
    assert acc["blue"] == 1.0
    assert get_sun_zenith_from_xml(str(tmp_path / "nope.xml")) == 45.0


def _write_band(path, value, dtype="uint16"):
    arr = np.full((8, 8), value, dtype=dtype)
    profile = {
        "driver": "GTiff", "height": 8, "width": 8, "count": 1,
        "dtype": dtype, "crs": "EPSG:32723",
        "transform": from_origin(300000, 7400000, 64, 64),
    }
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(arr, 1)


@pytest.mark.parametrize("sat,bands", [
    ("amazonia1", [1, 2, 3, 4]),
    ("cbers4", [13, 14, 15, 16]),
    ("cbers4a", [5, 6, 7, 8]),
])
def test_identify_bands_by_number(tmp_path, sat, bands):
    scene = tmp_path / "scene"
    scene.mkdir()
    for b in bands:
        _write_band(str(scene / f"SCENE_BAND{b}.tif"), 100)
    files = identify_band_files(str(scene), sat)
    assert set(files) == {"blue", "green", "red", "nir"}


def test_convert_scene_to_toa_bbox_crop(tmp_path):
    """bbox= must crop the TOA output to the requested area."""
    from pyproj import Transformer

    scene = tmp_path / "AMAZONIA1_WFI03401920250217ETC2"
    scene.mkdir()
    n = 40  # 40x40 px @ 64 m
    for b in (1, 2, 3, 4):
        arr = np.full((n, n), 500, dtype="uint16")
        profile = {
            "driver": "GTiff", "height": n, "width": n, "count": 1,
            "dtype": "uint16", "crs": "EPSG:32723",
            "transform": from_origin(300000, 7400000, 64, 64),
        }
        with rasterio.open(str(scene / f"AMAZONIA1_WFI_BAND{b}.tif"), "w", **profile) as dst:
            dst.write(arr, 1)
    (scene / "AMAZONIA1_WFI_BAND2.xml").write_text(XML)

    # central 20x20-px core, expressed in EPSG:4326
    tr = Transformer.from_crs("EPSG:32723", "EPSG:4326", always_xy=True)
    lon0, lat0 = tr.transform(300000 + 10 * 64, 7400000 - 30 * 64)
    lon1, lat1 = tr.transform(300000 + 30 * 64, 7400000 - 10 * 64)
    bbox = [lon0, lat0, lon1, lat1]

    out = str(tmp_path / "toa" / "toa_crop.tif")
    meta = convert_scene_to_toa(str(scene), out, bbox=bbox)
    assert meta is not None
    with rasterio.open(out) as src:
        # reprojection rounding: allow a small margin around 20x20
        assert 18 <= src.width <= 24
        assert 18 <= src.height <= 24
        assert src.tags().get("BBOX")

    # bbox with no overlap -> scene skipped
    out2 = str(tmp_path / "toa" / "toa_nooverlap.tif")
    assert convert_scene_to_toa(str(scene), out2, bbox=[0.0, 0.0, 1.0, 1.0]) is None
    assert not os.path.exists(out2)


def test_convert_scene_to_toa_calibration_override(tmp_path):
    """esun=/acc= must take precedence over the package defaults."""
    scene = tmp_path / "AMAZONIA1_WFI03401920250217ETC2"
    scene.mkdir()
    dn = 500
    for b in (1, 2, 3, 4):
        _write_band(str(scene / f"AMAZONIA1_WFI_BAND{b}.tif"), dn)
    (scene / "AMAZONIA1_WFI_BAND2.xml").write_text(XML)

    ones = {b: 1.0 for b in ("blue", "green", "red", "nir")}
    esun = {b: 1000.0 for b in ("blue", "green", "red", "nir")}
    out = str(tmp_path / "toa" / "toa_override.tif")
    meta = convert_scene_to_toa(str(scene), out, esun=esun, acc=ones)
    assert meta is not None
    with rasterio.open(out) as src:
        blue = src.read(1)
    zen = radians(90.0 - 62.5)
    expected = pi * 1.0 * dn / (1000.0 * cos(zen))
    assert blue[0, 0] == pytest.approx(expected, rel=1e-5)

    # per-satellite override that does NOT cover this satellite -> defaults
    out2 = str(tmp_path / "toa" / "toa_other_sat.tif")
    meta2 = convert_scene_to_toa(str(scene), out2, acc={"cbers4a": ones})
    assert meta2["acc"] == ACC_OVERRIDE["amazonia1"]


def test_convert_scene_to_toa(tmp_path):
    scene = tmp_path / "AMAZONIA1_WFI03401920250217ETC2"
    scene.mkdir()
    dn = 500
    for b in (1, 2, 3, 4):
        _write_band(str(scene / f"AMAZONIA1_WFI_BAND{b}.tif"), dn)
    (scene / "AMAZONIA1_WFI_BAND2.xml").write_text(XML)

    out = str(tmp_path / "toa" / "toa_scene.tif")
    meta = convert_scene_to_toa(str(scene), out)
    assert meta is not None
    assert meta["satellite"] == "amazonia1"
    assert os.path.exists(out)

    with rasterio.open(out) as src:
        assert src.count == 4
        blue = src.read(1)

    # Expected: pi * ACC_override * DN / (ESUN * cos(zenith))
    zen = radians(90.0 - 62.5)
    expected = pi * ACC_OVERRIDE["amazonia1"]["blue"] * dn / (
        ESUN["amazonia1"]["blue"] * cos(zen)
    )
    assert blue[0, 0] == pytest.approx(expected, rel=1e-5)
