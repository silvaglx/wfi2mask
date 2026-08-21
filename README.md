# wfi2mask

**Detecção automática de água em imagens WFI (CBERS-4, CBERS-4A e Amazonia-1)**

*Automated water detection from WFI images of the Brazilian satellites CBERS-4, CBERS-4A and Amazonia-1.*

O `wfi2mask` busca imagens no catálogo do INPE, converte para reflectância TOA e
gera máscaras d'água vetoriais (shapefile) com 4 níveis de confiança, seguindo o
algoritmo de Matiz (Hue) de **Namikawa et al. (2016)** aprimorado com filtros
**NDWI**, **HAND** (MERIT Hydro) e brilho **NIR**.

> Status: protótipo em desenvolvimento (v0.1.0), já testável.

## Instalação

```bash
pip install git+https://github.com/SEU_USUARIO/wfi2mask.git
```

Requisito: conta (e-mail) cadastrada no
[catálogo do INPE](https://www.dgi.inpe.br/catalogo/explore) para o download
das imagens.

## Uso rápido

```python
import wfi2mask

# 1) Buscar, baixar e converter para TOA
wfi2mask.get_toa(
    date="2025-07-01, 2025-09-30",          # data única ou intervalo
    bbox=[-46.65, -23.85, -46.45, -23.65],  # [lon_min, lat_min, lon_max, lat_max]
    product="amazonia1",                    # 'amazonia1' | 'cbers4a' | 'cbers4' | 'all'
    max_cloud=-1,                           # -1 desativa o filtro de nuvem
    user="seu_email@cadastrado_no_inpe.br",
    outdir="./wfi2mask_data",
)

# 2) Gerar a máscara d'água (shapefiles + plot de demonstração)
resultado = wfi2mask.get_water_mask(
    path="./wfi2mask_data/toa",
    bbox=[-46.65, -23.85, -46.45, -23.65],
    coarse=100,   # resolução de análise (m), compatível com o HAND (~90 m)
    hand=15,      # HAND máximo (m)
    ndwi=0.0,     # limiar NDWI
    nir=0.35,     # NIR TOA máximo (escala de reflectância [0, ~1])
)
```

Saídas de `get_water_mask`:

* `water_<cena>.shp` — máscara por cena com as 4 classes de confiança
  (WATER, WATER95, WATER90, WATER80);
* `water_composite_majority.shp` — composição temporal pela regra da
  maioria (>50 %), quando há 2+ cenas;
* `water_mask_overlay.png` — plot de demonstração (cor verdadeira + máscara).

## Dados HAND

O filtro topográfico usa tiles HAND de 5°×5° do MERIT Hydro
(Yamazaki et al., 2019). Os tiles necessários para o `bbox` são **baixados
sob demanda** e mantidos em cache local (`~/.wfi2mask/hand`). Veja
`docs/hand.md` para hospedar/atualizar os tiles.

## Algoritmo

```
Água = (Hue ∈ [16°, 35°) OU NDWI > 0) E (HAND ≤ 15 m) E (NIR < 0,35) E pixel válido
```

Validado em 16 áreas no Brasil com Sentinel-2 (F1 médio ≈ 0,95 fora de áreas
úmidas rasas). Limitações conhecidas: Pantanal (F1 0,42) e água muito escura
(compensada pelo NDWI). Detalhes na documentação.

## Documentação

https://wfi2mask.readthedocs.io (pt-BR)

## Referências

* Namikawa, L.M.; Korting, T.; Castejon, E.F. (2016). *Water Body Extraction
  From RapidEye Images*. RBC 68:1097-1111.
* Yamazaki, D. et al. (2019). *MERIT Hydro: A high-resolution global
  hydrography map*. Water Resources Research 55:5053-5073.
* Pinto, C.T. et al. (2016). *First in-flight radiometric calibration of MUX
  and WFI on-board CBERS-4*. Remote Sensing 8(5):405.

## Licença

MIT
