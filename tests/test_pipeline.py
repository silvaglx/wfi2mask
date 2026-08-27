"""End-to-end synthetic test of get_water_mask (no network)."""

import glob
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
    """Synthetic local 5-band Sentinel-2 product: B,G,R,NIR + SCL.

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


def test_resolve_level():
    from wfi2mask.mask import _resolve_level

    assert _resolve_level("SR", "cbers4a") == "sr"
    assert _resolve_level("toa", "cbers4a") == "toa"
    # sem tag: Sentinel-2 e reflectancia de superficie; WFI antigo e TOA
    assert _resolve_level(None, "sentinel2") == "sr"
    assert _resolve_level(None, "amazonia1") == "toa"
    # tag desconhecida cai no padrao
    assert _resolve_level("l4", "amazonia1") == "toa"


def test_stac_collection_ids():
    from wfi2mask.stac import collection_id

    assert collection_id("cbers4a", "sr") == "CB4A-WFI-L4-SR-1"
    assert collection_id("amazonia1", "dn") == "AMZ1-WFI-L4-DN-1"
    assert collection_id("CBERS4", "SR") == "CB4-WFI-L4-SR-1"
    with pytest.raises(ValueError, match="Sem coleção STAC"):
        collection_id("sentinel2", "sr")


def test_get_reflectance_resolve_products():
    from wfi2mask.download import _resolve_products as resolver

    todos = resolver("all")
    assert {p["id"] for p in todos} == {
        "AMZ1-WFI-L4-SR-1", "AMZ1-WFI-L4-DN-1",
        "CB4A-WFI-L4-SR-1", "CB4A-WFI-L4-DN-1",
        "CB4-WFI-L4-SR-1", "CB4-WFI-L4-DN-1",
    }
    # nome completo do produto
    um = resolver("CB4A-WFI-L4-DN-1")
    assert [(p["id"], p["level"]) for p in um] == [("CB4A-WFI-L4-DN-1", "dn")]
    # lista mista, sem duplicar
    varios = resolver(["CB4A-WFI-L4-SR-1", "AMZ1-WFI-L4-DN-1", "CB4A-WFI-L4-SR-1"])
    assert [p["id"] for p in varios] == ["CB4A-WFI-L4-SR-1", "AMZ1-WFI-L4-DN-1"]
    # atalho antigo -> produto SR do sensor por padrao...
    assert resolver("cbers4a")[0]["id"] == "CB4A-WFI-L4-SR-1"
    # ...mas o alias get_toa mantem o caminho DN->TOA
    assert resolver("cbers4a", default_level="dn")[0]["id"] == "CB4A-WFI-L4-DN-1"
    # Sentinel-2 nao e baixavel por get_reflectance
    with pytest.raises(ValueError, match="get_water_mask"):
        resolver("sentinel-2-l2a")
    with pytest.raises(ValueError, match="get_products"):
        resolver("landsat9")


def test_resolve_catalog():
    from wfi2mask.stac import resolve_catalog

    assert resolve_catalog(None) == "INPE_STAC"
    assert resolve_catalog("INPE_CLASSIC") == "INPE_CLASSIC"
    assert resolve_catalog("classic") == "INPE_CLASSIC"
    assert resolve_catalog("stac") == "INPE_STAC"
    with pytest.raises(ValueError, match="Catálogo desconhecido"):
        resolve_catalog("USGS")


def test_product_names_are_catalog_specific():
    from wfi2mask.stac import resolve_product

    # o nome do produto ja determina o catalogo
    assert resolve_product("CB4A-WFI-L4-DN-1")["catalog"] == "INPE_STAC"
    assert resolve_product("CBERS4A_WFI_L4_DN")["catalog"] == "INPE_CLASSIC"
    # atalho resolve dentro do catalogo pedido
    assert resolve_product("cbers4a", catalog="INPE_CLASSIC")["id"] == \
        "CBERS4A_WFI_L4_DN"
    assert resolve_product("cbers4a", catalog="INPE_STAC")["id"] == \
        "CB4A-WFI-L4-SR-1"
    # conflito explicito e recusado, nao reinterpretado
    with pytest.raises(ValueError, match="pertence ao catálogo"):
        resolve_product("CBERS4A_WFI_L4_DN", catalog="INPE_STAC")
    # Sentinel-2 vale nos dois catalogos
    for cat in ("INPE_STAC", "INPE_CLASSIC"):
        assert resolve_product("s2", catalog=cat)["id"] == "sentinel-2-l2a"


def test_classic_requires_user(tmp_path):
    import wfi2mask as w2m

    with pytest.raises(ValueError, match="user="):
        w2m.get_reflectance(date="2025-12-01, 2025-12-31", bbox=BBOX,
                            product="CBERS4A_WFI_L4_DN",
                            catalog="INPE_CLASSIC", outdir=str(tmp_path))


def test_get_products_by_catalog(capsys):
    import wfi2mask as w2m

    stac = {i["id"] for i in w2m.get_products(catalog="INPE_STAC", verbose=False)}
    classico = {i["id"] for i in w2m.get_products(catalog="INPE_CLASSIC",
                                                  verbose=False)}
    assert "CB4A-WFI-L4-SR-1" in stac and "CBERS4A_WFI_L4_DN" not in stac
    assert "CBERS4A_WFI_L4_DN" in classico and "CB4A-WFI-L4-SR-1" not in classico
    # Sentinel-2 aparece nos dois
    assert "sentinel-2-l2a" in stac and "sentinel-2-l2a" in classico
    # o classico so tem DN
    assert all(i["level"] == "dn" for i in
               w2m.get_products(catalog="INPE_CLASSIC", source="inpe",
                                verbose=False))
    # 'all' lista os dois
    todos = {i["id"] for i in w2m.get_products(catalog="all", verbose=False)}
    assert stac | classico <= todos

    w2m.get_products(catalog="INPE_CLASSIC")
    saida = capsys.readouterr().out
    assert "INPE_CLASSIC" in saida and "cadastro" in saida


def test_get_products_listing(capsys):
    import wfi2mask as w2m

    itens = w2m.get_products()
    ids = {i["id"] for i in itens}
    assert "CB4A-WFI-L4-SR-1" in ids and "sentinel-2-l2a" in ids
    saida = capsys.readouterr().out
    assert "CB4A-WFI-L4-SR-1" in saida and "PRODUTO" in saida

    # filtros
    so_sr = w2m.get_products(level="sr", verbose=False)
    assert all(i["level"] == "sr" for i in so_sr)
    so_inpe = w2m.get_products(source="inpe", verbose=False)
    assert all(i["source"] == "inpe" for i in so_inpe)
    assert "sentinel-2-l2a" not in {i["id"] for i in so_inpe}


def test_resolve_nir_dict():
    from wfi2mask.mask import _resolve_nir

    # None -> filtro ausente
    assert _resolve_nir(None, "cbers4") is None
    # escalar -> vale para todos
    assert _resolve_nir(0.3, "amazonia1") == pytest.approx(0.3)
    # dicionario por satelite
    d = {"cbers4": 0.35, "amazonia1": 0.30}
    assert _resolve_nir(d, "cbers4") == pytest.approx(0.35)
    assert _resolve_nir(d, "amazonia1") == pytest.approx(0.30)
    # satelite fora do dicionario -> sem filtro
    assert _resolve_nir(d, "cbers4a") is None
    # apelidos e chaves com ':' sobrando sao tolerados
    assert _resolve_nir({"cbers-4a": 0.4}, "cbers4a") == pytest.approx(0.4)
    assert _resolve_nir({"cbers4:": 0.4}, "cbers4") == pytest.approx(0.4)


def test_nir_filter_off_by_default(tmp_path):
    """Sem nir=, nenhum pixel deve ser rejeitado por brilho NIR."""
    toa_dir = tmp_path / "toa"
    # cena com NIR alto no 'lago': so passa se o filtro NIR estiver desligado
    _make_toa(str(toa_dir / "toa_AMAZONIA1_WFI_T1.tif"), lake=True)
    hand_dir = tmp_path / "hand"
    _make_hand_tile(str(hand_dir))
    comum = dict(path=str(toa_dir), bbox=BBOX, coarse=100,
                 hand_dir=str(hand_dir), plot=False)

    sem_nir = get_water_mask(outdir=str(tmp_path / "a"), **comum)
    assert sem_nir["scenes"][0]["nir_max"] is None

    # limiar impossivelmente baixo remove tudo -> prova que o filtro atua
    com_nir = get_water_mask(nir={"amazonia1": 0.001},
                             outdir=str(tmp_path / "b"), **comum)
    assert com_nir["scenes"][0]["nir_max"] == pytest.approx(0.001)
    assert com_nir["scenes"][0]["n_water_px"] < sem_nir["scenes"][0]["n_water_px"]


def test_resolve_products():
    from wfi2mask.mask import _resolve_products

    assert _resolve_products(None) == (None, {})
    assert _resolve_products("all") == (None, {})
    assert _resolve_products("cbers4a")[0] == {"cbers4a"}
    assert _resolve_products(["amazonia1", "S2"])[0] == {"amazonia1", "sentinel2"}
    assert _resolve_products("Sentinel-2")[0] == {"sentinel2"}
    # o nome completo do produto define o nivel
    sats, niveis = _resolve_products("CB4A-WFI-L4-DN-1")
    assert sats == {"cbers4a"} and niveis == {"cbers4a": "dn"}
    sats, niveis = _resolve_products(["CB4A-WFI-L4-SR-1", "AMZ1-WFI-L4-DN-1"])
    assert niveis == {"cbers4a": "sr", "amazonia1": "dn"}
    with pytest.raises(ValueError, match="get_products"):
        _resolve_products("landsat9")


def test_get_water_mask_product_filter(tmp_path):
    """product= must restrict which satellites enter the analysis."""
    toa_dir = tmp_path / "toa"
    _make_toa(str(toa_dir / "amazonia1" / "toa_AMAZONIA1_WFI_T1.tif"), lake=True)
    _make_toa(str(toa_dir / "amazonia1" / "toa_AMAZONIA1_WFI_T2.tif"), lake=True)
    _make_toa(str(toa_dir / "cbers4a" / "toa_CBERS4A_WFI_T3.tif"), lake=True)
    hand_dir = tmp_path / "hand"
    _make_hand_tile(str(hand_dir))

    common = dict(path=str(toa_dir), bbox=BBOX, coarse=100,
                  hand_dir=str(hand_dir), plot=False)

    todos = get_water_mask(outdir=str(tmp_path / "out_all"), **common)
    assert {s["satellite"] for s in todos["scenes"]} == {"amazonia1", "cbers4a"}
    assert len(todos["scenes"]) == 3

    so_amz = get_water_mask(product="amazonia1",
                            outdir=str(tmp_path / "out_amz"), **common)
    assert {s["satellite"] for s in so_amz["scenes"]} == {"amazonia1"}
    assert len(so_amz["scenes"]) == 2

    lista = get_water_mask(product=["cbers4a"],
                           outdir=str(tmp_path / "out_c4a"), **common)
    assert [s["scene"] for s in lista["scenes"]] == ["CBERS4A_WFI_T3"]
    # a exportacao vetorial esta desativada: so ha plot + estatisticas
    assert "composite" not in lista and "shapefile" not in lista["scenes"][0]

    # nothing matches -> clear error mentioning product
    with pytest.raises(FileNotFoundError, match="cbers4"):
        get_water_mask(product="cbers4", outdir=str(tmp_path / "out_x"), **common)


def test_product_controls_sentinel2_streaming(monkeypatch, tmp_path):
    """'sentinel2' in product turns streaming on; omitting it turns it off."""
    import wfi2mask.mask as mask_mod

    toa_dir = tmp_path / "toa"
    _make_toa(str(toa_dir / "amazonia1" / "toa_AMAZONIA1_WFI_T1.tif"), lake=True)
    hand_dir = tmp_path / "hand"
    _make_hand_tile(str(hand_dir))

    chamadas = []
    monkeypatch.setattr(
        mask_mod, "_classify_s2_from_cloud",
        lambda *a, **k: chamadas.append(True),
    )
    common = dict(path=str(toa_dir), bbox=BBOX, coarse=100,
                  hand_dir=str(hand_dir), plot=False)

    # product exclui sentinel2 + include_s2=True -> streaming desligado
    get_water_mask(product="amazonia1", include_s2=True,
                   outdir=str(tmp_path / "o1"), **common)
    assert chamadas == []

    # 'sentinel2' no product -> streaming ligado mesmo com include_s2=False
    get_water_mask(product=["amazonia1", "sentinel2"],
                   outdir=str(tmp_path / "o2"), **common)
    assert chamadas == [True]


def test_infer_dates_from_scenes():
    from datetime import date

    from wfi2mask.mask import _infer_dates_from_scenes

    d = _infer_dates_from_scenes(
        ["toa_AMAZONIA1_WFI03401920250217ETC2.tif", "toa_S2_20250101.tif"]
    )
    assert d == (date(2025, 1, 1), date(2025, 2, 17))
    assert _infer_dates_from_scenes(["toa_SEM_DATA.tif"]) is None


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
        assert s["n_water_px"] > 0
        assert s["nir_max"] is None          # filtro NIR desativado por padrao
    # unica saida em disco: o plot de comparacao
    assert out["plot"] is not None and os.path.exists(out["plot"])
    assert not glob.glob(os.path.join(str(tmp_path / "out"), "*.shp"))


def test_get_water_mask_mixed_wfi_s2(tmp_path):
    """WFI + Sentinel-2 na mesma execucao: NIR por satelite via dicionario,
    mascara SCL por pixel, bbox derivado das imagens (bbox=None)."""
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
        nir={"amazonia1": 0.35, "sentinel2": 0.10},   # por satelite
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
    assert out["plot"] is not None and os.path.exists(out["plot"])
