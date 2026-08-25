"""wfi2mask — detecção automática de água em imagens WFI e Sentinel-2.

Máscaras d'água a partir de imagens dos sensores WFI dos satélites
brasileiros CBERS-4, CBERS-4A e Amazonia-1 — e do Sentinel-2 L2A, base da
validação do algoritmo — usando o algoritmo de Matiz (Hue) de Namikawa
et al. (2016) aprimorado com filtros NDWI, HAND e NIR.

Uso básico::

    import wfi2mask as w2m

    # WFI (INPE) — recortado no bbox e convertido para reflectância TOA
    w2m.get_toa(
        date="2025-07-01, 2025-09-30",
        bbox=[-46.65, -23.85, -46.45, -23.65],
        product="amazonia1",
        user="seu_email@cadastrado_no_inpe.br",
    )

    # máscara d'água; include_s2=True soma cenas Sentinel-2 processadas
    # direto da nuvem (sem download) à composição
    w2m.get_water_mask(path="./wfi2mask_data/toa", include_s2=True)
"""

from .algorithm import classify_scene, majority_composite, norm_scene, rgb_to_hsv_hue
from .download import get_toa
from .hand import get_hand_tiles, tiles_for_bbox
from .mask import get_water_mask
from .toa import convert_scene_to_toa

__version__ = "0.3.0"

__all__ = [
    "get_toa",
    "get_water_mask",
    "convert_scene_to_toa",
    "classify_scene",
    "majority_composite",
    "norm_scene",
    "rgb_to_hsv_hue",
    "tiles_for_bbox",
    "get_hand_tiles",
    "__version__",
]
