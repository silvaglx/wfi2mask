"""Exemplo completo: Represa Billings/SP.

Mostra os três caminhos do pacote:
  A) máscara d'água direto da nuvem (sem baixar nada, sem cadastro);
  B) baixando a reflectância antes (SR ou DN->TOA);
  C) usando o catálogo clássico do INPE (exige cadastro).
"""

import wfi2mask as w2m

BBOX = [-46.65, -23.85, -46.45, -23.65]     # Billings/SP
PERIODO = "2025-07-01, 2025-09-30"

# 0) Que produtos existem? ---------------------------------------------
w2m.get_products()

# A) Máscara d'água direto da nuvem ------------------------------------
# Nada é gravado em disco além do plot: as cenas de reflectância de
# superfície são lidas por janela, só o bbox trafega pela rede.
resultado = w2m.get_water_mask(
    bbox=BBOX,
    date=PERIODO,
    product=["CB4A-WFI-L4-SR-1", "AMZ1-WFI-L4-SR-1"],
    max_cloud=20,        # % de nuvem da cena; -1 desativa
    max_images=5,        # por produto, mais recentes primeiro
    coarse=100,          # resolução da análise (m)
    hand=15,             # HAND máximo (m)
    # nir={"cbers4a": 0.20},   # filtro NIR: desativado por padrão
    # hue_min=16, hue_max=35,  # janela de Matiz, ajustável
)

print("\nCenas classificadas:")
for cena in resultado["scenes"]:
    print(f"  {cena['scene']:<40} {cena['satellite']:<10} "
          f"{cena['level']:<4} {cena['n_water_px']:>7,d} px de água")
print("Plot:", resultado["plot"])

# Somando o Sentinel-2 à mesma composição:
#   product=["CB4A-WFI-L4-SR-1", "sentinel-2-l2a"]

# B) Baixando a reflectância antes -------------------------------------
# Útil para reprocessar várias vezes ou para trabalhar com TOA.
# arquivos = w2m.get_reflectance(
#     date=PERIODO,
#     bbox=BBOX,
#     product="CB4A-WFI-L4-DN-1",   # '-DN-' converte para TOA; '-SR-' usa como publicado
#     max_cloud=20,
#     outdir="./wfi2mask_data",
# )
# w2m.get_water_mask(path="./wfi2mask_data/reflectance")

# C) Catálogo clássico do INPE -----------------------------------------
# Lista mais cenas, mas exige cadastro e baixa a CENA INTEIRA (minutos por
# cena, sem leitura por janela e sem máscara de nuvem por pixel).
# w2m.get_water_mask(
#     bbox=BBOX,
#     date=PERIODO,
#     catalog="INPE_CLASSIC",
#     product="CBERS4A_WFI_L4_DN",
#     user="seu_email@cadastrado_no_inpe.br",
#     max_cloud=20,
#     max_images=2,
# )
