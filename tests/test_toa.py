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
