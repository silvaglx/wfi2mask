"""wfi2mask — detecção automática de água em imagens WFI e Sentinel-2.

Máscaras d'água a partir de imagens dos sensores WFI dos satélites
brasileiros CBERS-4, CBERS-4A e Amazonia-1 — e do Sentinel-2 L2A, base da
validação do algoritmo — usando o algoritmo de Matiz (Hue) de Namikawa
et al. (2016) aprimorado com filtros NDWI, HAND e NIR.

Uso básico::

    import wfi2mask as w2m

    # 1) quais produtos existem?
    w2m.get_products()

    # 2) máscara d'água direto da nuvem, sem baixar nada
    w2m.get_water_mask(
        bbox=[-46.65, -23.85, -46.45, -23.65],
        date="2025-07-01, 2025-09-30",
        product=["CB4A-WFI-L4-SR-1", "AMZ1-WFI-L4-SR-1"],
    )

    # 3) ou baixe a reflectância recortada no bbox (SR ou DN->TOA)
    w2m.get_reflectance(
        date="2025-07-01, 2025-09-30",
        bbox=[-46.65, -23.85, -46.45, -23.65],
        product="CB4A-WFI-L4-DN-1",
    )
    w2m.get_water_mask(path="./wfi2mask_data/reflectance")

Nenhum cadastro é necessário — o STAC do INPE é aberto.
"""

from . import constants, stac
from .algorithm import classify_scene, majority_composite, norm_scene, rgb_to_hsv_hue
from .download import get_reflectance, get_toa
from .hand import get_hand_tiles, tiles_for_bbox
from .mask import get_water_mask
from .stac import get_products, resolve_catalog, resolve_product, search_scenes
from .toa import convert_scene_to_toa

__version__ = "0.4.0"

__all__ = [
    "get_products",
    "get_reflectance",
    "get_water_mask",
    "get_toa",
    "resolve_catalog",
    "resolve_product",
    "search_scenes",
    "convert_scene_to_toa",
    "classify_scene",
    "majority_composite",
    "norm_scene",
    "rgb_to_hsv_hue",
    "tiles_for_bbox",
    "get_hand_tiles",
    "__version__",
]
