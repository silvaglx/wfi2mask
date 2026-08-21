"""Exemplo completo: Represa Billings/SP com Amazonia-1.

Requisito: e-mail cadastrado em https://www.dgi.inpe.br/catalogo/explore
"""

import wfi2mask

EMAIL = "seu_email@cadastrado_no_inpe.br"   # <<< EDITE AQUI
BBOX = [-46.65, -23.85, -46.45, -23.65]     # Billings/SP

# 1) Buscar, baixar e converter para TOA -------------------------------
wfi2mask.get_toa(
    date="2025-07-01, 2025-09-30",
    bbox=BBOX,
    product="amazonia1",
    max_cloud=-1,        # sem filtro de nuvem; use ex. 20 para ativar matchup S2
    user=EMAIL,
    outdir="./wfi2mask_data",
)

# 2) Gerar a máscara d'água --------------------------------------------
resultado = wfi2mask.get_water_mask(
    path="./wfi2mask_data/toa",
    bbox=BBOX,
    coarse=100,
    hand=15,
    ndwi=0.0,
    nir=0.35,
)

print("\nShapefiles gerados:")
for cena in resultado["scenes"]:
    print(" -", cena["shapefile"])
if resultado["composite"]:
    print(" -", resultado["composite"], "(composição pela maioria)")
print("Plot:", resultado["plot"])
