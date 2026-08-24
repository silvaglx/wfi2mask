# wfi2mask

**Detecção automática de água em imagens WFI (CBERS-4, CBERS-4A e Amazonia-1) e Sentinel-2**

*Automated water detection from WFI images of the Brazilian satellites CBERS-4, CBERS-4A and Amazonia-1 — with Sentinel-2 support.*

O `wfi2mask` busca imagens no catálogo do INPE (e, opcionalmente, Sentinel-2 L2A
na AWS), converte para reflectância recortada na área de interesse e gera
máscaras d'água vetoriais (shapefile) com 4 níveis de confiança, seguindo o
algoritmo de Matiz (Hue) de **Namikawa et al. (2016)** aprimorado com filtros
**NDWI**, **HAND** (MERIT Hydro) e brilho **NIR**.

> Status: protótipo em desenvolvimento (v0.2.0), já testável.

## Instalação

```bash
pip install wfi2mask
```

ou, para a versão de desenvolvimento:

```bash
pip install git+https://github.com/silvaglx/wfi2mask.git
```

Requisito: conta (e-mail) cadastrada no
[catálogo do INPE](https://www.dgi.inpe.br/catalogo/explore) para o download
das imagens WFI (o Sentinel-2 não exige cadastro).

## Uso rápido

```python
import wfi2mask as w2m

BBOX = [-46.65, -23.85, -46.45, -23.65]  # [lon_min, lat_min, lon_max, lat_max]

# 1) Buscar, baixar e converter para TOA (recortado no bbox)
w2m.get_toa(
    date="2025-07-01, 2025-09-30",   # data única ou intervalo
    bbox=BBOX,
    product="amazonia1",             # 'amazonia1' | 'cbers4a' | 'cbers4' | 'all'
    max_cloud=-1,                    # >=0 filtra pelo % de nuvem do catálogo INPE
    user="seu_email@cadastrado_no_inpe.br",
    outdir="./wfi2mask_data",
)

# 2) Gerar a máscara d'água; include_s2=True soma cenas Sentinel-2 L2A
#    processadas DIRETO DA NUVEM (sem download, sem cadastro, com máscara
#    de nuvem SCL por pixel) à mesma composição
resultado = w2m.get_water_mask(
    path="./wfi2mask_data/toa",
    coarse=100,   # resolução de análise (m), compatível com o HAND (~90 m)
    hand=15,      # HAND máximo (m)
    include_s2=True,
)
```

Saídas de `get_water_mask`:

* `water_<cena>.shp` — máscara por cena com as 4 classes de confiança
  (WATER, WATER95, WATER90, WATER80);
* `water_composite_majority.shp` — composição temporal pela regra da
  maioria (>50 %), quando há 2+ cenas (WFI e Sentinel-2 juntas);
* `water_mask_overlay.png` — plot de demonstração (cor verdadeira + máscara).

O limiar NIR é escolhido automaticamente por cena (0,35 para WFI TOA;
0,10 para Sentinel-2 L2A) e a janela de Matiz é ajustável
(`hue_min`/`hue_max`).

## Dados HAND

O filtro topográfico usa tiles HAND de 5°×5° do MERIT Hydro
(Yamazaki et al., 2019), hospedados no
[Release `hand-v1`](https://github.com/silvaglx/wfi2mask/releases/tag/hand-v1).
Os tiles necessários para o `bbox` são **baixados automaticamente** e mantidos
em cache local (`~/.wfi2mask/hand`) — nenhuma configuração é necessária.

## Algoritmo

```
Água = (Hue ∈ [16°, 35°) OU NDWI > 0) E (HAND ≤ 15 m) E (NIR < limiar) E pixel válido
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
