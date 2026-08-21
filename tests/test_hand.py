from wfi2mask.hand import tile_name, tiles_for_bbox


def test_tile_name_south_west():
    assert tile_name(-25, -50) == "s25w050_hnd.tif"
    assert tile_name(-5, -55) == "s05w055_hnd.tif"
    assert tile_name(0, -60) == "n00w060_hnd.tif"


def test_tiles_single():
    # Billings: fits inside s25w050 (lat -25..-20, lon -50..-45)
    assert tiles_for_bbox([-46.65, -23.85, -46.45, -23.65]) == ["s25w050_hnd.tif"]


def test_tiles_project_summary_rois():
    """Tile assignments must match the validated ROI table."""
    cases = {
        "jacarei": ([-46.208068, -23.276797, -46.065303, -23.168024], "s25w050_hnd.tif"),
        "santarem": ([-54.85, -2.55, -54.60, -2.35], "s05w055_hnd.tif"),
        "sobradinho": ([-40.95, -9.55, -40.75, -9.35], "s10w045_hnd.tif"),
        "tres_marias": ([-45.40, -18.35, -45.20, -18.15], "s20w050_hnd.tif"),
        "lagoa_patos": ([-52.20, -32.15, -52.00, -31.95], "s35w055_hnd.tif"),
        "itaipu": ([-54.55, -25.45, -54.35, -25.25], "s30w055_hnd.tif"),
    }
    for name, (bbox, tile) in cases.items():
        assert tiles_for_bbox(bbox) == [tile], name


def test_tiles_crossing_boundary():
    # bbox crossing the -50 meridian tile edge -> two tiles
    tiles = tiles_for_bbox([-50.2, -23.5, -49.8, -23.3])
    assert set(tiles) == {"s25w055_hnd.tif", "s25w050_hnd.tif"}
