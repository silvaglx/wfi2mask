"""Exemplo completo: Represa Billings/SP com Amazonia-1 + Sentinel-2.

Requisito: e-mail cadastrado em https://www.dgi.inpe.br/catalogo/explore
(apenas para o WFI — o Sentinel-2 dispensa cadastro).
"""

import wfi2mask as w2m

EMAIL = "seu_email@cadastrado_no_inpe.br"   # <<< EDITE AQUI
BBOX = [-46.65, -23.85, -46.45, -23.65]     # Billings/SP

# 1) Buscar, baixar e converter para TOA (recortado no bbox) -----------
w2m.get_toa(
    date="2025-07-01, 2025-09-30",
    bbox=BBOX,
    product="amazonia1",
    max_cloud=-1,        # >=0 filtra pelo % de nuvem do catálogo INPE
    user=EMAIL,
    outdir="./wfi2mask_data",
)

# 2) (Opcional) Adicionar Sentinel-2 L2A à composição ------------------
w2m.get_s2(
    date="2025-07-01, 2025-09-30",
    bbox=BBOX,
    max_cloud=20,
    max_images=5,
    outdir="./wfi2mask_data",
)

# 3) Gerar a máscara d'água (WFI + Sentinel-2 juntos) ------------------
resultado = w2m.get_water_mask(
    path="./wfi2mask_data/toa",
    coarse=100,
    hand=15,
    # nir=None (padrão): limiar automático por cena (0.35 WFI / 0.10 S2)
    # hue_min=16, hue_max=35: janela de Matiz ajustável
)

print("\nShapefiles gerados:")
for cena in resultado["scenes"]:
    print(f" - {cena['shapefile']} ({cena['satellite']})")
if resultado["composite"]:
    print(" -", resultado["composite"], "(composição pela maioria)")
print("Plot:", resultado["plot"])
